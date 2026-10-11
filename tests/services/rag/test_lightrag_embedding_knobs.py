"""LightRAG embedding concurrency knobs: SDK defaults unless configured.

Covers scan item L-2: ``embedding_func_max_async`` / ``embedding_batch_num``
must reach the pinned LightRAG constructor when set, and must stay absent
when unset so the SDK (and its environment overrides) keeps the default.
"""

from __future__ import annotations

from deeptutor.services.rag.pipelines.lightrag import config as lightrag_config


def test_constructor_kwargs_keep_sdk_defaults_when_unset(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings",
        lambda: {
            "llm_model_max_async": 4,
            "entity_extract_max_gleaning": 1,
            "llm_timeout": 240,
            "embedding_func_max_async": None,
            "embedding_batch_num": None,
        },
    )

    assert lightrag_config.constructor_kwargs_from_settings() == {
        "llm_model_max_async": 4,
        "entity_extract_max_gleaning": 1,
        "default_llm_timeout": 240,
    }


def test_constructor_kwargs_omit_embedding_knobs_for_legacy_settings(monkeypatch) -> None:
    """A lightrag.json written before these knobs existed must load unchanged."""
    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings",
        lambda: {
            "llm_model_max_async": 8,
            "entity_extract_max_gleaning": 2,
            "llm_timeout": 480,
        },
    )

    kwargs = lightrag_config.constructor_kwargs_from_settings()

    assert kwargs == {
        "llm_model_max_async": 8,
        "entity_extract_max_gleaning": 2,
        "default_llm_timeout": 480,
    }
    assert "embedding_func_max_async" not in kwargs
    assert "embedding_batch_num" not in kwargs


def test_constructor_kwargs_forward_configured_embedding_knobs(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings",
        lambda: {
            "llm_model_max_async": 4,
            "entity_extract_max_gleaning": 1,
            "llm_timeout": 240,
            "embedding_func_max_async": 12,
            "embedding_batch_num": 64,
        },
    )

    kwargs = lightrag_config.constructor_kwargs_from_settings()

    assert kwargs["embedding_func_max_async"] == 12
    assert kwargs["embedding_batch_num"] == 64
    assert kwargs["llm_model_max_async"] == 4
