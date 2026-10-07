"""Snapshot diff tests — the pure-logic contract of ``diff_snapshots``.

``diff.diff_snapshots`` turns two ``state`` dicts (``{entity_id: fingerprint}``)
into the ``ChangeEntry`` list the change log renders. These tests pin that
contract without any I/O: the add / remove / modify / no-diff outcomes, label
resolution (``label_map`` for present entities, ``prev_label_map`` with an
id fallback for removed ones), deterministic ordering, and the single shared
UTC timestamp stamped onto every entry of one call.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from deeptutor.services.memory.snapshot.diff import diff_snapshots
from deeptutor.services.memory.snapshot.entity import ChangeEntry

DICT_KEYS = {"ts", "kind", "entity_id", "label", "prev_fingerprint", "new_fingerprint"}


def _shape(entry: ChangeEntry) -> tuple[str, str, str, str | None, str | None]:
    """Compare everything but the timestamp, which has its own test."""
    return (
        entry.kind,
        entry.entity_id,
        entry.label,
        entry.prev_fingerprint,
        entry.new_fingerprint,
    )


@pytest.mark.parametrize(
    ("prev", "curr"),
    [
        pytest.param({}, {}, id="both-empty"),
        pytest.param({"a": "fa"}, {"a": "fa"}, id="same-keys-same-fingerprints"),
        pytest.param(
            {"a": "fa", "b": "fb", "c": "fc"},
            {"c": "fc", "a": "fa", "b": "fb"},
            id="same-content-different-order",
        ),
    ],
)
def test_equal_states_yield_no_changes(prev: dict[str, str], curr: dict[str, str]) -> None:
    assert diff_snapshots(prev, curr, label_map={}) == []


@pytest.mark.parametrize(
    ("prev", "curr", "label_map", "expected"),
    [
        pytest.param(
            {},
            {"n1": "f1"},
            {"n1": "First"},
            [("added", "n1", "First", None, "f1")],
            id="added-entity-uses-label-map",
        ),
        pytest.param(
            {},
            {"n1": "f1", "n2": "f2"},
            {},
            [("added", "n1", "n1", None, "f1"), ("added", "n2", "n2", None, "f2")],
            id="added-entities-fall-back-to-id-and-sort",
        ),
        pytest.param(
            {"old": "fold"},
            {"old": "fold", "z": "fz", "a": "fa"},
            {"z": "Zeta", "a": "Alpha"},
            [("added", "a", "Alpha", None, "fa"), ("added", "z", "Zeta", None, "fz")],
            id="added-entities-sorted-by-id-not-label",
        ),
    ],
)
def test_added_entities_contract(
    prev: dict[str, str],
    curr: dict[str, str],
    label_map: dict[str, str],
    expected: list[tuple[str, str, str, str | None, str | None]],
) -> None:
    entries = diff_snapshots(prev, curr, label_map=label_map)
    assert [_shape(e) for e in entries] == expected
    assert all(isinstance(e, ChangeEntry) for e in entries)


@pytest.mark.parametrize(
    ("prev_label_map", "entity_id", "fingerprint", "expected_label"),
    [
        pytest.param(None, "gone", "fg", "gone", id="no-prev-map-falls-back-to-id"),
        pytest.param({}, "gone", "fg", "gone", id="empty-prev-map-falls-back-to-id"),
        pytest.param({"gone": ""}, "gone", "fg", "gone", id="blank-prev-label-falls-back-to-id"),
        pytest.param({"gone": "Old Title"}, "gone", "fg", "Old Title", id="prev-map-label-wins"),
    ],
)
def test_removed_entities_label_contract(
    prev_label_map: dict[str, str] | None,
    entity_id: str,
    fingerprint: str,
    expected_label: str,
) -> None:
    entries = diff_snapshots(
        {entity_id: fingerprint},
        {},
        label_map={},
        prev_label_map=prev_label_map,
    )

    assert [_shape(e) for e in entries] == [
        ("removed", entity_id, expected_label, fingerprint, None)
    ]


@pytest.mark.parametrize(
    ("label_map", "expected_label"),
    [
        pytest.param({"n1": "First"}, "First", id="modified-uses-label-map"),
        pytest.param({}, "n1", id="modified-falls-back-to-id"),
    ],
)
def test_modified_entities_contract(label_map: dict[str, str], expected_label: str) -> None:
    entries = diff_snapshots(
        {"n1": "old-fp", "same": "keep"},
        {"n1": "new-fp", "same": "keep"},
        label_map=label_map,
    )

    assert [_shape(e) for e in entries] == [("modified", "n1", expected_label, "old-fp", "new-fp")]


def test_mixed_changes_group_added_removed_modified_in_order() -> None:
    prev = {"n2": "f2a", "n1": "f1a", "n3": "f3", "n4": "f4"}
    curr = {"n1": "f1b", "n3": "f3", "n4": "f4", "n0": "f0", "n5": "f5"}
    label_map = {"n0": "Zero", "n1": "One", "n5": "Five"}
    prev_label_map = {"n2": "Two"}

    entries = diff_snapshots(prev, curr, label_map=label_map, prev_label_map=prev_label_map)

    assert [_shape(e) for e in entries] == [
        ("added", "n0", "Zero", None, "f0"),
        ("added", "n5", "Five", None, "f5"),
        ("removed", "n2", "Two", "f2a", None),
        ("modified", "n1", "One", "f1a", "f1b"),
    ]


def test_entries_share_one_utc_timestamp() -> None:
    entries = diff_snapshots(
        {"a": "fa", "b": "fb"},
        {"a": "fa2", "c": "fc"},
        label_map={"a": "A", "b": "B", "c": "C"},
    )

    assert len(entries) == 3
    timestamps = {e.ts for e in entries}
    assert len(timestamps) == 1
    ts = datetime.fromisoformat(next(iter(timestamps)))
    assert ts.tzinfo is not None
    assert ts.utcoffset() == timedelta(0)


def test_change_entry_to_dict_exposes_full_record() -> None:
    (entry,) = diff_snapshots({}, {"n1": "f1"}, label_map={"n1": "First"})

    record = entry.to_dict()
    assert set(record) == DICT_KEYS
    assert record["kind"] == "added"
    assert record["entity_id"] == "n1"
    assert record["label"] == "First"
    assert record["prev_fingerprint"] is None
    assert record["new_fingerprint"] == "f1"
