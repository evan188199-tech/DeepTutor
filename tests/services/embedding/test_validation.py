"""Tests for embedding vector validation helpers (validate_embedding_batch)."""

from __future__ import annotations

import math

import pytest

from deeptutor.services.embedding.validation import validate_embedding_batch

# ---------------------------------------------------------------------------
# Happy path: dense numeric vectors pass through, normalized to floats
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_vectors_unchanged_for_floats(self) -> None:
        batch = [[0.1, 0.2], [0.3, 0.4]]
        result = validate_embedding_batch(batch, expected_count=2)
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_int_coordinates_are_normalized_to_float(self) -> None:
        batch = [[1, 2, 3]]
        result = validate_embedding_batch(batch, expected_count=1)
        assert result == [[1.0, 2.0, 3.0]]
        assert all(type(value) is float for value in result[0])

    def test_tuple_sequences_are_accepted(self) -> None:
        batch = [(0.5, 0.5), [0.25, 0.75]]
        result = validate_embedding_batch(batch, expected_count=2)
        assert result == [[0.5, 0.5], [0.25, 0.75]]
        assert all(type(value) is float for vector in result for value in vector)

    def test_empty_batch_with_expected_count_zero(self) -> None:
        assert validate_embedding_batch([], expected_count=0) == []

    def test_returned_copy_is_not_the_input_object(self) -> None:
        batch = [[0.1, 0.2]]
        result = validate_embedding_batch(batch, expected_count=1)
        assert result is not batch
        assert result[0] is not batch[0]


# ---------------------------------------------------------------------------
# Malformed payload: not a sequence of vectors at all
# ---------------------------------------------------------------------------


class TestMalformedPayload:
    @pytest.mark.parametrize("payload", [None, "text", b"bytes"])
    def test_none_str_bytes_payload_rejected(self, payload: object) -> None:
        with pytest.raises(ValueError, match="invalid embeddings payload"):
            validate_embedding_batch(payload, expected_count=1)

    @pytest.mark.parametrize("payload", [42, 1.5, {"a": [0.1]}, {0.1, 0.2}])
    def test_non_sequence_payload_rejected(self, payload: object) -> None:
        with pytest.raises(ValueError, match="invalid embeddings payload"):
            validate_embedding_batch(payload, expected_count=1)

    def test_payload_error_mentions_expected_count_and_type(self) -> None:
        with pytest.raises(ValueError, match="expected a list of 3 vector.*got str"):
            validate_embedding_batch("oops", expected_count=3)

    def test_payload_error_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            validate_embedding_batch(None, expected_count=2)


# ---------------------------------------------------------------------------
# Count contract: number of returned vectors must match the request
# ---------------------------------------------------------------------------


class TestCountContract:
    def test_too_few_vectors_rejected(self) -> None:
        with pytest.raises(ValueError, match="unexpected number of vectors"):
            validate_embedding_batch([[0.1, 0.2]], expected_count=2)

    def test_too_many_vectors_rejected(self) -> None:
        batch = [[0.1, 0.2]] * 3
        with pytest.raises(ValueError, match="expected 2, got 3"):
            validate_embedding_batch(batch, expected_count=2)

    def test_count_error_mentions_dropped_inputs(self) -> None:
        with pytest.raises(ValueError, match="dropped one or more inputs"):
            validate_embedding_batch([[0.1, 0.2]], expected_count=5)


# ---------------------------------------------------------------------------
# Vector-level rejection: null / non-sequence / empty
# ---------------------------------------------------------------------------


class TestInvalidVectorShape:
    def test_null_vector_rejected(self) -> None:
        batch = [[0.1, 0.2], None]
        with pytest.raises(ValueError, match="vector is null"):
            validate_embedding_batch(batch, expected_count=2)

    @pytest.mark.parametrize("vector", ["0.1,0.2", b"\x00\x01", 7, 3.14, {"dim": 1}])
    def test_non_sequence_vector_rejected(self, vector: object) -> None:
        batch = [vector]
        with pytest.raises(ValueError, match="expected a numeric sequence, got "):
            validate_embedding_batch(batch, expected_count=1)

    def test_empty_vector_rejected(self) -> None:
        with pytest.raises(ValueError, match="vector is empty"):
            validate_embedding_batch([[]], expected_count=1)

    def test_vector_error_names_the_item_index(self) -> None:
        with pytest.raises(ValueError, match="at item 2"):
            validate_embedding_batch([[0.1], [0.2], None], expected_count=3)


# ---------------------------------------------------------------------------
# Coordinate-level rejection: null / non-numeric / non-finite
# ---------------------------------------------------------------------------


class TestInvalidCoordinates:
    def test_null_coordinate_rejected_with_dimension_index(self) -> None:
        with pytest.raises(ValueError, match="dimension 1 is null"):
            validate_embedding_batch([[0.1, None, 0.3]], expected_count=1)

    @pytest.mark.parametrize("value", ["0.5", True, False, {"k": 1}, [0.1], (0.1,)])
    def test_non_numeric_coordinate_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match="not a number"):
            validate_embedding_batch([[1.0, value]], expected_count=1)

    def test_nan_coordinate_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding_batch([[0.1, float("nan"), 0.3]], expected_count=1)

    def test_positive_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding_batch([[float("inf"), 0.2]], expected_count=1)

    def test_negative_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding_batch([[float("-inf"), 0.2]], expected_count=1)

    def test_coordinate_error_names_the_item_index(self) -> None:
        with pytest.raises(ValueError, match="at item 1"):
            validate_embedding_batch(
                [[0.1, 0.2], [0.3, math.nan]],
                expected_count=2,
            )

    def test_bool_rejected_even_though_int_subclass(self) -> None:
        with pytest.raises(ValueError, match="dimension 0 is bool, not a number"):
            validate_embedding_batch([[True, 0.2]], expected_count=1)


# ---------------------------------------------------------------------------
# Dimension consistency: all vectors in a batch must share one dimension
# ---------------------------------------------------------------------------


class TestDimensionConsistency:
    def test_inconsistent_dimensions_rejected(self) -> None:
        batch = [[0.1, 0.2], [0.3, 0.4, 0.5]]
        with pytest.raises(ValueError, match="inconsistent vector dimensions"):
            validate_embedding_batch(batch, expected_count=2)

    def test_dimension_error_lists_sorted_unique_dims(self) -> None:
        batch = [[0.3, 0.4, 0.5], [0.1, 0.2], [0.6] * 3]
        with pytest.raises(ValueError, match=r"dimensions=\[2, 3\]"):
            validate_embedding_batch(batch, expected_count=3)

    def test_matching_dimensions_pass(self) -> None:
        batch = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        result = validate_embedding_batch(batch, expected_count=3)
        assert result == batch


# ---------------------------------------------------------------------------
# Error context: binding/model/batch and start_index surface in messages
# ---------------------------------------------------------------------------


class TestErrorContext:
    def test_binding_and_model_in_message(self) -> None:
        with pytest.raises(
            ValueError, match=r"binding=rag, model=text-embedding-x"
        ):
            validate_embedding_batch(
                None,
                expected_count=1,
                binding="rag",
                model="text-embedding-x",
            )

    def test_batch_position_in_message(self) -> None:
        with pytest.raises(ValueError, match=r"batch=2/5"):
            validate_embedding_batch(
                None,
                expected_count=1,
                binding="rag",
                model="m",
                batch_index=2,
                total_batches=5,
            )

    def test_no_context_when_no_metadata_given(self) -> None:
        with pytest.raises(ValueError, match=r"payload: expected"):
            validate_embedding_batch(None, expected_count=1)

    def test_start_index_offsets_reported_item(self) -> None:
        with pytest.raises(ValueError, match="at item 7"):
            validate_embedding_batch(
                [[0.1, 0.2], [0.3, math.nan]],
                expected_count=2,
                start_index=6,
            )

    def test_start_index_zero_reports_local_index(self) -> None:
        with pytest.raises(ValueError, match="at item 0"):
            validate_embedding_batch([[math.nan, 0.2]], expected_count=1)

    def test_item_index_error_names_batch_position_too(self) -> None:
        with pytest.raises(ValueError, match=r"item 1 \(binding=b, model=m, batch=0/1\)"):
            validate_embedding_batch(
                [[0.1], None],
                expected_count=2,
                binding="b",
                model="m",
                batch_index=0,
                total_batches=1,
            )


# ---------------------------------------------------------------------------
# Error-message guidance: reruns should be actionable
# ---------------------------------------------------------------------------


class TestErrorMessageGuidance:
    def test_invalid_vector_message_mentions_reindex(self) -> None:
        with pytest.raises(ValueError, match="re-index the knowledge base"):
            validate_embedding_batch([[math.nan]], expected_count=1)

    def test_payload_message_mentions_dense_numeric_embeddings(self) -> None:
        with pytest.raises(ValueError, match="invalid embeddings payload"):
            validate_embedding_batch("nope", expected_count=1)
