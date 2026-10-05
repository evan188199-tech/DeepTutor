"""Layered title-block rebuild: input boundary cases.

Covers out-of-order input, sparse/missing physical pages, and duplicate
titles (TOC page vs body) across the ``chapter_rebuild`` layers: text
extraction, adjacent merge, layout page count, the ``rebuild`` filter
pipeline, page-range assignment, mid-page frame detection, level-aware
header rebuild and printed-offset verification.
"""

from __future__ import annotations

import pytest

from deeptutor.textbook_struct import Chapter, rebuild_from_headers_level, verify_offset
from deeptutor.textbook_struct.chapter_rebuild import (
    assign_page_ranges,
    block_text,
    detect_frames,
    layout_page_count,
    merge_adjacent,
    rebuild,
)


def _span(text: str) -> dict:
    return {"content": text}


def _title(text: str, bbox: list[float]) -> dict:
    return {"type": "title", "bbox": bbox, "lines": [{"spans": [_span(text)]}]}


def _page(page_idx: int, blocks: list[dict]) -> dict:
    return {"page_idx": page_idx, "para_blocks": blocks}


def _footer(text: str) -> dict:
    return {"type": "footer", "lines": [{"spans": [_span(text)]}]}


def _page_number(n: str) -> dict:
    return {"type": "page_number", "lines": [{"spans": [_span(n)]}]}


def _furniture_page(page_idx: int, discarded: list[dict]) -> dict:
    return {"page_idx": page_idx, "discarded_blocks": discarded}


# ── block_text: span joining ─────────────────────────────────────────────


def test_block_text_joins_spans_across_lines_and_strips() -> None:
    block = {
        "lines": [
            {"spans": [_span("第一课 "), _span("集合")]},
            {"spans": [_span("与常用逻辑")]},
        ]
    }
    assert block_text(block) == "第一课 集合与常用逻辑"
    assert block_text({}) == ""


# ── merge_adjacent: sort by y0, gap + x-overlap, no input mutation ────────


def test_merge_adjacent_sorts_out_of_order_and_merges_wrap() -> None:
    top = _title("集合与", [10.0, 100.0, 200.0, 122.0])
    bottom = _title("常用逻辑", [12.0, 130.0, 210.0, 152.0])
    merged = merge_adjacent([bottom, top])  # input given bottom-first
    assert len(merged) == 1
    assert merged[0]["text"] == "集合与常用逻辑"
    assert merged[0]["bbox"] == [10.0, 100.0, 210.0, 152.0]
    # Original blocks are untouched (no "text" key, bbox intact).
    assert "text" not in top and top["bbox"] == [10.0, 100.0, 200.0, 122.0]


@pytest.mark.parametrize(
    ("second_bbox", "gap"),
    [
        ([12.0, 182.0, 210.0, 204.0], 40.0),  # vertical gap ≥ merge gap
        ([300.0, 130.0, 400.0, 152.0], 40.0),  # no x-overlap
    ],
)
def test_merge_adjacent_keeps_separate_blocks(second_bbox: list[float], gap: float) -> None:
    top = _title("第一课", [10.0, 100.0, 200.0, 122.0])
    other = _title("第二课", second_bbox)
    merged = merge_adjacent([top, other], gap=gap)
    assert [b["text"] for b in merged] == ["第一课", "第二课"]


# ── layout_page_count: sparse physical page indices ───────────────────────


@pytest.mark.parametrize(
    ("pdf_info", "expected"),
    [
        ([], 0),
        ([_page(0, []), _page(1, []), _page(2, [])], 3),
        ([_page(0, []), _page(19, [])], 20),  # sparse: count up to max index
        ([_page(7, [])], 8),
    ],
)
def test_layout_page_count_sparse_indices(pdf_info: list[dict], expected: int) -> None:
    assert layout_page_count({"pdf_info": pdf_info}) == expected


# ── rebuild: layered filter pipeline ──────────────────────────────────────


def test_rebuild_layer_filters_table() -> None:
    # Every rejected candidate fails exactly one layer: layer 0 blacklist,
    # layer 1 regex, min title length, layer 2 top band. Rejected blocks use
    # distinct lanes / ≥ 40 gaps so merge_adjacent keeps them apart; the one
    # survivor sits alone on its own page.
    layout = {
        "pdf_info": [
            _page(
                0,
                [
                    _title("探究与分享", [10.0, 30.0, 200.0, 52.0]),  # blacklist
                    _title("前言", [10.0, 100.0, 200.0, 122.0]),  # not a chapter token
                    _title("第1课", [300.0, 30.0, 490.0, 52.0]),  # too short (< 4 chars)
                    _title("第一课 集合", [10.0, 240.0, 200.0, 262.0]),  # below top band
                ],
            ),
            _page(1, [_title("第一课 集合与常用逻辑", [10.0, 30.0, 200.0, 52.0])]),
        ]
    }
    chapters = rebuild(layout)
    assert [(c.title, c.page_idx, c.end_page_idx) for c in chapters] == [
        ("第一课 集合与常用逻辑", 1, 2)
    ]


def test_rebuild_dedupe_keeps_body_over_toc() -> None:
    # Same title hits the TOC page (0) and the body (2): keep the body hit.
    layout = {
        "pdf_info": [
            _page(0, [_title("第一课 集合", [10.0, 30.0, 200.0, 52.0])]),
            _page(2, [_title("第一课 集合", [10.0, 30.0, 200.0, 52.0])]),
        ]
    }
    chapters = rebuild(layout)
    assert [(c.title, c.page_idx, c.end_page_idx) for c in chapters] == [("第一课 集合", 2, 3)]


def test_rebuild_missing_pages_fall_inside_preceding_range() -> None:
    # Physical pages 1–4 are absent from pdf_info; sparse indices only.
    layout = {
        "pdf_info": [
            _page(0, [_title("第一课 A", [10.0, 30.0, 200.0, 52.0])]),
            _page(5, [_title("第二课 B", [10.0, 30.0, 200.0, 52.0])]),
            _page(9, [_title("第三课 C", [10.0, 30.0, 200.0, 52.0])]),
        ]
    }
    chapters = rebuild(layout)
    assert layout_page_count(layout) == 10
    assert [(c.title, c.page_idx, c.end_page_idx) for c in chapters] == [
        ("第一课 A", 0, 5),  # pages 1–4 belong to chapter 1
        ("第二课 B", 5, 9),
        ("第三课 C", 9, 10),  # final range reaches the last physical page
    ]


def test_rebuild_pages_out_of_order_output_sorted() -> None:
    layout = {
        "pdf_info": [
            _page(5, [_title("第二课 B", [10.0, 30.0, 200.0, 52.0])]),
            _page(0, [_title("第一课 A", [10.0, 30.0, 200.0, 52.0])]),
        ]
    }
    chapters = rebuild(layout)
    assert [c.title for c in chapters] == ["第一课 A", "第二课 B"]
    assert [c.page_idx for c in chapters] == [0, 5]
    assert [c.end_page_idx for c in chapters] == [5, 6]


# ── assign_page_ranges: sorting + same-page + over-count edge ─────────────


def test_assign_page_ranges_sorts_and_handles_same_page_and_overcount() -> None:
    # Chapters arrive unordered; sort is stable, so same-page ties keep
    # their relative input order.
    chapters = [
        Chapter("A2", 2, []),
        Chapter("A1", 2, []),
        Chapter("B", 5, []),
    ]
    assign_page_ranges(chapters, page_count=3)
    assert [(c.title, c.page_idx, c.end_page_idx) for c in chapters] == [
        ("A2", 2, 3),  # next chapter starts on the same page → at least own+1
        ("A1", 2, 5),
        ("B", 5, 6),  # page_count undercounts the physical page → own+1 wins
    ]


# ── detect_frames: height bands + noise filters + guards ──────────────────


def test_detect_frames_band_table() -> None:
    layout = {
        "pdf_info": [
            _page(
                1,
                [
                    _title("框题探究详解", [10.0, 100.0, 200.0, 122.0]),  # frame band (h 22)
                    _title("综合探究", [10.0, 150.0, 200.0, 177.0]),  # extras band (h 27)
                    _title("第一课 集合", [10.0, 300.0, 200.0, 322.0]),  # lesson level
                    _title("探究与分享", [10.0, 400.0, 200.0, 422.0]),  # blacklist
                    _title("思想政治", [10.0, 500.0, 200.0, 527.0]),  # publisher noise
                    _title("框探究", [10.0, 600.0, 200.0, 622.0]),  # too short for frame
                ],
            )
        ]
    }
    frames, extras = detect_frames(layout)
    assert [(f["title"], f["page_idx"]) for f in frames] == [("框题探究详解", 1)]
    assert [(e["title"], e["page_idx"]) for e in extras] == [("综合探究", 1)]
    assert frames[0]["height"] == 22.0


def test_detect_frames_guards_drop_front_matter_and_residue() -> None:
    layout = {
        "pdf_info": [
            _page(1, [_title("集合间的关系", [10.0, 100.0, 200.0, 122.0])]),
            _page(3, [_title("集合间的关系", [10.0, 100.0, 200.0, 122.0])]),
        ]
    }
    # Guard 1: frames before the first lesson page are front matter.
    frames, _ = detect_frames(layout, first_lesson_page_idx=3)
    assert [f["page_idx"] for f in frames] == [3]
    # Guard 2: wrap residue that is a substring of a lesson title is dropped.
    frames, _ = detect_frames(layout, lesson_titles=["第一课 集合间的关系"])
    assert frames == []


# ── rebuild_from_headers_level: boundary inputs ───────────────────────────


def test_rebuild_level_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="unknown unit"):
        rebuild_from_headers_level({}, unit="篇")


def test_rebuild_level_pages_out_of_order_output_sorted() -> None:
    layout = {
        "pdf_info": [
            _furniture_page(2, [_footer("第二章 B"), _page_number("5")]),
            _furniture_page(0, [_footer("第一章 A"), _page_number("1")]),
        ]
    }
    chapters = rebuild_from_headers_level(layout, unit="章")
    assert [(c.title, c.page_idx) for c in chapters] == [("第一章 A", 0), ("第二章 B", 2)]


# ── verify_offset: printed-offset consistency table ───────────────────────


@pytest.mark.parametrize(
    ("printed_pages", "expected"),
    [
        ([2, 5], {"offsets": [0], "consistent": True, "ok": True}),  # constant offset 0
        ([2, 3], {"offsets": [0, 2], "consistent": False, "ok": False}),  # boundary drift
        ([None], {"offsets": [], "consistent": True, "ok": False}),  # nothing to verify
    ],
)
def test_verify_offset_table(printed_pages: list[int | None], expected: dict) -> None:
    chapters = [
        Chapter(f"C{i}", page_idx, [], meta={"printed_page": printed})
        for i, (page_idx, printed) in enumerate(zip([1, 4], printed_pages))
    ]
    result = verify_offset(chapters)
    assert result["offsets"] == expected["offsets"]
    assert result["consistent"] is expected["consistent"]
    assert result["ok"] is expected["ok"]
