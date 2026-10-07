"""Focused tests for the ``deeptutor.api.run_server`` startup script.

The whole uvicorn/config layer is mocked here: ``main()`` must only assemble
arguments and hand them to ``uvicorn.run`` — no real server is started and no
port is ever bound.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import deeptutor.api.run_server as run_server
from deeptutor.runtime.mode import RunMode

_BACKEND_PORT = 8321
_WS_MAX_SIZE = 987_654_321
_KEEP_ALIVE = 271_828


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    home = tmp_path / "runtime-home"
    home.mkdir()
    return home


@pytest.fixture
def launch(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Wire ``run_server.main()`` against fakes; return the recorded mocks."""
    from deeptutor.logging import configure_logging  # noqa: F401  (import probe)
    from deeptutor.runtime import mode as mode_module
    from deeptutor.services import config as config_module
    from deeptutor.services import setup as setup_module

    load_settings = Mock(return_value={})
    ws_max_size = Mock(return_value=_WS_MAX_SIZE)
    backend_port = Mock(return_value=_BACKEND_PORT)
    configure_logging_mock = Mock()
    set_mode_mock = Mock()

    monkeypatch.setattr(run_server, "get_runtime_home", lambda: project_root)
    monkeypatch.setattr(config_module, "load_system_settings", load_settings)
    monkeypatch.setattr(config_module, "get_ws_max_size", ws_max_size)
    monkeypatch.setattr(config_module, "HTTP_KEEP_ALIVE_TIMEOUT", _KEEP_ALIVE)
    monkeypatch.setattr(setup_module, "get_backend_port", backend_port)
    monkeypatch.setattr("deeptutor.logging.configure_logging", configure_logging_mock)
    monkeypatch.setattr(mode_module, "set_mode", set_mode_mock)

    uvicorn_run = Mock()
    monkeypatch.setattr(run_server.uvicorn, "run", uvicorn_run)

    # main() chdirs into the runtime home; make sure the test's cwd is
    # restored afterwards no matter how the assertions end.
    monkeypatch.chdir(project_root)

    return SimpleNamespace(
        run=uvicorn_run,
        load_settings=load_settings,
        ws_max_size=ws_max_size,
        backend_port=backend_port,
        configure_logging=configure_logging_mock,
        set_mode=set_mode_mock,
    )


def test_main_assembles_uvicorn_launch_config(launch: SimpleNamespace, project_root: Path) -> None:
    run_server.main()

    launch.run.assert_called_once()
    call = launch.run.call_args
    assert call.args == ("deeptutor.api.main:app",)
    kwargs = call.kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == _BACKEND_PORT
    assert kwargs["reload"] is False
    assert kwargs["workers"] == 1
    assert kwargs["reload_excludes"] is None
    assert kwargs["log_level"] == "info"
    assert kwargs["access_log"] is False
    assert kwargs["proxy_headers"] is False
    assert kwargs["ws_max_size"] == _WS_MAX_SIZE
    assert kwargs["timeout_keep_alive"] == _KEEP_ALIVE


def test_main_switches_runtime_context_before_launch(
    launch: SimpleNamespace, project_root: Path
) -> None:
    run_server.main()

    launch.set_mode.assert_called_once_with(RunMode.SERVER)
    launch.configure_logging.assert_called_once_with()
    launch.backend_port.assert_called_once_with(project_root)
    launch.ws_max_size.assert_called_once_with()
    # The runtime workspace root owns data/user/settings, so the process must
    # be running inside it before the server starts.
    assert Path.cwd() == project_root


def test_main_reload_excludes_limited_to_existing_dirs(
    launch: SimpleNamespace, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_DEV_RELOAD", "1")
    (project_root / "venv").mkdir()
    (project_root / "data").mkdir()

    run_server.main()

    kwargs = launch.run.call_args.kwargs
    assert kwargs["reload"] is True
    # Only the directories that actually exist survive the filter, in the
    # order the script declares them.
    assert kwargs["reload_excludes"] == [
        str(project_root / "venv"),
        str(project_root / "data"),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        (" On ", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("off", False),
        ("no", False),
    ],
)
def test_main_dev_reload_flag_env_parsing(
    launch: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_DEV_RELOAD", value)

    run_server.main()

    kwargs = launch.run.call_args.kwargs
    assert kwargs["reload"] is expected
    if expected:
        # No directories exist under the fixture root, so the filtered list
        # is empty rather than None.
        assert kwargs["reload_excludes"] == []
    else:
        assert kwargs["reload_excludes"] is None


def test_main_backend_workers_clamped_to_one(launch: SimpleNamespace) -> None:
    launch.load_settings.side_effect = [
        {"backend_workers": 4},
        {"backend_workers": 0},
    ]

    run_server.main()
    assert launch.run.call_args.kwargs["workers"] == 4

    run_server.main()
    assert launch.run.call_args.kwargs["workers"] == 1


def test_main_rejects_dev_reload_with_multiple_workers(
    launch: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_DEV_RELOAD", "1")
    launch.load_settings.return_value = {"backend_workers": 3}

    with pytest.raises(SystemExit, match="mutually exclusive"):
        run_server.main()

    launch.run.assert_not_called()


class _RecordingStream:
    def __init__(self) -> None:
        self.reconfigure_calls: list[dict[str, object]] = []

    def reconfigure(self, **kwargs: object) -> None:
        self.reconfigure_calls.append(kwargs)


def test_module_import_forces_unbuffered_line_buffered_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    fake_stdout = _RecordingStream()
    fake_stderr = _RecordingStream()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    importlib.reload(run_server)

    assert os.environ["PYTHONUNBUFFERED"] == "1"
    expected = {"line_buffering": True, "encoding": "utf-8", "errors": "replace"}
    assert fake_stdout.reconfigure_calls == [expected]
    assert fake_stderr.reconfigure_calls == [expected]


def _exec_module_source() -> None:
    source = Path(run_server.__file__).read_text(encoding="utf-8")
    exec(compile(source, str(run_server.__file__), "exec"), {})


def test_windows_platform_selects_proactor_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeProactorPolicy:
        pass

    installed: list[object] = []
    monkeypatch.setattr(
        asyncio, "WindowsProactorEventLoopPolicy", _FakeProactorPolicy, raising=False
    )
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: installed.append(policy))
    monkeypatch.setattr(sys, "platform", "win32")

    _exec_module_source()

    assert len(installed) == 1
    assert isinstance(installed[0], _FakeProactorPolicy)


def test_non_windows_platform_keeps_default_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[object] = []
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: installed.append(policy))
    monkeypatch.setattr(sys, "platform", "linux")

    _exec_module_source()

    assert installed == []
