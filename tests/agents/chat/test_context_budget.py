"""Per-turn context-window accounting for the chat loop.

The composer chip reports what the model's window actually held. These cover
the pure measurement seam (segment keys, arithmetic, ordering, degradation)
plus one end-to-end pass proving the breakdown reaches the result envelope
alongside ``cost_summary``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents.loop.agent_loop import MAX_SETTLEMENT_ROUNDS
from deeptutor.agents.loop.context_budget import (
    LLMRequestSnapshot,
    build_context_budget,
    count_conversation_tokens,
    resolve_window_info,
)
from deeptutor.capabilities import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.runtime.stream_bus import StreamBus


def _chars(text: str) -> int:
    """Deterministic stand-in for tiktoken: one character = one token."""
    return len(text)


def _schema(name: str, description: str = "d") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": {}},
    }


def _budget(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "blocks": [],
        "request": LLMRequestSnapshot(),
        "model": "gpt-test",
        "context_window": 1000,
        "counter": _chars,
    }
    kwargs.update(overrides)
    budget = build_context_budget(**kwargs)
    assert budget is not None
    return budget


def _tokens(budget: dict[str, Any]) -> dict[str, int]:
    return {segment["key"]: segment["tokens"] for segment in budget["segments"]}


# ---- segment keys + arithmetic ------------------------------------------


def test_every_source_of_context_lands_in_its_own_segment() -> None:
    budget = _budget(
        blocks=[
            PromptBlock("general", "you are"),
            PromptBlock("runtime_policy", "policy"),
            PromptBlock("loop", "loop rules"),
            PromptBlock("memory", "remembered"),
            PromptBlock("tools", "- rag"),
            PromptBlock("extended_tools", "manifest line"),
            PromptBlock("solve", "playbook"),
        ],
        request=LLMRequestSnapshot(
            messages=[
                {"role": "system", "content": "SYSTEM PROMPT"},
                {"role": "user", "content": "question"},
            ],
            tool_schemas=[_schema("rag"), _schema("mcp_pageindex_get_page_content")],
        ),
        loaded_deferred_names={"mcp_pageindex_get_page_content"},
    )

    tokens = _tokens(budget)
    assert set(tokens) == {
        "system_prompt",
        "memory",
        "tool_manifest",
        "extended_tools",
        "capability",
        "system_tools",
        "mcp_tools",
        "messages",
    }
    # general + runtime_policy + loop read as one preamble line.
    assert tokens["system_prompt"] == sum(
        _chars(f"## {name}\n{content}")
        for name, content in (
            ("general", "you are"),
            ("runtime_policy", "policy"),
            ("loop", "loop rules"),
        )
    )
    # A block ships with its rendered "## name" heading, so that is measured too.
    assert tokens["memory"] == _chars("## memory\nremembered")
    # An unrecognised block name is a capability playbook.
    assert tokens["capability"] == _chars("## solve\nplaybook")
    assert budget["used_tokens"] == sum(tokens.values())
    assert budget["free_tokens"] == 1000 - budget["used_tokens"]
    assert budget["model"] == "gpt-test"
    assert budget["counter"] in {"cl100k_base", "heuristic"}


def test_capability_blocks_are_summed_under_one_key() -> None:
    budget = _budget(blocks=[PromptBlock("solve", "aaa"), PromptBlock("obsidian", "bb")])

    assert _tokens(budget) == {
        "capability": _chars("## solve\naaa") + _chars("## obsidian\nbb"),
    }


def test_segments_sorted_desc_with_empty_ones_dropped() -> None:
    budget = _budget(
        blocks=[
            PromptBlock("memory", "m" * 50),
            PromptBlock("skills", "s" * 200),
            PromptBlock("sources", "   "),
            PromptBlock("workspace", ""),
        ],
    )

    keys = [segment["key"] for segment in budget["segments"]]
    assert keys == ["skills", "memory"]
    assert [segment["tokens"] for segment in budget["segments"]] == sorted(
        (segment["tokens"] for segment in budget["segments"]), reverse=True
    )
    # No zero rows: an unsent block is absent, not a 0-token line.
    assert all(segment["tokens"] > 0 for segment in budget["segments"])


def test_free_tokens_never_goes_negative() -> None:
    budget = _budget(blocks=[PromptBlock("memory", "x" * 400)], context_window=100)

    assert budget["used_tokens"] > 100
    assert budget["free_tokens"] == 0


# ---- messages ------------------------------------------------------------


def test_system_message_is_not_counted_twice() -> None:
    system = {"role": "system", "content": "SYSTEM PROMPT"}
    blocks = [PromptBlock("general", "SYSTEM PROMPT")]
    request = LLMRequestSnapshot(messages=[system, {"role": "user", "content": "hi"}])

    budget = _budget(blocks=blocks, request=request)

    # The system prompt is itemized by its blocks; the leading system message
    # carrying the same bytes must not be added on top of that.
    assert _tokens(budget)["messages"] == _chars("hi")


def test_prompt_render_overhead_lands_in_the_system_prompt_segment() -> None:
    # ``render`` welds the blocks with ``---`` separators and appends the
    # language directive, so the shipped system message is bigger than the sum
    # of its blocks. That difference is real context and has to be attributed,
    # not dropped — the segment must account for the whole shipped string.
    blocks = [PromptBlock("general", "you are"), PromptBlock("loop", "one loop")]
    shipped = "## general\nyou are\n\n---\n\n## loop\none loop\n\nReply in English."
    request = LLMRequestSnapshot(messages=[{"role": "system", "content": shipped}])

    budget = _budget(blocks=blocks, request=request)

    assert _tokens(budget)["system_prompt"] == _chars(shipped)


def test_mid_conversation_system_messages_still_count() -> None:
    # Only the leading system prompt is itemized elsewhere; the compressed
    # history summary and context checkpoints are real conversation payload.
    messages = [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "system", "content": "[Conversation summary] earlier"},
        {"role": "user", "content": "hi"},
    ]

    assert count_conversation_tokens(messages, _chars) == _chars(
        "[Conversation summary] earlier"
    ) + _chars("hi")


def test_messages_count_tool_calls_and_multimodal_text() -> None:
    messages = [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "rag", "arguments": '{"query": "x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "passage"},
    ]

    total = count_conversation_tokens(messages, _chars)

    # Text part + tool-call payload + tool result; the image URL is not text.
    assert total > _chars("describe") + _chars("passage")
    assert "data:image/png" not in "".join(
        str(message.get("content")) for message in messages if message["role"] == "tool"
    )


# ---- window / counter / deferred tools -----------------------------------


def test_window_estimated_when_not_configured() -> None:
    info = resolve_window_info(context_window=None, model="unknown")

    assert info.estimated is True
    assert info.window > 0
    assert _budget(context_window=None, model="unknown")["window_estimated"] is True


def test_window_not_estimated_when_configured() -> None:
    info = resolve_window_info(context_window=128000, model="gpt-4o")

    assert info.estimated is False
    assert info.window == 128000
    budget = _budget(context_window=128000, model="gpt-4o")
    assert budget["window_estimated"] is False
    assert budget["window"] == 128000


def test_configured_window_is_not_clamped_to_the_planner_ceiling() -> None:
    # A configured window is what the settings page shows, so the readout must
    # repeat it verbatim. Routing it through ``resolve_effective_context_window``
    # would cap it at MAX_EFFECTIVE_CONTEXT_WINDOW (1M) — fine for sizing the
    # history budget, but it would report a 2M model as 1M and disagree with
    # settings, and every percentage would be computed against the wrong total.
    assert resolve_window_info(context_window=1_048_576, model="gemini-3-flash").window == 1_048_576

    budget = _budget(context_window=2_097_152, model="gemini-1.5-pro")

    assert budget["window"] == 2_097_152
    assert budget["window_estimated"] is False
    assert budget["free_tokens"] == 2_097_152 - budget["used_tokens"]


def test_unparseable_window_falls_back_and_says_so() -> None:
    # ``resolve_effective_context_window`` treats junk as absent; the flag must
    # follow the same branch rather than trusting the raw config value.
    info = resolve_window_info(context_window="not-a-number", model="unknown")

    assert info.estimated is True


def test_deferred_tools_split_from_builtins_and_unloaded_ones_are_a_scalar() -> None:
    budget = _budget(
        request=LLMRequestSnapshot(
            tool_schemas=[_schema("rag"), _schema("mcp_x", "a longer description")],
        ),
        loaded_deferred_names={"mcp_x"},
        deferred_tool_count=12,
    )

    tokens = _tokens(budget)
    assert tokens["system_tools"] == _chars(
        '{"type": "function", "function": {"name": "rag", "description": "d", "parameters": {}}}'
    )
    assert tokens["mcp_tools"] > 0
    assert budget["deferred_tool_count"] == 12
    # Unloaded extended tools cost only their manifest line — never a segment.
    assert "deferred" not in tokens


# ---- degradation ---------------------------------------------------------


def test_failing_counter_degrades_to_no_budget() -> None:
    def _boom(_text: str) -> int:
        raise RuntimeError("tokenizer exploded")

    assert (
        build_context_budget(
            blocks=[PromptBlock("general", "x")],
            request=LLMRequestSnapshot(messages=[{"role": "user", "content": "hi"}]),
            context_window=1000,
            counter=_boom,
        )
        is None
    )


def test_malformed_material_degrades_to_no_budget() -> None:
    assert build_context_budget(blocks=None, request=LLMRequestSnapshot()) is None  # type: ignore[arg-type]


# ---- end to end ----------------------------------------------------------


class _Registry:
    def deferred_tools(self) -> list[Any]:
        """No provider tools, so the turn keeps using this registry directly.

        ``build_tool_view`` short-circuits to the base registry when there is
        nothing external to scope; without this the view would raise and the
        turn would fall back to a scoped wrapper reading through ``get``.
        """
        return []

    def build_prompt_text(self, *_args: Any, **_kwargs: Any) -> str:
        return "- rag: retrieve from a knowledge base"

    def build_openai_schemas(self, _enabled_tools: list[str]) -> list[dict[str, Any]]:
        return [_schema("rag", "Retrieve")]

    async def execute(self, _name: str, **_kwargs: Any) -> ToolResult:
        return ToolResult(content="", sources=[], metadata={})


class _ScriptedChatClient:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self.calls: list[dict[str, Any]] = []

        class _Completions:
            def __init__(self, parent: _ScriptedChatClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any) -> Any:
                self.parent.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
                return _stream(chunks)

        class _Chat:
            def __init__(self, parent: _ScriptedChatClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


class _MultiTurnChatClient:
    """Serves a different scripted stream per call.

    Lets a test drive a turn that calls tools and is then forced to finish —
    the round where the loop deliberately ships no tool schemas.
    """

    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._scripts = list(scripts)

        class _Completions:
            def __init__(self, parent: _MultiTurnChatClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any) -> Any:
                self.parent.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
                script = self.parent._scripts.pop(0) if self.parent._scripts else []
                return _stream(script)

        class _Chat:
            def __init__(self, parent: _MultiTurnChatClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


def _tool_call_chunk(name: str, arguments: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="c1",
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                )
            )
        ]
    )


async def _stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_turn_result_carries_the_context_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            context_window=128000,
        ),
    )
    client = _ScriptedChatClient(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Answer.", tool_calls=None))]
            )
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()  # type: ignore[assignment]
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["rag"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await pipeline.run(
        UnifiedContext(
            session_id="s1",
            user_message="Explain gradient descent",
            language="en",
            metadata={"turn_id": "t1"},
        ),
        bus,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    budget = result.metadata["metadata"]["context_budget"]
    assert budget["window"] == 128000
    assert budget["window_estimated"] is False
    assert budget["model"] == "gpt-test"
    assert budget["used_tokens"] == sum(s["tokens"] for s in budget["segments"])
    assert budget["free_tokens"] == 128000 - budget["used_tokens"]
    keys = {segment["key"] for segment in budget["segments"]}
    # The measured request is the one the client actually received.
    assert {"system_prompt", "tool_manifest", "system_tools", "messages"} <= keys
    sent_system = client.calls[0]["messages"][0]["content"]
    assert "Explain gradient descent" not in sent_system


@pytest.mark.asyncio
async def test_forced_finish_still_reports_the_tools_the_turn_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A turn that exhausts its round budget ends on a round the loop strips
    # tools from, to make the model answer. Reading the budget off that round
    # verbatim would report zero tool tokens for a turn whose schemas sat in
    # the window the entire time.
    #
    # Exhausting the budget means exploration *and* the bounded settlement
    # window that follows it — settlement rounds deliberately keep tools
    # available, so the model must keep requesting them to reach the hard
    # finish.
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            context_window=128000,
        ),
    )
    client = _MultiTurnChatClient(
        [
            [_tool_call_chunk("rag", '{"query": "gd", "kb_name": "kb"}')]
            for _ in range(1 + MAX_SETTLEMENT_ROUNDS)
        ]
        + [
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="Answer.", tool_calls=None))
                    ]
                )
            ],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()  # type: ignore[assignment]
    pipeline._max_rounds = 1  # one tool round, then the forced finish
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["rag"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await pipeline.run(
        UnifiedContext(
            session_id="s2",
            user_message="Explain gradient descent",
            language="en",
            metadata={"turn_id": "t2"},
        ),
        bus,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    # The finishing call really did ship without tools...
    assert not client.calls[-1].get("tools")
    # ...yet the turn still reports what its window held.
    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    budget = result.metadata["metadata"]["context_budget"]
    assert _tokens(budget)["system_tools"] > 0


def test_known_context_window_readout_is_not_clamped():
    info = resolve_window_info(model="gemini-2.5-pro")
    assert info.window == 1048576
    assert info.estimated is False


# ---- trimming order -------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot_flagged", "shipped_system", "expected_tokens"),
    [
        pytest.param(
            True,
            "## general\nyou are\n\n---\n\nLANG",
            {
                "system_prompt": _chars("## general\nyou are\n\n---\n\nLANG"),
                "memory": _chars("## memory\nremembered facts"),
                "messages": _chars("hi"),
            },
            id="snapshot-trims-dynamic-blocks-out-of-system-itemization",
        ),
        pytest.param(
            False,
            "## general\nyou are\n\n---\n\n## memory\nremembered facts\n\nLANG",
            {
                "system_prompt": _chars(
                    "## general\nyou are\n\n---\n\n## memory\nremembered facts\n\nLANG"
                )
                - _chars("## memory\nremembered facts"),
                "memory": _chars("## memory\nremembered facts"),
                "messages": _chars("hi") + _chars("## memory\nremembered facts"),
            },
            id="no-snapshot-keeps-runtime-block-in-system-and-counts-snapshot-text",
        ),
    ],
)
def test_runtime_snapshot_moves_dynamic_block_attribution(
    snapshot_flagged: bool,
    shipped_system: str,
    expected_tokens: dict[str, int],
) -> None:
    snapshot_message: dict[str, Any] = {
        "role": "user",
        "content": "## memory\nremembered facts",
    }
    if snapshot_flagged:
        snapshot_message["_context_snapshot"] = "memory"
    budget = _budget(
        blocks=[
            PromptBlock("general", "you are"),
            PromptBlock("memory", "remembered facts"),
        ],
        request=LLMRequestSnapshot(
            messages=[
                {"role": "system", "content": shipped_system},
                {"role": "user", "content": "hi"},
                snapshot_message,
            ]
        ),
    )

    assert _tokens(budget) == expected_tokens


@pytest.mark.parametrize(
    ("blocks", "expected_order"),
    [
        pytest.param(
            [PromptBlock("memory", "w" * 4), PromptBlock("skills", "w" * 4)],
            ["memory", "skills"],
            id="equal-tokens-sort-by-name",
        ),
        pytest.param(
            [PromptBlock("workspace", "w" * 4), PromptBlock("notebooks", "w" * 4)],
            ["notebooks", "workspace"],
            id="equal-tokens-sort-by-name-reversed-input",
        ),
        pytest.param(
            [PromptBlock("workspace", "w" * 50), PromptBlock("memory", "w" * 4)],
            ["workspace", "memory"],
            id="larger-tokens-win-regardless-of-name",
        ),
    ],
)
def test_segment_ranking_is_tokens_desc_then_name_asc(
    blocks: list[PromptBlock], expected_order: list[str]
) -> None:
    segments = _budget(blocks=blocks, context_window=10_000)["segments"]

    assert [segment["key"] for segment in segments] == expected_order
    assert all(segment["tokens"] > 0 for segment in segments)


def test_blank_block_content_is_trimmed_and_rendered_form_is_measured() -> None:
    budget = _budget(
        blocks=[
            PromptBlock("memory", None),  # type: ignore[arg-type]
            PromptBlock("skills", "  \n\t "),
            PromptBlock("sources", "  padded  "),
        ],
    )

    assert _tokens(budget) == {"sources": _chars("## sources\npadded")}


def test_non_dict_tool_schemas_are_skipped() -> None:
    valid = _schema("rag", "longer description")
    budget = _budget(
        request=LLMRequestSnapshot(tool_schemas=[None, "junk", 42, valid]),
    )

    assert _tokens(budget) == {"system_tools": _chars(json.dumps(valid, ensure_ascii=False))}


# ---- over-limit fallback --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(-5, 0, id="negative-clamps-to-zero"),
        pytest.param(0, 0, id="zero-stays-zero"),
        pytest.param("7", 7, id="numeric-string-coerced"),
        pytest.param(12, 12, id="int-passthrough"),
        pytest.param(10**9, 10**9, id="large-value-kept"),
    ],
)
def test_deferred_tool_count_is_coerced_and_clamped(raw: Any, expected: int) -> None:
    assert _budget(deferred_tool_count=raw)["deferred_tool_count"] == expected


@pytest.mark.parametrize("raw", ["not-a-number", None, object()])
def test_non_numeric_deferred_tool_count_degrades_to_no_budget(raw: Any) -> None:
    assert (
        build_context_budget(
            blocks=[],
            request=LLMRequestSnapshot(),
            context_window=1000,
            deferred_tool_count=raw,
            counter=_chars,
        )
        is None
    )


@pytest.mark.parametrize(
    ("snapshot_text", "extra_user_text"),
    [
        pytest.param("s", "hi", id="conversation-smaller-than-dynamic-tokens"),
        pytest.param("## memory\n" + "x" * 10, "", id="conversation-exactly-dynamic-tokens"),
    ],
)
def test_messages_segment_clamps_at_zero_when_dynamic_tokens_cover_conversation(
    snapshot_text: str, extra_user_text: str
) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "## general\nyou are"},
        {"role": "user", "content": snapshot_text, "_context_snapshot": "memory"},
    ]
    if extra_user_text:
        messages.insert(1, {"role": "user", "content": extra_user_text})
    budget = _budget(
        blocks=[PromptBlock("general", "you are"), PromptBlock("memory", "x" * 10)],
        request=LLMRequestSnapshot(messages=messages),
    )

    assert _tokens(budget) == {"system_prompt": _chars("## general\nyou are"), "memory": 20}


@pytest.mark.parametrize(
    "request_material",
    [
        pytest.param(None, id="request-none"),
        pytest.param(LLMRequestSnapshot(messages=None), id="messages-none"),
        pytest.param(LLMRequestSnapshot(messages=[], tool_schemas=None), id="tool-schemas-none"),
    ],
)
def test_malformed_request_material_degrades_to_no_budget(request_material: Any) -> None:
    assert (
        build_context_budget(
            blocks=[],
            request=request_material,
            context_window=1000,
            counter=_chars,
        )
        is None
    )


@pytest.mark.parametrize(
    ("window", "expected_free"),
    [
        pytest.param(13, 0, id="window-equals-used"),
        pytest.param(12, 0, id="window-below-used"),
        pytest.param(14, 1, id="window-one-above-used"),
    ],
)
def test_free_tokens_boundary_around_exact_usage(window: int, expected_free: int) -> None:
    budget = _budget(blocks=[PromptBlock("memory", "abc")], context_window=window)

    assert budget["used_tokens"] == _chars("## memory\nabc")
    assert budget["free_tokens"] == expected_free


# ---- boundary values ------------------------------------------------------


@pytest.mark.parametrize(
    ("context_window", "expected_window", "estimated"),
    [
        pytest.param("3000", 3000, False, id="numeric-string-verbatim"),
        pytest.param(3000, 3000, False, id="int-verbatim"),
        pytest.param("0", None, True, id="zero-is-not-positive"),
        pytest.param("-5", None, True, id="negative-falls-back"),
        pytest.param("12.5", None, True, id="float-string-unparseable"),
        pytest.param(True, None, True, id="bool-unparseable"),
    ],
)
def test_window_value_boundaries_route_between_verbatim_and_estimated(
    context_window: Any, expected_window: int | None, estimated: bool
) -> None:
    info = resolve_window_info(context_window=context_window, model="unknown")

    assert info.estimated is estimated
    if expected_window is None:
        assert info.window > 0
    else:
        assert info.window == expected_window


@pytest.mark.parametrize(
    ("messages", "expected_counted"),
    [
        pytest.param(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
            "firstsecond",
            id="conversation-not-opening-with-system",
        ),
        pytest.param(
            [
                {"role": "system", "content": [{"type": "text", "text": "abc"}]},
                {"role": "user", "content": "hi"},
            ],
            "hi",
            id="leading-system-content-not-a-string-still-skipped",
        ),
    ],
)
def test_leading_system_prompt_absent_or_unrenderable_skips_overhead(
    messages: list[dict[str, Any]], expected_counted: str
) -> None:
    budget = _budget(request=LLMRequestSnapshot(messages=messages))

    tokens = _tokens(budget)
    assert "system_prompt" not in tokens
    assert tokens["messages"] == _chars(expected_counted)


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        pytest.param([], 0, id="no-messages"),
        pytest.param([{"role": "system", "content": "only"}], 0, id="leading-system-only"),
        pytest.param(
            [{"role": "system", "content": None}, {"role": "user", "content": "hi"}],
            _chars("hi"),
            id="leading-system-content-none",
        ),
        pytest.param(
            [
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": ""},
                        {"type": "image_url", "image_url": {}},
                    ],
                },
                {"role": "user", "content": "hi"},
            ],
            _chars("hi"),
            id="multimodal-empty-text-and-image-only",
        ),
    ],
)
def test_conversation_token_counting_boundaries(
    messages: list[dict[str, Any]], expected: int
) -> None:
    assert count_conversation_tokens(messages, _chars) == expected


def test_empty_turn_yields_zero_usage_readout() -> None:
    empty = _budget()

    assert empty["segments"] == []
    assert empty["used_tokens"] == 0
    assert empty["free_tokens"] == 1000
    assert empty["window_estimated"] is False

    estimated = _budget(model="unknown", context_window=None)

    assert estimated["window_estimated"] is True
    assert estimated["used_tokens"] == 0
    assert estimated["free_tokens"] == estimated["window"]
    assert estimated["window"] > 0


def test_deferred_split_matches_top_level_named_schemas() -> None:
    deferred = {"type": "function", "name": "mcp_y", "description": "d"}
    builtin = {"type": "function", "name": "rag", "description": "d"}
    budget = _budget(
        request=LLMRequestSnapshot(tool_schemas=[deferred, builtin]),
        loaded_deferred_names={"mcp_y"},
    )

    tokens = _tokens(budget)
    assert tokens["mcp_tools"] == _chars(json.dumps(deferred, ensure_ascii=False))
    assert tokens["system_tools"] == _chars(json.dumps(builtin, ensure_ascii=False))
