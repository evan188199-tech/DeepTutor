"""Public, stable views of pending mastery questions.

The persisted :class:`~deeptutor.learning.models.PendingQuestion` contains the
server-only expected answer. This module projects it into the smaller contract
that is safe to give to the tutor model and interactive clients. It also
re-exports the pure multiple-choice translations (they live in the leaf
:mod:`~deeptutor.learning.options_text` so ``models`` and ``pending`` share
them without importing each other), keeping the established
``deeptutor.learning.pending`` import path stable for every caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deeptutor.learning.options_text import (
    OPTION_PREFIX_RE,
    canonical_labels,
    has_option_bodies,
    is_readable_choice_answer,
    option_label_intent,
    parse_options,
    positional_label,
    resolve_answer,
    resolve_choice_submission,
)
from deeptutor.utils.text_display import decode_escaped_unicode_for_display

if TYPE_CHECKING:
    from deeptutor.learning.models import PendingQuestion


@dataclass(frozen=True, slots=True)
class PublicPendingOption:
    """One learner-visible option; ``id`` and ``label`` are intentionally stable."""

    id: str
    label: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "body": self.body}


@dataclass(frozen=True, slots=True)
class PublicPendingQuestion:
    """Learner-visible pending state, deliberately excluding the answer key."""

    question_id: str
    prompt: str
    question_type: str
    options: tuple[PublicPendingOption, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "prompt": self.prompt,
            "question_type": self.question_type,
            "options": [option.to_dict() for option in self.options],
        }


def public_pending_question(pending: PendingQuestion) -> PublicPendingQuestion:
    """Project persisted pending state without exposing ``expected_answer``."""
    options = (
        tuple(
            PublicPendingOption(id=option.label, label=option.label, body=option.body)
            for option in pending.options
        )
        if pending.question_type == "choice"
        else ()
    )
    return PublicPendingQuestion(
        question_id=pending.question_id,
        prompt=decode_escaped_unicode_for_display(pending.prompt),
        question_type=pending.question_type,
        options=tuple(
            PublicPendingOption(
                id=option.id,
                label=decode_escaped_unicode_for_display(option.label),
                body=decode_escaped_unicode_for_display(option.body),
            )
            for option in options
        ),
    )


__all__ = [
    "OPTION_PREFIX_RE",
    "canonical_labels",
    "PublicPendingOption",
    "PublicPendingQuestion",
    "has_option_bodies",
    "is_readable_choice_answer",
    "option_label_intent",
    "parse_options",
    "positional_label",
    "public_pending_question",
    "resolve_answer",
    "resolve_choice_submission",
]
