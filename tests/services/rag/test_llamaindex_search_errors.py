"""Tests for LlamaIndex RAG search error normalization."""

from __future__ import annotations

import pytest

from deeptutor.services.rag.pipelines.llamaindex.errors import search_error_result

INVALID_PROVIDER = RuntimeError("embedding provider returned invalid query vector dims")
NULL_VECTOR = RuntimeError("unsupported operand type(s) for *: 'NoneType' and 'float'")
INHOMOGENEOUS = ValueError("inhomogeneous shape: (3,) (4,)")
NOT_ALIGNED = ValueError("shapes (3,) and (4,) not aligned")
INVALID_PERSISTED = RuntimeError("rag index contains invalid embedding vectors")
UNRELATED = RuntimeError("connection refused")

PROVIDER_ANSWER_PREFIX = "RAG search failed because the embedding provider"
INDEX_ANSWER_PREFIX = "RAG search failed because this knowledge base index"


@pytest.mark.parametrize(
    ("exc", "expected_error_type", "expected_answer_prefix"),
    [
        (INVALID_PROVIDER, "invalid_embedding_provider_response", PROVIDER_ANSWER_PREFIX),
        (NULL_VECTOR, "invalid_embedding_index", INDEX_ANSWER_PREFIX),
        (INHOMOGENEOUS, "invalid_embedding_index", INDEX_ANSWER_PREFIX),
        (NOT_ALIGNED, "invalid_embedding_index", INDEX_ANSWER_PREFIX),
        (INVALID_PERSISTED, "invalid_embedding_index", INDEX_ANSWER_PREFIX),
        (UNRELATED, None, "Search failed: connection refused"),
    ],
)
def test_error_classification_table(
    exc: Exception,
    expected_error_type: str | None,
    expected_answer_prefix: str,
) -> None:
    result = search_error_result("kb query", exc)

    assert result["query"] == "kb query"
    assert result["provider"] == "llamaindex"
    assert result["content"] == ""
    assert result["error"] == str(exc)
    assert result["answer"].startswith(expected_answer_prefix)

    if expected_error_type is None:
        assert "error_type" not in result
        assert "needs_reindex" not in result
        assert "log_message" not in result
    else:
        assert result["error_type"] == expected_error_type
        assert "log_message" in result


@pytest.mark.parametrize(
    ("exc", "needs_reindex"),
    [
        (INVALID_PROVIDER, False),
        (NULL_VECTOR, True),
        (INHOMOGENEOUS, True),
        (NOT_ALIGNED, True),
        (INVALID_PERSISTED, True),
        (UNRELATED, False),
    ],
)
def test_needs_reindex_flag_is_set_only_for_recoverable_indexes(
    exc: Exception,
    needs_reindex: bool,
) -> None:
    result = search_error_result("q", exc)
    assert bool(result.get("needs_reindex")) is needs_reindex


def test_invalid_provider_answer_embeds_the_original_error() -> None:
    result = search_error_result("q", INVALID_PROVIDER)
    assert result["error"] in result["answer"]


def test_reindex_answer_directs_to_a_full_reindex() -> None:
    result = search_error_result("q", INHOMOGENEOUS)
    assert "Re-index" in result["answer"]
    assert result["needs_reindex"] is True


@pytest.mark.parametrize(
    "message",
    ["EMBEDDING PROVIDER RETURNED INVALID VECTOR", "Inhomogeneous Shape: (3,) (4,)"],
)
def test_classification_is_case_insensitive(message: str) -> None:
    result = search_error_result("q", RuntimeError(message))
    assert result["error_type"] in {
        "invalid_embedding_provider_response",
        "invalid_embedding_index",
    }


def test_provider_message_wins_over_later_index_markers() -> None:
    combined = RuntimeError(
        "embedding provider returned invalid response while reading "
        "rag index contains invalid embedding vectors"
    )
    result = search_error_result("q", combined)
    assert result["error_type"] == "invalid_embedding_provider_response"
    assert "needs_reindex" not in result
