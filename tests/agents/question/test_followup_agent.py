"""Focused unit tests for the single-call quiz ``FollowupAgent``.

Covers the prompt-assembly contract (custom vs. built-in fallback template,
blank-input normalization), the LLM output contract (chunks joined verbatim,
malformed text passed through unvalidated, empty stream -> empty reply), and
the failure contract (provider errors and timeouts propagate to the caller —
degradation is owned upstream, the agent must not mask them).

All LLM traffic is stubbed on the agent subclass; nothing touches the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from deeptutor.agents.question.agents.followup_agent import FollowupAgent


class RecordingFollowupAgent(FollowupAgent):
    """``FollowupAgent`` stub that skips ``BaseAgent.__init__``, scripts the
    streamed chunks, and records every ``stream_llm`` call for assertions."""

    def __init__(
        self,
        prompts: dict[str, Any] | None = None,
        chunks: Sequence[str] = (),
        stream_error: BaseException | None = None,
        language: str = "zh",
    ) -> None:
        self.module_name = "question"
        self.agent_name = "followup_agent"
        self.language = language
        self.prompts = prompts
        self.chunks = list(chunks)
        self.stream_error = stream_error
        self.calls: list[dict[str, Any]] = []

    async def stream_llm(self, **kwargs: Any):  # type: ignore[override]
        self.calls.append(dict(kwargs))
        for chunk in self.chunks:
            yield chunk
        if self.stream_error is not None:
            raise self.stream_error


async def _process(
    agent: RecordingFollowupAgent,
    *,
    user_message: str = "why?",
    question_context: dict[str, Any] | None = None,
    history_context: str = "",
    attachments: list[Any] | None = None,
) -> str:
    return await agent.process(
        user_message=user_message,
        question_context=question_context if question_context is not None else {},
        history_context=history_context,
        attachments=attachments,
    )


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_formats_custom_template_with_rendered_context() -> None:
    template = "CTX:{question_context}||HIST:{history_context}||MSG:{user_message}"
    agent = RecordingFollowupAgent(
        prompts={"system": "Followup system", "answer_followup": template},
        chunks=["答", "案"],
    )

    reply = await _process(
        agent,
        user_message="  Why this answer?  ",
        question_context={"question_id": "q_7", "question": "Q text"},
        history_context="user: hi",
    )

    assert reply == "答案"
    assert len(agent.calls) == 1
    call = agent.calls[0]
    user_prompt = str(call["user_prompt"])
    assert user_prompt.startswith("CTX:")
    assert "Question ID: q_7" in user_prompt
    assert "Question:\nQ text" in user_prompt
    assert "HIST:user: hi" in user_prompt
    assert "MSG:Why this answer?" in user_prompt
    assert call["stage"] == "followup_answer"
    assert call["attachments"] is None
    assert str(call["system_prompt"]).startswith("Followup system")


@pytest.mark.asyncio
async def test_process_falls_back_to_builtin_template_when_prompt_missing() -> None:
    agent = RecordingFollowupAgent(prompts=None, chunks=["ok"])

    reply = await _process(
        agent,
        question_context={"question_id": "q_2", "question": "2+2?"},
    )

    assert reply == "ok"
    user_prompt = str(agent.calls[0]["user_prompt"])
    assert "Question context:" in user_prompt
    assert "Conversation history:" in user_prompt
    assert "User follow-up:" in user_prompt
    assert "2+2?" in user_prompt
    assert "why?" in user_prompt


@pytest.mark.asyncio
async def test_process_normalizes_blank_user_message_and_history() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "H:{history_context}|M:{user_message}"},
        chunks=["x"],
    )

    await _process(agent, user_message="   \n\t", history_context="")

    user_prompt = str(agent.calls[0]["user_prompt"])
    assert "M:(empty)" in user_prompt
    assert "H:(none)" in user_prompt


@pytest.mark.asyncio
async def test_process_joins_chunks_in_order_and_builds_trace_metadata() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "Q:{question_context}"},
        chunks=["a", "b", "c"],
    )
    attachment = object()

    reply = await _process(
        agent,
        question_context={"question_id": "q_3"},
        history_context="h",
        attachments=[attachment],
    )

    assert reply == "abc"
    call = agent.calls[0]
    assert call["attachments"] == [attachment]
    trace = call["trace_meta"]
    assert trace["label"] == "Answer follow-up for Question 3"
    assert trace["phase"] == "generation"
    assert trace["call_kind"] == "llm_generation"
    assert trace["trace_id"] == "q_3"
    assert trace["question_id"] == "q_3"
    assert str(trace["call_id"]).startswith("quiz-followup-q_3-")


# ---------------------------------------------------------------------------
# LLM output contract (parsing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_returns_malformed_output_verbatim() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "Q:{question_context}"},
        chunks=['{"answer": ', "not closed", " }}}"],
    )

    reply = await _process(agent)

    assert reply == '{"answer": not closed }}}'
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_process_returns_empty_string_when_stream_is_empty() -> None:
    agent = RecordingFollowupAgent(prompts={"answer_followup": "Q:{question_context}"})

    reply = await _process(agent)

    assert reply == ""


# ---------------------------------------------------------------------------
# Failure / timeout degradation contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_propagates_llm_failure_without_partial_reply() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "Q:{question_context}"},
        stream_error=RuntimeError("provider down"),
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await _process(agent)
    assert agent.calls  # the single LLM call surfaced the failure


@pytest.mark.asyncio
async def test_process_propagates_mid_stream_failure() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "Q:{question_context}"},
        chunks=["partial answer "],
        stream_error=RuntimeError("stream cut"),
    )

    with pytest.raises(RuntimeError, match="stream cut"):
        await _process(agent)


@pytest.mark.asyncio
async def test_process_propagates_llm_timeout() -> None:
    agent = RecordingFollowupAgent(
        prompts={"answer_followup": "Q:{question_context}"},
        stream_error=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await _process(agent)


# ---------------------------------------------------------------------------
# Question-context rendering
# ---------------------------------------------------------------------------


def test_render_question_context_renders_options_and_correctness() -> None:
    rendered = FollowupAgent._render_question_context(
        {
            "question_id": "q_4",
            "question_type": "single_choice",
            "difficulty": "easy",
            "concentration": "vectors",
            "question": "Which is true?",
            "options": {"A": "Option A", "B": "", "C": "   ", "D": "Option D"},
            "user_answer": "A",
            "is_correct": True,
            "correct_answer": "A",
            "explanation": "Because A.",
        }
    )

    assert "Question ID: q_4" in rendered
    assert "Question type: single_choice" in rendered
    assert "Difficulty: easy" in rendered
    assert "Concentration: vectors" in rendered
    assert "Options:" in rendered
    assert "A. Option A" in rendered
    assert "D. Option D" in rendered
    assert "B." not in rendered
    assert "C." not in rendered
    assert "Learner answer: A" in rendered
    assert "Learner result: correct" in rendered
    assert "Reference answer: A" in rendered
    assert "Explanation:\nBecause A." in rendered
    assert "Knowledge context:" not in rendered


def test_render_question_context_missing_fields_and_knowledge_context() -> None:
    rendered = FollowupAgent._render_question_context(
        {
            "question_id": "",
            "question": "",
            "is_correct": False,
            "knowledge_context": "  Note about vectors.  ",
        }
    )

    assert "Question ID: (none)" in rendered
    assert "Question type: (none)" in rendered
    assert "Difficulty: (none)" in rendered
    assert "Concentration: (none)" in rendered
    assert "Options:" not in rendered
    assert "Learner answer: (not provided)" in rendered
    assert "Learner result: incorrect" in rendered
    assert "Reference answer: (none)" in rendered
    assert "Explanation:\n(none)" in rendered
    assert "Knowledge context:\nNote about vectors." in rendered


@pytest.mark.parametrize(
    ("is_correct", "expected"),
    [
        (True, "correct"),
        (False, "incorrect"),
        (None, "unknown"),
        ("yes", "unknown"),
    ],
)
def test_render_question_context_correctness_mapping(is_correct: Any, expected: str) -> None:
    rendered = FollowupAgent._render_question_context({"is_correct": is_correct})
    assert f"Learner result: {expected}" in rendered


@pytest.mark.parametrize("options", [None, ["A", "B"], "AB"])
def test_render_question_context_ignores_non_dict_options(options: Any) -> None:
    rendered = FollowupAgent._render_question_context({"options": options})
    assert "Options:" not in rendered


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("q_1", "Question 1"),
        ("q_42", "Question 42"),
        ("Q_7", "Question 7"),
        ("q_1b", "q_1b"),
        ("quiz-9", "quiz-9"),
        ("", "question"),
        (None, "question"),
        (0, "question"),
    ],
)
def test_humanize_question_id_variants(raw: Any, expected: str) -> None:
    assert FollowupAgent._humanize_question_id(raw) == expected
