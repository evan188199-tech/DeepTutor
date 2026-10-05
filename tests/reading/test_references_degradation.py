"""Degradation semantics of ``resolve_reading_sources``.

Locks the fail-closed behavior of the two bare ``except Exception: continue``
guards in ``deeptutor/reading/references.py``:

- a material whose stored metadata cannot be read is dropped whole, while
  sibling materials in the same call still resolve;
- a locator whose stored unit text cannot be read is dropped alone, while
  sibling locators still resolve;
- the return value alone cannot distinguish "never existed" from "failed to
  read": both degrade to a shorter list with no error marker;
- repeated material rows merge in first-seen order, so resolution order
  follows input order and locators are never re-sorted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.reading.references import (
    ResolvedReadingSource,
    resolve_reading_sources,
)
from deeptutor.reading.store import ReadingStore

DAMAGED_ID = "aaaa000000000001"
HEALTHY_ID = "bbbb000000000002"
CORRUPT_ONLY_ID = "cccc000000000003"
MISSING_ID = "dddd000000000004"


class _CorruptStore:
    """Duck-typed ReadingStore proxy that fails selected calls.

    ``failures`` holds ``(method, material_id)`` or
    ``(method, material_id, locator)`` tuples; matching calls raise OSError to
    simulate on-disk corruption without depending on the store layout.
    """

    def __init__(self, inner: ReadingStore, failures: set[tuple[Any, ...]]) -> None:
        self._inner = inner
        self._failures = failures

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def manifest(self, material_id: str) -> Any:
        if ("manifest", material_id) in self._failures:
            raise OSError(f"simulated unreadable manifest for {material_id}")
        return self._inner.manifest(material_id)

    def outline(self, material_id: str) -> Any:
        if ("outline", material_id) in self._failures:
            raise OSError(f"simulated unreadable outline for {material_id}")
        return self._inner.outline(material_id)

    def unit_references(self, material_id: str) -> Any:
        if ("unit_references", material_id) in self._failures:
            raise OSError(f"simulated unreadable unit references for {material_id}")
        return self._inner.unit_references(material_id)

    def unit_text(self, material_id: str, locator: int) -> str:
        if ("unit_text", material_id, locator) in self._failures:
            raise OSError(f"simulated unreadable unit file {material_id}#{locator}")
        return self._inner.unit_text(material_id, locator)

    def revisions(self, material_id: str) -> Any:
        if ("revisions", material_id) in self._failures:
            raise OSError(f"simulated unreadable revision log for {material_id}")
        return self._inner.revisions(material_id)

    def revision_unit_text(self, material_id: str, revision: int, locator: int) -> str:
        if ("revision_unit_text", material_id, revision, locator) in self._failures:
            raise OSError(f"simulated unreadable revision unit {material_id} r{revision}#{locator}")
        return self._inner.revision_unit_text(material_id, revision, locator)


def _reference(material_id: str, revision: int, locators: list[int]) -> dict[str, Any]:
    return {"material_id": material_id, "revision": revision, "locators": locators}


def _ingest(store: ReadingStore, material_id: str, units: list[str], filename: str) -> Any:
    return store.ingest_units(
        material_id,
        filename=filename,
        units=units,
        source_type="url_snapshot",
    )


def test_unreadable_manifest_skips_only_that_material(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    damaged = _ingest(store, DAMAGED_ID, ["Damaged material text."], "damaged.md")
    healthy = _ingest(store, HEALTHY_ID, ["Healthy material text."], "healthy.md")
    corrupt = _CorruptStore(store, {("manifest", damaged.material_id)})

    resolved = resolve_reading_sources(
        [
            _reference(damaged.material_id, damaged.revision, [1]),
            _reference(healthy.material_id, healthy.revision, [1]),
        ],
        store=corrupt,
    )

    assert [row.source_id for row in resolved] == [
        f"rd-{healthy.material_id}-r{healthy.revision}-1"
    ]
    assert "Healthy material text." in resolved[0].full_text
    assert DAMAGED_ID not in resolved[0].full_text


def test_all_manifests_unreadable_degrades_to_empty_without_raising(
    tmp_path: Path,
) -> None:
    store = ReadingStore(tmp_path / "reading")
    first = _ingest(store, DAMAGED_ID, ["First material text."], "first.md")
    second = _ingest(store, HEALTHY_ID, ["Second material text."], "second.md")
    corrupt = _CorruptStore(
        store,
        {("manifest", first.material_id), ("manifest", second.material_id)},
    )

    resolved = resolve_reading_sources(
        [
            _reference(first.material_id, first.revision, [1]),
            _reference(second.material_id, second.revision, [1]),
        ],
        store=corrupt,
    )

    assert resolved == []


def test_unreadable_unit_file_skips_only_that_locator(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    material = _ingest(
        store,
        DAMAGED_ID,
        ["Unit one text.", "Unit two text.", "Unit three text."],
        "book.md",
    )
    corrupt = _CorruptStore(store, {("unit_text", material.material_id, 2)})

    resolved = resolve_reading_sources(
        [_reference(material.material_id, material.revision, [1, 2, 3])],
        store=corrupt,
    )

    assert [row.source_id for row in resolved] == [
        f"rd-{material.material_id}-r{material.revision}-1",
        f"rd-{material.material_id}-r{material.revision}-3",
    ]
    assert "Unit two text." not in "".join(row.full_text for row in resolved)


def test_all_unit_files_unreadable_degrade_to_empty_without_raising(
    tmp_path: Path,
) -> None:
    store = ReadingStore(tmp_path / "reading")
    material = _ingest(
        store,
        DAMAGED_ID,
        ["Unit one text.", "Unit two text.", "Unit three text."],
        "book.md",
    )
    corrupt = _CorruptStore(
        store,
        {("unit_text", material.material_id, locator) for locator in (1, 2, 3)},
    )

    resolved = resolve_reading_sources(
        [_reference(material.material_id, material.revision, [1, 2, 3])],
        store=corrupt,
    )

    assert resolved == []


def test_unreadable_metadata_failure_is_indistinguishable_from_missing(
    tmp_path: Path,
) -> None:
    """Corrupt metadata and a never-ingested material degrade identically."""
    store = ReadingStore(tmp_path / "reading")
    healthy = _ingest(store, HEALTHY_ID, ["Healthy material text."], "healthy.md")
    corrupt = _CorruptStore(store, {("manifest", CORRUPT_ONLY_ID)})

    degraded = resolve_reading_sources(
        [_reference(CORRUPT_ONLY_ID, 1, [1])],
        store=corrupt,
    )
    absent = resolve_reading_sources(
        [_reference(MISSING_ID, 1, [1])],
        store=store,
    )
    available = resolve_reading_sources(
        [_reference(healthy.material_id, healthy.revision, [1])],
        store=store,
    )

    assert degraded == absent == []
    assert available != []
    assert all(isinstance(row, ResolvedReadingSource) for row in available)


def test_stale_reference_with_unreadable_revision_log_is_skipped(
    tmp_path: Path,
) -> None:
    store = ReadingStore(tmp_path / "reading")
    first = _ingest(store, DAMAGED_ID, ["Original revision text."], "story.md")
    second = store.ingest_units(
        DAMAGED_ID,
        filename="story.md",
        units=["Replacement revision text."],
        source_type="url_snapshot",
    )
    assert second.revision == first.revision + 1
    corrupt = _CorruptStore(store, {("revisions", DAMAGED_ID)})

    resolved = resolve_reading_sources(
        [
            _reference(DAMAGED_ID, first.revision, [1]),
            _reference(DAMAGED_ID, second.revision, [1]),
        ],
        store=corrupt,
    )

    assert [row.source_id for row in resolved] == [f"rd-{DAMAGED_ID}-r{second.revision}-1"]


def test_repeated_material_rows_merge_in_first_seen_resolution_order(
    tmp_path: Path,
) -> None:
    store = ReadingStore(tmp_path / "reading")
    alpha = _ingest(
        store,
        DAMAGED_ID,
        ["Alpha one text.", "Alpha two text.", "Alpha three text."],
        "alpha.md",
    )
    beta = _ingest(store, HEALTHY_ID, ["Beta one text."], "beta.md")

    resolved = resolve_reading_sources(
        [
            _reference(alpha.material_id, alpha.revision, [2]),
            _reference(beta.material_id, beta.revision, [1]),
            _reference(alpha.material_id, alpha.revision, [3, 1]),
        ],
        store=store,
    )

    # Repeated rows merge into the first occurrence's slot: alpha resolves
    # as one group (locators 2, then 3 and 1 in arrival order — never
    # re-sorted, and 2 is not duplicated), placed before the later beta row.
    assert [row.source_id for row in resolved] == [
        f"rd-{alpha.material_id}-r{alpha.revision}-2",
        f"rd-{alpha.material_id}-r{alpha.revision}-3",
        f"rd-{alpha.material_id}-r{alpha.revision}-1",
        f"rd-{beta.material_id}-r{beta.revision}-1",
    ]
