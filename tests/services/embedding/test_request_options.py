"""Unit tests for the shared embedding request-option decision.

Covers ``should_send_embedding_dimensions`` precedence, tri-state handling,
auto-mode model-family heuristics, Jina variable-dimension gating, and
degradation on invalid or missing values.
"""

from __future__ import annotations

import pytest

from deeptutor.services.embedding.request_options import (
    should_send_embedding_dimensions,
)


class TestExplicitOverridePrecedence:
    """Explicit user choices must win over the automatic heuristics."""

    @pytest.mark.parametrize(
        ("binding", "model"),
        [
            ("openai", "some-unknown-model"),
            ("custom", "bge-m3"),
            ("jina", "jina-embeddings-v2"),
        ],
    )
    def test_explicit_true_forces_sending(self, binding: str, model: str) -> None:
        assert (
            should_send_embedding_dimensions(
                binding=binding,
                model=model,
                dimension=512,
                send_dimensions=True,
            )
            is True
        )

    @pytest.mark.parametrize(
        ("binding", "model"),
        [
            ("openai", "text-embedding-3-large"),
            ("custom", "qwen3-embedding-8b"),
            ("jina", "jina-embeddings-v3"),
        ],
    )
    def test_explicit_false_suppresses_sending(self, binding: str, model: str) -> None:
        assert (
            should_send_embedding_dimensions(
                binding=binding,
                model=model,
                dimension=1024,
                send_dimensions=False,
            )
            is False
        )

    @pytest.mark.parametrize("dimension", [None, 0])
    def test_missing_dimension_gates_even_explicit_true(self, dimension: int | None) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model="text-embedding-3-large",
                dimension=dimension,
                send_dimensions=True,
            )
            is False
        )


class TestAutoModeModelFamilies:
    """With no explicit choice, only known families auto-send."""

    @pytest.mark.parametrize(
        ("model", "dimension"),
        [
            ("text-embedding-3-small", 512),
            ("text-embedding-3-large", 256),
            ("Text-Embedding-3-Large", 3072),
            ("Qwen/Qwen3-Embedding-8B", 4096),
            ("qwen3-vl-embedding-2b", 1024),
            ("SomePrefix-qwen3-embedding-0.6b", 1024),
        ],
    )
    def test_auto_sends_for_supported_families(self, model: str, dimension: int) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model=model,
                dimension=dimension,
                send_dimensions=None,
            )
            is True
        )

    @pytest.mark.parametrize(
        ("model", "dimension"),
        [
            ("bge-m3", 1024),
            ("nomic-embed-text", 768),
            ("jina-embeddings-v3", 1024),  # jina names need a jina binding
            (None, 1024),
            ("   ", 1024),
        ],
    )
    def test_auto_suppresses_for_unknown_or_blank_models(
        self, model: str | None, dimension: int
    ) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model=model,
                dimension=dimension,
                send_dimensions=None,
            )
            is False
        )


class TestJinaVariableDimensions:
    """Jina auto-mode only sends for on-grid Matryoshka dimensions."""

    @pytest.mark.parametrize(
        ("model", "dimension"),
        [
            ("jina-embeddings-v3", 32),
            ("jina-embeddings-v3", 768),
            ("jina-embeddings-v3", 1024),
            ("jina-embeddings-v4", 256),
            ("jina-embeddings-v4", 512),
        ],
    )
    def test_auto_sends_on_variable_grid(self, model: str, dimension: int) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model=model,
                dimension=dimension,
                send_dimensions=None,
            )
            is True
        )

    @pytest.mark.parametrize(
        ("model", "dimension"),
        [
            ("jina-embeddings-v3", 100),
            ("jina-embeddings-v3", 1536),
            ("jina-embeddings-v4", 64 + 1),
            ("jina-embeddings-v2", 1024),
            (None, 1024),
        ],
    )
    def test_auto_suppresses_offgrid_and_unknown_models(
        self, model: str | None, dimension: int
    ) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="jina",
                model=model,
                dimension=dimension,
                send_dimensions=None,
            )
            is False
        )

    @pytest.mark.parametrize("binding", ["Jina", " JINA ", "jina"])
    def test_binding_normalization_routes_to_jina_gate(self, binding: str) -> None:
        assert (
            should_send_embedding_dimensions(
                binding=binding,
                model="jina-embeddings-v3",
                dimension=1024,
                send_dimensions=None,
            )
            is True
        )
        assert (
            should_send_embedding_dimensions(
                binding=binding,
                model="jina-embeddings-v3",
                dimension=1536,
                send_dimensions=None,
            )
            is False
        )


class TestInvalidValuesDegradeToAuto:
    """Only real booleans count as explicit choices; others fall through."""

    @pytest.mark.parametrize("send_dimensions", [1, "true", "false", "0"])
    def test_non_bool_truthiness_is_not_an_explicit_choice(self, send_dimensions: object) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model="some-unknown-model",
                dimension=1024,
                send_dimensions=send_dimensions,  # type: ignore[arg-type]
            )
            is False
        )

    def test_non_bool_value_degrades_to_family_heuristic(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding="openai",
                model="text-embedding-3-large",
                dimension=3072,
                send_dimensions="true",  # type: ignore[arg-type]
            )
            is True
        )

    def test_none_binding_and_model_without_choice(self) -> None:
        assert (
            should_send_embedding_dimensions(
                binding=None,
                model=None,
                dimension=1024,
                send_dimensions=None,
            )
            is False
        )
