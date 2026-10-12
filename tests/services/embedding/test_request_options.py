"""Tests for the tri-state embedding ``dimensions`` request policy."""

from __future__ import annotations

import pytest

from deeptutor.services.embedding.request_options import should_send_embedding_dimensions


class TestExplicitChoices:
    def test_explicit_true_sends_when_dimension_set(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="custom", model="bge-m3", dimension=1024, send_dimensions=True
            )
            is True
        )

    def test_explicit_false_wins_over_supported_model(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model="text-embedding-3-small",
                dimension=1536,
                send_dimensions=False,
            )
            is False
        )

    @pytest.mark.parametrize("dimension", [None, 0])
    def test_missing_dimension_never_sends(self, dimension: int | None) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model="jina-embeddings-v3",
                dimension=dimension,
                send_dimensions=True,
            )
            is False
        )


class TestJinaAutomaticMode:
    @pytest.mark.parametrize("dimension", [32, 512, 768, 1024])
    def test_known_matryoshka_dimension_sends(self, dimension: int) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model="jina-embeddings-v3",
                dimension=dimension,
                send_dimensions=None,
            )
            is True
        )

    def test_off_grid_dimension_is_skipped(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model="jina-embeddings-v3",
                dimension=100,
                send_dimensions=None,
            )
            is False
        )

    def test_unknown_jina_model_is_skipped(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model="jina-embeddings-v2-base-zh",
                dimension=768,
                send_dimensions=None,
            )
            is False
        )

    def test_v4_model_shares_dimension_grid(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model="jina-embeddings-v4",
                dimension=256,
                send_dimensions=None,
            )
            is True
        )


class TestOpenAICompatibleAutomaticMode:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("text-embedding-3-small", True),
            ("text-embedding-3-large", True),
            ("Text-Embedding-3-Large", True),
            ("qwen3-embedding-0.6b", True),
            ("qwen3-vl-embedding", True),
            ("text-embedding-ada-002", False),
            ("bge-m3", False),
            ("", False),
        ],
    )
    def test_model_family_rules(self, model: str, expected: bool) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="custom", model=model, dimension=1024, send_dimensions=None
            )
            is expected
        )

    def test_missing_model_is_skipped(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai", model=None, dimension=1536, send_dimensions=None
            )
            is False
        )

    def test_binding_aliases_fall_through_to_model_rules(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai_compatible",
                model="text-embedding-3-small",
                dimension=1536,
                send_dimensions=None,
            )
            is True
        )
        assert (
            should_send_embedding_dimensions(
                binding="google",
                model="text-embedding-ada-002",
                dimension=768,
                send_dimensions=None,
            )
            is False
        )

    def test_missing_binding_still_applies_model_rules(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding=None,
                model="qwen3-embedding-4b",
                dimension=2560,
                send_dimensions=None,
            )
            is True
        )
