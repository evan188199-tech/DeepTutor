"""Focused unit tests for ``deeptutor.agents._shared`` tool plumbing.

Covers the three shared modules under the agentic pipelines:

* ``capability_result``  — the final ``stream.result`` envelope contract
  (``cost_summary`` from the task-local tracker, ``usage_summary`` from the
  request-scoped collector, payload untouched when both are absent).
* ``tool_composition``   — the per-turn enabled-tool merge order, the
  exclusive-knowledge short-circuit, builtin-whitelist gating, forced /
  suppressed handling and the fail-closed context probes.
* ``tool_runtime``       — server-side runtime binding (workspace identity,
  exec sandbox mounts, generation media dir) and the fail-closed
  generation-tool config probe.

All collaborators are in-memory stubs; no LLM, sandbox process, or model
catalog service is started.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.agents._shared.tool_composition import (
    AUTO_MOUNTED_TOOLS,
    WORKSPACE_BASELINE_TOOLS,
    ToolMountFlags,
    compose_enabled_tools,
    default_optional_tools,
    partner_can_record_questions,
    user_has_mastery_topics,
    user_has_memory,
    user_has_notebooks,
    user_has_question_bank,
)
from deeptutor.agents._shared.tool_runtime import (
    GENERATION_TOOL_SERVICES,
    bind_workspace_tool_runtime,
    drop_unconfigured_generation_tools,
    fallback_task_dir_from_metadata,
)
from deeptutor.core.context import (
    TurnRuntimeContext,
    UnifiedContext,
    WorkspaceRuntimeContext,
)
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES, USER_TOGGLEABLE_TOOL_NAMES

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _ResultBus:
    """Records ``result()`` emissions instead of fanning out events."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    async def result(self, payload: dict[str, Any], *, source: str) -> None:
        self.calls.append((payload, source))


class _StubCollector:
    def __init__(self, summary: dict[str, Any] | None) -> None:
        self._summary = summary

    def summary(self) -> dict[str, Any] | None:
        return self._summary


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Registry:
    """``get_enabled`` keeps requested order and drops unknown names."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    def get_enabled(self, requested: list[str]) -> list[_Tool]:
        return [_Tool(name) for name in requested if name in self._known]


@pytest.fixture
def isolated_request_usage():
    from deeptutor.services.llm.metrics import current_usage

    token = current_usage.set(None)
    try:
        yield current_usage
    finally:
        current_usage.reset(token)


# ---------------------------------------------------------------------------
# capability_result — final result envelope contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_capability_result_passes_payload_through_without_usage(
    isolated_request_usage,
) -> None:
    bus = _ResultBus()
    payload: dict[str, Any] = {"response": "ok"}

    await emit_capability_result(bus, payload, source="chat")

    assert payload == {"response": "ok"}
    assert "metadata" not in payload
    assert bus.calls == [(payload, "chat")]


@pytest.mark.asyncio
async def test_emit_capability_result_merges_tracker_cost_summary_in_place(
    isolated_request_usage,
) -> None:
    bus = _ResultBus()
    tracker = UsageTracker()
    tracker.add_estimated(input_chars=350, output_chars=70)
    payload = {"response": "ok", "metadata": {"stage": "final"}}

    await emit_capability_result(bus, payload, source="deep_solve", usage=tracker)

    assert payload["metadata"]["stage"] == "final"
    assert payload["metadata"]["cost_summary"] == tracker.summary()
    assert payload["metadata"]["cost_summary"]["total_calls"] == 1
    assert bus.calls == [(payload, "deep_solve")]


@pytest.mark.asyncio
async def test_emit_capability_result_empty_tracker_invents_no_metadata(
    isolated_request_usage,
) -> None:
    bus = _ResultBus()
    payload: dict[str, Any] = {"response": "ok"}

    await emit_capability_result(bus, payload, source="chat", usage=UsageTracker())

    assert "metadata" not in payload
    assert bus.calls == [(payload, "chat")]


@pytest.mark.asyncio
async def test_emit_capability_result_attaches_request_usage_summary(
    isolated_request_usage,
) -> None:
    isolated_request_usage.set(_StubCollector({"total_tokens": 7}))
    bus = _ResultBus()
    tracker = UsageTracker()
    tracker.add_estimated(input_chars=70, output_chars=35)
    payload: dict[str, Any] = {"response": "ok"}

    await emit_capability_result(bus, payload, source="chat", usage=tracker)

    assert payload["metadata"]["cost_summary"] == tracker.summary()
    assert payload["metadata"]["usage_summary"] == {"total_tokens": 7}


@pytest.mark.asyncio
async def test_emit_capability_result_skips_empty_request_usage_summary(
    isolated_request_usage,
) -> None:
    isolated_request_usage.set(_StubCollector(None))
    bus = _ResultBus()
    payload: dict[str, Any] = {"response": "ok"}

    await emit_capability_result(bus, payload, source="chat")

    assert "metadata" not in payload


# ---------------------------------------------------------------------------
# tool_composition — merge order and exclusive short-circuit
# ---------------------------------------------------------------------------


def test_compose_enabled_tools_merge_order() -> None:
    registry = _Registry({"web_search", "brainstorm"})
    flags = ToolMountFlags(has_kb=True)

    tools = compose_enabled_tools(
        registry=registry,
        requested_tools=["web_search", "brainstorm", "unknown_tool"],
        optional_whitelist=["web_search", "brainstorm"],
        mount_flags=flags,
        capability_owned=("solve_plan",),
    )

    assert tools == [
        *WORKSPACE_BASELINE_TOOLS,
        "web_search",
        "brainstorm",
        "rag",
        "kb_files",
        "knowledge_frontier",
        "solve_plan",
        "write_memory",
        "learning_status",
        "learning_update",
        "web_fetch",
        "github",
        "ask_user",
        "cron",
    ]


def test_compose_enabled_tools_exclusive_short_circuits_to_owned_surface() -> None:
    registry = _Registry({"web_search"})

    tools = compose_enabled_tools(
        registry=registry,
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(),
        capability_owned=("vault_read",),
        exclusive=True,
    )

    assert tools == [*WORKSPACE_BASELINE_TOOLS, "vault_read", "ask_user"]


def test_compose_enabled_tools_exclusive_keeps_kb_coexistence() -> None:
    registry = _Registry({"web_search"})

    tools = compose_enabled_tools(
        registry=registry,
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(has_kb=True),
        capability_owned=("vault_read",),
        exclusive=True,
    )
    gated = compose_enabled_tools(
        registry=registry,
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(has_kb=True),
        capability_owned=("vault_read",),
        exclusive=True,
        builtin_whitelist={"vault_read"},
    )

    assert tools == [
        *WORKSPACE_BASELINE_TOOLS,
        "vault_read",
        "rag",
        "kb_files",
        "knowledge_frontier",
        "ask_user",
    ]
    assert gated == [*WORKSPACE_BASELINE_TOOLS, "vault_read", "ask_user"]


def test_compose_enabled_tools_builtin_whitelist_gates_but_never_adds() -> None:
    registry = _Registry({"web_search"})
    kwargs: dict[str, Any] = {
        "registry": registry,
        "requested_tools": ["web_search"],
        "optional_whitelist": ["web_search"],
        "mount_flags": ToolMountFlags(has_kb=True),
    }

    gated = compose_enabled_tools(builtin_whitelist={"write_memory", "ask_user"}, **kwargs)
    over_whitelisted = compose_enabled_tools(
        mount_flags=ToolMountFlags(),
        builtin_whitelist={"rag", "cron"},
        **{k: v for k, v in kwargs.items() if k != "mount_flags"},
    )

    assert "web_search" in gated
    assert "write_memory" in gated and "ask_user" in gated
    assert "rag" not in gated and "kb_files" not in gated
    assert "web_fetch" not in gated and "github" not in gated and "cron" not in gated
    assert "rag" not in over_whitelisted
    assert "cron" in over_whitelisted


def test_compose_enabled_tools_forced_bypasses_gates_and_suppressed_wins() -> None:
    tools = compose_enabled_tools(
        registry=_Registry(set()),
        requested_tools=[],
        optional_whitelist=[],
        mount_flags=ToolMountFlags(),
        builtin_whitelist=set(),
        forced=("partner_read", "workspace_read", "write_memory"),
        suppressed=("write_memory", "github"),
    )

    assert tools == [*WORKSPACE_BASELINE_TOOLS, "partner_read"]
    assert "write_memory" not in tools


def test_compose_enabled_tools_dedupes_first_occurrence() -> None:
    tools = compose_enabled_tools(
        registry=_Registry({"web_search"}),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(),
        capability_owned=("web_search",),
        forced=("web_search",),
    )

    assert tools.count("web_search") == 1
    assert tools.index("web_search") == len(WORKSPACE_BASELINE_TOOLS)


def test_default_optional_tools_excludes_automounted_and_excluded() -> None:
    defaults = default_optional_tools()

    assert set(defaults) <= set(USER_TOGGLEABLE_TOOL_NAMES) & set(BUILTIN_TOOL_NAMES)
    assert not set(defaults) & AUTO_MOUNTED_TOOLS
    excluded = frozenset(defaults[:2])
    assert default_optional_tools(excluded=excluded) == [
        name for name in defaults if name not in excluded
    ]


def test_context_probes_fail_closed_on_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("store unavailable")

    monkeypatch.setattr("deeptutor.services.memory.get_memory_store", _raise)
    monkeypatch.setattr("deeptutor.services.notebook.get_notebook_manager", _raise)
    monkeypatch.setattr("deeptutor.learning.navigation.learner_has_topics", _raise)
    monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", _raise)
    monkeypatch.setattr("deeptutor.services.partners.interaction.get_partner_turn_context", _raise)

    assert user_has_memory() is False
    assert user_has_notebooks() is False
    assert user_has_mastery_topics() is False
    assert user_has_question_bank() is False
    assert partner_can_record_questions() is False


def test_user_has_memory_requires_stripped_slot_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        def __init__(self, slots: dict[str, str]) -> None:
            self._slots = slots

        def read_raw(self, level: str, slot: str) -> str:
            return self._slots.get(slot, "")

    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: _Store({"profile": "  ", "scope": "algebra learner"}),
    )
    assert user_has_memory() is True

    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: _Store({"recent": "", "profile": "   "}),
    )
    assert user_has_memory() is False


# ---------------------------------------------------------------------------
# tool_runtime — server-side binding and fail-closed config probe
# ---------------------------------------------------------------------------


def test_generation_tool_services_contract() -> None:
    assert GENERATION_TOOL_SERVICES == {"imagegen": "imagegen", "videogen": "videogen"}


def test_drop_unconfigured_generation_tools_passthrough_without_generation_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.model_catalog.get_model_catalog_service",
        _unexpected_probe,
    )
    tools = ["web_search", "rag", "read_memory"]

    assert drop_unconfigured_generation_tools(tools) == tools


def test_drop_unconfigured_generation_tools_keeps_only_configured_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CatalogService:
        def load(self) -> dict[str, bool]:
            return {"loaded": True}

        def get_active_model(self, _catalog: Any, service: str) -> dict[str, str] | None:
            return {"model": "img-1"} if service == "imagegen" else None

    monkeypatch.setattr(
        "deeptutor.services.config.model_catalog.get_model_catalog_service",
        lambda: _CatalogService(),
    )

    assert drop_unconfigured_generation_tools(["web_search", "imagegen", "videogen"]) == [
        "web_search",
        "imagegen",
    ]


def test_drop_unconfigured_generation_tools_fails_closed_on_probe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenCatalogService:
        def load(self) -> dict[str, bool]:
            raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        "deeptutor.services.config.model_catalog.get_model_catalog_service",
        lambda: _BrokenCatalogService(),
    )

    assert drop_unconfigured_generation_tools(["web_search", "imagegen", "videogen"]) == [
        "web_search"
    ]


def _unexpected_probe(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("model catalog probe must not run for this input")


def _workspace_context(tmp_path: Path, *, language: str = "zh") -> UnifiedContext:
    workspace = WorkspaceRuntimeContext(
        workspace_id="ws-9",
        root=str(tmp_path / "root"),
        output_dir=str(tmp_path / "out"),
    )
    return UnifiedContext(
        language=language,
        runtime=TurnRuntimeContext(workspace=workspace),
    )


def test_bind_workspace_tool_runtime_injects_workspace_identity(
    tmp_path: Path,
) -> None:
    context = _workspace_context(tmp_path)
    args = {"path": "notes.txt"}

    kwargs = bind_workspace_tool_runtime("workspace_read", args, context)

    assert kwargs["path"] == "notes.txt"
    assert kwargs["_workspace_id"] == "ws-9"
    assert kwargs["_language"] == "zh"
    assert args == {"path": "notes.txt"}

    english_kwargs = bind_workspace_tool_runtime(
        "workspace_list", {}, _workspace_context(tmp_path, language="")
    )
    assert english_kwargs["_language"] == "en"


def test_bind_workspace_tool_runtime_binds_exec_sandbox(tmp_path: Path) -> None:
    from deeptutor.services.sandbox import Mount

    context = _workspace_context(tmp_path)

    kwargs = bind_workspace_tool_runtime("exec", {"code": "1+1"}, context)

    workdir = tmp_path / "out" / "exec"
    state_dir = tmp_path / "out" / ".deeptutor" / "execution"
    assert kwargs["code"] == "1+1"
    assert kwargs["_sandbox_workdir"] == str(workdir)
    assert kwargs["_sandbox_internal_root"] == str(state_dir)
    assert kwargs["_sandbox_code_workdir"] == str(workdir)
    assert kwargs["_sandbox_source_dir"] == str(state_dir / "exec_calls")
    assert kwargs["_sandbox_env"]["HOME"] == str(state_dir / "home")
    assert kwargs["_workspace_id"] == "ws-9"
    assert kwargs["_workspace_root"] == str(tmp_path / "root")
    mounts = kwargs["_sandbox_mounts"]
    assert mounts[0] == Mount(
        host_path=str(tmp_path / "root"),
        sandbox_path=str(tmp_path / "root"),
        read_only=True,
    )
    assert Mount(host_path=str(workdir), sandbox_path=str(workdir), read_only=False) in mounts
    assert workdir.is_dir()


def test_bind_workspace_tool_runtime_exec_without_task_dir_returns_early() -> None:
    context = UnifiedContext()

    plain = bind_workspace_tool_runtime("exec", {"cmd": "ls"}, context)
    with_user = bind_workspace_tool_runtime(
        "exec", {"cmd": "ls"}, context, sandbox_user_id="user-1"
    )

    assert plain == {"cmd": "ls"}
    assert with_user == {"cmd": "ls", "_sandbox_user_id": "user-1"}


def test_bind_workspace_tool_runtime_generation_tools_get_media_dir(
    tmp_path: Path,
) -> None:
    workspace_kwargs = bind_workspace_tool_runtime("imagegen", {}, _workspace_context(tmp_path))
    fallback_dir = tmp_path / "legacy-task"
    fallback_kwargs = bind_workspace_tool_runtime(
        "videogen", {}, UnifiedContext(), fallback_task_dir=fallback_dir
    )

    assert workspace_kwargs["_workspace_dir"] == str(tmp_path / "out" / "media")
    assert (tmp_path / "out" / "media").is_dir()
    assert workspace_kwargs["_workspace_id"] == "ws-9"
    assert fallback_kwargs["_workspace_dir"] == str(fallback_dir / "media")
    assert (fallback_dir / "media").is_dir()
    assert "_workspace_id" not in fallback_kwargs


def test_fallback_task_dir_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    assert fallback_task_dir_from_metadata(UnifiedContext(), feature="reading") is None
    assert (
        fallback_task_dir_from_metadata(
            UnifiedContext(metadata={"turn_id": "   "}), feature="reading"
        )
        is None
    )

    class _PathService:
        def get_task_workspace(self, feature: str, task_id: str) -> Path:
            return Path("/data") / feature / task_id

    monkeypatch.setattr("deeptutor.services.path_service.get_path_service", lambda: _PathService())

    resolved = fallback_task_dir_from_metadata(
        UnifiedContext(metadata={"turn_id": "t-1"}), feature="reading"
    )
    assert resolved == Path("/data/reading/t-1")
