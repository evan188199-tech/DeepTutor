"""Unit-level failure paths and ref mapping for objective relations.

Complements test_objective_relations.py (service-level flows) with direct
coverage of source_ref_map, normalize_refs, cycle reporting, and
resolve_relation_refs error paths.
"""

from __future__ import annotations

import dataclasses

import pytest

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.objective_relations import (
    ObjectiveRelationError,
    RelationRefs,
    normalize_refs,
    resolve_relation_refs,
    source_ref_map,
    validate_objective_relations,
)


def _kp(kp_id: str, *, prerequisites: list[str] | None = None) -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id,
        name=f"Objective {kp_id}",
        type=KnowledgeType.CONCEPT,
        module_id="m0",
        prerequisite_ids=prerequisites or [],
    )


def _module(kp_id: str, *points: KnowledgePoint) -> LearningModule:
    return LearningModule(
        id=kp_id, name=f"Module {kp_id}", order=0, knowledge_points=list(points)
    )


def _source(source_id: str = "source_notes", kind: TopicSourceKind = TopicSourceKind.NOTEBOOK):
    return TopicSource(id=source_id, kind=kind, label=source_id)


def test_objective_relation_error_is_a_value_error():
    assert issubclass(ObjectiveRelationError, ValueError)


def test_relation_refs_defaults_are_empty_and_frozen():
    refs = RelationRefs()

    assert refs.client_ref == ""
    assert refs.prerequisite_refs == []
    assert refs.topic_source_refs == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        refs.client_ref = "x"


def test_normalize_refs_returns_empty_list_for_none_and_drops_noise():
    assert normalize_refs(None, label="prerequisite") == []

    cleaned = normalize_refs(["", "   ", None, " a1 ", "a1", 7, 0], label="prerequisite")

    assert cleaned == ["a1", "7"]


def test_source_ref_map_maps_durable_ids_skips_goal_sources_and_blank_aliases():
    sources = [
        _source("source_notes"),
        _source("source_book", TopicSourceKind.BOOK),
        _source("goal", TopicSourceKind.GOAL),
    ]

    resolved = source_ref_map(sources, aliases={"": "source_notes", "   ": "source_book"})

    assert resolved == {"source_notes": "source_notes", "source_book": "source_book"}


def test_source_ref_map_resolves_aliases_to_durable_ids():
    resolved = source_ref_map([_source("source_notes")], aliases={"notes": "source_notes"})

    assert resolved == {"source_notes": "source_notes", "notes": "source_notes"}


def test_source_ref_map_rejects_duplicate_durable_source_ids():
    with pytest.raises(ObjectiveRelationError, match="Duplicate topic source id"):
        source_ref_map([_source("source_notes"), _source("source_notes")])


def test_source_ref_map_rejects_alias_to_unknown_source():
    with pytest.raises(ObjectiveRelationError, match="names unknown source 'missing'"):
        source_ref_map([_source("source_notes")], aliases={"notes": "missing"})


def test_source_ref_map_rejects_alias_shadowing_a_different_durable_id():
    with pytest.raises(ObjectiveRelationError, match="'source_notes' is ambiguous"):
        source_ref_map(
            [_source("source_notes"), _source("source_book")],
            aliases={"source_notes": "source_book"},
        )


def test_validation_rejects_duplicate_knowledge_point_ids_across_modules():
    first = _module("m0", _kp("kp1"))
    second = _module("m1", _kp("kp1"))

    with pytest.raises(ObjectiveRelationError, match="must be unique"):
        validate_objective_relations([first, second], [])


def test_validation_reports_the_full_prerequisite_cycle_path():
    first = _kp("kp1", prerequisites=["kp3"])
    second = _kp("kp2", prerequisites=["kp1"])
    third = _kp("kp3", prerequisites=["kp2"])

    with pytest.raises(
        ObjectiveRelationError,         match=r"Prerequisite cycle: kp1 -> kp3 -> kp2 -> kp1"
    ):
        validate_objective_relations([_module("m0", first, second, third)], [])


def test_resolve_dedupes_distinct_refs_resolving_to_the_same_durable_ids():
    referenced = _kp("draft_a")
    untouched = _kp("draft_b")
    untouched.prerequisite_ids = ["keep"]
    untouched.topic_source_ids = ["keep_source"]
    refs = {
        "draft_a": RelationRefs(
            prerequisite_refs=["alias_one", "alias_two"],
            topic_source_refs=["alias_a", "alias_b"],
        )
    }

    resolve_relation_refs(
        [_module("m0", referenced, untouched)],
        refs,
        prerequisite_aliases={
            "alias_one": "final",
            "alias_two": "final",
            "draft_b": "other",
        },
        source_aliases={"alias_a": "source_notes", "alias_b": "source_notes"},
        sources=[_source()],
    )

    assert referenced.prerequisite_ids == ["final"]
    assert referenced.topic_source_ids == ["source_notes"]
    assert untouched.prerequisite_ids == ["keep"]
    assert untouched.topic_source_ids == ["keep_source"]


def test_resolve_rejects_unknown_topic_source_ref():
    point = _kp("draft_a")
    refs = {"draft_a": RelationRefs(topic_source_refs=["ghost"])}

    with pytest.raises(ObjectiveRelationError, match="unknown topic source ref 'ghost'"):
        resolve_relation_refs(
            [_module("m0", point)],
            refs,
            prerequisite_aliases={},
            source_aliases={},
            sources=[_source()],
        )
