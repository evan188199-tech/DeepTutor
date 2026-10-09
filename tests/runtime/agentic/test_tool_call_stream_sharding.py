"""Shard aggregation and malformed deltas for :class:`ToolCallAccumulator`.

The accumulator's contract is per-field: ``id``/``name`` assign, ``arguments``
concatenate, provider extensions assign whole. These tests push the wire
edges that shuffling in front of the provider produces — arguments arriving
one character at a time, deltas without a ``function`` payload, non-dict
extension objects, and indices that arrive out of order.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.runtime.agentic.tool_call_stream import ToolCallAccumulator


class _Fn:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _Delta:
    def __init__(
        self,
        index: int | None = 0,
        id: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
        function: Any = "default",
        extra_content: Any = None,
    ) -> None:
        self.index = index
        self.id = id
        self.extra_content = extra_content
        if function == "default":
            function = _Fn(name, arguments)
        self.function = function


def test_arguments_sharded_one_character_at_a_time_reassemble_exactly() -> None:
    payload = json.dumps({"query": 'say "hi"', "lang": "中文"}, ensure_ascii=False)
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=0, id="call_shard", name="rag_search"))
    for i in range(len(payload)):
        acc.feed(_Delta(index=0, arguments=payload[i]))

    (call,) = acc.collected()
    assert call["arguments"] == payload
    assert call["id"] == "call_shard"
    assert call["name"] == "rag_search"


def test_empty_arguments_fragment_is_dropped_not_appended() -> None:
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=0, id="c1", name="rag_search", arguments='{"q":1}'))
    acc.feed(_Delta(index=0, arguments=""))

    assert acc.part_at(0)["arguments"] == '{"q":1}'


def test_delta_without_function_payload_bills_nothing_and_stays_nameless() -> None:
    acc = ToolCallAccumulator()
    chars = acc.feed(_Delta(index=4, id="call_x", function=None, extra_content={}))

    assert chars == 0
    # The index slot exists but carries no dispatchable call.
    assert acc.ordered() == [{"id": "call_x", "name": "", "arguments": ""}]
    assert acc.collected() == []


def test_extra_content_that_is_not_a_dict_is_ignored() -> None:
    acc = ToolCallAccumulator()
    acc.feed(
        _Delta(
            index=0,
            id="c1",
            name="mastery_status",
            arguments="{}",
            extra_content="signature-from-gemini",
        )
    )

    assert "extra_content" not in acc.collected()[0]


def test_extra_content_assignment_replaces_not_merges() -> None:
    acc = ToolCallAccumulator()
    acc.feed(
        _Delta(
            index=0,
            id="c1",
            name="m",
            arguments="{}",
            extra_content={"google": {"thought_signature": "first"}},
        )
    )
    acc.feed(
        _Delta(index=0, arguments="", extra_content={"google": {"thought_signature": "second"}})
    )

    (call,) = acc.collected()
    assert call["extra_content"] == {"google": {"thought_signature": "second"}}


def test_part_at_reads_running_state_for_any_provider_index() -> None:
    acc = ToolCallAccumulator()
    assert acc.part_at(7) is None
    acc.feed(_Delta(index=7, id="call_7", name="web_search", arguments='{"q"'))
    part = acc.part_at(7)

    assert part["name"] == "web_search"
    assert part["arguments"] == '{"q"'
    assert acc.part_at(0) is None


def test_indices_arriving_out_of_order_replay_sorted() -> None:
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=3, id="call_c", name="videogen", arguments="{}"))
    acc.feed(_Delta(index=1, id="call_a", name="rag_search", arguments="{}"))
    acc.feed(_Delta(index=2, id="call_b", name="web_search", arguments="{}"))

    assert [call["id"] for call in acc.collected()] == ["call_a", "call_b", "call_c"]
    assert [part["id"] for part in acc.ordered()] == ["call_a", "call_b", "call_c"]


def test_name_reassignment_after_partial_arguments_keeps_fragments() -> None:
    """A late ``name`` delta overwrites cleanly but must not reset the
    argument fragments already folded for that index."""
    acc = ToolCallAccumulator()
    acc.feed(_Delta(index=0, id="c1", name="rag_search", arguments='{"q"'))
    acc.feed(_Delta(index=0, name="rag_search", arguments=':"x"}'))

    (call,) = acc.collected()
    assert call["name"] == "rag_search"
    assert call["arguments"] == '{"q":"x"}'
