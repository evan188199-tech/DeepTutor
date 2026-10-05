"""Focused tests for ``adapters._iso`` aware-UTC normalization.

The string branch used to echo parseable inputs back verbatim, so naive,
``Z``-suffixed and offset stamps landed on the snapshot timeline as three
incomparable string formats — while ``consolidator/modes/update.py`` orders
entities by the raw ``ts`` string. These tests pin the normalized contract:
every parseable stamp (string or numeric) comes out as one aware-UTC
isoformat, and unparseable inputs keep degrading to ``""`` without raising.

Complements ``test_snapshot_adapters.py`` (adapter bridging) and the
failure-path lock-in file for the degradation contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.memory.snapshot.adapters import _iso

# ── String branch: one aware-UTC isoformat per instant ────────────────


def test_naive_string_normalized_to_aware_utc() -> None:
    assert _iso("2026-01-15T10:30:00") == "2026-01-15T10:30:00+00:00"


def test_z_suffix_and_offset_forms_unify() -> None:
    assert _iso("2026-01-15T10:30:00Z") == "2026-01-15T10:30:00+00:00"
    assert _iso("2026-01-15T10:30:00Z") == _iso("2026-01-15T10:30:00+00:00")


def test_non_utc_offset_converted_to_utc() -> None:
    assert _iso("2026-01-15T18:30:00+08:00") == "2026-01-15T10:30:00+00:00"


def test_space_separated_form_normalized() -> None:
    assert _iso("2026-01-15 10:30:00") == "2026-01-15T10:30:00+00:00"


def test_date_only_normalized_to_midnight_utc() -> None:
    assert _iso("2026-01-15") == "2026-01-15T00:00:00+00:00"


def test_mixed_pool_sorts_by_instant() -> None:
    stamps = [
        _iso("2026-01-15T18:30:00+08:00"),
        _iso("2026-01-15T11:30:00Z"),
        _iso("2026-01-15T09:30:00"),
    ]
    assert sorted(stamps) == [
        "2026-01-15T09:30:00+00:00",
        "2026-01-15T10:30:00+00:00",
        "2026-01-15T11:30:00+00:00",
    ]


# ── Numeric branch: stays UTC, agrees with the string branch ─────────


def test_numeric_epoch_stays_utc_isoformat() -> None:
    assert _iso(1737000000) == "2025-01-16T04:00:00+00:00"


def test_string_and_numeric_branches_agree_on_same_instant() -> None:
    assert _iso("2025-01-16T04:00:00Z") == _iso(1737000000)


# ── Degradation contract: unparseable inputs never raise ─────────────


@pytest.mark.parametrize(
    "bad",
    [None, "", "not-a-date", "not-a-dateZ", "2026-13-45T99:99:99", "1737000000"],
)
def test_unparseable_inputs_degrade_to_empty(bad: object) -> None:
    assert _iso(bad) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_epoch", [float("nan"), float("inf"), 1e30, -1e30])
def test_non_finite_epochs_degrade_to_empty(bad_epoch: float) -> None:
    assert _iso(bad_epoch) == ""


# ── Propagation: an adapter emits the normalized stamp ───────────────


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root


def test_partner_session_entity_carries_normalized_ts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partner session whose last record carries an offset timestamp must
    surface on the entity as the same instant in aware-UTC form."""
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(tmp_path))
    import deeptutor.multi_user.paths as mu_paths

    monkeypatch.setattr(mu_paths, "get_admin_path_service", lambda: _FakePathService(tmp_path))
    sessions = tmp_path / "partners" / "bot1" / "sessions"
    sessions.mkdir(parents=True)
    with (sessions / "web:s1.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "role": "user",
                    "content": "hi",
                    "timestamp": "2026-01-15T18:30:00+08:00",
                }
            )
            + "\n"
        )

    entities = adapters.read_partner_entities()

    assert entities[0].ts == "2026-01-15T10:30:00+00:00"
