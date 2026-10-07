"""Partner-level LLM selection: normalization contract and default fallback.

Covers ``deeptutor/services/partners/model_runtime.py`` only — the selection
vocabulary itself (``LLMSelection``) is owned by ``tests/services/model_selection``
and partner access control by ``tests/multi_user/test_partner_access``. Here the
question is what a partner config's ``llm_selection``/legacy ``model`` fields
mean when a turn is about to run: a validated selection dict, or the system
default config.

The resolver seam is patched, so every case below is pure logic — no settings
catalog, no provider runtime, no services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection import LLMSelection
from deeptutor.services.partners.model_runtime import (
    normalize_partner_llm_selection,
    resolve_partner_llm_config,
)


@dataclass
class _Partner:
    """The partner-config surface the resolver reads via ``getattr``."""

    llm_selection: Any = None
    model: Any = None


def _system_default() -> LLMConfig:
    return LLMConfig(model="system-default", api_key="sk-default")


def _install_resolver(monkeypatch, calls: list[Any]) -> None:
    """A deterministic selection resolver: the dict decides the model name."""

    def _resolve(selection: Any) -> LLMConfig:
        calls.append(selection)
        if selection is None:
            return _system_default()
        return LLMConfig(
            model=f"{selection['profile_id']}::{selection['model_id']}",
            api_key="sk-selection",
            reasoning_effort=selection.get("reasoning_effort"),
        )

    monkeypatch.setattr(
        "deeptutor.services.partners.model_runtime.resolve_llm_config_for_selection",
        _resolve,
    )


class TestNormalizeValidSelections:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            pytest.param(
                {"profile_id": "p1", "model_id": "m1"},
                {"profile_id": "p1", "model_id": "m1"},
                id="profile-and-model",
            ),
            pytest.param(
                {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "HIGH"},
                {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "high"},
                id="effort-lowercased",
            ),
            pytest.param(
                {"profile_id": "  p1  ", "model_id": "\tm1\n"},
                {"profile_id": "p1", "model_id": "m1"},
                id="ids-stripped",
            ),
            pytest.param(
                LLMSelection(profile_id="p1", model_id="m1", reasoning_effort="low"),
                {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "low"},
                id="selection-instance",
            ),
        ],
    )
    def test_valid_payloads_normalize_to_a_stable_dict(self, payload, expected):
        assert normalize_partner_llm_selection(payload) == expected


class TestNormalizeDefaultsToSystemDefault:
    """A partner without a usable selection means "use the system default"."""

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(None, id="none"),
            pytest.param({}, id="empty-dict"),
            pytest.param({"profile_id": "", "model_id": "   "}, id="blank-ids"),
            pytest.param({"profile_id": None, "model_id": None}, id="null-ids"),
        ],
    )
    def test_unusable_payloads_fall_back_to_none(self, payload):
        assert normalize_partner_llm_selection(payload) is None


class TestNormalizeRejectsInvalidSelections:
    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"profile_id": "p1"}, id="model-missing"),
            pytest.param({"model_id": "m1"}, id="profile-missing"),
            pytest.param(
                {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "ultra"},
                id="unsupported-effort",
            ),
            pytest.param("gpt-4o", id="raw-string"),
            pytest.param(42, id="integer"),
            pytest.param(["p1", "m1"], id="list"),
        ],
    )
    def test_invalid_payloads_raise_value_error(self, payload):
        with pytest.raises(ValueError):
            normalize_partner_llm_selection(payload)


class TestResolvePartnerLLMConfig:
    def test_selection_resolves_through_the_selection_path(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(
            _Partner(llm_selection={"profile_id": "p1", "model_id": "m1"})
        )

        # Exactly one resolution, keyed by the normalized selection — the
        # system default is never consulted when a selection exists.
        assert calls == [{"profile_id": "p1", "model_id": "m1"}]
        assert config.model == "p1::m1"
        assert config.reasoning_effort is None

    def test_selection_beats_a_legacy_model_string(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(
            _Partner(
                llm_selection={"profile_id": "p1", "model_id": "m1"},
                model="legacy-gpt",
            )
        )

        assert calls == [{"profile_id": "p1", "model_id": "m1"}]
        assert config.model == "p1::m1"

    def test_selection_carries_the_reasoning_effort_override(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(
            _Partner(
                llm_selection={
                    "profile_id": "p1",
                    "model_id": "m1",
                    "reasoning_effort": "high",
                }
            )
        )

        assert config.model == "p1::m1"
        assert config.reasoning_effort == "high"

    def test_no_selection_and_no_legacy_model_gets_the_system_default(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(_Partner())

        assert calls == [None]
        assert config.model == "system-default"
        assert config.api_key == "sk-default"

    def test_legacy_model_overrides_only_the_model_field(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(
            _Partner(model="  legacy-gpt  "),  # type: ignore[arg-type]
        )

        assert calls == [None]
        assert config.model == "legacy-gpt"
        assert config.api_key == "sk-default"

    def test_legacy_override_does_not_mutate_the_resolved_default(self, monkeypatch):
        # Hand out one shared default instance: a in-place rewrite of ``model``
        # would leak the partner's legacy model into every later resolution.
        shared_default = _system_default()
        monkeypatch.setattr(
            "deeptutor.services.partners.model_runtime.resolve_llm_config_for_selection",
            lambda selection: shared_default if selection is None else _system_default(),
        )

        config = resolve_partner_llm_config(_Partner(model="legacy-gpt"))

        assert config.model == "legacy-gpt"
        assert shared_default.model == "system-default"

    @pytest.mark.parametrize(
        "legacy_model",
        [
            pytest.param("", id="empty-string"),
            pytest.param("   ", id="whitespace"),
            pytest.param(None, id="none"),
        ],
    )
    def test_blank_legacy_model_stays_on_the_system_default(self, monkeypatch, legacy_model):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        config = resolve_partner_llm_config(_Partner(model=legacy_model))

        assert calls == [None]
        assert config.model == "system-default"

    def test_config_object_without_selection_fields_gets_the_default(self, monkeypatch):
        calls: list[Any] = []
        _install_resolver(monkeypatch, calls)

        class _Bare:
            pass

        config = resolve_partner_llm_config(_Bare())  # type: ignore[arg-type]

        assert calls == [None]
        assert config.model == "system-default"
