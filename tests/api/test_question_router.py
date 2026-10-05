from __future__ import annotations

import base64
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
import types

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture(autouse=True)
def _cleanup_question_router_module():
    yield
    sys.modules.pop("deeptutor.api.routers.question", None)


class _DummyProcessLogEvent:
    def __init__(self, **kwargs) -> None:
        self.data = {"type": "process_log", **kwargs}

    def to_dict(self):
        return self.data


@contextmanager
def _noop_context(*_args, **_kwargs):
    yield


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _fake_config_module() -> types.ModuleType:
    """Stand in for ``deeptutor.services.config``, deferring the rest to the real one.

    Only the two names the question router reads at import time are overridden.
    Everything else resolves to the real attribute, because the websocket
    handler lazily imports ``deeptutor.api.routers.auth``, which pulls
    *unrelated* loaders (auth settings, integrations, …) out of this same
    package. Stubbing those one at a time was whack-a-mole, and skipping them
    left the test passing only when an earlier test had already put
    ``deeptutor.api.routers.auth`` in ``sys.modules`` — so the lazy import was
    a cache hit that never reached this stand-in. Green in a full run, red on
    its own.
    """
    real = importlib.import_module("deeptutor.services.config")
    module = types.ModuleType("deeptutor.services.config")
    module.__getattr__ = lambda name: getattr(real, name)  # PEP 562
    module.PROJECT_ROOT = Path.cwd()
    module.load_config_with_main = lambda *_args, **_kwargs: {}
    return module


def _load_question_router_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("deeptutor.api.routers.question", None)

    fake_agents = _package("deeptutor.agents")
    fake_agents_question = types.ModuleType("deeptutor.agents.question")
    fake_agents_question.AgentCoordinator = object
    fake_agents.question = fake_agents_question
    monkeypatch.setitem(sys.modules, "deeptutor.agents", fake_agents)
    monkeypatch.setitem(sys.modules, "deeptutor.agents.question", fake_agents_question)

    fake_logging = _package("deeptutor.logging")
    fake_logging.ProcessLogEvent = _DummyProcessLogEvent
    fake_logging.bind_log_context = _noop_context
    fake_logging.capture_process_logs = _noop_context
    fake_logging.current_log_context = lambda: {}
    monkeypatch.setitem(sys.modules, "deeptutor.logging", fake_logging)

    monkeypatch.setitem(sys.modules, "deeptutor.services.config", _fake_config_module())

    fake_llm_package = _package("deeptutor.services.llm")
    fake_llm_config = types.ModuleType("deeptutor.services.llm.config")
    fake_llm_config.get_llm_config = lambda: None
    fake_llm_package.config = fake_llm_config
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm", fake_llm_package)
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm.config", fake_llm_config)

    fake_settings_package = _package("deeptutor.services.settings")
    fake_interface_settings = types.ModuleType("deeptutor.services.settings.interface_settings")
    fake_interface_settings.get_ui_language = lambda default="en": default
    # The router asks for the *response* language now that reader-facing output
    # no longer follows the interface locale; the stand-in module has to offer
    # both readers the real one does.
    fake_interface_settings.get_response_language = lambda default="en": default
    fake_settings_package.interface_settings = fake_interface_settings
    monkeypatch.setitem(sys.modules, "deeptutor.services.settings", fake_settings_package)
    monkeypatch.setitem(
        sys.modules,
        "deeptutor.services.settings.interface_settings",
        fake_interface_settings,
    )

    fake_tools = _package("deeptutor.tools")
    fake_tools_question = types.ModuleType("deeptutor.tools.question")

    async def _default_mimic_exam_questions(*_args, **_kwargs):
        return {"success": True}

    fake_tools_question.mimic_exam_questions = _default_mimic_exam_questions
    fake_tools.question = fake_tools_question
    monkeypatch.setitem(sys.modules, "deeptutor.tools", fake_tools)
    monkeypatch.setitem(sys.modules, "deeptutor.tools.question", fake_tools_question)

    return importlib.import_module("deeptutor.api.routers.question")


def _build_app(router_module) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/question")
    app.include_router(router_module.ws_router, prefix="/ws/questions")
    return app


def test_mimic_websocket_accepts_config_and_returns_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    async def _fake_mimic_exam_questions(*_args, **_kwargs):
        return {"success": False, "error": "stub mimic failure"}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _fake_mimic_exam_questions)
    # ``MIMIC_OUTPUT_DIR`` was a module-level constant resolved at import time
    # (which froze it to the admin path). It's now a per-call helper so the
    # path follows whichever user is running. Patch the helper instead.
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": str(tmp_path / "paper"),
                    "kb_name": "demo-kb",
                    "max_questions": 3,
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == ["status", "status", "error"]
    assert messages[0]["stage"] == "init"
    assert messages[1]["stage"] == "processing"
    assert messages[2]["content"] == "stub mimic failure"


def test_mimic_upload_failures_return_neutral_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    with TestClient(_build_app(question_router_module)) as client:
        # Undecodable upload payload.
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {"mode": "upload", "pdf_data": "not-base64!", "pdf_name": "paper.pdf"}
            )
            messages = [websocket.receive_json() for _ in range(2)]
        assert messages[0]["type"] == "status"
        assert messages[1] == {
            "type": "error",
            "content": "The uploaded PDF data is corrupt. Re-upload the file.",
        }

        # Upload rejected by the filename/size validator.
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "upload",
                    "pdf_data": base64.b64encode(b"placeholder").decode(),
                    "pdf_name": "paper.txt",
                }
            )
            messages = [websocket.receive_json() for _ in range(2)]
        assert messages[1] == {
            "type": "error",
            "content": "That attachment could not be loaded.",
        }

        # Written upload fails the file-level checks.
        def _missing_file(_path):
            raise FileNotFoundError(2, "No such file or directory", str(tmp_path / "gone.pdf"))

        monkeypatch.setattr(
            question_router_module.DocumentValidator, "validate_file", staticmethod(_missing_file)
        )
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "upload",
                    "pdf_data": base64.b64encode(b"placeholder").decode(),
                    "pdf_name": "paper.pdf",
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]
        assert messages[2] == {
            "type": "error",
            "content": "That attachment could not be loaded.",
        }


def test_mimic_generation_failure_error_is_neutral(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    async def _failing_mimic_exam_questions(*_args, **_kwargs):
        raise RuntimeError(
            "provider call to https://provider.example/v1 failed (request id: req-1)"
        )

    monkeypatch.setattr(
        question_router_module, "mimic_exam_questions", _failing_mimic_exam_questions
    )
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": str(tmp_path / "paper"),
                    "kb_name": "demo-kb",
                    "max_questions": 3,
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == ["status", "status", "error"]
    assert messages[2]["content"] == "Generation failed. Please try again in a moment."
    assert "provider.example" in caplog.text
