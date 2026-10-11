"""page_headers degradation + non-level rebuild contract.

Complements ``test_page_headers.py`` (which drives the level-aware path):
these cover the branches the existing suite misses — empty/abnormal
``discarded_blocks`` degradation in :func:`page_facts`, and the plain
``rebuild_from_headers`` footer/header pipeline end to end (seen-dedupe,
printed-page meta, sparse page counts).
"""

from __future__ import annotations

from deeptutor.textbook_struct.page_headers import (
    normalize_header_chapter,
    page_facts,
    rebuild_from_headers,
)


def _page(page_idx: int, discarded: list[dict]) -> dict:
    return {"page_idx": page_idx, "discarded_blocks": discarded}


def _footer(text: str) -> dict:
    return {"type": "footer", "lines": [{"spans": [{"content": text}]}]}


def _header(text: str) -> dict:
    return {"type": "header", "lines": [{"spans": [{"content": text}]}]}


def _page_number(n: str) -> dict:
    return {"type": "page_number", "lines": [{"spans": [{"content": n}]}]}


# ── normalize: pre/post length contracts (20/30-char cut-offs) ────────────


def test_normalize_accepts_pre_name_at_twenty_chars() -> None:
    name = "前" * 20
    assert normalize_header_chapter(f"{name}第3章") == f"第3章 {name}"


def test_normalize_rejects_pre_name_over_twenty_chars() -> None:
    assert normalize_header_chapter(f"{'前' * 21}第3章") is None


def test_normalize_accepts_post_name_at_thirty_chars() -> None:
    name = "后" * 30
    assert normalize_header_chapter(f"第3章{name}") == f"第3章 {name}"


def test_normalize_rejects_post_name_over_thirty_chars() -> None:
    assert normalize_header_chapter(f"第3章{'后' * 31}") is None


# ── page_facts: degraded and non-matching furniture is ignored ────────────


def test_page_facts_skips_blocks_without_text() -> None:
    # No lines, no spans, empty content, whitespace-only — none of these
    # may crash the pass or contribute a chapter/pageno.
    discarded = [
        {"type": "footer"},
        {"type": "footer", "lines": []},
        {"type": "header", "lines": [{"spans": []}]},
        {"type": "page_number", "lines": [{"spans": [{"content": "   "}]}]},
    ]
    assert page_facts(_page(0, discarded)) == ([], "")


def test_page_facts_ignores_non_chapter_footer_and_header() -> None:
    discarded = [
        _footer("人民教育出版社"),  # footer without a chapter token
        _header("高中数学·必修第一册"),  # header without a chapter token
    ]
    assert page_facts(_page(0, discarded)) == ([], "")


def test_page_facts_ignores_non_digit_page_number() -> None:
    footers, printed = page_facts(_page(0, [_footer("第一章 集合"), _page_number("iv-12")]))
    assert footers == ["第一章 集合"]
    assert printed == ""


def test_page_facts_last_page_number_block_wins() -> None:
    _, printed = page_facts(_page(0, [_page_number("4"), _page_number("5")]))
    assert printed == "5"


def test_page_facts_tolerates_missing_discarded_blocks() -> None:
    assert page_facts({"page_idx": 0}) == ([], "")


# ── rebuild_from_headers: non-level pipeline end to end ───────────────────


def test_rebuild_from_headers_dedupes_repeats_and_mixed_channels() -> None:
    layout = {
        "pdf_info": [
            _page(0, [_header("高中数学·必修第一册"), _page_number("1")]),  # cover: no chapter
            _page(1, [_footer("第一章 集合"), _page_number("2")]),
            _page(2, [_footer("第一章 集合"), _page_number("3")]),  # repeat → no new chapter
            _page(5, [_header("函数 第2章"), _page_number("6")]),  # header channel
            _page(7, [_footer("第2章 函数"), _page_number("8")]),  # same title verbatim → deduped
            _page(9, [_footer("第三章 统计"), _page_number("iv")]),  # printed stays absent
        ]
    }
    chapters = rebuild_from_headers(layout)
    assert [c.title for c in chapters] == ["第一章 集合", "第2章 函数", "第三章 统计"]
    assert [c.page_idx for c in chapters] == [1, 5, 9]
    # page_count from sparse indices: last physical page_idx + 1.
    assert [c.end_page_idx for c in chapters] == [5, 9, 10]
    # Header path always carries an empty bbox; printed page is best-effort.
    assert all(c.bbox == [] for c in chapters)
    assert [c.meta["printed_page"] for c in chapters] == [2, 6, None]


def test_rebuild_from_headers_empty_layout_returns_empty() -> None:
    assert rebuild_from_headers({}) == []
    assert rebuild_from_headers({"pdf_info": []}) == []
