"""Contract tests for the shared workspace tool runtime binding.

Covers the three public helpers of ``agents/_shared/tool_runtime.py``:
generation-tool filtering, workspace/sandbox binding, and the legacy
fallback turn-dir resolution. External service layers are faked; the
only filesystem writes land under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.agents._shared.tool_runtime import (
    bind_workspace_tool_runtime,
    drop_unconfigured_generation_tools,
    fallback_task_dir_from_metadata,
)
from deeptutor.core.context import (
    TurnRuntimeContext,
    UnifiedContext,
    WorkspaceRuntimeContext,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCatalogService:
    """Stand-in for the model catalog service."""

    def __init__(self, active: dict[str, dict[str, Any] | None]) -> None:
        self._active = active
        self.load_calls = 0

    def load(self) -> dict[str, Any]:
        self.load_calls += 1
        return {"providers": {}}

    def get_active_model(
        self, catalog: dict[str, Any], service_name: str
    ) -> dict[str, Any] | None:
        return self._active.get(service_name)


class _FakePathService:
    def __init__(self, mapping: dict[tuple[str, str], Path]) -> None:
        self._mapping = mapping
        self.requested: list[tuple[str, str]] = []

    def get_task_workspace(self, feature: str, task_id: str) -> Path:
        self.requested.append((feature, task_id))
        return self._mapping[(feature, task_id)]


def _make_context(
    workspace: WorkspaceRuntimeContext | None,
    *,
    language: str = "en",
    metadata: dict[str, Any] | None = None,
) -> UnifiedContext:
    runtime = TurnRuntimeContext(workspace=workspace)
    return UnifiedContext(language=language, metadata=metadata or {}, runtime=runtime)


# ---------------------------------------------------------------------------
# drop_unconfigured_generation_tools
# ---------------------------------------------------------------------------


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, service: _FakeCatalogService | None) -> None:
    def _factory() -> Any:
        assert service is not None
        return service

    if service is None:

        def _boom() -> Any:
            raise RuntimeError("catalog unavailable")

        _factory = _boom  # type: ignore[assignment]
    monkeypatch.setattr(
        "deeptutor.services.config.model_catalog.get_model_catalog_service", _factory
    )


def test_drop_unconfigured_passthrough_without_generation_tools() -> None:
    """No generation tools present: the list is returned untouched."""
    tools = ["rag", "read_memory", "web_fetch"]

    assert drop_unconfigured_generation_tools(tools) == tools


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        ({"imagegen": {"model": "img-1"}, "videogen": {"model": "vid-1"}}, ["rag", "imagegen", "videogen"]),
        ({"imagegen": {"model": "img-1"}, "videogen": None}, ["rag", "imagegen"]),
        ({"imagegen": None, "videogen": None}, ["rag"]),
        ({"imagegen": {}, "videogen": {"model": "vid-1"}}, ["rag", "videogen"]),
    ],
)
def test_drop_unconfigured_generation_tools_table(
    monkeypatch: pytest.MonkeyPatch, active: dict[str, Any], expected: list[str]
) -> None:
    """Configured generation tools stay; unconfigured ones are hidden."""
    _patch_catalog(monkeypatch, _FakeCatalogService(active))

    tools = ["rag", "imagegen", "videogen"]
    assert drop_unconfigured_generation_tools(list(tools)) == expected


def test_drop_unconfigured_catalog_failure_hides_all_generation_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing config probe must not leave unusable tools mounted."""
    _patch_catalog(monkeypatch, None)

    assert drop_unconfigured_generation_tools(["rag", "imagegen", "videogen"]) == ["rag"]


def test_drop_unconfigured_probe_failure_swallowed_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The failure is logged at debug level, never raised to callers."""
    import logging

    _patch_catalog(monkeypatch, None)

    with caplog.at_level(logging.DEBUG, logger="deeptutor.agents._shared.tool_runtime"):
        drop_unconfigured_generation_tools(["imagegen"])

    assert any("generation-tool config probe failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# bind_workspace_tool_runtime — non-bound tools
# ---------------------------------------------------------------------------


def test_unrelated_tool_args_copied_without_binding(tmp_path: Path) -> None:
    """Plain tools get a copy of args; no sandbox or workspace keys appear."""
    context = _make_context(None)
    args = {"query": "hello", "depth": 2}

    result = bind_workspace_tool_runtime("rag", args, context)

    assert result == args
    assert result is not args
    assert not any(str(k).startswith("_") for k in result)


def test_workspace_tool_injects_id_and_language(tmp_path: Path) -> None:
    """``workspace_*`` tools receive the workspace id and turn language."""
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(tmp_path / "out")
    )
    context = _make_context(workspace, language="zh")

    result = bind_workspace_tool_runtime("workspace_write", {"path": "a.txt"}, context)

    assert result["_workspace_id"] == "ws-1"
    assert result["_language"] == "zh"
    assert result["path"] == "a.txt"


def test_workspace_tool_defaults_language_to_en(tmp_path: Path) -> None:
    """An empty language falls back to ``en``."""
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(tmp_path / "out")
    )
    context = _make_context(workspace, language="")

    result = bind_workspace_tool_runtime("workspace_read", {}, context)

    assert result["_language"] == "en"


def test_workspace_tool_without_runtime_workspace_stays_unbound() -> None:
    """``workspace_*`` with no runtime workspace injects nothing."""
    context = _make_context(None)

    result = bind_workspace_tool_runtime("workspace_write", {"path": "a.txt"}, context)

    assert result == {"path": "a.txt"}


# ---------------------------------------------------------------------------
# bind_workspace_tool_runtime — exec / cli_ sandbox binding
# ---------------------------------------------------------------------------


def test_exec_binding_with_workspace_mounts_root_read_only(tmp_path: Path) -> None:
    """Full sandbox wiring: workdir, state dir, env, and three mounts."""
    task_dir = tmp_path / "task"
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(task_dir)
    )
    context = _make_context(workspace)

    result = bind_workspace_tool_runtime("exec", {"command": "ls"}, context)

    workdir = task_dir / "exec"
    state_dir = task_dir / ".deeptutor" / "execution"
    assert result["_sandbox_workdir"] == str(workdir)
    assert result["_sandbox_internal_root"] == str(state_dir)
    assert result["_sandbox_code_workdir"] == str(workdir)
    assert result["_sandbox_source_dir"] == str(state_dir / "exec_calls")
    assert result["_sandbox_env"]["DEEPTUTOR_WORKSPACE_ROOT"] == str(
        (tmp_path / "root").expanduser().resolve()
    )
    assert result["_workspace_id"] == "ws-1"
    assert result["_workspace_root"] == str(tmp_path / "root")
    mounts = result["_sandbox_mounts"]
    assert len(mounts) == 3
    assert (mounts[0].host_path, mounts[0].read_only) == (str(tmp_path / "root"), True)
    assert (mounts[1].host_path, mounts[1].read_only) == (str(workdir), False)
    assert (mounts[2].host_path, mounts[2].read_only) == (str(state_dir), False)
    assert workdir.is_dir()
    assert state_dir.is_dir()


def test_exec_binding_with_fallback_task_dir(tmp_path: Path) -> None:
    """No runtime workspace: the fallback dir drives the sandbox layout."""
    task_dir = tmp_path / "legacy-task"
    context = _make_context(None)

    result = bind_workspace_tool_runtime(
        "exec", {}, context, fallback_task_dir=task_dir, sandbox_user_id="user-7"
    )

    assert result["_sandbox_user_id"] == "user-7"
    assert result["_sandbox_workdir"] == str(task_dir / "exec")
    assert "DEEPTUTOR_WORKSPACE_ROOT" not in result["_sandbox_env"]
    mounts = result["_sandbox_mounts"]
    assert len(mounts) == 2
    assert not any(m.read_only for m in mounts)
    assert "_workspace_id" not in result
    assert "_workspace_root" not in result


def test_exec_binding_without_any_task_dir_stays_light() -> None:
    """No workspace and no fallback: only user id propagates, no sandbox."""
    context = _make_context(None)

    result = bind_workspace_tool_runtime("exec", {}, context, sandbox_user_id="user-7")

    assert result == {"_sandbox_user_id": "user-7"}
    assert not any(k.startswith("_sandbox") and k != "_sandbox_user_id" for k in result)


def test_exec_binding_sandbox_user_id_with_workspace(tmp_path: Path) -> None:
    """The sandbox user id rides along on the full path too."""
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(tmp_path / "task")
    )
    context = _make_context(workspace)

    result = bind_workspace_tool_runtime("exec", {}, context, sandbox_user_id="user-7")

    assert result["_sandbox_user_id"] == "user-7"


def test_cli_app_tool_binding_uses_cli_workdir(tmp_path: Path) -> None:
    """``cli_``-prefixed tools bind like exec but without code workdir keys."""
    task_dir = tmp_path / "task"
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(task_dir)
    )
    context = _make_context(workspace)

    result = bind_workspace_tool_runtime("cli_diagram", {}, context)

    assert result["_sandbox_workdir"] == str(task_dir / "cli")
    assert "_sandbox_code_workdir" not in result
    assert "_sandbox_source_dir" not in result
    assert len(result["_sandbox_mounts"]) == 3


# ---------------------------------------------------------------------------
# bind_workspace_tool_runtime — generation tools
# ---------------------------------------------------------------------------


def test_generation_tool_binds_media_dir_with_workspace(tmp_path: Path) -> None:
    """Generation tools get a media dir and the workspace id."""
    task_dir = tmp_path / "task"
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-1", root=str(tmp_path / "root"), output_dir=str(task_dir)
    )
    context = _make_context(workspace)

    result = bind_workspace_tool_runtime("imagegen", {"prompt": "cat"}, context)

    assert result["_workspace_dir"] == str(task_dir / "media")
    assert result["_workspace_id"] == "ws-1"
    assert (task_dir / "media").is_dir()
    assert not any(k.startswith("_sandbox") for k in result)


def test_generation_tool_with_fallback_dir_has_no_workspace_id(tmp_path: Path) -> None:
    """Fallback dir still binds media; no workspace identity is injected."""
    context = _make_context(None)

    result = bind_workspace_tool_runtime(
        "videogen", {}, context, fallback_task_dir=tmp_path / "legacy"
    )

    assert result["_workspace_dir"] == str(tmp_path / "legacy" / "media")
    assert "_workspace_id" not in result


def test_generation_tool_without_task_dir_unchanged() -> None:
    """No task dir anywhere: args pass through without media binding."""
    context = _make_context(None)

    result = bind_workspace_tool_runtime("imagegen", {"prompt": "cat"}, context)

    assert result == {"prompt": "cat"}


# ---------------------------------------------------------------------------
# fallback_task_dir_from_metadata
# ---------------------------------------------------------------------------


def test_fallback_dir_resolved_from_turn_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A turn id in metadata resolves through the path service."""
    expected = tmp_path / "feature" / "turn-42"
    fake = _FakePathService({("research", "turn-42"): expected})
    monkeypatch.setattr("deeptutor.services.path_service.get_path_service", lambda: fake)

    context = _make_context(None, metadata={"turn_id": "turn-42"})

    assert fallback_task_dir_from_metadata(context, feature="research") == expected
    assert fake.requested == [("research", "turn-42")]


@pytest.mark.parametrize(
    "metadata",
    [{}, {"turn_id": ""}, {"turn_id": "   "}, None],
)
def test_fallback_dir_requires_turn_id(metadata: dict[str, Any] | None) -> None:
    """Missing or blank turn id resolves to None without touching services."""
    runtime = TurnRuntimeContext(workspace=None)
    context = UnifiedContext(metadata=metadata or {}, runtime=runtime)

    assert fallback_task_dir_from_metadata(context, feature="research") is None
