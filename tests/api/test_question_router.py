from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
import logging
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


# ---------------------------------------------------------------------------
# DT-22 MEDIUM pins for ``websocket_question_generate`` (evidence:
# agent/dt22-todo-scan report §7 rows question.py:385 / :438 / :505): the
# missing-requirement error broadcast, the ``ws_callback`` log enqueue and the
# batch-summary broadcast each swallowed delivery failures with a bare
# ``pass``, so a failed generation could leave no server-side trace. The
# failure-injection tests below pin the contract that every failure path
# leaves a log record (visibility) while the handler keeps running and keeps
# its narrow exception semantics (no escape, cleanup still happens).
# ---------------------------------------------------------------------------


class _FakeQuestionWebSocket:
    """Direct-call websocket stand-in for the question generation endpoint."""

    def __init__(self, config: dict, fail_send_when=None) -> None:
        self._config = config
        self._fail_send_when = fail_send_when
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self) -> None:
        pass

    async def receive_json(self) -> dict:
        return self._config

    async def send_json(self, payload: dict) -> None:
        if self._fail_send_when is not None and self._fail_send_when(payload):
            raise RuntimeError("connection is closed")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


class _StubPathService:
    def __init__(self, base: Path) -> None:
        self._base = base

    def get_question_batch_dir(self, batch_id: str) -> Path:
        return self._base / "question" / batch_id


def _question_config() -> dict:
    return {
        "requirement": {"knowledge_point": "photosynthesis"},
        "kb_name": "demo-kb",
        "count": 2,
    }


def _install_stub_coordinator(monkeypatch: pytest.MonkeyPatch, generate_impl):
    """Replace ``AgentCoordinator`` with a stub that captures the ws callback."""

    class _StubCoordinator:
        def __init__(self, **kwargs) -> None:
            self.init_kwargs = kwargs
            self.ws_callback = None

        def set_ws_callback(self, callback) -> None:
            self.ws_callback = callback

        async def generate_from_topic(self, **kwargs):
            return await generate_impl(self, **kwargs)

    monkeypatch.setattr(
        sys.modules["deeptutor.agents.question"], "AgentCoordinator", _StubCoordinator
    )


async def _run_question_endpoint(
    monkeypatch: pytest.MonkeyPatch, question_router_module, websocket
) -> None:
    async def _allow(_websocket) -> str:
        return "test-user-token"

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", _allow)

    await asyncio.wait_for(
        question_router_module.websocket_question_generate(websocket), timeout=10
    )


async def _successful_generation(coordinator, **_kwargs) -> dict:
    return {"success": True, "completed": 2, "failed": 0}


@pytest.mark.asyncio
async def test_question_missing_requirement_error_send_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report row :385 — when the client is gone and the missing-requirement
    error event cannot be delivered, the delivery failure must be logged
    instead of silently discarded."""
    question_router_module = _load_question_router_module(monkeypatch)

    websocket = _FakeQuestionWebSocket(
        config={"kb_name": "demo-kb", "count": 1},
        fail_send_when=lambda payload: payload.get("type") == "error",
    )

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.question"):
        await _run_question_endpoint(monkeypatch, question_router_module, websocket)

    assert websocket.sent == []
    assert any(
        record.levelno == logging.DEBUG
        and "cannot send missing-requirement error" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_question_ws_callback_enqueue_failure_is_logged_and_run_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report row :438 — a failed ``log_queue.put`` inside ``ws_callback``
    must be logged, and the generation run must continue to completion."""

    async def _generate_with_poison_update(coordinator, **_kwargs) -> dict:
        await coordinator.ws_callback({"type": "progress", "content": "poison"})
        return {"success": True, "completed": 2, "failed": 0}

    question_router_module = _load_question_router_module(monkeypatch)
    _install_stub_coordinator(monkeypatch, _generate_with_poison_update)
    monkeypatch.setattr(
        question_router_module, "get_path_service", lambda: _StubPathService(tmp_path)
    )

    real_put = asyncio.Queue.put

    async def _failing_put(self, item):
        if item.get("type") == "progress":
            raise RuntimeError("queue is closed")
        return await real_put(self, item)

    monkeypatch.setattr(asyncio.Queue, "put", _failing_put)

    websocket = _FakeQuestionWebSocket(config=_question_config())

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.question"):
        await _run_question_endpoint(monkeypatch, question_router_module, websocket)

    assert [message["type"] for message in websocket.sent] == [
        "task_id",
        "status",
        "batch_summary",
        "complete",
    ]
    assert websocket.closed
    assert any(
        record.levelno == logging.DEBUG and "log queue put failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_question_batch_summary_send_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report row :505 — when the batch summary cannot be delivered, the loss
    must be logged and the run must still finish (complete signal where the
    socket allows it, cleanup regardless)."""
    question_router_module = _load_question_router_module(monkeypatch)
    _install_stub_coordinator(monkeypatch, _successful_generation)
    monkeypatch.setattr(
        question_router_module, "get_path_service", lambda: _StubPathService(tmp_path)
    )

    websocket = _FakeQuestionWebSocket(
        config=_question_config(),
        fail_send_when=lambda payload: payload.get("type") == "batch_summary",
    )

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.question"):
        await _run_question_endpoint(monkeypatch, question_router_module, websocket)

    assert [message["type"] for message in websocket.sent] == [
        "task_id",
        "status",
        "complete",
    ]
    assert websocket.closed
    assert any(
        record.levelno == logging.DEBUG and "cannot send batch summary" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_question_generation_happy_path_frames_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Main-flow semantics pin: a healthy run still streams coordinator
    updates and finishes with batch_summary + complete."""

    async def _generate_with_updates(coordinator, **_kwargs) -> dict:
        await coordinator.ws_callback({"type": "progress", "content": "step 1"})
        await coordinator.ws_callback({"type": "question", "content": "q1"})
        return {"success": True, "completed": 1, "failed": 0}

    question_router_module = _load_question_router_module(monkeypatch)
    _install_stub_coordinator(monkeypatch, _generate_with_updates)
    monkeypatch.setattr(
        question_router_module, "get_path_service", lambda: _StubPathService(tmp_path)
    )

    websocket = _FakeQuestionWebSocket(config=_question_config())

    await _run_question_endpoint(monkeypatch, question_router_module, websocket)

    assert websocket.sent[0]["type"] == "task_id"
    assert websocket.sent[1] == {"type": "status", "content": "started"}
    assert {"type": "progress", "content": "step 1"} in websocket.sent
    assert {"type": "question", "content": "q1"} in websocket.sent
    summary = next(m for m in websocket.sent if m["type"] == "batch_summary")
    assert summary == {"type": "batch_summary", "requested": 2, "completed": 1, "failed": 0}
    assert websocket.sent[-1]["type"] == "complete"
    assert websocket.closed
