"""Output-contract tests for the deep_question QuestionPipeline.

Locks the ideation → generation product contract at the pipeline boundary:

* **Plan stage (ideation)** — every usable idea becomes a ``QuizTemplate``
  with a canonical ``q_N`` id, a taxonomy-valid ``question_type`` (unknown
  planner types fall back), a ``difficulty`` inside the valid set, and the
  analysis carried through; the ``ideas`` alias is accepted so a prompt
  rewording cannot silently zero the quiz.
* **Quiz stage (generation)** — the FINISH JSON becomes a ``QuizPair`` whose
  fields (including the legacy ``concentration`` key) downstream renderers
  depend on; choice answers given as option text normalize to the option
  key; concept answers coerce to ``true``/``false``; non-choice options are
  stripped.
* **Result envelope** — ``response`` / ``summary`` / ``mode`` field contract,
  honest success accounting, and the per-question ``quiz_question_emitted``
  card metadata.
* **Empty knowledge boundary** — an empty exploration hands the planner an
  explicit empty-trace marker (never a dangling section), and a plan with
  zero templates fails loudly instead of shipping a zero-question quiz.
* **Generation failure** — an unparseable FINISH triggers exactly one repair
  round and degrades to a ``[Generation failed]`` placeholder with recorded
  issues; a pipeline-level failure emits a visible error event before
  re-raising.

The LLM seam is mocked at the ``deeptutor.runtime.agentic`` primitives
(``run_agentic_loop`` / ``run_labeled_step``) so the real orchestration runs
end to end with no network access.

Evidence: coverage gap 15 — ``deeptutor/agents/question/pipeline.py``
(origin/main @ ef2d9e5c3, 283 statements missing / 65.6%).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.question.pipeline import (
    CALL_KIND_QUIZ_QUESTION,
    STAGE_EXPLORING,
    STAGE_QUIZZING,
    SOURCE,
    QuestionPipeline,
    QuizPair,
    QuizTemplate,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic import LabeledStepResult, LoopOutcome


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_llm_config(monkeypatch) -> None:
    """Pipeline unit tests must not depend on a configured model catalog."""
    from deeptutor.services.llm.config import LLMConfig

    monkeypatch.setattr(
        "deeptutor.agents.question.pipeline.get_llm_config",
        lambda: LLMConfig(model="test-model", api_key="test-key"),
    )


def _make_pipeline() -> QuestionPipeline:
    return QuestionPipeline(language="en")


class _RecordingBus:
    """Duck-typed StreamBus capturing every emission for assertions."""

    def __init__(self) -> None:
        self.stages_started: list[str] = []
        self.stages_ended: list[str] = []
        self.contents: list[dict[str, Any]] = []
        self.progress_events: list[dict[str, Any]] = []
        self.error_events: list[dict[str, Any]] = []

    @asynccontextmanager
    async def stage(self, name: str, source: str = "", metadata: dict | None = None):
        self.stages_started.append(name)
        try:
            yield
        finally:
            self.stages_ended.append(name)

    async def content(
        self, text: str, source: str = "", stage: str = "", metadata: dict | None = None
    ) -> None:
        self.contents.append(
            {"text": text, "source": source, "stage": stage, "metadata": metadata or {}}
        )

    async def thinking(
        self, text: str, source: str = "", stage: str = "", metadata: dict | None = None
    ) -> None:
        return None

    async def progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0,
        source: str = "",
        stage: str = "",
        metadata: dict | None = None,
    ) -> None:
        self.progress_events.append(
            {"message": message, "source": source, "stage": stage, "metadata": metadata or {}}
        )

    async def error(
        self, message: str, source: str = "", stage: str = "", metadata: dict | None = None
    ) -> None:
        self.error_events.append(
            {"message": message, "source": source, "stage": stage, "metadata": metadata or {}}
        )


class _FakeLoop:
    """Stand-in for ``run_agentic_loop``: scripted FINISH replies per stage."""

    def __init__(self, *, explore_text: str = "", quiz_texts: list[str] | None = None) -> None:
        self.explore_text = explore_text
        self.quiz_texts = list(quiz_texts or [])
        self.calls: list[str] = []

    async def __call__(self, **kwargs: Any) -> LoopOutcome:
        stage = kwargs["stage"]
        self.calls.append(stage)
        if stage == STAGE_EXPLORING:
            return LoopOutcome(
                final_label="FINISH",
                final_text=self.explore_text,
                iterations=1,
                completed=True,
                messages=[],
            )
        if stage == STAGE_QUIZZING:
            return LoopOutcome(
                final_label="FINISH",
                final_text=self.quiz_texts.pop(0),
                iterations=1,
                completed=True,
                messages=[],
            )
        raise AssertionError(f"unexpected agentic loop stage {stage!r}")


class _FakeLabeledStep:
    """Stand-in for ``run_labeled_step``: canned PLAN / repair replies.

    The two protocols are told apart by ``allowed_labels`` — PLAN steps run
    under the PLAN-only protocol, repair under the FINISH-only protocol.
    """

    def __init__(self, *, plan_text: str = "", repair_texts: list[str] | None = None) -> None:
        self.plan_text = plan_text
        self.repair_texts = list(repair_texts or [])
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> LabeledStepResult:
        self.calls.append(kwargs)
        if tuple(kwargs["allowed_labels"]) == ("PLAN",):
            return LabeledStepResult(label="PLAN", text=self.plan_text, finish_reason="stop")
        return LabeledStepResult(
            label="FINISH", text=self.repair_texts.pop(0), finish_reason="stop"
        )


def _wire(
    monkeypatch,
    pipeline: QuestionPipeline,
    *,
    loop: _FakeLoop,
    step: _FakeLabeledStep,
) -> list[dict[str, Any]]:
    """Patch the module-level LLM seams and capture the result emission."""
    monkeypatch.setattr(
        "deeptutor.agents.question.pipeline.build_openai_client", lambda config: object()
    )
    monkeypatch.setattr(pipeline, "_prepare_pageindex_tools", AsyncMock())
    monkeypatch.setattr("deeptutor.agents.question.pipeline.run_agentic_loop", loop)
    monkeypatch.setattr("deeptutor.agents.question.pipeline.run_labeled_step", step)
    emitted: list[dict[str, Any]] = []

    async def fake_emit(stream, payload, *, source=None, usage=None):
        emitted.append({"source": source, "payload": payload})

    monkeypatch.setattr("deeptutor.agents.question.pipeline.emit_capability_result", fake_emit)
    return emitted


def _run(pipeline: QuestionPipeline, bus: _RecordingBus, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "context": UnifiedContext(user_message="quiz me", session_id="contract-test"),
        "user_message": "quiz me",
        "num_questions": 2,
        "stream": bus,
    }
    kwargs.update(overrides)
    return asyncio.run(pipeline.run(**kwargs))


_CHOICE_QUIZ_JSON = json.dumps(
    {
        "question": "Which process converts sunlight into chemical energy?",
        "options": {
            "A": "Respiration",
            "B": "Photosynthesis",
            "C": "Evaporation",
            "D": "Erosion",
        },
        "correct_answer": "Photosynthesis",
        "explanation": "Chloroplasts capture light energy.",
    }
)

_SHORT_ANSWER_QUIZ_JSON = json.dumps(
    {
        "question": "Define entropy in one sentence.",
        "correct_answer": "A measure of the disorder of a system.",
        "explanation": "It quantifies unavailable energy (second law).",
    }
)

_TWO_TEMPLATE_PLAN_JSON = json.dumps(
    {
        "analysis": "one recall + one applied",
        "templates": [
            {
                "topic": "Photosynthesis basics",
                "question_type": "choice",
                "difficulty": "easy",
            },
            {
                "topic": "Entropy",
                "question_type": "short_answer",
                "difficulty": "medium",
            },
        ],
    }
)


# ---------------------------------------------------------------------------
# Two-stage end-to-end product contract
# ---------------------------------------------------------------------------


def test_two_stage_run_output_field_contract(monkeypatch) -> None:
    """Full custom-mode run: plan fields, quiz fields, envelope, cards.

    The planner omits ``question_id`` on purpose — the pipeline must assign
    the canonical ``q_N`` sequence, because the emitted question cards, the
    notebook write-back and the frontend renderer all key on it. The choice
    answer arrives as option *text* and must reach the consumer as the
    option *key*.
    """
    pipeline = _make_pipeline()
    bus = _RecordingBus()
    loop = _FakeLoop(
        explore_text="I researched photosynthesis and entropy; generating 2 questions.",
        quiz_texts=[_CHOICE_QUIZ_JSON, _SHORT_ANSWER_QUIZ_JSON],
    )
    step = _FakeLabeledStep(plan_text=_TWO_TEMPLATE_PLAN_JSON)
    emitted = _wire(monkeypatch, pipeline, loop=loop, step=step)

    result = _run(pipeline, bus)

    # Stage order: exploring → planning → quizzing, each closed exactly once.
    assert bus.stages_started == ["exploring", "planning", "quizzing"]
    assert bus.stages_ended == ["exploring", "planning", "quizzing"]
    assert loop.calls == ["exploring", "quizzing", "quizzing"]
    assert len(step.calls) == 1

    # Envelope: exactly the three top-level keys, capability source tagged.
    assert set(result.keys()) == {"response", "summary", "mode"}
    assert result["mode"] == "custom"
    # Custom mode: response carries the explore FINISH preface, and the
    # per-question markdown lives only in the cards / summary.results.
    assert result["response"] == (
        "I researched photosynthesis and entropy; generating 2 questions."
    )
    assert len(emitted) == 1
    assert emitted[0]["source"] == SOURCE

    summary = result["summary"]
    assert set(summary.keys()) == {
        "success",
        "source",
        "requested",
        "template_count",
        "completed",
        "failed",
        "templates",
        "results",
        "analysis",
    }
    assert summary["success"] is True
    assert summary["source"] == "topic"
    assert summary["requested"] == 2
    assert summary["template_count"] == 2
    assert summary["completed"] == 2
    assert summary["failed"] == 0
    assert summary["analysis"] == "one recall + one applied"

    # Plan-stage contract: canonical ids, planner fields preserved, snapshot
    # exposes source + reference fields for downstream consumers.
    assert [t["question_id"] for t in summary["templates"]] == ["q_1", "q_2"]
    assert [t["topic"] for t in summary["templates"]] == ["Photosynthesis basics", "Entropy"]
    assert [t["question_type"] for t in summary["templates"]] == ["choice", "short_answer"]
    assert [t["difficulty"] for t in summary["templates"]] == ["easy", "medium"]
    assert all(t["source"] == "custom" for t in summary["templates"])
    assert all(t["reference_question"] is None for t in summary["templates"])

    # Quiz-stage contract: legacy qa_pair shape QuizViewer renders.
    qa_choice = summary["results"][0]["qa_pair"]
    assert set(qa_choice.keys()) == {
        "question_id",
        "question",
        "question_type",
        "options",
        "correct_answer",
        "explanation",
        "difficulty",
        "concentration",
    }
    assert qa_choice["question_id"] == "q_1"
    assert qa_choice["question_type"] == "choice"
    assert qa_choice["correct_answer"] == "B", "answer text must normalize to the option key"
    assert set(qa_choice["options"].keys()) == {"A", "B", "C", "D"}
    assert qa_choice["concentration"] == "Photosynthesis basics", (
        "legacy consumers read the topic under the 'concentration' key"
    )
    assert summary["results"][0]["metadata"] == {}

    qa_written = summary["results"][1]["qa_pair"]
    assert qa_written["correct_answer"] == "A measure of the disorder of a system."
    assert qa_written["options"] is None
    assert qa_written["concentration"] == "Entropy"

    # Incremental per-question cards: one structured CONTENT event each,
    # carrying the qa_pair the frontend renders immediately.
    cards = [c for c in bus.contents if c["metadata"].get("call_kind") == CALL_KIND_QUIZ_QUESTION]
    assert len(cards) == 2
    assert [c["metadata"]["question_index"] for c in cards] == [0, 1]
    assert all(c["metadata"]["total_questions"] == 2 for c in cards)
    assert all(c["metadata"]["trace_role"] == "quiz_question" for c in cards)
    assert all(c["source"] == SOURCE and c["stage"] == STAGE_QUIZZING for c in cards)
    assert cards[0]["metadata"]["qa_pair"]["question_id"] == "q_1"
    assert cards[1]["metadata"]["qa_pair"]["question_id"] == "q_2"
    assert "Which process converts sunlight" in cards[0]["text"]


# ---------------------------------------------------------------------------
# Plan-stage field contract (ideation output)
# ---------------------------------------------------------------------------


def test_plan_stage_field_contract(monkeypatch) -> None:
    """``_parse_plan`` output contract: canonical ids, type fallback,
    dedup + cap, and the ``ideas`` alias.

    A prompt change that renames ``templates`` to ``ideas`` (or emits an
    out-of-taxonomy type) must degrade to a valid quiz, never to a silent
    zero-question result or a bogus type leaking downstream.
    """
    pipeline = _make_pipeline()
    raw = json.dumps(
        {
            "analysis": "mixed recall and application",
            "templates": [
                "not-a-dict",
                {"topic": "", "question_type": "choice"},
                {"topic": "Chain rule", "question_type": "hyperbolic", "difficulty": "easy"},
                {"topic": "chain rule", "question_type": "choice"},
                {"topic": "Gradient descent", "question_type": "written", "difficulty": "hard"},
                {"topic": "Extra beyond the ask", "question_type": "written"},
            ],
        }
    )
    plan = pipeline._parse_plan(raw, requested=2, allowed_types=[], target_difficulty="")

    assert plan.analysis == "mixed recall and application"
    assert [t.question_id for t in plan.templates] == ["q_1", "q_2"], (
        "canonical sequential ids are assigned by the pipeline, not the planner"
    )
    assert [t.topic for t in plan.templates] == ["Chain rule", "Gradient descent"]
    assert plan.templates[0].question_type == "short_answer", (
        "an out-of-taxonomy type falls back to short_answer, not the bogus value"
    )
    assert plan.templates[0].difficulty == "easy"
    assert plan.templates[1].question_type == "written"
    assert len(plan.templates) == 2, "capped at the requested count"

    # A restricted allow-list pins the fallback type to that set.
    plan_choice = pipeline._parse_plan(
        raw, requested=2, allowed_types=["choice"], target_difficulty=""
    )
    assert all(t.question_type == "choice" for t in plan_choice.templates)

    # The ``ideas`` key is the accepted alias for ``templates``.
    plan_ideas = pipeline._parse_plan(
        json.dumps({"analysis": "", "ideas": [{"topic": "Bayes theorem"}]}),
        requested=3,
        allowed_types=[],
        target_difficulty="medium",
    )
    assert [t.question_id for t in plan_ideas.templates] == ["q_1"]
    assert plan_ideas.templates[0].topic == "Bayes theorem"
    assert plan_ideas.templates[0].question_type == "short_answer"
    assert plan_ideas.templates[0].difficulty == "medium", (
        "target difficulty applies when the template omits one"
    )


# ---------------------------------------------------------------------------
# Quiz-stage field contract (generation output)
# ---------------------------------------------------------------------------


def test_quiz_stage_payload_contract(monkeypatch) -> None:
    """``_quiz_one`` output contract per question type.

    The FINISH JSON is the model-facing product surface: whatever it emits,
    the QuizPair must come out type-correct — choice answers keyed, concept
    answers coerced to true/false, non-choice options stripped — because the
    grader and the renderer both read these fields verbatim.
    """
    choice_template = QuizTemplate(
        question_id="q_1", topic="Photosynthesis basics", question_type="choice", difficulty="easy"
    )
    concept_template = QuizTemplate(
        question_id="q_2", topic="Earth orbits the Sun", question_type="concept", difficulty="easy"
    )
    written_template = QuizTemplate(
        question_id="q_3", topic="Entropy", question_type="written", difficulty="medium"
    )

    pipeline = _make_pipeline()
    bus = _RecordingBus()
    loop = _FakeLoop(
        quiz_texts=[
            _CHOICE_QUIZ_JSON,
            json.dumps(
                {
                    "question": "地球绕太阳转。",
                    "correct_answer": "对",
                    "explanation": "公转。",
                    "options": {"A": "对", "B": "错"},
                }
            ),
            json.dumps(
                {
                    "question": "Define entropy in one sentence.",
                    "correct_answer": "A measure of disorder.",
                    "explanation": "Second law.",
                    "options": {"A": "x", "B": "y", "C": "z", "D": "w"},
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "deeptutor.agents.question.pipeline.build_openai_client", lambda config: object()
    )
    monkeypatch.setattr("deeptutor.agents.question.pipeline.run_agentic_loop", loop)

    async def quiz_one(template: QuizTemplate) -> QuizPair:
        return await pipeline._quiz_one(
            template=template,
            question_number=1,
            total_questions=3,
            exploration_trace="trace",
            plan=type("Plan", (), {"templates": [], "analysis": ""})(),
            previous_pairs=[],
            image_attachments=[],
            context=UnifiedContext(user_message="quiz me", session_id="s"),
            stream=bus,
            client=object(),
        )

    qa_choice = asyncio.run(quiz_one(choice_template))
    assert qa_choice.question_id == "q_1"
    assert qa_choice.question_type == "choice"
    assert qa_choice.correct_answer == "B"
    assert set(qa_choice.options.keys()) == {"A", "B", "C", "D"}
    assert qa_choice.topic == "Photosynthesis basics"
    assert qa_choice.difficulty == "easy"
    assert qa_choice.metadata == {}

    qa_concept = asyncio.run(quiz_one(concept_template))
    assert qa_concept.correct_answer == "true", "Chinese/alias truth values coerce to lowercase"
    assert qa_concept.options is None, "concept questions never carry options"

    qa_written = asyncio.run(quiz_one(written_template))
    assert qa_written.options is None, "non-choice options are stripped"
    assert qa_written.correct_answer == "A measure of disorder."
    assert qa_written.metadata == {}


# ---------------------------------------------------------------------------
# Empty knowledge points boundary
# ---------------------------------------------------------------------------


def test_empty_knowledge_points_handoff_contract(monkeypatch) -> None:
    """Empty exploration → planner still gets a coherent prompt.

    When Phase 1 finds nothing (empty FINISH, no messages), the plan and
    quiz prompts must carry the explicit empty-trace marker — never an
    empty string that leaves a dangling ``## Exploration trace`` section —
    and the run must still produce a valid quiz.
    """
    pipeline = _make_pipeline()

    marker = pipeline._render_exploration_trace([], finish_text="")
    assert marker.startswith("(no exploration trace"), (
        "the empty-trace marker must be the fallback, not ''"
    )

    bus = _RecordingBus()
    loop = _FakeLoop(explore_text="", quiz_texts=[_SHORT_ANSWER_QUIZ_JSON])
    step = _FakeLabeledStep(
        plan_text=json.dumps({"analysis": "", "templates": [{"topic": "Entropy"}]})
    )
    _wire(monkeypatch, pipeline, loop=loop, step=step)

    result = _run(pipeline, bus, num_questions=1)

    assert result["summary"]["success"] is True
    assert result["summary"]["completed"] == 1
    # The planner was told there is no trace, in so many words.
    plan_prompt = step.calls[0]["messages"][1]["content"]
    assert "(no exploration trace" in plan_prompt


def test_empty_plan_fails_with_visible_error(monkeypatch) -> None:
    """Zero usable templates is no quiz at all.

    The pipeline must fail loudly (RuntimeError), emit one visible error
    event + a ⚠ content line, emit no capability result, and never enter
    the quiz loop — the shape #1318 shipped silently.
    """
    pipeline = _make_pipeline()
    bus = _RecordingBus()
    loop = _FakeLoop(explore_text="explored", quiz_texts=[])
    step = _FakeLabeledStep(plan_text=json.dumps({"analysis": "nothing usable"}))
    emitted = _wire(monkeypatch, pipeline, loop=loop, step=step)

    with pytest.raises(RuntimeError):
        _run(pipeline, bus)

    assert loop.calls == ["exploring"], "the quiz loop must not run on an empty plan"
    assert emitted == []

    assert len(bus.error_events) == 1
    event = bus.error_events[0]
    assert event["message"].startswith("RuntimeError: ")
    assert event["source"] == SOURCE
    assert event["metadata"].get("trace_kind") == "error"
    assert any(
        c["text"].startswith("⚠") and "RuntimeError" in c["text"] for c in bus.contents
    ), "the failure must also land in the chat bubble with the warning prefix"


# ---------------------------------------------------------------------------
# Generation failure: repair once, then degrade honestly
# ---------------------------------------------------------------------------


def test_unparseable_generation_repairs_once_then_degrades(monkeypatch) -> None:
    """A quiz FINISH that parses to nothing gets exactly one repair round.

    When the repair also fails, the question degrades to a ``[Generation
    failed]`` placeholder with the issues recorded, the envelope counts it
    as failed, and the per-question card still emits — the learner sees a
    question, and the failure is traceable rather than silent (#1508).
    """
    pipeline = _make_pipeline()
    bus = _RecordingBus()
    loop = _FakeLoop(explore_text="preface", quiz_texts=["no json here at all"])
    step = _FakeLabeledStep(
        plan_text=json.dumps(
            {"analysis": "", "templates": [{"topic": "Chain rule", "question_type": "written"}]}
        ),
        repair_texts=["also not json"],
    )
    emitted = _wire(monkeypatch, pipeline, loop=loop, step=step)

    result = _run(pipeline, bus, num_questions=1)

    # Exactly one repair round under the FINISH-only protocol, fed the
    # detected issues and the invalid payload.
    repair_calls = [c for c in step.calls if tuple(c["allowed_labels"]) == ("FINISH",)]
    assert len(repair_calls) == 1
    repair_prompt = repair_calls[0]["messages"][1]["content"]
    assert "missing_question" in repair_prompt
    assert "Chain rule" in repair_prompt

    warnings = [
        p
        for p in bus.progress_events
        if p["metadata"].get("trace_kind") == "warning" and "repair" in p["message"].lower()
    ]
    assert len(warnings) == 2, "one warning for the attempt, one for the failed repair"

    qa = result["summary"]["results"][0]["qa_pair"]
    assert qa["question"] == "[Generation failed] Chain rule"
    assert qa["correct_answer"] == "N/A"
    assert qa["explanation"] == "N/A"
    assert qa["options"] is None
    assert result["summary"]["results"][0]["metadata"]["issues"], "issues must survive to metadata"

    summary = result["summary"]
    assert summary["completed"] == 0
    assert summary["failed"] == 1
    assert summary["success"] is False
    assert len(emitted) == 1, "the degraded quiz still ships as a result event"

    # The placeholder card still reached the frontend.
    cards = [c for c in bus.contents if c["metadata"].get("call_kind") == CALL_KIND_QUIZ_QUESTION]
    assert len(cards) == 1
    assert cards[0]["metadata"]["qa_pair"]["question"] == "[Generation failed] Chain rule"
