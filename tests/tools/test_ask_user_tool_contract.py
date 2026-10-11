"""Contract tests for the ``ask_user`` tool surface.

Covers the parts around ``tests/tools/test_ask_user.py``'s payload
coverage: the ``AskUserTool`` definition/execute contract, the residual
branches of ``deeptutor/tools/ask_user.py`` (clipping, legacy preview
shape, duplicate-id suffixing, non-string coercion), and the pause
boundary in ``agents/loop/pipeline.py`` — submit / unresolved-wait /
cancel — that turns a ``pause_for_user`` result into either a resumed
loop or a halted turn.

The drafts (``ask_user_drafts``), trace persistence
(``ask_user_trace``) and frontend interaction axes are covered elsewhere.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.loop.pipeline import (
    _flatten_ask_user_summary,
    _format_user_reply_body,
    _normalise_user_reply,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.tools.ask_user import (
    MAX_INTRO_CHARS,
    MAX_PLACEHOLDER_CHARS,
    build_ask_user_payload,
    build_ask_user_preview,
)
from deeptutor.tools.builtin import AskUserTool

# --------------------------- tool parameter contract ---------------------------


def test_definition_name_and_required_parameters() -> None:
    definition = AskUserTool().get_definition()
    assert definition.name == "ask_user"
    required = {p.name: p.required for p in definition.parameters}
    assert required == {"questions": True, "intro": False}
    questions = next(p for p in definition.parameters if p.name == "questions")
    assert questions.type == "array"
    assert questions.items["required"] == ["prompt"]


def test_definition_hides_legacy_shape_and_documents_option_label() -> None:
    definition = AskUserTool().get_definition()
    assert [p.name for p in definition.parameters] == ["questions", "intro"]
    questions = next(p for p in definition.parameters if p.name == "questions")
    option_item = questions.items["properties"]["options"]["items"]
    assert option_item["required"] == ["label"]
    assert "multi_select" in questions.items["properties"]
    assert "allow_free_text" in questions.items["properties"]


# ------------------------------ execute: success ------------------------------


@pytest.mark.asyncio
async def test_execute_returns_pause_result_with_payload_metadata() -> None:
    result = await AskUserTool().execute(
        questions=[{"prompt": "Scope?", "options": ["A", "B"]}],
        intro="pick one",
    )
    assert result.success is True
    payload = result.pause_for_user
    assert payload is not None
    assert result.metadata["ask_user"] == payload
    assert payload["intro"] == "pick one"
    assert payload["questions"][0]["prompt"] == "Scope?"
    assert payload["questions"][0]["options"] == [
        {"label": "A", "description": None},
        {"label": "B", "description": None},
    ]
    assert "Scope?" in result.content


@pytest.mark.asyncio
async def test_execute_normalises_legacy_single_question_shape() -> None:
    result = await AskUserTool().execute(question="Depth?", options=["Shallow", "Deep"])
    assert result.success is True
    payload = result.pause_for_user
    assert payload is not None
    assert len(payload["questions"]) == 1
    only = payload["questions"][0]
    assert only["prompt"] == "Depth?"
    assert [o["label"] for o in only["options"]] == ["Shallow", "Deep"]


# ------------------------------ execute: rejection -----------------------------


@pytest.mark.parametrize(
    ("kwargs", "error_fragment"),
    [
        ({"questions": []}, "at least one"),
        ({"questions": "not-a-list"}, "array"),
        ({"questions": ["bare string"]}, "object"),
        ({"question": "   "}, "prompt"),
        ({}, "at least one"),
    ],
)
@pytest.mark.asyncio
async def test_execute_rejects_invalid_arguments_without_pause(
    kwargs: dict[str, Any], error_fragment: str
) -> None:
    result = await AskUserTool().execute(**kwargs)
    assert result.success is False
    assert error_fragment in result.content
    assert result.pause_for_user is None


# ------------------- payload builder: residual clipped branches -----------------


def test_intro_is_clipped_with_ellipsis_in_payload() -> None:
    payload, err = build_ask_user_payload(
        questions=[{"prompt": "hi"}],
        intro="x" * (MAX_INTRO_CHARS + 40),
    )
    assert err is None and payload is not None
    assert payload.intro is not None
    assert payload.intro.endswith("…")
    assert len(payload.intro) <= MAX_INTRO_CHARS + 1


def test_intro_is_clipped_with_ellipsis_in_preview() -> None:
    preview = build_ask_user_preview(
        '{"intro": "' + "x" * (MAX_INTRO_CHARS + 40) + '", "questions": []}'
    )
    assert preview is not None
    intro = preview["intro"]
    assert intro is not None
    assert intro.endswith("…")
    assert len(intro) <= MAX_INTRO_CHARS + 1


def test_both_question_sources_missing_is_rejected() -> None:
    payload, err = build_ask_user_payload()
    assert payload is None
    assert err and "at least one" in err


def test_preview_accepts_legacy_question_key() -> None:
    preview = build_ask_user_preview('{"question": "Legacy?", "options": ["a"]}')
    assert preview is not None
    assert preview["intro"] is None
    assert len(preview["questions"]) == 1
    assert preview["questions"][0]["prompt"] == "Legacy?"
    assert [o["label"] for o in preview["questions"][0]["options"]] == ["a"]


def test_preview_returns_none_when_repair_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.tools.ask_user as ask_user_module

    def _boom(_text: str) -> Any:
        raise ValueError("unparseable")

    monkeypatch.setattr(ask_user_module.json_repair, "loads", _boom)
    assert build_ask_user_preview('{"questions": "') is None


def test_placeholder_is_clipped_with_ellipsis() -> None:
    payload, _ = build_ask_user_payload(
        questions=[{"prompt": "x", "placeholder": "p" * (MAX_PLACEHOLDER_CHARS + 30)}]
    )
    assert payload is not None
    placeholder = payload.questions[0].placeholder
    assert placeholder is not None
    assert placeholder.endswith("…")
    assert len(placeholder) <= MAX_PLACEHOLDER_CHARS + 1


def test_triple_duplicate_ids_get_sequential_suffixes() -> None:
    payload, _ = build_ask_user_payload(
        questions=[
            {"id": "x", "prompt": "1"},
            {"id": "x", "prompt": "2"},
            {"id": "x", "prompt": "3"},
        ]
    )
    assert payload is not None
    assert payload.question_ids == ("x", "x_2", "x_3")


@pytest.mark.parametrize(
    "raw",
    [7, 4.5],
)
def test_non_string_question_fields_are_coerced(raw: Any) -> None:
    payload, err = build_ask_user_payload(questions=[{"id": raw, "prompt": raw}])
    assert err is None and payload is not None
    assert payload.questions[0].prompt == str(raw)


# ------------------------- reply normalisation helpers -------------------------


def test_normalise_user_reply_plain_string() -> None:
    assert _normalise_user_reply("just text") == ("just text", None)


def test_normalise_user_reply_dict_with_answers() -> None:
    text, answers = _normalise_user_reply(
        {
            "text": "picks",
            "answers": [
                {"questionId": "q1", "text": "Advanced"},
                {"id": "q2", "text": "Core"},
                "junk",
                {"text": "no question id"},
            ],
        }
    )
    assert text == "picks"
    assert answers == [
        {"questionId": "q1", "text": "Advanced"},
        {"questionId": "q2", "text": "Core"},
    ]


def test_normalise_user_reply_dict_without_answers() -> None:
    assert _normalise_user_reply({"text": "free reply"}) == ("free reply", None)
    assert _normalise_user_reply({}) == ("", None)


def test_normalise_user_reply_other_types_become_strings() -> None:
    assert _normalise_user_reply(None) == ("", None)
    assert _normalise_user_reply(7) == ("7", None)


def test_format_user_reply_body_maps_answers_to_prompts() -> None:
    body = _format_user_reply_body(
        "",
        [{"questionId": "scope", "text": "Advanced"}],
        {"questions": [{"id": "scope", "prompt": "Which scope?"}]},
    )
    assert body == "User answered:\n- Which scope?\n  -> Advanced"


def test_format_user_reply_body_empty_answer_becomes_skipped() -> None:
    body = _format_user_reply_body(
        "",
        [{"questionId": "scope", "text": "  "}],
        {"questions": [{"id": "scope", "prompt": "Which scope?"}]},
    )
    assert "-> (skipped)" in body


def test_format_user_reply_body_unknown_question_id_uses_id() -> None:
    body = _format_user_reply_body("", [{"questionId": "ghost", "text": "x"}], {})
    assert "- ghost\n  -> x" in body


def test_format_user_reply_body_plain_text_reply() -> None:
    body = _format_user_reply_body("make it fast", None, {})
    assert body == "User answered: make it fast"


def test_format_user_reply_body_empty_reply_falls_back() -> None:
    assert _format_user_reply_body("   ", None, {}) == "User answered: (empty reply)"


def test_flatten_ask_user_summary_joins_prompts() -> None:
    summary = _flatten_ask_user_summary({"questions": [{"prompt": "A?"}, {"prompt": "B?"}]})
    assert summary == "A? | B?"


def test_flatten_ask_user_summary_legacy_question_field() -> None:
    assert _flatten_ask_user_summary({"question": "legacy?"}) == "legacy?"


# ------------------------- pause boundary (resume axis) ------------------------


def _pause_dispatch() -> DispatchOutcome:
    return DispatchOutcome(
        tool_messages=[
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "ask_user",
                "content": "[awaiting user reply to: Scope?]",
            }
        ],
        pause=True,
        pause_payload={
            "tool_name": "ask_user",
            "ask_user": {
                "intro": None,
                "questions": [
                    {
                        "id": "scope",
                        "prompt": "Scope?",
                        "header": None,
                        "multi_select": False,
                        "options": [{"label": "Advanced", "description": None}],
                        "allow_free_text": True,
                        "placeholder": None,
                    }
                ],
            },
        },
        pause_tool_call_id="call-1",
    )


def _context(**overrides: Any) -> UnifiedContext:
    return UnifiedContext(session_id="s", user_message="hi", language="en", **overrides)


def _tool_message(dispatch: DispatchOutcome) -> dict[str, Any]:
    return dispatch.tool_messages[0]


async def _resolve(
    pipeline: Any,
    context: UnifiedContext,
    dispatch: DispatchOutcome,
) -> tuple[bool, StreamBus]:
    bus = StreamBus()
    resumed = await pipeline._await_user_reply_and_resolve(
        context=context, stream=bus, dispatch=dispatch
    )
    return resumed, bus


@pytest.fixture
def pipeline() -> Any:
    from deeptutor.agents.loop.pipeline import AgenticLoopPipeline

    return AgenticLoopPipeline(language="en")


@pytest.mark.asyncio
async def test_submitted_answers_resume_the_loop_and_substitute_into_the_tool_message(
    pipeline: Any,
) -> None:
    context = _context()

    async def _reply() -> dict[str, Any]:
        return {"text": "", "answers": [{"questionId": "scope", "text": "Advanced"}]}

    context.runtime.wait_for_user_reply = _reply
    dispatch = _pause_dispatch()
    resumed, bus = await _resolve(pipeline, context, dispatch)

    assert resumed is True
    body = _tool_message(dispatch)["content"]
    assert "User answered:" in body
    assert "Scope?" in body
    assert "-> Advanced" in body
    assert "Continue the user's original request" in body

    traces = [e for e in bus._history if e.type == StreamEventType.PROGRESS]
    resolved = [e for e in traces if e.metadata.get("ask_user_resolved")]
    assert len(resolved) == 1
    assert resolved[0].metadata["answers"] == [{"questionId": "scope", "text": "Advanced"}]
    assert resolved[0].metadata["ask_user_tool_call_id"] == "call-1"


@pytest.mark.asyncio
async def test_pause_and_resume_hooks_receive_the_payload_and_answers(
    pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class _Recorder:
        name = "recorder"

        async def on_user_pause(self, context: Any, ask_user: dict[str, Any]) -> None:
            seen["pause"] = ask_user

        async def on_user_resume(
            self,
            context: Any,
            ask_user: dict[str, Any],
            *,
            reply_text: str,
            answers: Any,
        ) -> None:
            seen["resume"] = (reply_text, answers)

    import deeptutor.agents.loop.pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module, "active_loop_capabilities", lambda _context: (_Recorder(),)
    )
    context = _context()

    async def _reply() -> dict[str, Any]:
        return {"text": "free", "answers": None}

    context.runtime.wait_for_user_reply = _reply
    dispatch = _pause_dispatch()
    resumed, _bus = await _resolve(pipeline, context, dispatch)

    assert resumed is True
    assert seen["pause"]["questions"][0]["prompt"] == "Scope?"
    assert seen["resume"] == ("free", None)


@pytest.mark.asyncio
async def test_missing_waiter_halts_with_question_summary_as_final_response(
    pipeline: Any,
) -> None:
    """No runtime waiter — the pending question becomes the final artefact."""
    context = _context()
    dispatch = _pause_dispatch()
    resumed, bus = await _resolve(pipeline, context, dispatch)

    assert resumed is False
    contents = [e for e in bus._history if e.type == StreamEventType.CONTENT]
    assert len(contents) == 1
    assert contents[0].content == "Scope?"
    assert contents[0].metadata["tool_metadata"]["ask_user"]["questions"][0]["prompt"] == "Scope?"
    assert _tool_message(dispatch)["content"] == "[awaiting user reply to: Scope?]"


@pytest.mark.asyncio
async def test_cancelled_wait_stops_without_substitution_or_final_response(
    pipeline: Any,
) -> None:
    """A ``None`` reply is the learner abandoning the turn — nothing more to do."""
    context = _context()

    async def _reply() -> None:
        return None

    context.runtime.wait_for_user_reply = _reply
    dispatch = _pause_dispatch()
    resumed, bus = await _resolve(pipeline, context, dispatch)

    assert resumed is False
    assert bus._history == []
    assert _tool_message(dispatch)["content"] == "[awaiting user reply to: Scope?]"


@pytest.mark.asyncio
async def test_end_loop_signal_stops_after_the_reply_is_traced(pipeline: Any) -> None:
    """A stop signal raised while paused wins over feeding the answer back."""
    context = _context()
    context.interaction.end_loop = True

    async def _reply() -> dict[str, Any]:
        return {"text": "free reply", "answers": None}

    context.runtime.wait_for_user_reply = _reply
    dispatch = _pause_dispatch()
    resumed, bus = await _resolve(pipeline, context, dispatch)

    assert resumed is False
    traces = [e for e in bus._history if e.metadata.get("ask_user_resolved")]
    assert len(traces) == 1
    assert _tool_message(dispatch)["content"] == "[awaiting user reply to: Scope?]"
