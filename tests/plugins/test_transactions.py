"""Transactions tests fixate the non-blocking lock contract for plugin state.

`deeptutor/plugins/transactions.py` provides process-level mutual exclusion
for plugin lifecycle/state writes: `transaction()` takes an exclusive
non-blocking flock on a sibling `.lock` file (mapping contention to
`PluginStateError`) and `serialized()` runs a method inside it, targeting
`self.registry` when present and falling back to `self` as the lock owner.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from deeptutor.plugins.registry import PluginStateError
from deeptutor.plugins.transactions import serialized, transaction

POSIX = sys.platform != "win32"


def _registry(tmp_path):
    return SimpleNamespace(state_path=tmp_path / "state" / "plugins.json")


def _hold_exclusive(path):
    import fcntl

    handle = path.open("a+b")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


class _StateOwner:
    """A lifecycle-style manager whose writes are serialized on its registry."""

    def __init__(self, registry):
        self.registry = registry
        self.contended = None

    @serialized
    def rename(self, value):
        return value.upper()

    @serialized
    def probe(self):
        try:
            with transaction(self.registry):
                self.contended = False
        except PluginStateError:
            self.contended = True


class _SelfLocked:
    """A bare state owner with no ``registry`` attribute."""

    def __init__(self, state_path):
        self.state_path = state_path

    @serialized
    def duplicate(self, value):
        return value * 2


class _FailingOwner:
    def __init__(self, registry):
        self.registry = registry
        self.attempts = 0

    @serialized
    def fail(self):
        self.attempts += 1
        raise PluginStateError("plugin is broken")


def test_transaction_creates_lock_file_and_releases_after_exit(tmp_path) -> None:
    registry = _registry(tmp_path)
    lock_path = tmp_path / "state" / "plugins.lock"
    assert not lock_path.exists()

    with transaction(registry):
        assert lock_path.exists()

    with transaction(registry):
        pass  # a released lease is re-acquirable by the next transaction


@pytest.mark.skipif(not POSIX, reason="exclusivity probe uses fcntl")
def test_transaction_holds_exclusive_lock_while_body_runs(tmp_path) -> None:
    registry = _registry(tmp_path)
    lock_path = tmp_path / "state" / "plugins.lock"

    with transaction(registry):
        intruder = lock_path.open("a+b")
        try:
            import fcntl

            with pytest.raises(OSError):
                fcntl.flock(intruder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            intruder.close()


@pytest.mark.skipif(not POSIX, reason="contention is simulated with fcntl")
def test_transaction_maps_contention_to_plugin_state_error(tmp_path) -> None:
    registry = _registry(tmp_path)
    lock_path = tmp_path / "state" / "plugins.lock"
    lock_path.parent.mkdir(parents=True)
    holder = _hold_exclusive(lock_path)
    try:
        with pytest.raises(PluginStateError) as excinfo:
            with transaction(registry):
                pass
        assert "Another plugin lifecycle transaction is active" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, OSError)
    finally:
        holder.close()

    with transaction(registry):
        pass  # no permanent poisoning once the external holder exits


def test_transaction_releases_lock_when_body_raises(tmp_path) -> None:
    registry = _registry(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        with transaction(registry):
            raise RuntimeError("boom")

    with transaction(registry):
        pass


def test_transaction_is_not_reentrant_on_the_same_state_path(tmp_path) -> None:
    registry = _registry(tmp_path)

    with transaction(registry):
        with pytest.raises(PluginStateError):
            with transaction(registry):
                pass

    with transaction(registry):
        pass  # outer transaction is unaffected by the failed inner one


def test_serialized_runs_method_inside_registry_transaction(tmp_path) -> None:
    registry = _registry(tmp_path)
    owner = _StateOwner(registry)

    assert owner.rename("ok") == "OK"
    assert owner.rename.__name__ == "rename"
    assert (tmp_path / "state" / "plugins.lock").exists()


@pytest.mark.skipif(not POSIX, reason="probe relies on fcntl lock semantics")
def test_serialized_holds_registry_lock_for_method_duration(tmp_path) -> None:
    owner = _StateOwner(_registry(tmp_path))

    owner.probe()

    assert owner.contended is True


def test_serialized_falls_back_to_self_as_lock_owner(tmp_path) -> None:
    state_path = tmp_path / "lifecycle" / "state.json"
    owner = _SelfLocked(state_path)

    assert owner.duplicate("ab") == "abab"
    assert state_path.with_suffix(".lock").exists()


def test_serialized_propagates_errors_and_releases_lock(tmp_path) -> None:
    owner = _FailingOwner(_registry(tmp_path))

    with pytest.raises(PluginStateError, match="plugin is broken"):
        owner.fail()
    assert owner.attempts == 1

    with pytest.raises(PluginStateError, match="plugin is broken"):
        owner.fail()  # the lease was released, so a retry reaches the method
    assert owner.attempts == 2
