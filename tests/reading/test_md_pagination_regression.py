"""Regression fixtures for the reading module's Markdown pagination (#1641).

Every test here is keyed to a known defect scenario from upstream issues
HKUDS/DeepTutor#1641 and #1637, exercised through the local ``.md`` upload
path (``ReadingStore.ingest`` → ``extract_material``), which is the path the
reporter used. The fence-tracking scenarios must flip green when the fence
fix (upstream PR #1637) lands; the flat-fallback guard pins the store-level
answer to #1641's maintainer question about empty outlines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.reading import ReadingStore

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reading"


@pytest.fixture
def store(tmp_path: Path) -> ReadingStore:
    return ReadingStore(root=tmp_path / "materials")


def _outline_titles(store: ReadingStore, material_id: str) -> list[str]:
    return [row.title for row in store.outline(material_id)]


def test_nested_longer_fence_keeps_example_comments_out_of_outline(store, tmp_path) -> None:
    """#1637 case 1 / #1641: a ```` fence wraps a ``` example; the example's
    ``# Install dependencies`` comment is code content, not an outline row."""
    manifest = store.ingest(FIXTURES / "issue1641_nested_fence.md")

    titles = _outline_titles(store, manifest.material_id)

    assert titles == ["Writing READMEs", "Code blocks", "Publishing"]


def test_pseudo_fence_line_with_backticks_keeps_later_headings(store, tmp_path) -> None:
    """#1637 case 3 / #1641: a line like `` ```inline``` text `` is not a fence
    opener (its info string contains a backtick), so later headings survive."""
    manifest = store.ingest(FIXTURES / "issue1641_pseudo_fence.md")

    titles = _outline_titles(store, manifest.material_id)

    assert titles == ["Field notes", "Alpha", "Beta"]


def test_flat_fallback_stores_synthesised_outline_rows(store, tmp_path) -> None:
    """#1641 maintainer question: a document with only one usable heading falls
    back to flat sections — the stored outline must still get one synthesised
    row per unit so the reader paginates instead of showing a single page."""
    manifest = store.ingest(FIXTURES / "issue1641_flat_fallback.md")

    units = list(store.iter_units(manifest.material_id))
    outline = store.outline(manifest.material_id)

    assert manifest.unit_count > 1
    assert len(units) == manifest.unit_count
    assert len(outline) == manifest.unit_count
    assert all(row.synthesised for row in outline)
    assert [row.locator for row in outline] == list(range(1, manifest.unit_count + 1))
