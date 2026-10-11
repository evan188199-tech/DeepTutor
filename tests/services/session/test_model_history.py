from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.services.session.context_builder import ContextBuilder, _ContextSummaryAgent
from deeptutor.services.session.model_history import (
    complete_tool_results,
    normalize_model_turn,
    replay_history,
)
from deeptutor.services.session.provider_response_state import redact_private_message_metadata


def turn_record(text="tool evidence"):
    return {
        "version": 1,
        "system": "Standing tutor instructions",
        "tools": [
            {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
        ],
        "route": {"provider": "openai", "model": "gpt-test"},
        "messages": [
            {"role": "user", "content": "Question with prepared seed"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private plan",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{ "key": "value" }'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": text},
            {"role": "assistant", "content": "Original answer"},
        ],
    }


def rows(record, start=1):
    return [
        {"id": start, "role": "user", "content": "Question"},
        {
            "id": start + 1,
            "role": "assistant",
            "content": "Displayed answer",
            "metadata": {"model_turn": record},
        },
    ]


def test_replay_preserves_exact_protocol_without_duplicating_the_display_rows():
    record = turn_record()
    source = rows(record)
    result = replay_history(source)
    assert result == record["messages"]
    result[-1]["content"] = "mutated by the next turn"
    assert record["messages"][-1]["content"] == "Original answer"
    redact_private_message_metadata(source)
    assert source[-1]["metadata"] == {}


def test_invalid_or_incomplete_protocol_uses_display_history():
    record = turn_record()
    record["messages"].pop(2)
    assert normalize_model_turn(record) is None
    assert replay_history(rows(record)) == [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Displayed answer"},
    ]
    record["version"] = 99
    assert normalize_model_turn(record) is None


def test_interruption_closes_unfinished_calls_without_claiming_success():
    messages = turn_record()["messages"][:2]
    closed = complete_tool_results(messages)
    assert len(messages) == 2
    assert closed[-1]["tool_call_id"] == "call-1"
    assert "interrupted" in closed[-1]["content"]
    assert normalize_model_turn({"version": 1, "messages": closed}) is not None


def test_model_switch_keeps_tool_evidence_but_drops_provider_private_state():
    record = turn_record()
    record["messages"][1]["_provider_response_state"] = {
        "responses_output_items": [{"type": "reasoning", "id": "provider-only"}]
    }
    source = rows(record)
    same = replay_history(source, route=record["route"])
    switched = replay_history(source, route={"provider": "anthropic", "model": "claude-test"})
    assert same[1]["reasoning_content"] == "private plan"
    assert "reasoning_content" not in switched[1]
    assert "_provider_response_state" not in switched[1]
    assert switched[1]["tool_calls"] == same[1]["tool_calls"]
    assert switched[2]["content"] == "tool evidence"


def test_image_and_resolved_user_reply_survive_the_private_history_projection():
    record = turn_record()
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}
    record["messages"][0]["content"] = [{"type": "text", "text": "Explain this"}, image]
    record["messages"][1]["tool_calls"][0]["function"]["name"] = "ask_user"
    record["messages"][2]["content"] = "The user answered: use a geometric proof."
    rebuilt = replay_history(rows(record))
    assert rebuilt[0]["content"][1] == image
    assert rebuilt[2]["tool_call_id"] == "call-1"
    assert "geometric proof" in rebuilt[2]["content"]


@pytest.mark.asyncio
async def test_compaction_preserves_whole_tool_turns_and_reuses_the_old_prefix():
    old = turn_record("evidence " * 1800)
    # The overflow must come from dialogue, which replay condensation never
    # shrinks; the old turn's tool evidence stays whole in the replay request.
    old["messages"][0]["content"] = "Question detail " * 400
    recent = turn_record("recent evidence")
    records = rows(old) + rows(recent, 3)
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
    )
    store.get_messages_for_context = AsyncMock(return_value=records)
    store.update_summary = AsyncMock()
    builder = ContextBuilder(store)
    builder._summarize = AsyncMock(return_value=("Summary preserving the evidence", []))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(
            model="gpt-test",
            max_tokens=512,
            context_window=4096,
        ),
    )
    request = builder._summarize.call_args.kwargs["replay_request"]
    assert request["messages"] == [
        {"role": "system", "content": recent["system"]},
        *old["messages"],
    ]
    assert request["tools"] == recent["tools"]
    store.update_summary.assert_awaited_once_with("s", "Summary preserving the evidence", 2)
    assert result.model_history[1:] == recent["messages"]
    assert result.conversation_history[-1]["content"] == "Displayed answer"


@pytest.mark.asyncio
async def test_summary_instruction_is_appended_after_original_messages_and_tools(monkeypatch):
    captured = {}

    async def stream(_self, **kwargs):
        captured.update(kwargs)
        yield "Summary"

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    record = turn_record()
    request = {
        "messages": [{"role": "system", "content": record["system"]}, *record["messages"]],
        "tools": record["tools"],
    }
    original = deepcopy(request)
    await ContextBuilder(MagicMock())._summarize(
        session_id="s",
        language="en",
        source_text="fallback transcript",
        summary_budget=256,
        replay_request=request,
    )
    assert captured["messages"][:-1] == request["messages"]
    assert captured["messages"][-1]["role"] == "user"
    assert captured["tools"] == request["tools"]
    assert "tool_choice" not in captured
    assert request == original


@pytest.mark.asyncio
async def test_branch_replay_and_public_export_are_isolated(tmp_path):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "history.db")
    session = await store.create_session()
    sid = session["id"]
    root = await store.add_message(sid, "user", "Root")
    first = await store.add_message(
        sid,
        "assistant",
        "Branch A",
        parent_message_id=root,
        metadata={"model_turn": turn_record("A only")},
    )
    await store.add_message(
        sid,
        "assistant",
        "Branch B",
        parent_message_id=root,
        metadata={"model_turn": turn_record("B only")},
    )
    built = await ContextBuilder(store).build(
        session_id=sid,
        leaf_message_id=first,
        llm_config=SimpleNamespace(model="gpt-test", context_window=128000, max_tokens=4096),
    )
    tool_results = [m["content"] for m in built.model_history if m["role"] == "tool"]
    assert tool_results == ["A only"]


# ---------------------------------------------------------------------------
# Replay tool-result budget (upstream #1920)
# ---------------------------------------------------------------------------

_REPLAY_ENV_KNOBS = (
    "DEEPTUTOR_REPLAY_FULL_TOOL_TURNS",
    "DEEPTUTOR_REPLAY_TOOL_RESULT_MAX_CHARS",
    "DEEPTUTOR_REPLAY_TOOL_RESULTS_TOTAL_CHARS",
)


def tool_turn_record(results, user="Question"):
    """A model turn with one tool round per ``(tool_name, result)`` pair."""
    messages = [{"role": "user", "content": user}]
    for index, (tool_name, result) in enumerate(results):
        call_id = f"call-{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
    messages.append({"role": "assistant", "content": "Answer"})
    return {
        "version": 1,
        "system": "Standing tutor instructions",
        "tools": [
            {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
        ],
        "route": {"provider": "openai", "model": "gpt-test"},
        "messages": messages,
    }


def _pin_replay_budget(monkeypatch, *, max_chars, total_chars, full_turns="1"):
    monkeypatch.setenv("DEEPTUTOR_REPLAY_TOOL_RESULT_MAX_CHARS", str(max_chars))
    monkeypatch.setenv("DEEPTUTOR_REPLAY_TOOL_RESULTS_TOTAL_CHARS", str(total_chars))
    monkeypatch.setenv("DEEPTUTOR_REPLAY_FULL_TOOL_TURNS", str(full_turns))


def _tool_contents(messages):
    return [m["content"] for m in messages if m.get("role") == "tool"]


def test_older_turn_tool_results_condensed_newest_turn_kept_full(monkeypatch):
    _pin_replay_budget(monkeypatch, max_chars=4000, total_chars=32000)
    old_result = "mastery map " + "a" * 50_000
    new_result = "latest map " + "b" * 50_000
    old = rows(tool_turn_record([("mastery_build", old_result)]))
    new = rows(tool_turn_record([("mastery_revise", new_result)]), 3)
    replayed = replay_history(old + new)
    contents = _tool_contents(replayed)
    assert len(contents) == 2
    assert contents[1] == new_result
    assert contents[0].startswith(old_result[:100])
    assert "condensed" in contents[0]
    assert len(contents[0]) <= 4_000 + 300
    assert [m["content"] for m in replayed if m.get("role") == "user"] == ["Question", "Question"]
    assert [
        m["content"] for m in replayed if m.get("role") == "assistant" and m.get("content")
    ] == ["Answer", "Answer"]
    call_ids = {c["id"] for m in replayed for c in m.get("tool_calls") or []}
    assert call_ids == {m["tool_call_id"] for m in replayed if m.get("role") == "tool"}


def test_learner_replies_survive_condensation_with_defaults(monkeypatch):
    for name in _REPLAY_ENV_KNOBS:
        monkeypatch.delenv(name, raising=False)
    learner_answer = "The user answered: I prefer a geometric proof because " * 200
    status_map = "status map " + "c" * 50_000
    old = rows(tool_turn_record([("ask_user", learner_answer), ("mastery_status", status_map)]))
    new = rows(tool_turn_record([("mastery_status", '{"objectives": []}')]), 3)
    contents = _tool_contents(replay_history(old + new))
    assert contents[0] == learner_answer
    assert contents[1].startswith("status map ")
    assert "condensed" in contents[1]
    assert contents[2] == '{"objectives": []}'


def test_multi_turn_replay_payload_stays_bounded(monkeypatch):
    _pin_replay_budget(monkeypatch, max_chars=4000, total_chars=8000)
    state = "state " + "x" * 19_994
    turns = [
        rows(tool_turn_record([("mastery_status", state)]), start=index * 2 + 1)
        for index in range(6)
    ]
    replayed = replay_history([row for turn in turns for row in turn])
    tool_chars = sum(len(content) for content in _tool_contents(replayed))
    # Unbudgeted replay would carry 6 x 20k = 120k characters of tool state;
    # the budget holds the older axis at 8k while the newest turn stays whole.
    assert 20_000 <= tool_chars <= 20_000 + 8_000 + 6 * 250
    assert _tool_contents(replayed)[-1] == state
    assert _tool_contents(replayed)[0].startswith("[older tool result")


def test_condensation_can_be_tuned_or_disabled(monkeypatch):
    huge = "z" * 30_000
    old = rows(tool_turn_record([("mastery_build", huge)]))
    new = rows(tool_turn_record([("mastery_build", huge)]), 3)
    monkeypatch.setenv("DEEPTUTOR_REPLAY_TOOL_RESULT_MAX_CHARS", "0")
    assert replay_history(old + new) == replay_history(old + new, condense_tool_results=False)
    _pin_replay_budget(monkeypatch, max_chars=500, total_chars=100_000)
    condensed = _tool_contents(replay_history(old + new))[0]
    assert condensed.startswith("z" * 100)
    assert len(condensed) <= 500 + 250
    third = rows(tool_turn_record([("mastery_build", huge)]), 5)
    _pin_replay_budget(monkeypatch, max_chars=500, total_chars=100_000, full_turns="2")
    contents = _tool_contents(replay_history(old + new + third))
    assert contents[2] == huge
    assert contents[1] == huge
    assert "condensed" in contents[0]


def test_condensation_never_mutates_stored_records(monkeypatch):
    _pin_replay_budget(monkeypatch, max_chars=1000, total_chars=32000)
    old = rows(tool_turn_record([("mastery_build", "map " + "a" * 9_996)]))
    new = rows(tool_turn_record([("mastery_build", "latest map")]), 3)
    snapshot = deepcopy(old + new)
    replay_history(old + new)
    assert old + new == snapshot


@pytest.mark.asyncio
async def test_within_budget_history_condenses_older_turn_results(monkeypatch):
    _pin_replay_budget(monkeypatch, max_chars=4000, total_chars=32000)
    turns = [
        rows(tool_turn_record([("mastery_build", "map " + "a" * 49_996)]), 1),
        rows(tool_turn_record([("mastery_revise", "map " + "b" * 49_996)]), 3),
        rows(tool_turn_record([("mastery_status", '{"objectives": []}')]), 5),
    ]
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
    )
    store.get_messages_for_context = AsyncMock(return_value=[row for turn in turns for row in turn])
    builder = ContextBuilder(store)
    builder._summarize = AsyncMock(return_value=("Summary", []))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-test", max_tokens=512, context_window=272000),
    )
    builder._summarize.assert_not_awaited()
    contents = _tool_contents(result.model_history)
    assert contents[2] == '{"objectives": []}'
    assert "condensed" in contents[0]
    assert "condensed" in contents[1]
    assert contents[1].startswith("map ")
    assert [m["content"] for m in result.model_history if m.get("role") == "user"] == [
        "Question"
    ] * 3


@pytest.mark.asyncio
async def test_summarizer_replay_request_sees_full_old_evidence(monkeypatch):
    _pin_replay_budget(monkeypatch, max_chars=4000, total_chars=32000)
    results = {
        "a": "map a " + "a" * 49_993,
        "b": "map b " + "b" * 49_993,
        "c": "map c " + "c" * 49_993,
        "d": "map d " + "d" * 7_994,
    }
    long_question = "Question detail " * 1000
    turns = [
        rows(
            tool_turn_record(
                [("mastery_build", results["a"]), ("mastery_status", results["b"])],
                user=long_question,
            )
        ),
        rows(tool_turn_record([("mastery_revise", results["c"])], user=long_question)),
        rows(tool_turn_record([("mastery_revise", results["d"])], user="Question detail " * 500)),
        rows(tool_turn_record([("mastery_status", '{"objectives": []}')]), 7),
    ]
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
    )
    store.get_messages_for_context = AsyncMock(return_value=[row for turn in turns for row in turn])
    store.update_summary = AsyncMock()
    builder = ContextBuilder(store)
    builder._summarize = AsyncMock(return_value=("Summary", []))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-test", max_tokens=512, context_window=24000),
    )
    builder._summarize.assert_awaited_once()
    # The drift-free rebuild folds the FULL old evidence into the summary.
    request = builder._summarize.call_args.kwargs["replay_request"]
    assert _tool_contents(request["messages"]) == [results["a"], results["b"], results["c"]]
    # The main-loop replay itself stays budgeted: the newest retained turn
    # verbatim, the older retained turn condensed.
    contents = _tool_contents(result.model_history)
    assert contents[1] == '{"objectives": []}'
    assert "condensed" in contents[0]
    assert contents[0].startswith("map d ")
