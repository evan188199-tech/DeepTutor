"""Caption-grounded practice from knowledge-base source figures.

Minimal vertical slice for the #1611 learning workflow: turn a verified
source visual (see :mod:`deeptutor.services.rag.visual_assets`) into one
practice exercise, grade the learner's answer deterministically, and hand
the graded attempt to the canonical assessment writer so it lands in the
Question Notebook and — through a trusted objective linkage — as
``LearningEvidence`` on the mastery path.

The exercise is deliberately derived from the figure's stored caption and
surrounding source text, never from a model's unverified interpretation of
the pixels: an asset whose caption provides no usable grounding produces no
question at all. This is guided caption-grounded recognition, not
label-masking or region interaction; those remain future work, as does any
vision-model grading.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from deeptutor.learning.assessment import AssessmentRecord, is_correct_to_result
from deeptutor.learning.grading import grade_answer

_ASSET_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_LABEL_RE = re.compile(
    r"^\s*((?:figure|fig\.?|table|chart|diagram|plate|image|图|表|插图)\s*"
    r"\d+(?:\s*[.\-–—]\s*\d+)*)\s*[:：.\-–—]?\s*",
    re.IGNORECASE,
)
# Below this the caption is a fragment (a bare label, "chart", one word) and
# must not become an authoritative answer key.
MIN_SUBJECT_CHARS = 8
# ``grade_answer`` "short" semantics apply only up to this length; longer
# reference answers grade by significant-token containment instead.
SHORT_ANSWER_CHARS = 30
TOKEN_MATCH_RATIO = 0.6
_MIN_TOKEN_CHARS = 4
_STOPWORDS = frozenset(
    {
        "about",
        "above",
        "after",
        "again",
        "against",
        "along",
        "among",
        "around",
        "before",
        "behind",
        "below",
        "between",
        "during",
        "inside",
        "near",
        "onto",
        "other",
        "over",
        "shown",
        "shows",
        "their",
        "there",
        "these",
        "those",
        "through",
        "under",
        "until",
        "where",
        "which",
        "while",
        "with",
        "your",
    }
)


class VisualPracticeQuestion(BaseModel):
    """One practice exercise derived from a verified source figure.

    ``expected_answer`` and ``explanation`` are server-side grading state,
    like ``PendingQuestion``: project with
    :func:`public_visual_practice_question` before posing the question so
    the key never travels to the learner.
    """

    model_config = ConfigDict(extra="ignore")

    question_id: str
    kb_name: str
    asset_id: str
    source_path: str
    source_locator: str
    page_number: int | None = None
    caption: str
    task: str = "figure_subject"
    prompt: str
    question_type: str
    expected_answer: str
    explanation: str


def _split_label(caption: str) -> tuple[str, str]:
    """Split ``"Figure 3.1: Fluid mosaic model"`` into label and subject."""
    match = _LABEL_RE.match(caption)
    if match is None:
        return "", caption.strip()
    label = " ".join(match.group(1).split())
    subject = caption[match.end() :].strip()
    return label, subject


def _significant_tokens(text: str) -> list[str]:
    """Latin words (and digits) as tokens, CJK text as per-character tokens."""
    tokens: list[str] = []
    for word in re.findall(r"[0-9a-z]+", text.lower()):
        if len(word) >= _MIN_TOKEN_CHARS or word.isdigit():
            tokens.append(word)
    tokens.extend(re.findall(r"[\u4e00-\u9fff]", text))
    return tokens


def _token_grade(user_answer: str, expected_answer: str) -> bool:
    want = [token for token in _significant_tokens(expected_answer) if token not in _STOPWORDS]
    if not want:
        return grade_answer(user_answer, expected_answer, "short")
    got = set(_significant_tokens(user_answer))
    matched = sum(1 for token in want if token in got)
    return matched / len(want) >= TOKEN_MATCH_RATIO


def build_visual_practice_question(
    kb_name: str, record: dict[str, Any]
) -> VisualPracticeQuestion | None:
    """Build one caption-grounded exercise from a visual asset record.

    Returns ``None`` when the asset has no caption grounding good enough to
    serve as an answer key — an ambiguous asset becomes no exercise, not a
    fabricated one.
    """
    asset_id = str(record.get("asset_id") or "")
    if not _ASSET_ID_RE.fullmatch(asset_id):
        return None
    caption = str(record.get("caption") or "").strip()
    if not caption:
        return None
    label, subject = _split_label(caption)
    if len(subject) < MIN_SUBJECT_CHARS:
        return None

    source_path = str(record.get("source_path") or "").strip()
    source_locator = str(record.get("source_locator") or "").strip()
    page_number = record.get("page_number")
    page_number = int(page_number) if isinstance(page_number, int) else None
    context = str(record.get("context") or "").strip()

    location = f"page {page_number}" if page_number else f"locator {source_locator}"
    named = f"{label} in “{source_path}”" if label else f"A figure in “{source_path}”"
    prompt = (
        f"{named} ({location}) depicts a concept covered by the surrounding "
        "passage of this source. Identify what the figure shows, using the "
        "source's own terminology."
    )
    evidence_parts = [f"Source caption: {caption}"]
    if context:
        evidence_parts.append(f"Surrounding source text: {context}")
    evidence_parts.append(
        f"Provenance: asset {asset_id[:12]}… of document “{source_path}”, {location}."
    )
    explanation = " — ".join(evidence_parts)

    return VisualPracticeQuestion(
        question_id=f"visual:{asset_id[:24]}",
        kb_name=kb_name,
        asset_id=asset_id,
        source_path=source_path,
        source_locator=source_locator,
        page_number=page_number,
        caption=caption,
        prompt=prompt,
        question_type="short" if len(subject) <= SHORT_ANSWER_CHARS else "open",
        expected_answer=subject,
        explanation=explanation,
    )


def practice_question_from_store(
    store: Any, kb_name: str, asset_id: str
) -> VisualPracticeQuestion | None:
    """Resolve a question from a ``VisualAssetStore`` manifest record."""
    if not _ASSET_ID_RE.fullmatch(asset_id):
        return None
    record = store.records().get(asset_id)
    if not isinstance(record, dict):
        return None
    return build_visual_practice_question(kb_name, record)


def public_visual_practice_question(question: VisualPracticeQuestion) -> dict[str, Any]:
    """Project the question for the learner without the grading key."""
    return {
        "question_id": question.question_id,
        "kb_name": question.kb_name,
        "asset_id": question.asset_id,
        "task": question.task,
        "prompt": question.prompt,
        "question_type": question.question_type,
    }


def grade_visual_practice(question: VisualPracticeQuestion, user_answer: str) -> bool:
    """Deterministically grade one answer against the caption-derived key."""
    expected = question.expected_answer.strip()
    user = str(user_answer or "").strip()
    if not expected or not user:
        return False
    if question.question_type == "short" and len(expected) <= SHORT_ANSWER_CHARS:
        return grade_answer(user, expected, "short")
    return _token_grade(user, expected)


def visual_practice_record(
    question: VisualPracticeQuestion,
    *,
    user_answer: str,
    is_correct: bool,
    mastery_path_id: str = "",
    knowledge_point_id: str = "",
    attempt_count: int = 1,
    attempt_id: str = "",
) -> AssessmentRecord:
    """Build the canonical assessment record for one graded submission.

    Linkage is only honoured when both ids are present;
    :func:`deeptutor.learning.assessment.record_assessment` independently
    verifies the objective exists on the saved path before any evidence is
    applied, and drops untrusted linkage without touching the attempt log.
    """
    return AssessmentRecord(
        origin_type="document_analysis",
        origin_ref=f"visual:{question.kb_name}:{question.asset_id[:12]}",
        turn_id=question.asset_id,
        question_id=question.question_id,
        question=question.prompt,
        question_type=question.question_type,
        correct_answer=question.expected_answer,
        explanation=question.explanation,
        user_answer=user_answer,
        is_correct=is_correct,
        result=is_correct_to_result(is_correct),
        source="source_visual",
        assessment_type="quiz",
        material_id=question.source_path,
        material_title=Path(question.source_path).name if question.source_path else "",
        section_id=question.asset_id,
        section_title=question.caption[:80],
        mastery_path_id=mastery_path_id,
        knowledge_point_id=knowledge_point_id,
        attempt_count=attempt_count,
        attempt_id=attempt_id,
    )


__all__ = [
    "VisualPracticeQuestion",
    "build_visual_practice_question",
    "grade_visual_practice",
    "practice_question_from_store",
    "public_visual_practice_question",
    "visual_practice_record",
]
