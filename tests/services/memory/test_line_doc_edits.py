"""Focused tests for the line-numbered view + line-level edit ops.

Complements ``test_line_doc.py`` with the failure paths: out-of-range
line numbers, non-editable targets, conflicting ops in one batch,
truncated / malformed LLM payloads, numbering stability, and content
consistency of the document after ``apply_edits``.
"""

from __future__ import annotations

from deeptutor.services.memory.consolidator.line_doc import (
    DeleteLinesOp,
    EditReport,
    InsertAfterOp,
    LineView,
    ReplaceLineOp,
    apply_edits,
    parse_edits_payload,
    render_view,
)
from deeptutor.services.memory.document import Document, Entry
from deeptutor.services.memory.ids import is_entry_id, new_entry_id


def _three_entry_doc() -> tuple[Document, list[str]]:
    ids = [new_entry_id() for _ in range(3)]
    doc = Document(
        title="notebook memory",
        sections=[
            (
                "Themes",
                [
                    Entry(
                        id=ids[0],
                        section="Themes",
                        text="uses spaced repetition",
                        refs=["notebook:r1"],
                    ),
                    Entry(
                        id=ids[1],
                        section="Themes",
                        text="prefers Anki over Quizlet",
                        refs=["notebook:r2"],
                    ),
                ],
            ),
            (
                "Open questions",
                [
                    Entry(
                        id=ids[2],
                        section="Open questions",
                        text="epsilon-delta meaning",
                        refs=["notebook:r3"],
                    )
                ],
            ),
        ],
    )
    return doc, ids


def _wide_doc(section_a: int = 10, section_b: int = 5) -> tuple[Document, list[str]]:
    ids = [new_entry_id() for _ in range(section_a + section_b)]
    sections = [
        (
            "Alpha",
            [
                Entry(id=ids[i], section="Alpha", text=f"alpha fact {i}", refs=["notebook:a"])
                for i in range(section_a)
            ],
        ),
        (
            "Beta",
            [
                Entry(
                    id=ids[section_a + i],
                    section="Beta",
                    text=f"beta fact {i}",
                    refs=["notebook:b"],
                )
                for i in range(section_b)
            ],
        ),
    ]
    return Document(title="wide doc", sections=sections), ids


# ── Numbering stability ─────────────────────────────────────────────────


def test_view_line_numbers_contiguous_and_trailing_blank_stripped() -> None:
    doc, ids = _wide_doc()
    view = render_view(doc)
    assert [line.number for line in view.lines] == list(range(1, len(view.lines) + 1))
    # Trailing blank is stripped so line counts stay predictable.
    assert view.lines[-1].kind == "bullet"
    # Lookup tables agree with the rendered order.
    assert [e.id for e in view.entries_in_order] == ids
    assert set(view.entry_by_id) == set(ids)
    bullets = [line for line in view.lines if line.kind == "bullet"]
    assert [line.entry_id for line in bullets] == ids


def test_view_line_lookup_boundaries() -> None:
    doc, _ = _three_entry_doc()
    view = render_view(doc)
    total = len(view.lines)
    assert view.line(1) is not None
    assert view.line(total) is not None
    assert view.line(0) is None
    assert view.line(-1) is None
    assert view.line(total + 1) is None


def test_render_numbered_alignment_and_unnumbered_mode() -> None:
    doc, _ = _wide_doc()
    view = render_view(doc)
    numbered = view.render(with_numbers=True).splitlines()
    width = max(2, len(str(len(view.lines))))
    assert len(numbered) == len(view.lines)
    for i, row in enumerate(numbered, start=1):
        assert row.startswith(f"{i:>{width}}: ")
    plain = view.render(with_numbers=False).splitlines()
    assert plain == [line.text for line in view.lines]


def test_view_stable_after_apply_reinsert_cycle() -> None:
    doc, ids = _three_entry_doc()
    view = render_view(doc)
    delete = DeleteLinesOp(line_start=8, line_end=8, reason="stale")
    anchor = next(line for line in view.lines if line.entry_id == ids[1])
    insert = InsertAfterOp(
        after_line=anchor.number, text="new fact", refs=["notebook:r4"], reason="add"
    )
    new_doc, report = apply_edits(doc, [delete, insert])
    assert not report.rejected
    view2 = render_view(new_doc)
    assert [line.number for line in view2.lines] == list(range(1, len(view2.lines) + 1))
    assert view2.lines[-1].kind == "bullet"
    assert len([line for line in view2.lines if line.kind == "bullet"]) == 3


# ── Out-of-range line numbers ───────────────────────────────────────────


def test_replace_out_of_range_lines_rejected() -> None:
    doc, _ = _three_entry_doc()
    view = render_view(doc)
    for bad_line in (0, len(view.lines) + 1, -3):
        edit = ReplaceLineOp(line=bad_line, new_text="x", refs=["notebook:r1"], reason="r")
        _new_doc, report = apply_edits(doc, [edit])
        assert len(report.rejected) == 1
        assert "out of range" in report.rejected[0].detail


def test_delete_fully_out_of_range_rejected() -> None:
    doc, _ = _three_entry_doc()
    edit = DeleteLinesOp(line_start=99, line_end=100, reason="r")
    _new_doc, report = apply_edits(doc, [edit])
    assert len(report.rejected) == 1
    assert "range covers no entries" in report.rejected[0].detail


def test_delete_inverted_range_rejected() -> None:
    doc, _ = _three_entry_doc()
    edit = DeleteLinesOp(line_start=5, line_end=4, reason="r")
    _new_doc, report = apply_edits(doc, [edit])
    assert len(report.rejected) == 1
    assert "line_end" in report.rejected[0].detail


def test_insert_after_line_out_of_range_without_section_rejected() -> None:
    doc, _ = _three_entry_doc()
    edit = InsertAfterOp(after_line=99, text="x", refs=["notebook:r1"], reason="r")
    _new_doc, report = apply_edits(doc, [edit])
    assert len(report.rejected) == 1
    assert "after_line out of range" in report.rejected[0].detail


def test_insert_top_of_doc_with_explicit_section_applied() -> None:
    doc, ids = _three_entry_doc()
    edit = InsertAfterOp(
        after_line=0, text="top fact", refs=["notebook:r9"], section="Open questions", reason="r"
    )
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    oq = next(entries for name, entries in new_doc.sections if name == "Open questions")
    assert oq[-1].text == "top fact"
    assert all(e.id != i for e in oq[:-1] for i in ids[:2])


def test_insert_anchored_on_title_or_blank_without_section_rejected() -> None:
    doc, _ = _three_entry_doc()
    for anchor_line in (1, 2):  # title line, blank line
        edit = InsertAfterOp(after_line=anchor_line, text="x", refs=["notebook:r1"], reason="r")
        _new_doc, report = apply_edits(doc, [edit])
        assert len(report.rejected) == 1
        assert "no section context" in report.rejected[0].detail


def test_insert_after_section_header_resolves_section_from_header() -> None:
    doc, _ = _three_entry_doc()
    edit = InsertAfterOp(after_line=3, text="appended fact", refs=["notebook:r5"], reason="r")
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    themes = next(entries for name, entries in new_doc.sections if name == "Themes")
    assert themes[-1].text == "appended fact"


# ── Non-editable targets & conflicting ops ──────────────────────────────


def test_replace_on_section_header_or_title_rejected() -> None:
    doc, _ = _three_entry_doc()
    view = render_view(doc)
    for line in view.lines:
        if line.kind in ("title", "section"):
            edit = ReplaceLineOp(line=line.number, new_text="x", refs=["notebook:r1"], reason="r")
            _new_doc, report = apply_edits(doc, [edit])
            assert len(report.rejected) == 1
            assert "not an editable entry" in report.rejected[0].detail


def test_replace_blank_new_text_rejected() -> None:
    doc, ids = _three_entry_doc()
    view = render_view(doc)
    target = next(line for line in view.lines if line.entry_id == ids[0])
    edit = ReplaceLineOp(line=target.number, new_text="   ", refs=["notebook:r1"], reason="r")
    _new_doc, report = apply_edits(doc, [edit])
    assert len(report.rejected) == 1
    assert "new_text empty" in report.rejected[0].detail


def test_delete_range_without_entries_rejected() -> None:
    doc, _ = _three_entry_doc()
    for start, end in ((3, 3), (2, 2), (1, 2)):  # header only / blank only / title+blank
        edit = DeleteLinesOp(line_start=start, line_end=end, reason="r")
        _new_doc, report = apply_edits(doc, [edit])
        assert len(report.rejected) == 1
        assert "range covers no entries" in report.rejected[0].detail


def test_conflicting_delete_then_replace_same_line() -> None:
    doc, ids = _three_entry_doc()
    edit_delete = DeleteLinesOp(line_start=4, line_end=4, reason="drop")
    edit_replace = ReplaceLineOp(line=4, new_text="conflicting", refs=["notebook:r1"], reason="r")
    new_doc, report = apply_edits(doc, [edit_replace, edit_delete])
    # Delete wins (processed first); the replace on the same line is
    # rejected because its entry no longer exists — no corruption.
    assert len(report.applied) == 1 and len(report.rejected) == 1
    assert isinstance(report.applied[0].op, DeleteLinesOp)
    assert isinstance(report.rejected[0].op, ReplaceLineOp)
    assert "not found" in report.rejected[0].detail
    assert all(e.id != ids[0] for e in new_doc.all_entries())


def test_mixed_batch_partial_success_report() -> None:
    doc, ids = _three_entry_doc()
    good = ReplaceLineOp(line=4, new_text="ok text", refs=["notebook:r1"], reason="r")
    bad_line = ReplaceLineOp(line=999, new_text="x", refs=["notebook:r1"], reason="r")
    bad_target = DeleteLinesOp(line_start=3, line_end=3, reason="r")
    new_doc, report = apply_edits(doc, [bad_target, good, bad_line])
    assert isinstance(report, EditReport)
    assert len(report.applied) == 1 and len(report.rejected) == 2
    results = report.all_results
    assert any(r.op is good for r in results if r.status == "applied")
    assert {id(r.op) for r in results if r.status == "rejected"} == {id(bad_line), id(bad_target)}
    assert any(e.text == "ok text" for e in new_doc.all_entries())


# ── Content consistency after apply ─────────────────────────────────────


def test_apply_delete_leaves_original_doc_untouched() -> None:
    doc, ids = _three_entry_doc()
    edit = DeleteLinesOp(line_start=4, line_end=5, reason="drop themes")
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    assert len(new_doc.all_entries()) == 1
    # Original keeps its entries and section structure.
    assert len(doc.all_entries()) == 3
    assert [name for name, _ in doc.sections] == ["Themes", "Open questions"]
    assert doc.find(ids[0]) is not None and doc.find(ids[2]) is not None


def test_insert_assigns_valid_id_and_local_position() -> None:
    doc, ids = _three_entry_doc()
    view = render_view(doc)
    anchor = next(line for line in view.lines if line.entry_id == ids[1])
    edit = InsertAfterOp(
        after_line=anchor.number, text="right after", refs=["notebook:r6"], reason="r"
    )
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    themes = next(entries for name, entries in new_doc.sections if name == "Themes")
    assert [e.text for e in themes][-2:] == ["prefers Anki over Quizlet", "right after"]
    inserted = themes[-1]
    assert is_entry_id(inserted.id)
    assert inserted.id not in ids
    assert inserted.section == "Themes"
    assert inserted.refs == ["notebook:r6"]


def test_multi_entry_delete_span_and_full_empty() -> None:
    doc, ids = _three_entry_doc()
    # Span from first bullet through last bullet: crosses blank + section
    # lines; only bullets count toward deletion.
    edit = DeleteLinesOp(line_start=4, line_end=8, reason="wipe")
    new_doc, report = apply_edits(doc, [edit])
    assert not report.rejected
    assert len(new_doc.all_entries()) == 0
    assert new_doc.sections == []
    detail = report.applied[0].detail
    assert "3" in detail  # deleted 3 entries


def test_double_delete_idempotent_no_corruption() -> None:
    doc, ids = _three_entry_doc()
    edit = DeleteLinesOp(line_start=4, line_end=4, reason="dup")
    new_doc, report = apply_edits(doc, [edit, edit])
    assert len(report.applied) == 2 and not report.rejected
    assert len(new_doc.all_entries()) == 2
    assert all(e.id != ids[0] for e in new_doc.all_entries())
    assert [e.id for e in new_doc.all_entries()] == ids[1:]


# ── Parsing: malformed / truncated / odd payloads ───────────────────────


def test_parse_malformed_truncated_or_missing_json_returns_empty() -> None:
    truncated_mid_object = '{"edits": [{"op": "replace", "line": 4, "new_text": "x", "refs": ["a:b"'
    truncated_in_fence = '```json\n{"edits": [{"op": "delete", "line_start": 4'
    prose_only = "I could not produce any edits, sorry."
    for raw in (truncated_mid_object, truncated_in_fence, prose_only, ""):
        assert parse_edits_payload(raw) == []


def test_parse_unknown_ops_and_non_dict_items_dropped() -> None:
    raw = (
        '{"edits": ['
        '{"op": "truncate", "line": 1}, '
        "42, "
        '"nope", '
        '{"op": "replace", "line": 4, "new_text": "x", "refs": ["a:b"], "reason": "y"}'
        "]}"
    )
    edits = parse_edits_payload(raw)
    assert len(edits) == 1
    assert isinstance(edits[0], ReplaceLineOp)


def test_parse_edits_field_not_a_list_returns_empty() -> None:
    assert parse_edits_payload('{"edits": {"op": "replace", "line": 4}}') == []
    assert parse_edits_payload('{"edits": "replace line 4"}') == []


def test_parse_non_integer_line_fields_dropped() -> None:
    raw = (
        '{"edits": ['
        '{"op": "replace", "line": "L4", "new_text": "x", "refs": ["a:b"], "reason": "r"}, '
        '{"op": "delete", "line_start": null, "line_end": 5, "reason": "r"}, '
        '{"op": "insert", "after_line": "top", "text": "x", "refs": ["a:b"], "reason": "r"}'
        "]}"
    )
    assert parse_edits_payload(raw) == []


def test_parse_top_level_array_and_delete_line_fallback() -> None:
    raw = '[{"op": "delete", "line": 4, "reason": "r"}]'
    edits = parse_edits_payload(raw)
    assert len(edits) == 1
    assert isinstance(edits[0], DeleteLinesOp)
    assert edits[0].line_start == 4 and edits[0].line_end == 4


def test_parse_insert_blank_section_becomes_none_and_text_stripped() -> None:
    raw_ws = (
        '{"edits": ['
        '{"op": "insert", "after_line": 0, "text": "  padded  ", "refs": ["a:b"], '
        '"section": "   ", "reason": "r"}'
        "]}"
    )
    edits = parse_edits_payload(raw_ws)
    assert len(edits) == 1
    assert isinstance(edits[0], InsertAfterOp)
    # Whitespace-only section survives the strip as an empty string —
    # the tolerant parser only maps a *falsy* section to None.
    assert edits[0].section == ""
    assert edits[0].text == "padded"
    raw_empty = (
        '{"edits": ['
        '{"op": "insert", "after_line": 0, "text": "t", "refs": ["a:b"], '
        '"section": "", "reason": "r"}'
        "]}"
    )
    edits_empty = parse_edits_payload(raw_empty)
    assert edits_empty[0].section is None


def test_parsed_ops_roundtrip_through_apply() -> None:
    """End-to-end: LLM-style fenced payload parses, applies, stays consistent."""
    doc, ids = _three_entry_doc()
    raw = """```json
{"edits": [
  {"op": "replace", "line": 4, "new_text": "rewritten", "refs": ["notebook:r1x"], "reason": "clearer"},
  {"op": "insert", "after_line": 5, "text": "inserted", "refs": ["notebook:r7"], "reason": "new"},
  {"op": "delete", "line_start": 8, "line_end": 8, "reason": "stale"}
]}
```"""
    edits = parse_edits_payload(raw)
    assert len(edits) == 3
    new_doc, report = apply_edits(doc, edits)
    assert not report.rejected and len(report.applied) == 3
    assert any(e.text == "rewritten" and e.refs == ["notebook:r1x"] for e in new_doc.all_entries())
    assert all(e.id != ids[2] for e in new_doc.all_entries())
    view = render_view(new_doc)
    assert [line.number for line in view.lines] == list(range(1, len(view.lines) + 1))
    assert view.line(4) is not None and view.line(4).kind == "bullet"


def test_line_view_type_surface() -> None:
    """Public names resolve; LineView repr-free sanity on a tiny doc."""
    doc, _ = _three_entry_doc()
    view = render_view(doc)
    assert isinstance(view, LineView)
    kinds = {line.kind for line in view.lines}
    assert kinds == {"title", "blank", "section", "bullet"}
    assert all(line.section is None for line in view.lines if line.kind != "bullet")
    assert all(line.entry_id is not None for line in view.lines if line.kind == "bullet")
