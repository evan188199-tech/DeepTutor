"""Contract tests for ``adapters._iso`` — DT-22 HIGH failure-path lock-in.

``_iso`` (``deeptutor/services/memory/snapshot/adapters.py:46``) wraps both
of its parse attempts in a bare ``except Exception: pass`` and degrades
every failure to ``""``. These tests pin the behavior *as it is today* so a
later fix (logging, normalization, stricter surfaces) must consciously
update them rather than silently shifting the contract.

Three path families are covered:

* valid ISO strings (naive, offset, space-separated, date-only) — echoed
  back verbatim, never normalized;
* the ``Z`` suffix — parses via ``ts.replace("Z", "+00:00")`` but the
  *original* string is returned, so ``Z``- and ``+00:00``-suffixed pools
  keep mixed formats;
* illegal inputs (garbage, numeric strings, out-of-range values, ``None``,
  out-of-range epochs, ``NaN``/``inf``) — silently degraded to ``""``.

Downstream consequences of the ``""`` degradation (L2 ordering, recall
exclusion, ``days_ago=None``) are documented in
``evidence/memory-snapshot-tests-2026-10-04/README.md`` and asserted at
the unit boundary by the propagation tests at the bottom of this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.memory.snapshot.adapters import _iso
from deeptutor.services.memory.snapshot.entity import EntityStamp

# ── Valid ISO strings: echoed verbatim, never normalized ─────────────


def test_valid_naive_iso_string_echoed_unchanged() -> None:
    assert _iso("2026-01-15T10:30:00") == "2026-01-15T10:30:00"


def test_valid_offset_iso_string_echoed_unchanged() -> None:
    assert _iso("2026-01-15T10:30:00+00:00") == "2026-01-15T10:30:00+00:00"
    assert _iso("2026-01-15T10:30:00+08:00") == "2026-01-15T10:30:00+08:00"


def test_valid_space_separator_iso_string_echoed_unchanged() -> None:
    # Python 3.11+ fromisoformat accepts the space separator form.
    assert _iso("2026-01-15 10:30:00") == "2026-01-15 10:30:00"


def test_valid_date_only_iso_string_echoed_unchanged() -> None:
    assert _iso("2026-01-15") == "2026-01-15"


def test_z_suffix_parses_and_echoes_original_with_z() -> None:
    # The Z form parses (via replace) but the ORIGINAL string is returned,
    # not the normalized +00:00 form — Z-form and offset-form stamps for the
    # same instant stay different strings in the entity pool.
    z = _iso("2026-01-15T10:30:00Z")
    offset = _iso("2026-01-15T10:30:00+00:00")
    assert z == "2026-01-15T10:30:00Z"
    assert offset == "2026-01-15T10:30:00+00:00"
    assert z != offset


# ── Numeric inputs: converted to UTC ISO format ──────────────────────


def test_int_timestamp_converted_to_utc_isoformat() -> None:
    assert _iso(1737000000) == "2025-01-16T04:00:00+00:00"


def test_float_timestamp_keeps_fraction() -> None:
    assert _iso(1737000000.5) == "2025-01-16T04:00:00.500000+00:00"


def test_bool_is_treated_as_unix_second() -> None:
    # isinstance(True, int) is True, so booleans quietly become 1970 stamps.
    assert _iso(True) == "1970-01-01T00:00:01+00:00"
    assert _iso(False) == "1970-01-01T00:00:00+00:00"


# ── Illegal inputs: silently degraded to "" (current defect) ─────────


def test_garbage_string_degrades_to_empty() -> None:
    assert _iso("not-a-date") == ""


def test_empty_string_degrades_to_empty() -> None:
    assert _iso("") == ""


def test_garbage_with_z_suffix_degrades_to_empty() -> None:
    # replace("Z", "+00:00") runs before parsing; garbage stays garbage.
    assert _iso("not-a-dateZ") == ""


def test_out_of_range_calendar_values_degrade_to_empty() -> None:
    # Well-formed ISO shape, impossible values: ValueError is swallowed.
    assert _iso("2026-13-45T99:99:99") == ""


def test_numeric_string_degrades_to_empty() -> None:
    # A str never reaches the numeric branch — "1737000000" is NOT the same
    # as 1737000000, even though stores sometimes swap the two.
    assert _iso("1737000000") == ""
    assert _iso(1737000000) != ""


def test_none_degrades_to_empty() -> None:
    assert _iso(None) == ""


def test_out_of_range_epoch_degrades_to_empty() -> None:
    # The concrete exception (OverflowError / OSError / ValueError) is
    # platform-dependent; the contract under test is the silent "".
    assert _iso(1e30) == ""
    assert _iso(-1e30) == ""


def test_non_finite_epoch_degrades_to_empty() -> None:
    assert _iso(float("nan")) == ""
    assert _iso(float("inf")) == ""


# ── Propagation: the "" degradation reaches real consumers ───────────


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root

    def get_notebook_index_file(self) -> Path:
        return self.workspace_root / "notebook_index.json"

    def get_notebook_file(self, nb_id: str) -> Path:
        return self.workspace_root / "notebooks" / f"{nb_id}.json"


def test_corrupt_notebook_timestamp_lands_as_empty_ts_on_entity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record whose ``created_at`` cannot be parsed still becomes an Entity
    — with ``ts=""``. Nothing logs, nothing skips; the blank stamp is the
    only trace of the corruption."""
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(tmp_path))
    nb_dir = tmp_path / "notebooks"
    nb_dir.mkdir(parents=True)
    (tmp_path / "notebook_index.json").write_text(
        json.dumps({"notebooks": [{"id": "nb1", "name": "Algebra"}]}), encoding="utf-8"
    )
    (nb_dir / "nb1.json").write_text(
        json.dumps(
            {
                "records": [
                    {"id": "good", "title": "Good", "created_at": "2026-01-15T10:30:00"},
                    {"id": "bad", "title": "Bad", "created_at": "not-a-date"},
                ]
            }
        ),
        encoding="utf-8",
    )

    by_id = {e.id: e for e in adapters.read_notebook_entities()}

    assert by_id["good"].ts == "2026-01-15T10:30:00"
    assert by_id["bad"].ts == ""


def test_recent_recall_drops_entities_with_unusable_stamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``recall.recent`` treats ``ts=""`` (or any unparseable stamp) as "not
    recent": the item is silently excluded from the learner's activity list
    even though the entity exists. That exclusion is the retention-policy
    cost of the swallowed parse failure."""
    from deeptutor.services.memory import recall

    stamps = [
        EntityStamp(id="good", label="Good note", fingerprint="f1", ts="2026-01-15T10:30:00"),
        EntityStamp(id="bad", label="Bad note", fingerprint="f2", ts="not-a-date"),
        EntityStamp(id="blank", label="Blank note", fingerprint="f3", ts=""),
    ]
    monkeypatch.setattr(adapters, "read_stamps", lambda surface: stamps)

    hits = recall.recent(days=None, surfaces=("notebook",))

    labels = [hit.label for hit in hits]
    assert "Good note" in labels
    assert "Bad note" not in labels
    assert "Blank note" not in labels
