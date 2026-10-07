"""Contract tests for the TurnContextAssembler seam.

Table-driven, pure-logic coverage for
``deeptutor.services.session.turns.context_assembler``: store binding (the
field mapping into ``ContextBuilder``) and default/absent-attribute
behaviour. No services, no network, no store backends.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deeptutor.services.session.scope import StoreScope
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from deeptutor.services.session.turns import TurnContextAssembler
from deeptutor.services.session.turns.context_assembler import (
    TurnContextAssembler as AssemblerModuleClass,
)


class _Host(TurnContextAssembler):
    """Minimal composition host standing in for TurnRuntimeManager."""

    def __init__(self, store):
        self.store = store


@dataclass
class _FakeStore:
    name: str


STORE_DOUBLES = [
    MagicMock(name="magic-store"),
    _FakeStore(name="dataclass-store"),
    SimpleNamespace(name="namespace-store"),
]
STORE_DOUBLE_IDS = ["magic-mock", "fake-dataclass", "simple-namespace"]


@pytest.mark.parametrize("store", STORE_DOUBLES, ids=STORE_DOUBLE_IDS)
def test_builder_is_bound_to_the_host_store(store):
    builder = _Host(store)._create_context_builder()
    assert builder.store is store


def test_builder_keeps_context_builder_default_budgets():
    builder = _Host(MagicMock())._create_context_builder()
    assert builder.history_budget_ratio == 0.35
    assert builder.summary_target_ratio == 0.40


def test_context_builder_class_resolved_at_call_time(monkeypatch):
    created: dict = {}

    class _SentinelBuilder:
        def __init__(self, *args, **kwargs):
            created["args"] = args
            created["kwargs"] = kwargs

    import deeptutor.services.session.context_builder as provider

    monkeypatch.setattr(provider, "ContextBuilder", _SentinelBuilder)
    store = MagicMock(name="store")
    builder = _Host(store)._create_context_builder()
    assert isinstance(builder, _SentinelBuilder)
    assert created["args"] == (store,)
    assert created["kwargs"] == {}


def test_seam_module_import_does_not_load_context_builder():
    code = (
        "import sys;"
        "import deeptutor.services.session.turns.context_assembler;"
        "assert 'deeptutor.services.session.context_builder' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_store_is_type_checking_only_and_absence_fails_loudly():
    assert AssemblerModuleClass is TurnContextAssembler
    assert "store" not in vars(TurnContextAssembler)
    assert "store" not in getattr(TurnContextAssembler, "__annotations__", {})
    assert "__init__" not in vars(TurnContextAssembler)
    with pytest.raises(AttributeError):
        TurnContextAssembler()._create_context_builder()


def test_composed_runtime_manager_routes_store_into_builder():
    scope = StoreScope(backend="fake", resource="res", owner_id="owner")
    store = SimpleNamespace(store_scope=scope)
    manager = TurnRuntimeManager(store=store, turn_engine=MagicMock(name="engine"))
    assert TurnContextAssembler in type(manager).__mro__
    assert manager._create_context_builder().store is store
