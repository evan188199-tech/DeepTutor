"""Unit tests for :mod:`deeptutor_cli._tool_result` truncation and buffering.

The module is pure logic with no I/O; these tests pin the boundary behavior
the CLI REPL depends on: ``truncate_for_display`` head-line budgeting
(``head_lines <= 0``, the exactly-equal case, per-line hard clipping and the
hidden-line count), the ``ToolResultBuffer`` ring capacity with stable
indices across eviction, and the ``/show`` selector resolution on
``ToolResultBuffer.get``.
"""

from __future__ import annotations

from deeptutor_cli._tool_result import (
    DEFAULT_HEAD_LINES,
    DEFAULT_LINE_HARD_CAP,
    DEFAULT_RING_CAPACITY,
    ToolResultBuffer,
    ToolResultEntry,
    truncate_for_display,
)


def test_head_lines_zero_hides_every_line() -> None:
    assert truncate_for_display("a\nb\nc", head_lines=0) == ("", 3)


def test_head_lines_negative_hides_every_line() -> None:
    assert truncate_for_display("a\nb", head_lines=-1) == ("", 2)


def test_head_lines_zero_on_empty_body_reports_zero_hidden() -> None:
    assert truncate_for_display("", head_lines=0) == ("", 0)


def test_head_lines_exactly_equal_to_line_count_keeps_full_body() -> None:
    assert truncate_for_display("a\nb\nc", head_lines=3) == ("a\nb\nc", 0)


def test_head_lines_beyond_line_count_keeps_full_body() -> None:
    assert truncate_for_display("a\nb", head_lines=DEFAULT_HEAD_LINES) == ("a\nb", 0)


def test_overflow_slices_head_and_counts_hidden_lines() -> None:
    assert truncate_for_display("1\n2\n3\n4\n5", head_lines=2) == ("1\n2", 3)


def test_default_head_budget_hides_exactly_one_line() -> None:
    body = "\n".join(str(i) for i in range(DEFAULT_HEAD_LINES + 1))
    visible, hidden = truncate_for_display(body)
    assert visible == "\n".join(str(i) for i in range(DEFAULT_HEAD_LINES))
    assert hidden == 1


def test_hidden_count_uses_raw_lines_not_clipped_lines() -> None:
    _, hidden = truncate_for_display("x" * 300 + "\nrest", head_lines=1)
    assert hidden == 1


def test_overlong_line_clipped_to_default_cap_with_ellipsis() -> None:
    visible, hidden = truncate_for_display("a" * 500, head_lines=1)
    assert len(visible) == DEFAULT_LINE_HARD_CAP
    assert visible.endswith("…")
    assert visible[: DEFAULT_LINE_HARD_CAP - 1] == "a" * (DEFAULT_LINE_HARD_CAP - 1)
    assert hidden == 0


def test_custom_cap_clips_every_head_line_independently() -> None:
    assert truncate_for_display("abcdef\nshort", head_lines=2, line_hard_cap=4) == (
        "abc…\nsho…",
        0,
    )
    assert truncate_for_display("abcdef\nok", head_lines=2, line_hard_cap=4) == (
        "abc…\nok",
        0,
    )


def test_line_exactly_at_cap_is_not_clipped() -> None:
    line = "c" * DEFAULT_LINE_HARD_CAP
    assert truncate_for_display(line, head_lines=1) == (line, 0)


def test_non_positive_cap_disables_clipping() -> None:
    line = "b" * 1000
    assert truncate_for_display(line, head_lines=1, line_hard_cap=0) == (line, 0)
    assert truncate_for_display(line, head_lines=1, line_hard_cap=-5) == (line, 0)


def test_buffer_defaults_match_module_constants() -> None:
    buf = ToolResultBuffer()
    assert buf.capacity == DEFAULT_RING_CAPACITY
    assert buf.head_lines == DEFAULT_HEAD_LINES
    assert buf.line_hard_cap == DEFAULT_LINE_HARD_CAP


def test_remember_assigns_monotonic_one_based_indices() -> None:
    buf = ToolResultBuffer()
    first = buf.remember("rag", "one")
    second = buf.remember("web", "two")
    assert (first.index, first.label, first.body) == (1, "rag", "one")
    assert second.index == 2


def test_remember_empty_label_defaults_to_tool() -> None:
    assert ToolResultBuffer().remember("", "x").label == "tool"


def test_ring_evicts_oldest_and_preserves_survivor_indices() -> None:
    buf = ToolResultBuffer(capacity=2)
    buf.remember("a", "1")
    buf.remember("b", "2")
    buf.remember("c", "3")
    assert [entry.index for entry in buf.entries()] == [2, 3]
    assert buf.get(1) is None
    survivor = buf.get(2)
    assert survivor is not None and survivor.body == "2"


def test_capacity_zero_keeps_nothing() -> None:
    buf = ToolResultBuffer(capacity=0)
    buf.remember("a", "1")
    assert buf.entries() == []
    assert buf.last() is None


def test_indices_stay_stable_after_repeated_eviction() -> None:
    buf = ToolResultBuffer(capacity=1)
    for i in range(5):
        buf.remember(f"t{i}", str(i))
    assert buf.last() is not None and buf.last().index == 5
    assert buf.get("5") is not None and buf.get("5").index == 5


def test_clear_resets_entries_and_index_counter() -> None:
    buf = ToolResultBuffer(capacity=2)
    buf.remember("a", "1")
    buf.clear()
    assert buf.entries() == []
    assert buf.remember("b", "2").index == 1


def test_last_and_get_on_empty_buffer_are_none() -> None:
    buf = ToolResultBuffer()
    assert buf.last() is None
    assert buf.get(None) is None
    assert buf.get("last") is None
    assert buf.get(1) is None
    assert buf.get("rag") is None


def _populated_buffer() -> ToolResultBuffer:
    buf = ToolResultBuffer(capacity=5)
    buf.remember("rag", "first")
    buf.remember("web", "second")
    buf.remember("rag", "third")
    return buf


def test_get_none_empty_and_last_select_most_recent() -> None:
    buf = _populated_buffer()
    for selector in (None, "", "last"):
        assert buf.get(selector) is not None and buf.get(selector).body == "third"


def test_get_int_selector_fetches_exact_index() -> None:
    buf = _populated_buffer()
    assert buf.get(1).body == "first"
    assert buf.get(2).body == "second"
    assert buf.get(3).body == "third"


def test_get_numeric_string_selector_fetches_exact_index() -> None:
    buf = _populated_buffer()
    assert buf.get("1").body == "first"
    assert buf.get(" 2 ").body == "second"


def test_get_missing_or_invalid_index_returns_none() -> None:
    buf = _populated_buffer()
    assert buf.get(99) is None
    assert buf.get(0) is None
    assert buf.get("-1") is None


def test_get_label_selector_returns_most_recent_match() -> None:
    buf = _populated_buffer()
    assert buf.get("rag").body == "third"
    assert buf.get("web").body == "second"


def test_get_unknown_label_returns_none() -> None:
    assert _populated_buffer().get("nope") is None


def test_buffer_truncate_uses_buffer_policy() -> None:
    buf = ToolResultBuffer(head_lines=1, line_hard_cap=5)
    assert buf.truncate("abc\nhidden\nhidden2") == ("abc", 2)


def test_buffer_truncate_clips_long_lines_with_buffer_cap() -> None:
    buf = ToolResultBuffer(head_lines=2, line_hard_cap=4)
    assert buf.truncate("abcdef") == ("abc…", 0)


def test_tool_result_entry_stores_declared_fields() -> None:
    entry = ToolResultEntry(index=7, label="exec", body="out")
    assert (entry.index, entry.label, entry.body) == (7, "exec", "out")
