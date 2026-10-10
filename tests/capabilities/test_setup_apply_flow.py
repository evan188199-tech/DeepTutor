"""Focused tests for the apply pipeline in ``capabilities/setup/apply.py``.

The module's contract is the *order* of its steps and what happens when a
step refuses: refuse before probing, probe before writing, and a
value-equals-previous no-op that neither probes nor writes. The existing
``test_setup_capability.py`` pins end-to-end behaviour against the real spec
table; these tests drive ``apply_setting`` over a synthetic row backed by a
JSON file under ``tmp_path`` so each branch and the call order are asserted
directly — and no real configuration file is ever opened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.capabilities.setup import apply as apply_module
from deeptutor.capabilities.setup.access import AccessDecision
from deeptutor.capabilities.setup.apply import apply_setting
from deeptutor.services.config import settings_spec as spec_module
from deeptutor.services.config.settings_spec import ProbeResult, SettingChoice, SettingSpec


class _Row:
    """A synthetic spec row backed by one JSON document inside ``tmp_path``.

    The row, its neighbour and the access decision all resolve here, so the
    whole apply pipeline runs against test-owned state. Every interesting
    step appends a marker to ``events`` so the tests can assert the exact
    execution order rather than only the final outcome.
    """

    KEY = "synthetic.main"
    NEIGHBOUR_KEY = "synthetic.neighbour"

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.probed: list[str] = []
        self.allow = True
        self.probe_ok = True
        self.write_error: Exception | None = None
        self.validate_error: str | None = None
        self.offered: tuple[str, ...] = ("off", "on")
        self.unavailable: str | None = None
        self.normalize = False
        self.couple = False
        self.path = tmp_path / "synthetic-settings.json"
        self._flush({"main": "off", "neighbour": "en"})

        monkeypatch.setattr(apply_module, "get_setting_spec", self._lookup)
        monkeypatch.setattr(apply_module, "can_write", self._can_write)
        monkeypatch.setattr(spec_module, "specs_for_area", self._area_specs)

        self.spec = SettingSpec(
            key=self.KEY,
            area="interface",
            scope="personal",
            effect="instant",
            label="Main row",
            summary="synthetic row for apply-flow tests",
            read=self._read_main,
            choices=self._choices,
            write=self._write_main,
            validate=self._validate,
            probe=self._probe,
        )
        self.neighbour = SettingSpec(
            key=self.NEIGHBOUR_KEY,
            area="interface",
            scope="personal",
            effect="instant",
            label="Neighbour row",
            summary="synthetic neighbour used for coupling checks",
            read=self._read_neighbour,
            choices=lambda: (),
            write=lambda value: None,
        )

    # -- seams ------------------------------------------------------------

    def _lookup(self, key: str) -> SettingSpec | None:
        self.events.append("spec")
        if key == self.KEY:
            return self.spec
        return None

    def _can_write(self, scope: str) -> AccessDecision:
        self.events.append("scope")
        if self.allow:
            return AccessDecision(allowed=True)
        return AccessDecision(allowed=False, reason="ask an administrator")

    def _area_specs(self, area: str) -> tuple[SettingSpec, ...]:
        self.events.append("neighbours")
        return (self.spec, self.neighbour)

    # -- store ------------------------------------------------------------

    def _load(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self, data: dict[str, str]) -> None:
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def stored(self) -> dict[str, str]:
        return self._load()

    # -- spec callables ---------------------------------------------------

    def _read_main(self) -> str:
        self.events.append("read")
        return self._load()["main"]

    def _read_neighbour(self) -> str:
        return self._load()["neighbour"]

    def _choices(self) -> tuple[SettingChoice, ...]:
        self.events.append("choices")
        return tuple(
            SettingChoice(
                value=value,
                label=value.capitalize(),
                description="needs setup first" if value == self.unavailable else "",
                available=value != self.unavailable,
            )
            for value in self.offered
        )

    def _validate(self, value: str) -> str | None:
        self.events.append("validate")
        return self.validate_error

    async def _probe(self, value: str) -> ProbeResult:
        self.events.append("probe")
        self.probed.append(value)
        if self.probe_ok:
            return ProbeResult(ok=True, elapsed_ms=1)
        return ProbeResult(ok=False, detail="connection refused")

    def _write_main(self, value: str) -> None:
        self.events.append("write")
        if self.write_error is not None:
            raise self.write_error
        data = self._load()
        data["main"] = f"{value}@1" if self.normalize else value
        if self.couple:
            data["neighbour"] = "zh"
        self._flush(data)


@pytest.fixture
def _row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Row:
    return _Row(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_runs_its_steps_in_probe_before_write_order(_row: _Row) -> None:
    outcome = await apply_setting(_Row.KEY, "on")
    payload = outcome.to_dict()

    assert outcome.ok, outcome.error
    assert outcome.value == "on"
    assert outcome.previous == "off"
    assert _row.events == [
        "spec",
        "scope",
        "read",
        "choices",
        "validate",
        "probe",
        "neighbours",
        "write",
        "neighbours",
        "read",
    ], (
        "resolve, authorize, read, enumerate, validate, probe, snapshot, write, re-snapshot, read back"
    )
    assert payload["probe"]["ok"] is True
    assert "error" not in payload
    assert "also_changed" not in payload


@pytest.mark.asyncio
async def test_an_unoffered_value_is_refused_before_probing_or_writing(
    _row: _Row,
) -> None:
    outcome = await apply_setting(_Row.KEY, "klingon")

    assert not outcome.ok
    assert "not one of the available options" in outcome.error
    assert _row.events == ["spec", "scope", "read", "choices"]
    assert _row.stored()["main"] == "off"


@pytest.mark.asyncio
async def test_an_offered_but_unusable_choice_is_refused_before_probing(
    _row: _Row,
) -> None:
    _row.offered = ("off", "on", "turbo")
    _row.unavailable = "turbo"

    outcome = await apply_setting(_Row.KEY, "turbo")

    assert not outcome.ok
    assert "listed but not usable" in outcome.error
    assert _row.events == ["spec", "scope", "read", "choices"]
    assert _row.stored()["main"] == "off"


@pytest.mark.asyncio
async def test_a_validate_rejection_stops_before_the_probe(_row: _Row) -> None:
    _row.validate_error = "value rejected by the row"

    outcome = await apply_setting(_Row.KEY, "on")

    assert not outcome.ok
    assert outcome.error == "value rejected by the row"
    assert _row.events == ["spec", "scope", "read", "choices", "validate"]
    assert _row.probed == []
    assert _row.stored()["main"] == "off"


@pytest.mark.asyncio
async def test_a_scope_refusal_stops_before_the_row_is_read(_row: _Row) -> None:
    _row.allow = False

    outcome = await apply_setting(_Row.KEY, "on")

    assert not outcome.ok
    assert outcome.error == "ask an administrator"
    assert outcome.label == "Main row"
    assert _row.events == ["spec", "scope"]
    assert _row.stored() == {"main": "off", "neighbour": "en"}


@pytest.mark.asyncio
async def test_an_unknown_key_refuses_without_touching_any_row(_row: _Row) -> None:
    outcome = await apply_setting("synthetic.missing", "on")

    assert not outcome.ok
    assert "Unknown setting" in outcome.error
    assert _row.events == ["spec"]
    assert _row.stored() == {"main": "off", "neighbour": "en"}


# ---------------------------------------------------------------------------
# Idempotence and resume after a partial failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reapplying_the_same_value_is_a_noop_that_neither_probes_nor_writes(
    _row: _Row,
) -> None:
    first = await apply_setting(_Row.KEY, "on")
    assert first.ok

    _row.events.clear()
    _row.probed.clear()
    second = await apply_setting(_Row.KEY, "on")

    assert second.ok
    assert second.value == "on"
    assert second.previous == "on"
    assert second.effect == "instant"
    assert second.metadata == {"unchanged": True}
    assert second.to_dict()["metadata"] == {"unchanged": True}
    assert _row.events == ["spec", "scope", "read"], "the no-op must short-circuit before choices"
    assert _row.probed == []
    assert _row.stored()["main"] == "on"


@pytest.mark.asyncio
async def test_a_failed_apply_leaves_the_row_resumable(_row: _Row) -> None:
    refused = await apply_setting(_Row.KEY, "klingon")
    assert not refused.ok
    assert _row.stored()["main"] == "off"

    _row.events.clear()
    retried = await apply_setting(_Row.KEY, "on")
    assert retried.ok
    assert _row.stored()["main"] == "on"

    _row.events.clear()
    repeat = await apply_setting(_Row.KEY, "on")
    assert repeat.ok
    assert repeat.metadata == {"unchanged": True}
    assert "write" not in _row.events


@pytest.mark.asyncio
async def test_a_failed_probe_rolls_back_and_a_retry_can_succeed(_row: _Row) -> None:
    _row.probe_ok = False

    refused = await apply_setting(_Row.KEY, "on")

    assert not refused.ok
    assert refused.probe is not None and not refused.probe.ok
    assert "connection refused" in refused.error
    assert "write" not in _row.events
    assert _row.stored()["main"] == "off"

    _row.events.clear()
    _row.probed.clear()
    _row.probe_ok = True

    retried = await apply_setting(_Row.KEY, "on")

    assert retried.ok, retried.error
    assert _row.probed == ["on"], "the retry must probe the candidate again before writing"
    assert _row.stored()["main"] == "on"


@pytest.mark.asyncio
async def test_a_write_failure_reports_and_keeps_the_previous_value(_row: _Row) -> None:
    _row.write_error = RuntimeError("disk full")

    refused = await apply_setting(_Row.KEY, "on")

    assert not refused.ok
    assert "Could not save" in refused.error
    assert "disk full" in refused.error
    assert _row.probed == ["on"], "the probe still ran; only the commit was refused"
    assert _row.stored()["main"] == "off"

    _row.write_error = None
    _row.events.clear()

    retried = await apply_setting(_Row.KEY, "on")

    assert retried.ok, retried.error
    assert _row.stored()["main"] == "on"


# ---------------------------------------------------------------------------
# Read-back and coupled rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_normalising_writer_is_reported_as_adjusted(_row: _Row) -> None:
    _row.normalize = True

    outcome = await apply_setting(_Row.KEY, "on")

    assert outcome.ok, outcome.error
    assert outcome.value == "on@1"
    assert outcome.metadata == {"adjusted_from": "on"}
    assert _row.stored()["main"] == "on@1"


@pytest.mark.asyncio
async def test_a_coupled_row_is_reported_as_a_side_effect(_row: _Row) -> None:
    _row.couple = True

    outcome = await apply_setting(_Row.KEY, "on")

    assert outcome.ok, outcome.error
    assert [(effect.key, effect.previous, effect.value) for effect in outcome.side_effects] == [
        (_Row.NEIGHBOUR_KEY, "en", "zh")
    ]
    assert outcome.to_dict()["also_changed"] == [
        {
            "key": _Row.NEIGHBOUR_KEY,
            "label": "Neighbour row",
            "previous": "en",
            "value": "zh",
        }
    ]
    assert outcome.metadata == {}
