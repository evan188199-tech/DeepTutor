"""Managed plugin review lifecycle and revocable runtime gates (#1307)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.plugins.registry import PluginStateError
import deeptutor.plugins.runtime as runtime
from deeptutor.plugins.runtime import PluginRuntimeError, PluginWorkerTool
from tests.plugins.test_lifecycle import _manager, _wheel

PLUGIN_ID = "org.author.example"
EXTENSION_ID = "example_tool"


def _worker_stub(calls: list[str]):
    """Serve canned worker responses without launching any process."""

    def fake_run_worker(argv, *, input, env, cwd):
        request = json.loads(input)
        calls.append(request["operation"])
        if request["operation"] == "describe_tool":
            response = {
                "definition": {
                    "name": EXTENSION_ID,
                    "description": "Example tool",
                    "parameters": [],
                }
            }
        else:
            arguments = request.get("arguments", {})
            response = {
                "result": {
                    "content": f"echo: {arguments.get('message', '')}",
                    "sources": [],
                    "metadata": {},
                    "success": True,
                }
            }
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")

    return fake_run_worker


def _worker_tool(registry, record) -> PluginWorkerTool:
    return PluginWorkerTool(
        manifest=record.manifest,
        installation=record.installation,
        extension_id=EXTENSION_ID,
        registry=registry,
    )


def test_reviewed_lifecycle_state_transitions(tmp_path) -> None:
    manager = _manager(tmp_path)
    registry = manager.registry

    manager.install(_wheel(tmp_path, "1.0.0"))
    assert registry.get_plugin(PLUGIN_ID).status == "approval-required"

    assert registry.approve(PLUGIN_ID).status == "enabled"

    assert registry.set_enabled(PLUGIN_ID, False).status == "disabled"
    assert registry.set_enabled(PLUGIN_ID, True).status == "enabled"

    manager.install(_wheel(tmp_path, "1.1.0"))
    record = registry.get_plugin(PLUGIN_ID)
    assert record.version == "1.1.0"
    assert record.status == "approval-required"

    assert registry.approve(PLUGIN_ID).status == "enabled"


def test_stale_digest_approval_is_rejected_and_state_is_preserved(tmp_path) -> None:
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))
    before = registry.state_path.read_bytes()

    with pytest.raises(PluginStateError, match="snapshot changed"):
        registry.approve(PLUGIN_ID, expected_digest="0" * 64)

    assert registry.state_path.read_bytes() == before
    assert registry.get_plugin(PLUGIN_ID).status == "approval-required"

    digest = registry.get_plugin(PLUGIN_ID).to_dict()["approval_digest"]
    assert registry.approve(PLUGIN_ID, expected_digest=digest).status == "enabled"


def test_reinstall_and_uninstall_clear_review_state(tmp_path) -> None:
    manager = _manager(tmp_path)
    registry = manager.registry
    artifact = _wheel(tmp_path, "1.0.0")
    manager.install(artifact)
    registry.approve(PLUGIN_ID)

    result = manager.install(artifact, allow_reinstall=True)
    record = registry.get_plugin(PLUGIN_ID)
    assert result.action == "reinstalled"
    assert record.status == "approval-required"

    registry.approve(PLUGIN_ID)
    registry.set_enabled(PLUGIN_ID, False)
    assert registry.get_plugin(PLUGIN_ID).status == "disabled"

    manager.uninstall(PLUGIN_ID)
    assert PLUGIN_ID not in registry.state_snapshot()["disabled"]


def test_approve_is_idempotent_and_rejects_unknown_plugins(tmp_path) -> None:
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))
    registry.approve(PLUGIN_ID)

    assert registry.approve(PLUGIN_ID).status == "enabled"

    with pytest.raises(PluginStateError, match="unknown plugin"):
        registry.approve("org.author.missing")
    with pytest.raises(PluginStateError, match="unknown plugin"):
        registry.set_enabled("org.author.missing", False)


def test_unapproved_and_disabled_managed_workers_cannot_start(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime, "_run_worker", _worker_stub(calls))
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))

    record = registry.get_plugin(PLUGIN_ID)
    with pytest.raises(PluginRuntimeError, match="disabled, unapproved"):
        _worker_tool(registry, record)
    assert calls == []
    assert runtime.load_enabled_workers(registry) == ()
    assert calls == []

    registry.approve(PLUGIN_ID)
    registry.set_enabled(PLUGIN_ID, False)
    record = registry.get_plugin(PLUGIN_ID)
    assert record.status == "disabled"
    with pytest.raises(PluginRuntimeError, match="disabled, unapproved"):
        _worker_tool(registry, record)
    assert calls == []


@pytest.mark.asyncio
async def test_runtime_gate_revocation_is_immediate_and_reversible(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime, "_run_worker", _worker_stub(calls))
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))
    registry.approve(PLUGIN_ID)

    record = registry.get_plugin(PLUGIN_ID)
    tool = _worker_tool(registry, record)
    assert (await tool.execute(message="hello")).content == "echo: hello"
    launches = len(calls)

    registry.set_enabled(PLUGIN_ID, False)
    with pytest.raises(PluginRuntimeError, match="disabled, unapproved"):
        await tool.execute(message="hello")
    assert len(calls) == launches

    registry.set_enabled(PLUGIN_ID, True)
    assert (await tool.execute(message="again")).content == "echo: again"


@pytest.mark.asyncio
async def test_upgraded_generation_revokes_cached_worker_until_re_review(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime, "_run_worker", _worker_stub(calls))
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))
    registry.approve(PLUGIN_ID)

    record = registry.get_plugin(PLUGIN_ID)
    cached = _worker_tool(registry, record)
    assert (await cached.execute(message="hello")).content == "echo: hello"

    manager.install(_wheel(tmp_path, "1.1.0"))
    with pytest.raises(PluginRuntimeError, match="disabled, unapproved"):
        await cached.execute(message="hello")

    registry.approve(PLUGIN_ID)
    record = registry.get_plugin(PLUGIN_ID)
    fresh = _worker_tool(registry, record)
    assert (await fresh.execute(message="hello")).content == "echo: hello"


def test_load_enabled_workers_starts_only_enabled_records(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime, "_run_worker", _worker_stub(calls))
    manager = _manager(tmp_path)
    registry = manager.registry
    manager.install(_wheel(tmp_path, "1.0.0"))

    assert runtime.load_enabled_workers(registry) == ()

    registry.approve(PLUGIN_ID)
    workers = runtime.load_enabled_workers(registry)
    assert len(workers) == 1
    assert isinstance(workers[0], PluginWorkerTool)
    started = len(calls)
    assert started > 0

    registry.set_enabled(PLUGIN_ID, False)
    assert runtime.load_enabled_workers(registry) == ()
    assert len(calls) == started
