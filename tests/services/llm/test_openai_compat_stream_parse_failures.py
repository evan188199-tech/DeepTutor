"""Failing-test set for OpenAI-compatible chat-completions stream parsing.

Each ``test_*`` marked failing corresponds to a defect found on this branch;
baseline tests pin behaviour that is already correct so the fixing card gets
regression guards for free. Scenarios: chunked tool-argument JSON
concatenation, tool-call delta merging and ordering, out-of-order frames,
mid-stream truncation, and the choice-less usage tail frame.
"""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)


def _tc_delta(
    index: int,
    call_id: str | None,
    name: str | None,
    arguments: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(
    tool_calls: list[SimpleNamespace] | None = None,
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=content,
        reasoning_content=None,
        reasoning=None,
        tool_calls=tool_calls or [],
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _choiceless_chunk(usage: SimpleNamespace | None) -> SimpleNamespace:
    """The include_usage tail frame: no choices at all, maybe a usage report."""
    return SimpleNamespace(choices=[], usage=usage)


def test_parse_chunks_orders_parallel_tool_calls_by_provider_index_not_arrival() -> None:
    """Parallel tool calls must come out in provider index order.

    A gateway that flushes index 1 before index 0 (buffered writer, parallel
    generation) currently yields ``[call_b, call_a]`` because ``_parse_chunks``
    iterates its insertion-ordered dict, while the shared
    ``ToolCallAccumulator`` contract (``runtime/agentic/tool_call_stream.py``)
    documents and implements index order for the same wire protocol.
    """
    chunks = [
        _chunk([_tc_delta(1, "call_b", "tool_b", '{"y": 2}')]),
        _chunk([_tc_delta(0, "call_a", "tool_a", '{"x": 1}')]),
        _chunk(finish_reason="tool_calls"),
    ]

    response = OpenAICompatProvider._parse_chunks(chunks)

    assert [(call.name, call.id) for call in response.tool_calls] == [
        ("tool_a", "call_a"),
        ("tool_b", "call_b"),
    ]
    assert response.tool_calls[0].arguments == {"x": 1}
    assert response.tool_calls[1].arguments == {"y": 2}


def test_parse_chunks_does_not_report_stop_for_stream_without_terminal_frame() -> None:
    """A stream that ends without any finish_reason frame is a truncated one.

    When a gateway closes the connection after the last data chunk (proxy
    restart, read deadline), ``_parse_chunks`` still reports ``finish_reason
    == "stop"`` — a cut-off response is indistinguishable from a complete
    one. The parse must surface that no terminal frame was seen.
    """
    chunks = [_chunk(content="partial answer, no more chunks")]

    response = OpenAICompatProvider._parse_chunks(chunks)

    assert response.content == "partial answer, no more chunks"
    assert response.finish_reason != "stop"


# --- Baselines: already-correct behaviour pinned for the fixing card --------


def test_baseline_chunked_tool_argument_json_is_concatenated_and_parsed() -> None:
    """Tool-call arguments split across many deltas concatenate into JSON."""
    fragments = ['{"quer', 'y": "deep', 'seek", "lim', 'it": 3}']
    chunks = [
        _chunk([_tc_delta(0, "call_a", "search", fragment)]) for fragment in fragments
    ]

    response = OpenAICompatProvider._parse_chunks(chunks)

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"query": "deepseek", "limit": 3}


def test_baseline_repeated_id_and_name_are_assigned_not_appended() -> None:
    """A gateway re-sending id/name on every delta must not grow them (#937)."""
    chunks = [
        _chunk([_tc_delta(0, "call_a", "search", '{"qu')]),
        _chunk([_tc_delta(0, "call_a", "search", 'ery": 1}')]),
        _chunk([_tc_delta(0, "call_a", "search", None)], finish_reason="tool_calls"),
    ]

    response = OpenAICompatProvider._parse_chunks(chunks)

    assert response.tool_calls[0].id == "call_a"
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"query": 1}


def test_baseline_choiceless_usage_tail_frame_is_captured_and_zero_echo_ignored() -> None:
    """The include_usage tail feeds usage; a zero-filled echo does not wipe it."""
    real_usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    delta_report = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    tail_only = OpenAICompatProvider._parse_chunks(
        [_chunk(content="hi"), _choiceless_chunk(real_usage)]
    )
    assert tail_only.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }

    attached_to_delta = OpenAICompatProvider._parse_chunks(
        [_chunk(content="hi", usage=delta_report)]
    )
    assert attached_to_delta.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }

    zero_echo_after_real = OpenAICompatProvider._parse_chunks(
        [
            _chunk(content="hi", usage=delta_report),
            _choiceless_chunk(SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)),
        ]
    )
    assert zero_echo_after_real.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
