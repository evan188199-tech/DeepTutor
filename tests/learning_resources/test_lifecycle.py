"""Tests for the learning-resource provider lifecycle state machine (#961 slice 1)."""

from __future__ import annotations

import json

import pytest

from deeptutor.learning_resources.lifecycle import (
    InvalidProviderStateTransition,
    ProviderState,
    ProviderStateStore,
    transition,
)


def test_installed_can_be_enabled_and_disabled():
    assert transition(ProviderState.INSTALLED, ProviderState.ENABLED) is ProviderState.ENABLED
    assert transition(ProviderState.INSTALLED, ProviderState.DISABLED) is ProviderState.DISABLED


def test_enabled_can_be_disabled_or_fail():
    assert transition(ProviderState.ENABLED, ProviderState.DISABLED) is ProviderState.DISABLED
    assert transition(ProviderState.ENABLED, ProviderState.ERROR) is ProviderState.ERROR


def test_disabled_can_be_re_enabled():
    assert transition(ProviderState.DISABLED, ProviderState.ENABLED) is ProviderState.ENABLED


def test_error_can_retry_or_park():
    assert transition(ProviderState.ERROR, ProviderState.ENABLED) is ProviderState.ENABLED
    assert transition(ProviderState.ERROR, ProviderState.DISABLED) is ProviderState.DISABLED


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ProviderState.INSTALLED, ProviderState.ERROR),
        (ProviderState.INSTALLED, ProviderState.INSTALLED),
        (ProviderState.ENABLED, ProviderState.INSTALLED),
        (ProviderState.DISABLED, ProviderState.ERROR),
        (ProviderState.DISABLED, ProviderState.DISABLED),
        (ProviderState.ERROR, ProviderState.INSTALLED),
    ],
)
def test_invalid_transitions_raise(start, target):
    with pytest.raises(InvalidProviderStateTransition) as excinfo:
        transition(start, target)
    assert start.value in str(excinfo.value)
    assert target.value in str(excinfo.value)


class TestProviderStateStore:
    def test_load_unknown_provider_returns_none(self, tmp_path):
        store = ProviderStateStore(tmp_path)
        assert store.load("missing") is None

    def test_save_and_load_roundtrip(self, tmp_path):
        store = ProviderStateStore(tmp_path)
        store.save("example-dictionary", ProviderState.DISABLED, last_error=None)
        record = store.load("example-dictionary")
        assert record is not None
        assert record.state is ProviderState.DISABLED
        assert record.last_error is None

    def test_save_keeps_last_error(self, tmp_path):
        store = ProviderStateStore(tmp_path)
        store.save("example-dictionary", ProviderState.ERROR, last_error="network down")
        record = store.load("example-dictionary")
        assert record is not None
        assert record.state is ProviderState.ERROR
        assert record.last_error == "network down"

    def test_state_lives_under_provider_specific_directory(self, tmp_path):
        store = ProviderStateStore(tmp_path)
        store.save("example-dictionary", ProviderState.ENABLED)
        state_file = tmp_path / "example-dictionary" / "state.json"
        assert state_file.is_file()
        assert json.loads(state_file.read_text())["state"] == "enabled"

    def test_corrupt_state_file_is_ignored(self, tmp_path):
        (tmp_path / "example-dictionary").mkdir()
        (tmp_path / "example-dictionary" / "state.json").write_text("{not json")
        store = ProviderStateStore(tmp_path)
        assert store.load("example-dictionary") is None
