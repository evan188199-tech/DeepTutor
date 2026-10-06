"""ask_user_trace recovery contract: persist/reload roundtrip, bad history, concurrency.

The module recovers resolved ``ask_user`` exchanges from persisted assistant
rows, so every test exercises the stored ``events_json`` shape exactly as the
session stores write it and ``context_builder`` reads it back.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

from deeptutor.services.session.ask_user_trace import (
    extract_ask_user_clarification_blocks,
    extract_ask_user_clarifications,
    filter_ask_user_events,
    select_ask_user_events,
)


def _resolved_event(question_id: str, prompt: str, answer: str, *, offset: int = 12) -> dict:
    return {
        "type": "content",
        "content": "delta",
        "metadata": {
            "ask_user_resolved": True,
            "assistant_content_offset": offset,
            "answers": [{"questionId": question_id, "text": answer}],
        },
    }


def _pending_event(questions: list[dict]) -> dict:
    return {
        "type": "tool_result",
        "content": "asked",
        "metadata": {"ask_user": {"questions": questions}},
    }


def _full_trace() -> list[dict]:
    """A realistic assistant row: streamed deltas around one ask_user pause."""
    return [
        {"type": "content", "content": "let me ask first"},
        _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
        _resolved_event("q1", "Which chapter?", "Chapter 3"),
        {"type": "content", "content": "here is the answer"},
    ]


def _persist_trace(path, events: list[dict]) -> str:
    raw = json.dumps(events)
    path.write_text(raw, encoding="utf-8")
    return raw


def test_persisted_trace_roundtrips_through_disk(tmp_path) -> None:
    """Record side: events land in events_json on disk. Read side: the trace is
    filtered back down to just the ask_user exchanges, in order."""
    path = tmp_path / "assistant_row_events.json"
    _persist_trace(path, _full_trace())

    recovered = select_ask_user_events(path.read_text(encoding="utf-8"))

    assert len(recovered) == 2
    assert recovered[0]["type"] == "tool_result"
    assert recovered[0]["metadata"]["ask_user"]["questions"][0]["id"] == "q1"
    assert recovered[1]["metadata"]["ask_user_resolved"] is True

    message = {"role": "assistant", "events": recovered}
    blocks = extract_ask_user_clarification_blocks(message)
    assert len(blocks) == 1
    offset, text = blocks[0]
    assert offset == 12
    assert "Which chapter?" in text
    assert "Chapter 3" in text
    assert extract_ask_user_clarifications(message) == text


def test_roundtrip_reconstructs_question_prompt_from_pending_event(tmp_path) -> None:
    """Answers only carry a questionId; the prompt comes from the earlier
    tool_result row of the same persisted trace."""
    events = [
        _pending_event(
            [{"id": "q1", "prompt": "  Which chapter?  "}, {"id": "q2", "prompt": "Why?"}]
        ),
        _resolved_event("q2", "", "Because of the theorem."),
    ]
    raw = json.dumps(events)
    message = {"role": "assistant", "events": select_ask_user_events(raw)}

    blocks = extract_ask_user_clarification_blocks(message)

    assert len(blocks) == 1
    _, text = blocks[0]
    assert "Why?" in text
    assert "Because of the theorem." in text
    assert "Which chapter?" not in text


def test_snake_case_answer_key_roundtrips(tmp_path) -> None:
    events = [
        _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
        {
            "type": "content",
            "metadata": {
                "ask_user_resolved": True,
                "assistant_content_offset": 4,
                "answers": [{"question_id": "q1", "text": "Chapter 3"}],
            },
        },
    ]
    message = {"role": "assistant", "events": select_ask_user_events(json.dumps(events))}

    blocks = extract_ask_user_clarification_blocks(message)

    assert len(blocks) == 1
    assert "Chapter 3" in blocks[0][1]


def test_reply_preview_is_recovered_when_answers_are_missing(tmp_path) -> None:
    events = [
        _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
        {
            "type": "content",
            "metadata": {"ask_user_resolved": True, "reply_preview": "the third one"},
        },
    ]
    message = {"role": "assistant", "events": select_ask_user_events(json.dumps(events))}

    blocks = extract_ask_user_clarification_blocks(message)

    assert len(blocks) == 1
    assert "the third one" in blocks[0][1]


def test_unresolved_pending_trace_is_not_recovered(tmp_path) -> None:
    """Only resolved exchanges qualify: a pending pause without the resolved
    marker must not re-enter context as a user answer."""
    path = tmp_path / "pending_row_events.json"
    _persist_trace(path, [_pending_event([{"id": "q1", "prompt": "Which chapter?"}])])

    assert select_ask_user_events(path.read_text(encoding="utf-8")) == []


def test_multiple_resolved_exchanges_keep_offsets(tmp_path) -> None:
    events = [
        _pending_event([{"id": "q1", "prompt": "First?"}]),
        _resolved_event("q1", "First?", "one", offset=10),
        _pending_event([{"id": "q2", "prompt": "Second?"}]),
        _resolved_event("q2", "Second?", "two", offset=40),
    ]
    message = {"role": "assistant", "events": select_ask_user_events(json.dumps(events))}

    blocks = extract_ask_user_clarification_blocks(message)

    assert [offset for offset, _ in blocks] == [10, 40]
    assert "one" in blocks[0][1]
    assert "two" in blocks[1][1]


def test_malformed_history_inputs_degrade_to_empty() -> None:
    broken_raw = [
        None,
        "",
        "not json at all",
        '{"ask_user": truncated',
        json.dumps({"not": "a list"}),
        json.dumps("a plain string"),
        json.dumps(42),
        "42",
    ]
    for raw in broken_raw:
        assert select_ask_user_events(raw) == []


def test_marker_present_but_unparsable_trace_degrades_to_empty() -> None:
    """The raw-text marker passed, so the JSON parse itself fails and must be
    swallowed instead of poisoning context building."""
    broken_raw = [
        '{"ask_user_resolved": true, "events": [truncated',
        '["ask_user_resolved", {"unclosed": ',
        'not json {"ask_user_resolved"} at all',
    ]
    for raw in broken_raw:
        assert '"ask_user_resolved"' in raw
        assert select_ask_user_events(raw) == []


def test_filter_rejects_non_list_event_containers() -> None:
    for not_a_list in (None, "events", 42, {"0": {"type": "content"}}, ("a", "b")):
        assert filter_ask_user_events(not_a_list) == []


def test_malformed_events_inside_a_trace_are_skipped() -> None:
    mixed = [
        None,
        42,
        "content delta",
        {"type": "content"},  # no metadata
        {"type": "content", "metadata": "not a dict"},
        _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
        _resolved_event("q1", "Which chapter?", "Chapter 3"),
    ]

    kept = filter_ask_user_events(mixed)

    assert len(kept) == 2
    assert kept[0]["type"] == "tool_result"
    assert kept[1]["metadata"]["ask_user_resolved"] is True


def test_malformed_clarification_payloads_do_not_raise() -> None:
    cases: list[dict] = [
        {},
        {"role": "assistant"},
        {"role": "assistant", "events": None},
        {"role": "assistant", "events": "not a list"},
        {"role": "assistant", "events": [None, 1, "x"]},
        {"role": "assistant", "events": [{"type": "content", "metadata": None}]},
        {"role": "assistant", "events": [{"type": "content", "metadata": "not a dict"}]},
        {
            "role": "assistant",
            "events": [
                {"type": "tool_result", "metadata": {"ask_user": "not a dict"}},
                {"type": "content", "metadata": {"ask_user_resolved": True}},
            ],
        },
        {
            "role": "assistant",
            "events": [
                _pending_event([None, "junk", {"id": 3, "prompt": ""}, {"prompt": "Why?"}]),
                {
                    "type": "content",
                    "metadata": {
                        "ask_user_resolved": True,
                        "answers": [None, "junk", {}, {"questionId": "ghost", "text": "hi"}],
                    },
                },
            ],
        },
        {
            "role": "assistant",
            "events": [
                _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
                {
                    "type": "content",
                    "metadata": {
                        "ask_user_resolved": True,
                        "assistant_content_offset": "not a number",
                        "answers": [{"questionId": "q1", "text": "Chapter 3"}],
                    },
                },
            ],
        },
    ]

    for message in cases:
        blocks = extract_ask_user_clarification_blocks(message)
        for offset, _text in blocks:
            assert isinstance(offset, int)
            assert offset >= 0


def test_negative_and_none_offsets_clamp_to_zero() -> None:
    events = [
        _pending_event([{"id": "q1", "prompt": "Q?"}]),
        {
            "type": "content",
            "metadata": {
                "ask_user_resolved": True,
                "assistant_content_offset": -5,
                "answers": [{"questionId": "q1", "text": "a"}],
            },
        },
        _pending_event([{"id": "q2", "prompt": "R?"}]),
        {
            "type": "content",
            "metadata": {
                "ask_user_resolved": True,
                "answers": [{"questionId": "q2", "text": "b"}],
            },
        },
    ]

    blocks = extract_ask_user_clarification_blocks({"role": "assistant", "events": events})

    assert [offset for offset, _ in blocks] == [0, 0]


def test_filter_and_select_do_not_mutate_shared_input() -> None:
    trace = _full_trace()
    snapshot = json.dumps(trace)

    filter_ask_user_events(trace)
    select_ask_user_events(snapshot)

    assert json.dumps(trace) == snapshot


def test_concurrent_writers_and_readers_stay_consistent() -> None:
    """The persisted trace is shared state: writers append resolved rows while
    readers recover ask_user exchanges from other rows' events_json. Recovery
    must be race-free on its inputs — every read returns only valid ask_user
    events, and the shared trace grows by exactly the appended rows."""
    shared_trace: list[dict] = _full_trace()
    raw_traces = [
        json.dumps(_full_trace() + [{"type": "content", "content": f"tail {i}"}]) for i in range(32)
    ]

    def writer(index: int) -> int:
        event = _resolved_event("q1", "Which chapter?", f"answer {index}", offset=index)
        shared_trace.append(event)
        return len(shared_trace)

    def reader(raw: str) -> list[dict]:
        recovered = select_ask_user_events(raw)
        message = {"role": "assistant", "events": recovered}
        for offset, _text in extract_ask_user_clarification_blocks(message):
            assert isinstance(offset, int)
            assert offset >= 0
        return recovered

    with ThreadPoolExecutor(max_workers=8) as pool:
        writer_sizes = list(pool.map(writer, range(8)))
        read_results = list(pool.map(reader, raw_traces))

    assert max(writer_sizes) == len(shared_trace)
    assert len(shared_trace) == len(_full_trace()) + 8
    for recovered in read_results:
        assert len(recovered) == 2
        assert recovered[0]["type"] == "tool_result"
        assert recovered[1]["metadata"]["ask_user_resolved"] is True


def test_concurrent_disk_roundtrip_is_per_row_isolated(tmp_path) -> None:
    """Each persisted row is its own file: parallel record/read cycles must not
    bleed rows into each other."""
    paths = [tmp_path / f"row_{i}.json" for i in range(12)]

    def cycle(index: int) -> list[dict]:
        answer = f"answer {index}"
        events = [
            _pending_event([{"id": "q1", "prompt": "Which chapter?"}]),
            _resolved_event("q1", "Which chapter?", answer, offset=index),
        ]
        path = paths[index]
        raw = _persist_trace(path, events)
        assert raw == path.read_text(encoding="utf-8")
        recovered = select_ask_user_events(raw)
        blocks = extract_ask_user_clarification_blocks({"role": "assistant", "events": recovered})
        return blocks

    with ThreadPoolExecutor(max_workers=6) as pool:
        all_blocks = list(pool.map(cycle, range(12)))

    assert len(all_blocks) == 12
    for index, blocks in enumerate(all_blocks):
        assert len(blocks) == 1
        offset, text = blocks[0]
        assert offset == index
        assert f"answer {index}" in text
    assert all(path.exists() for path in paths)
