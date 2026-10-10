"""Assessment value vocabularies are a three-way contract; hold them pinned.

``deeptutor.core.assessment`` declares the shared assessment vocabulary once as
``Literal`` types and re-exports each as a frozenset for runtime membership
checks. Three independent consumers rely on those exports agreeing with the
type-level definitions: producers in ``deeptutor.learning.assessment`` decide
which values to write, ``deeptutor.services.session.sqlite_store`` validates
against them at persistence time, and the HTTP layer
(``deeptutor.api.routers.question_notebook``) accepts them through
``Literal``-typed request fields.

The frozensets are derived via ``get_args``, so they stay in sync only as long
as nobody replaces the derivation with a hardcoded copy, drops a member, or
renames a value on one side. Any of those drifts is silent: producers write
values persistence rejects, and the API splits into a second vocabulary. These
tests pin both halves of the contract — the derivation (each export equals the
``get_args`` of its paired Literal) and the shared vocabulary itself (each
export equals the exact value set all three consumers currently rely on).
"""

from __future__ import annotations

from typing import get_args

import pytest

from deeptutor.core import assessment
from deeptutor.core.assessment import (
    ASSESSMENT_RESULTS,
    ASSESSMENT_SOURCES,
    ASSESSMENT_TYPES,
    QUESTION_ORIGIN_TYPES,
    AssessmentResult,
    AssessmentSource,
    AssessmentType,
    QuestionOriginType,
)

# (export name, exported frozenset, paired Literal type, pinned shared vocabulary)
_CONTRACTS: dict[str, tuple[frozenset[str], object]] = {
    "ASSESSMENT_SOURCES": (ASSESSMENT_SOURCES, AssessmentSource),
    "QUESTION_ORIGIN_TYPES": (QUESTION_ORIGIN_TYPES, QuestionOriginType),
    "ASSESSMENT_TYPES": (ASSESSMENT_TYPES, AssessmentType),
    "ASSESSMENT_RESULTS": (ASSESSMENT_RESULTS, AssessmentResult),
}

_PINNED_VOCABULARIES: dict[str, frozenset[str]] = {
    "ASSESSMENT_SOURCES": frozenset(
        {
            "deep_question",
            "mastery_path",
            "immersive_reading",
            "book",
            "partner_chat",
            "import",
        }
    ),
    "QUESTION_ORIGIN_TYPES": frozenset(
        {"conversation", "external_import", "document_analysis"}
    ),
    "ASSESSMENT_TYPES": frozenset({"quiz", "focus_check", "qualitative", "review"}),
    "ASSESSMENT_RESULTS": frozenset(
        {"correct", "incorrect", "partial", "ungraded", "voided"}
    ),
}


@pytest.mark.parametrize("export_name", sorted(_CONTRACTS))
def test_export_derives_from_its_paired_literal(export_name: str) -> None:
    """Each frozenset export equals ``get_args`` of exactly its paired Literal.

    A crossed pairing (e.g. ``ASSESSMENT_TYPES`` built from
    ``AssessmentResult``) or a stale hardcoded copy passes unrelated tests and
    only fails at the persistence or API boundary.
    """
    exported, literal = _CONTRACTS[export_name]
    assert isinstance(exported, frozenset)
    assert exported == frozenset(get_args(literal))


@pytest.mark.parametrize("export_name", sorted(_PINNED_VOCABULARIES))
def test_export_matches_the_shared_vocabulary(export_name: str) -> None:
    """Each export stays equal to the value set all three consumers rely on."""
    exported = getattr(assessment, export_name)
    assert exported == _PINNED_VOCABULARIES[export_name]


@pytest.mark.parametrize("export_name", sorted(_CONTRACTS))
def test_export_members_are_non_empty_strings(export_name: str) -> None:
    """Members are non-empty strings; an empty export means a broken derivation."""
    exported = getattr(assessment, export_name)
    assert isinstance(exported, frozenset)
    assert exported
    assert all(isinstance(value, str) and value for value in exported)
