"""Branch coverage for the MinerU block policy beyond the contract happy path.

Complements ``test_lightrag_block_policy.py`` by pinning the decision and
ledger-writing edge branches: malformed block entries, page-index validation,
ledger metadata, and the attempt-ledger key/outcome contract.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.services.rag.pipelines.lightrag import block_policy


def _prepare(blocks: list[dict[str, object]]) -> block_policy.BlockPolicyDecision:
    return block_policy.prepare_content_list(
        blocks,
        engine="mineru",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )


def test_block_policy_decision_defaults_to_an_empty_unknown_summary() -> None:
    decision = block_policy.BlockPolicyDecision(content_list=[], ledger=None)

    assert decision.unknown_type_counts == ()
    assert decision.unknown_summary() == ""


def test_mineru_counts_non_dict_entries_as_invalid_and_skips_them() -> None:
    blocks: list[object] = [
        {"type": "text", "text": "body", "page_idx": 0},
        "raw parser line",
        None,
    ]

    decision = _prepare(blocks)

    assert [item["type"] for item in decision.content_list] == ["text"]
    assert decision.ledger is not None
    assert decision.ledger["counts"]["raw_total"] == 3
    assert decision.ledger["counts"]["raw_by_type"] == {
        "<invalid>": 2,
        "text": 1,
    }
    assert decision.ledger["counts"]["eligible_total"] == 1
    assert decision.ledger["counts"]["unknown_by_type"] == {"<invalid>": 2}
    assert decision.unknown_summary() == "<invalid>=2"


def test_mineru_multimodal_page_counts_require_a_nonnegative_integer_page_index() -> None:
    blocks = [
        {"type": "image", "img_path": "a.png", "page_idx": 2},
        {"type": "image", "img_path": "b.png", "page_idx": -1},
        {"type": "image", "img_path": "c.png"},
        {"type": "image", "img_path": "d.png", "page_idx": "3"},
    ]

    decision = _prepare(blocks)

    assert len(decision.content_list) == 4
    assert decision.ledger is not None
    counts = decision.ledger["counts"]
    assert counts["eligible_multimodal_total"] == 4
    assert counts["eligible_multimodal_by_type_and_page"] == {"image:2": 1}


def test_mineru_ledger_records_policy_parser_and_invariant_metadata() -> None:
    decision = _prepare([{"type": "text", "text": "body", "page_idx": 0}])

    assert decision.ledger is not None
    assert decision.ledger["schema_version"] == 1
    assert decision.ledger["policy"] == {
        "id": block_policy.POLICY_ID,
        "input_schema": "legacy-content-list",
        "filtered_layout_types": sorted(block_policy.FILTERED_LAYOUT_TYPES),
        "preserved_auxiliary_types": sorted(block_policy.PRESERVED_AUXILIARY_TYPES),
        "preserved_semantic_types": sorted(block_policy.PRESERVED_SEMANTIC_TYPES),
        "v2_auxiliary_equivalents": dict(
            sorted(block_policy.V2_AUXILIARY_EQUIVALENTS.items())
        ),
        "v2_auxiliary_normalized": True,
    }
    assert decision.ledger["parser"] == {
        "engine": "mineru",
        "source_hash": "source-hash",
        "parser_signature": "parser-signature",
    }
    assert decision.ledger["invariants"] == {
        "input_blocks_mutated": False,
        "eligible_order_preserved": True,
        "unknown_types_indexed": True,
        "raw_parser_artifacts_mutated": False,
    }


def test_mineru_result_blocks_do_not_alias_the_parser_input() -> None:
    blocks: list[dict[str, object]] = [
        {"type": "table", "cells": ["a"], "page_idx": 0},
        {"type": "footer", "text": "chrome", "page_idx": 0},
    ]
    snapshot = deepcopy(blocks)

    decision = _prepare(blocks)
    blocks[0]["cells"].append("mutated")  # type: ignore[union-attr]
    blocks.append({"type": "text", "text": "late", "page_idx": 0})

    assert decision.content_list == snapshot[:1]
    assert decision.content_list[0]["cells"] == ["a"]


def test_mineru_empty_document_yields_an_empty_index_and_zeroed_counts() -> None:
    decision = _prepare([])

    assert decision.content_list == []
    assert decision.ledger is not None
    assert decision.ledger["counts"] == {
        "raw_total": 0,
        "raw_by_type": {},
        "filtered_total": 0,
        "filtered_by_type": {},
        "eligible_total": 0,
        "eligible_by_type": {},
        "eligible_multimodal_total": 0,
        "eligible_multimodal_by_type_and_page": {},
        "unknown_total": 0,
        "unknown_by_type": {},
    }
    assert decision.unknown_summary() == ""


def test_mineru_indexes_malformed_type_values_as_invalid() -> None:
    blocks = [
        {"type": None, "page_idx": 0},
        {"type": 42, "page_idx": 0},
        {"type": "3chart", "page_idx": 0},
        {"type": "x" * 65, "page_idx": 0},
        {"type": "", "page_idx": 0},
    ]

    decision = _prepare(blocks)

    assert len(decision.content_list) == 5
    assert decision.ledger is not None
    assert decision.ledger["counts"]["unknown_by_type"] == {"<invalid>": 5}
    assert decision.unknown_summary() == "<invalid>=5"


def test_policy_type_vocabulary_constants_stay_consistent() -> None:
    assert block_policy.PRESERVED_TYPES == (
        block_policy.PRESERVED_AUXILIARY_TYPES | block_policy.PRESERVED_SEMANTIC_TYPES
    )
    assert block_policy.MULTIMODAL_TYPES == block_policy.PRESERVED_TYPES - {"text"}
    assert block_policy.FILTERED_LAYOUT_TYPES.isdisjoint(block_policy.PRESERVED_TYPES)
    assert set(block_policy.V2_AUXILIARY_EQUIVALENTS) == (
        block_policy.FILTERED_LAYOUT_TYPES | block_policy.PRESERVED_AUXILIARY_TYPES
    )
    inverse = {
        v2_name: legacy_name
        for legacy_name, v2_name in block_policy.V2_AUXILIARY_EQUIVALENTS.items()
        if v2_name != legacy_name
    }
    assert set(inverse.values()) <= (
        block_policy.FILTERED_LAYOUT_TYPES | block_policy.PRESERVED_AUXILIARY_TYPES
    )


def test_decision_ledger_includes_the_attempt_id_when_provided(tmp_path: Path) -> None:
    path = block_policy.write_decision_ledger(
        tmp_path,
        "document-id",
        {"schema_version": 1},
        attempt_id="attempt-123",
    )

    document_sha = hashlib.sha256(b"document-id").hexdigest()
    assert path == tmp_path / block_policy.LEDGER_DIRNAME / f"{document_sha[:16]}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["decision"] == {
        "ledger_role": "current-index",
        "policy_outcome": "accepted",
        "attempt_id": "attempt-123",
    }
    assert payload["document_id_sha256"] == document_sha


def test_attempt_ledger_rejects_unsupported_outcomes(tmp_path: Path) -> None:
    for outcome in ("failed", "rejected", ""):
        with pytest.raises(ValueError, match="Unsupported policy outcome"):
            block_policy.write_attempt_ledger(
                tmp_path,
                "document-id",
                {},
                outcome=outcome,
            )
    assert not (tmp_path / block_policy.ATTEMPT_LEDGER_DIRNAME).exists()


def test_attempt_ledger_filename_is_derived_from_the_documented_key_material(
    tmp_path: Path,
) -> None:
    decision = _prepare([{"type": "text", "text": "body", "page_idx": 0}])
    assert decision.ledger is not None

    path, attempt_id = block_policy.write_attempt_ledger(
        tmp_path,
        "document-id",
        decision.ledger,
        outcome="accepted",
    )

    document_sha = hashlib.sha256(b"document-id").hexdigest()
    key_material = "\0".join(
        (
            document_sha,
            block_policy.POLICY_ID,
            "parser-signature",
            "accepted",
            attempt_id,
        )
    )
    assert path.stem == hashlib.sha256(key_material.encode()).hexdigest()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["document_id_sha256"] == document_sha
    assert payload["decision"]["attempt_id"] == attempt_id
    assert payload["decision"]["ledger_role"] == "attempt"
    assert payload["decision"]["policy_outcome"] == "accepted"
    assert len(attempt_id) == 32
    int(attempt_id, 16)


def test_attempt_ledger_tolerates_a_ledger_without_policy_or_parser_sections(
    tmp_path: Path,
) -> None:
    path, attempt_id = block_policy.write_attempt_ledger(
        tmp_path,
        "document-id",
        {"schema_version": 1},
        outcome="unknown_types",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["decision"]["policy_outcome"] == "unknown_types"
    assert payload["decision"]["attempt_id"] == attempt_id
    assert payload["document_id_sha256"] == hashlib.sha256(b"document-id").hexdigest()
