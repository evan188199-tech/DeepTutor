"""``supported_reasoning_efforts``: catalog declaration first, family defaults second."""

from __future__ import annotations

from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts


def test_declared_catalog_levels_win_over_family_defaults():
    levels = supported_reasoning_efforts(
        "gemini",
        "gemini-2.5-pro",
        metadata={"codex_supported_reasoning_levels": ["high", "bogus", "low"]},
    )

    assert levels == ["low", "high"]


def test_an_empty_declaration_wins_over_family_defaults():
    levels = supported_reasoning_efforts(
        "gemini",
        "gemini-2.5-pro",
        metadata={"codex_supported_reasoning_levels": []},
    )

    assert levels == []


def test_a_declaration_is_clipped_to_the_wire_binary_choices():
    # deepseek rides an OpenAI-compatible wire whose binary knob can only
    # express off as minimal and on as high, whatever the catalog declares.
    levels = supported_reasoning_efforts(
        "deepseek",
        "deepseek-chat",
        metadata={"codex_supported_reasoning_levels": ["none", "minimal", "low", "high"]},
    )

    assert levels == ["minimal", "high"]


def test_a_disabled_reasoning_capability_beats_family_defaults():
    levels = supported_reasoning_efforts(
        "gemini",
        "gemini-2.5-pro",
        metadata={"capabilities": {"reasoning": False}},
    )

    assert levels == []


def test_gemini_family_defaults_follow_the_model_generation():
    assert supported_reasoning_efforts("gemini", "gemini-3-pro") == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("gemini", "gemini-2.5-pro") == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("gemini", "gemini-2.5-flash") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("gemini", "gemini-2.0-flash") == [
        "low",
        "medium",
        "high",
    ]


def test_anthropic_family_defaults_split_by_generation():
    assert supported_reasoning_efforts("anthropic", "claude-sonnet-4-5") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("anthropic", "claude-sonnet-5") == ["none", "adaptive"]


def test_binding_aliases_resolve_to_their_family():
    assert supported_reasoning_efforts("google", "gemini-2.5-flash") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("claude", "claude-sonnet-4-5") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("GEMINI", "gemini-2.5-flash") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("azureopenai", "gpt-5") == [
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ]


def test_model_name_families_apply_across_providers():
    assert supported_reasoning_efforts("custom", "gemini-2.5-flash") == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert supported_reasoning_efforts("anthropic_compatible", "claude-sonnet-4-5") == [
        "none",
        "low",
        "medium",
        "high",
    ]


def test_reasoning_reasoner_families_get_binary_choices():
    assert supported_reasoning_efforts("deepseek", "deepseek-reasoner") == ["minimal", "high"]
    assert supported_reasoning_efforts("dashscope", "qwen3-max") == ["minimal", "high"]
    assert supported_reasoning_efforts("minimax", "minimax-m2") == ["minimal", "high"]


def test_openai_generation_defaults():
    assert supported_reasoning_efforts("openai", "gpt-5.6-sol") == [
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert supported_reasoning_efforts("openai", "gpt-5-mini") == [
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert supported_reasoning_efforts("openai", "o3-mini") == ["low", "medium", "high"]


def test_a_declared_capability_flag_defaults_when_the_family_is_unknown():
    levels = supported_reasoning_efforts(
        "mystery_provider",
        "mystery-model",
        metadata={"capabilities": {"reasoning": True}},
    )

    assert levels == ["none", "low", "medium", "high"]


def test_an_unknown_provider_and_model_offer_no_choices():
    assert supported_reasoning_efforts("mystery_provider", "mystery-model") == []


def test_missing_metadata_is_tolerated():
    assert supported_reasoning_efforts("gemini", "gemini-2.5-flash", metadata=None) == [
        "none",
        "low",
        "medium",
        "high",
    ]
