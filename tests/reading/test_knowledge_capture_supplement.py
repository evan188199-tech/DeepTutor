"""Supplementary tests for reading annotation -> Notebook/Mastery capture.

These tests exercise `deeptutor.reading.knowledge_capture` against fake
catalog / reading stores and a fake notebook manager, so no real storage or
service layer is touched. Coverage focus: material dedup and locator grouping
in `organize_workspace_notes`, the record shape and bounds of
`mastery_source_records`, and the failure branches of
`send_workspace_to_notebook`.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from deeptutor.reading.catalog_models import (
    MaterialRecord,
    SourceKind,
    WorkspaceRecord,
    WorkspaceTab,
)
from deeptutor.reading.knowledge_capture import (
    mastery_source_records,
    organize_workspace_notes,
    send_workspace_to_notebook,
)
from deeptutor.reading.models import Annotation, MaterialManifest, MaterialNotFound, OutlineEntry, ReadingError


class _FakeCatalog:
    def __init__(self, *workspaces: WorkspaceRecord) -> None:
        self._workspaces = {w.workspace_id: w for w in workspaces}

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        return self._workspaces.get(workspace_id)


class _FakeReadingStore:
    def __init__(self) -> None:
        self._manifests: dict[str, MaterialManifest] = {}
        self._annotations: dict[str, list[Annotation]] = {}
        self._outlines: dict[str, list[OutlineEntry]] = {}
        self._units: dict[str, list[tuple[int, str]]] = {}

    def add_material(
        self,
        material_id: str,
        *,
        title: str,
        units: list[str],
        annotations: list[Annotation] | None = None,
        outline: list[OutlineEntry] | None = None,
        unit: str = "section",
    ) -> None:
        self._manifests[material_id] = MaterialManifest(
            material_id=material_id,
            filename=f"{material_id}.md",
            unit=unit,
            unit_count=len(units),
        )
        self._units[material_id] = list(enumerate(units, start=1))
        self._annotations[material_id] = list(annotations or ())
        self._outlines[material_id] = list(outline or ())

    def manifest(self, material_id: str) -> MaterialManifest:
        if material_id not in self._manifests:
            raise MaterialNotFound(f"material {material_id!r} not found")
        return self._manifests[material_id]

    def annotations(self, material_id: str) -> list[Annotation]:
        return list(self._annotations.get(material_id, ()))

    def outline(self, material_id: str) -> list[OutlineEntry]:
        return list(self._outlines.get(material_id, ()))

    def iter_units(self, material_id: str) -> Iterator[tuple[int, str]]:
        yield from self._units.get(material_id, ())


class _FakeNotebookManager:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls: list[dict] = []

    def add_record(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return dict(self._result)


def _material(material_id: str, title: str) -> MaterialRecord:
    return MaterialRecord(
        material_id=material_id,
        content_id=f"content-{material_id}",
        filename=f"{material_id}.md",
        title=title,
        source_kind=SourceKind.FILE,
    )


def _workspace(workspace_id: str, title: str, material_ids: list[str]) -> WorkspaceRecord:
    tabs = tuple(
        WorkspaceTab(material=_material(material_id, material_id.title()), tab_order=order)
        for order, material_id in enumerate(material_ids)
    )
    return WorkspaceRecord(workspace_id=workspace_id, title=title, tabs=tabs)


def _annotation(annotation_id: str, locator: int, quote: str = "", note: str = "") -> Annotation:
    return Annotation(annotation_id=annotation_id, locator=locator, quote=quote, note=note)


def _two_material_fixture() -> tuple[_FakeCatalog, _FakeReadingStore]:
    catalog = _FakeCatalog(_workspace("w1", "Synthesis", ["m1", "m2"]))
    store = _FakeReadingStore()
    store.add_material(
        "m1",
        title="m1.md",
        units=["alpha one", "alpha two"],
        annotations=[
            _annotation("a1", 1, quote="first highlight", note="needs synthesis"),
            _annotation("a2", 2, quote="second highlight"),
        ],
    )
    store.add_material(
        "m2",
        title="m2.md",
        units=["beta one"],
        annotations=[_annotation("b1", 1, quote="beta highlight")],
    )
    return catalog, store


def test_organize_dedups_material_ids_and_preserves_requested_order() -> None:
    catalog, store = _two_material_fixture()

    notes = organize_workspace_notes(
        "w1",
        material_ids=["m1", "m2", "m1"],
        catalog=catalog,
        reading_store=store,
    )

    assert notes.workspace_id == "w1"
    assert notes.title == "Synthesis"
    assert notes.material_ids == ("m1", "m2")
    assert notes.markdown.count("## M1") == 1
    assert notes.markdown.count("## M2") == 1
    assert notes.markdown.index("## M1") < notes.markdown.index("## M2")
    assert notes.annotation_count == 3
    payload = notes.to_dict()
    assert payload["material_ids"] == ["m1", "m2"]
    assert payload["annotation_count"] == 3


def test_organize_groups_annotations_by_locator_with_outline_and_fallback_labels() -> None:
    catalog = _FakeCatalog(_workspace("w2", "Chapter Notes", ["m1"]))
    store = _FakeReadingStore()
    store.add_material(
        "m1",
        title="m1.md",
        unit="chapter",
        units=["c1", "c2", "c3", "c5"],
        outline=[OutlineEntry(locator=1, title="Intro"), OutlineEntry(locator=3, title="Results")],
        annotations=[
            _annotation("x1", 1, quote="intro quote", note="intro note"),
            _annotation("x2", 1, quote="intro quote two"),
            _annotation("x3", 3, quote="results quote"),
            _annotation("x4", 5, note="loose note"),
        ],
    )

    notes = organize_workspace_notes("w2", catalog=catalog, reading_store=store)

    markdown = notes.markdown
    assert markdown.count("### Intro") == 1
    assert markdown.count("### Results") == 1
    assert markdown.count("### Chapter 5") == 1
    assert markdown.index("### Intro") < markdown.index("### Results") < markdown.index("### Chapter 5")
    assert "> intro quote" in markdown
    assert "> intro quote two" in markdown
    assert "intro note" in markdown
    assert "> results quote" in markdown
    assert "`x1`" in markdown and "`x4`" in markdown
    assert "locator 3" in markdown
    assert notes.annotation_count == 4


def test_organize_material_without_annotations_lists_placeholder() -> None:
    catalog = _FakeCatalog(_workspace("wp", "Quiet Workspace", ["m2"]))
    store = _FakeReadingStore()
    store.add_material("m2", title="m2.md", units=["untouched unit"])

    notes = organize_workspace_notes(
        "wp",
        catalog=catalog,
        reading_store=store,
    )

    assert "_No highlights or notes captured yet._" in notes.markdown
    assert notes.annotation_count == 0
    assert notes.material_ids == ("m2",)


def test_organize_rejects_unknown_workspace_and_foreign_material() -> None:
    catalog, store = _two_material_fixture()

    with pytest.raises(ReadingError, match="not found"):
        organize_workspace_notes("missing", catalog=catalog, reading_store=store)
    with pytest.raises(ReadingError, match="does not belong"):
        organize_workspace_notes("w1", material_ids=["ghost"], catalog=catalog, reading_store=store)


def test_send_to_notebook_requires_at_least_one_notebook() -> None:
    catalog, store = _two_material_fixture()
    manager = _FakeNotebookManager({"added_to_notebooks": ["nb-1"]})

    with pytest.raises(ReadingError, match="choose at least one notebook"):
        send_workspace_to_notebook(
            "w1",
            [],
            catalog=catalog,
            reading_store=store,
            notebook_manager=manager,
        )
    assert manager.calls == []


def test_send_to_notebook_raises_when_no_selected_notebook_exists() -> None:
    catalog, store = _two_material_fixture()
    manager = _FakeNotebookManager({"added_to_notebooks": [], "record": {}})

    with pytest.raises(ReadingError, match="none of the selected notebooks exists"):
        send_workspace_to_notebook(
            "w1",
            ["nb-gone"],
            catalog=catalog,
            reading_store=store,
            notebook_manager=manager,
        )
    assert len(manager.calls) == 1


def test_send_to_notebook_success_passes_metadata_and_returns_notes() -> None:
    catalog, store = _two_material_fixture()
    manager = _FakeNotebookManager(
        {"added_to_notebooks": ["nb-1"], "record": {"id": "rec-1", "type": "reading"}}
    )

    result = send_workspace_to_notebook(
        "w1",
        ["nb-1"],
        material_ids=["m1"],
        catalog=catalog,
        reading_store=store,
        notebook_manager=manager,
    )

    call = manager.calls[0]
    assert call["notebook_ids"] == ["nb-1"]
    assert call["record_type"] == "reading"
    assert call["title"] == "Synthesis"
    assert call["user_query"] == "Organize my Immersive Reading notes"
    assert call["metadata"] == {
        "reading_workspace_id": "w1",
        "reading_material_ids": ["m1"],
        "annotation_count": 2,
    }
    organized = organize_workspace_notes("w1", material_ids=["m1"], catalog=catalog, reading_store=store)
    assert call["output"] == organized.markdown
    assert result["added_to_notebooks"] == ["nb-1"]
    assert result["record"]["id"] == "rec-1"
    assert result["notes"] == organized.to_dict()


def test_send_to_notebook_title_and_summary_overrides_are_stripped() -> None:
    catalog, store = _two_material_fixture()
    manager = _FakeNotebookManager({"added_to_notebooks": ["nb-1"]})

    send_workspace_to_notebook(
        "w1",
        ["nb-1"],
        title="  Reading digest  ",
        summary="  weekly digest  ",
        catalog=catalog,
        reading_store=store,
        notebook_manager=manager,
    )

    assert manager.calls[0]["title"] == "Reading digest"
    assert manager.calls[0]["summary"] == "weekly digest"


def test_mastery_records_have_bounded_shape_and_unit_prefixes() -> None:
    catalog, store = _two_material_fixture()

    records = mastery_source_records("w1", catalog=catalog, reading_store=store)

    assert [record["id"] for record in records] == ["m1", "m2"]
    assert all(set(record) == {"id", "type", "title", "output"} for record in records)
    assert all(record["type"] == "reading" for record in records)
    assert [record["title"] for record in records] == ["M1", "M2"]
    assert records[0]["output"].startswith("[section 1]")
    assert "[section 1] alpha one" in records[0]["output"]
    assert "[section 2] alpha two" in records[0]["output"]
    assert "[section 1] beta one" in records[1]["output"]


def test_mastery_output_respects_max_chars_and_floors_at_500() -> None:
    catalog = _FakeCatalog(_workspace("wb", "Bounded", ["m1"]))
    store = _FakeReadingStore()

    long_unit = "x" * 700
    store.add_material("m1", title="m1.md", units=[long_unit])
    records = mastery_source_records(
        "wb",
        catalog=catalog,
        reading_store=store,
        max_chars_per_material=600,
    )
    assert len(records[0]["output"]) == 600

    catalog_small = _FakeCatalog(_workspace("wc", "Floored", ["m1"]))
    records = mastery_source_records(
        "wc",
        catalog=catalog_small,
        reading_store=store,
        max_chars_per_material=10,
    )
    assert len(records[0]["output"]) == 500


def test_mastery_output_stops_after_budget_is_spent_across_units() -> None:
    catalog = _FakeCatalog(_workspace("wd", "Multi unit", ["m1"]))
    store = _FakeReadingStore()
    store.add_material("m1", title="m1.md", units=["u" * 400, "v" * 400, "w" * 400])

    records = mastery_source_records(
        "wd",
        catalog=catalog,
        reading_store=store,
        max_chars_per_material=500,
    )

    output = records[0]["output"]
    assert output.startswith("[section 1]")
    assert "[section 2]" in output
    assert "[section 3]" not in output
    assert len(output) == len("[section 1] " + "u" * 400) + 2 + len(("[section 2] " + "v" * 400)[:88])


def test_mastery_dedups_selection_and_rejects_foreign_or_missing_sources() -> None:
    catalog, store = _two_material_fixture()

    records = mastery_source_records(
        "w1",
        material_ids=["m2", "m2"],
        catalog=catalog,
        reading_store=store,
    )
    assert [record["id"] for record in records] == ["m2"]

    with pytest.raises(ReadingError, match="Mastery source does not belong"):
        mastery_source_records("w1", material_ids=["ghost"], catalog=catalog, reading_store=store)
    with pytest.raises(ReadingError, match="not found"):
        mastery_source_records("missing", catalog=catalog, reading_store=store)


def test_mastery_caps_selected_materials_at_twenty_in_tab_order() -> None:
    material_ids = [f"m{index:02d}" for index in range(24)]
    catalog = _FakeCatalog(_workspace("wcap", "Wide Workspace", material_ids))
    store = _FakeReadingStore()
    for material_id in material_ids:
        store.add_material(material_id, title=f"{material_id}.md", units=["only unit"])

    records = mastery_source_records("wcap", catalog=catalog, reading_store=store)

    assert len(records) == 20
    assert [record["id"] for record in records] == material_ids[:20]


def test_mastery_material_without_units_yields_empty_output_record() -> None:
    catalog = _FakeCatalog(_workspace("we", "Empty Units", ["m1"]))
    store = _FakeReadingStore()
    store.add_material("m1", title="m1.md", units=[])

    records = mastery_source_records("we", catalog=catalog, reading_store=store)

    assert len(records) == 1
    assert records[0]["id"] == "m1"
    assert records[0]["output"] == ""
