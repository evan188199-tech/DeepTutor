from __future__ import annotations

from datetime import datetime
import json

import pytest

from deeptutor.services.session.event_preview import (
    MAX_LEGACY_EVENT_PAYLOAD_CHARS,
    compact_trace_preview,
)


@pytest.mark.parametrize(
    ("events", "expected_types"),
    [
        ([], []),
        (["not-a-dict", None, 42], []),
        ([{"type": "content", "content": "delta"}], []),
    ],
)
def test_empty_and_unremarkable_rows_yield_nothing_but_flag_omissions(
    events, expected_types
) -> None:
    preview, truncated = compact_trace_preview(events)

    assert [event.get("type") for event in preview] == expected_types
    assert truncated is (bool(events))


@pytest.mark.parametrize(
    ("metadata", "expected_kept"),
    [
        ({"ask_user": {"questions": ["q1"]}}, True),
        ({"tool_metadata": {"mastery_question": {"question_id": "q-1"}}}, True),
        ({"ask_user_resolved": True}, True),
        ({"ask_user": None}, False),
        ({"tool_metadata": {"mastery_question": "junk"}}, False),
        ({"tool_metadata": "junk"}, False),
        (None, False),
        ("junk", False),
    ],
)
def test_card_metadata_matrix_decides_whether_a_plain_row_survives(metadata, expected_kept) -> None:
    events = [{"type": "content", "content": "x", "metadata": metadata}]

    preview, truncated = compact_trace_preview(events)

    assert (len(preview) == 1) is expected_kept
    assert truncated is (not expected_kept)


def test_critical_rows_over_the_event_cap_keep_only_the_most_recent() -> None:
    events = [{"type": "result", "metadata": {"summary": index}} for index in range(5)]
    events.append({"type": "done", "metadata": {"status": "completed"}})

    preview, truncated = compact_trace_preview(events, max_events=2)

    assert truncated is True
    assert [event["type"] for event in preview] == ["result", "done"]
    assert preview[0]["metadata"]["summary"] == 4


@pytest.mark.parametrize(
    "content",
    ["x" * 50_000, "\U0001f31b" * 50_000],
    ids=["ascii", "astral-unicode"],
)
def test_an_oversized_row_collapses_to_a_stub_that_keeps_its_identity(content) -> None:
    source = {
        "type": "done",
        "turn_id": "turn-1",
        "session_id": "session-1",
        "seq": 7,
        "content": content,
        "metadata": {"status": "completed"},
    }

    preview, truncated = compact_trace_preview([source], max_bytes=2 * 1024)

    assert truncated is False
    stub = preview[0]
    assert stub["type"] == "done"
    assert stub["turn_id"] == "turn-1"
    assert stub["session_id"] == "session-1"
    assert stub["seq"] == 7
    assert stub["content"] == "...[truncated]"
    assert stub["_truncated"] is True
    assert "metadata" not in stub
    assert len(source["content"]) == len(content)


def test_an_oversized_non_critical_row_is_dropped_not_stubbed() -> None:
    events = [
        {"type": "done", "metadata": {"status": "completed"}},
        {"type": "tool_result", "content": "x" * 50_000, "metadata": {}},
    ]

    preview, truncated = compact_trace_preview(events, max_bytes=2 * 1024)

    assert truncated is True
    assert [event["type"] for event in preview] == ["done"]
    assert "_truncated" not in preview[0]


def test_the_byte_budget_counts_utf8_bytes_not_characters() -> None:
    """Two four-byte-grapheme tool results: 150 characters each, ~600 bytes each.

    Character-based accounting would keep both rows inside a 1000-byte budget;
    byte-based accounting keeps only the most recent one.
    """
    events = [
        {"type": "tool_result", "seq": 1, "content": "\U0001f31b" * 150, "metadata": {}},
        {"type": "tool_result", "seq": 2, "content": "\U0001f680" * 150, "metadata": {}},
    ]

    preview, truncated = compact_trace_preview(events, max_bytes=1000)

    assert truncated is True
    assert [event["seq"] for event in preview] == [2]


def test_legacy_tool_metadata_payloads_are_capped_without_touching_the_source() -> None:
    oversized = "y" * (MAX_LEGACY_EVENT_PAYLOAD_CHARS + 10)
    source = {
        "type": "tool_result",
        "content": "short",
        "metadata": {"tool_metadata": {"content": oversized, "answer": oversized}},
    }

    preview, truncated = compact_trace_preview([source])

    assert truncated is False
    tool_metadata = preview[0]["metadata"]["tool_metadata"]
    capped = MAX_LEGACY_EVENT_PAYLOAD_CHARS + len("...[truncated]")
    assert len(tool_metadata["content"]) == capped
    assert len(tool_metadata["answer"]) == capped
    assert tool_metadata["content"].endswith("...[truncated]")
    assert preview[0]["content"] == "short"
    assert source["metadata"]["tool_metadata"]["content"] == oversized


@pytest.mark.parametrize("value", [object(), b"raw-bytes", {1, 2}, datetime(2026, 1, 1)])
def test_non_serializable_metadata_values_are_tolerated(value) -> None:
    """Size measurement falls back to ``str`` for unserializable values; the
    preview row itself passes the original object through untouched."""
    events = [
        {"type": "result", "metadata": {"payload": value}},
        {"type": "done", "metadata": {"status": "completed"}},
    ]

    preview, truncated = compact_trace_preview(events)

    assert truncated is False
    assert [event["type"] for event in preview] == ["result", "done"]
    assert preview[0]["metadata"]["payload"] is value


def test_a_terminal_dropped_by_the_event_cap_is_reappended_from_the_full_trace() -> None:
    events = [
        {"type": "done", "turn_id": "turn-1", "metadata": {"status": "completed"}},
        {"type": "result", "metadata": {"summary": "ok"}},
    ]

    preview, truncated = compact_trace_preview(events, max_events=1)

    assert truncated is True
    assert [event["type"] for event in preview] == ["result", "done"]
    appended = preview[1]
    assert appended is not events[0]
    appended["metadata"]["status"] = "mutated"
    assert events[0]["metadata"]["status"] == "completed"


def test_bytes_content_measures_via_str_and_passes_through() -> None:
    source = {"type": "done", "content": b"\xff\xfe", "metadata": {}}

    preview, truncated = compact_trace_preview([source])

    assert truncated is False
    assert preview[0]["content"] is source["content"]


def test_preview_json_stays_ascii_safe_for_astral_content() -> None:
    events = [{"type": "result", "metadata": {"summary": "\U0001f31b" * 8}}]

    preview, _truncated = compact_trace_preview(events)

    encoded = json.dumps(preview[0], ensure_ascii=False)
    assert "\U0001f31b" in encoded
