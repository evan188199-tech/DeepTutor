"""Table-driven mapping of reasoning/thinking parameters across providers.

Locks down the wire mapping in
``reasoning_params.build_openai_compatible_reasoning_kwargs`` (consulted by the
OpenAI-compat provider, the agentic client and the LightRAG provider), the
choice mapping in ``model_selection.reasoning.supported_reasoning_efforts``,
and the ``provider_factory`` plumbing that threads ``LLMConfig.reasoning_effort``
into ``GenerationSettings``.

Cases marked *current-state* pin surprising-but-current fallback behavior for
unrecognized values so a future change (e.g. upstream #641) is a deliberate
decision, not an accident. They describe what the code does today, not what it
should do forever.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_factory import (
    _provider_cache_key,
    build_isolated_provider,
)
from deeptutor.services.llm.reasoning_params import (
    RETRY_REASONING_EFFORT,
    build_openai_compatible_reasoning_kwargs,
    default_reasoning_effort_for,
    thinking_off_effort_for,
)
from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts
from deeptutor.services.provider_registry import find_by_name


def _kwargs(binding: str, model: str, effort: str | None, spec=None) -> dict:
    return build_openai_compatible_reasoning_kwargs(
        spec=spec if spec is not None else find_by_name(binding),
        binding=binding,
        model=model,
        reasoning_effort=effort,
    )


class TestProviderThinkingStyleMapping:
    """Each provider's reasoning control lands on the wire in its own shape."""

    @pytest.mark.parametrize(
        "binding, model, effort, expected",
        [
            # Plain top-level field, no extra_body.
            ("openai", "gpt-4o", "high", {"reasoning_effort": "high"}),
            # thinking_type providers: top-level effort plus thinking.type.
            (
                "deepseek",
                "deepseek-v4-flash",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
            ),
            (
                "deepseek",
                "deepseek-reasoner",
                "none",
                {"extra_body": {"thinking": {"type": "disabled"}}},
            ),
            (
                "volcengine",
                "doubao-pro-32k",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
            ),
            (
                "volcengine_coding_plan",
                "doubao-seed-code",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
            ),
            (
                "byteplus",
                "doubao-pro-32k",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
            ),
            (
                "byteplus_coding_plan",
                "doubao-pro-32k",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
            ),
            # enable_thinking providers never send a top-level reasoning_effort.
            (
                "dashscope",
                "qwen3-max",
                "high",
                {"extra_body": {"enable_thinking": True}},
            ),
            (
                "dashscope",
                "qwen3-max",
                "minimal",
                {"extra_body": {"enable_thinking": False}},
            ),
            # reasoning_split providers send both channels.
            (
                "minimax",
                "MiniMax-Text-01",
                "high",
                {
                    "reasoning_effort": "high",
                    "extra_body": {"reasoning_split": True},
                },
            ),
            (
                "minimax",
                "MiniMax-Text-01",
                "none",
                {"extra_body": {"reasoning_split": False}},
            ),
            # OpenRouter exposes a provider-neutral reasoning object for "off",
            # and a plain top-level effort otherwise.
            ("openrouter", "gpt-4o", "high", {"reasoning_effort": "high"}),
            (
                "openrouter",
                "gpt-4o",
                "none",
                {"extra_body": {"reasoning": {"effort": "none", "exclude": True}}},
            ),
        ],
    )
    def test_wire_shape_per_provider(
        self,
        binding: str,
        model: str,
        effort: str,
        expected: dict,
    ) -> None:
        assert _kwargs(binding, model, effort) == expected


class TestCustomBindingModelFamilyInference:
    """Direct custom endpoints are identified by model family, not provider."""

    @pytest.mark.parametrize(
        "model, expected",
        [
            ("Qwen/Qwen3-32B", {"extra_body": {"enable_thinking": True}}),
            ("qwq-32b", {"extra_body": {"enable_thinking": True}}),
            ("qwen-plus-latest", {"extra_body": {"enable_thinking": True}}),
        ],
    )
    def test_qwen_family_uses_enable_thinking(self, model: str, expected: dict) -> None:
        assert _kwargs("custom", model, "high", spec=None) == expected

    def test_deepseek_family_inferred_high_by_default(self) -> None:
        # No explicit effort: the matching pattern list supplies "high".
        assert _kwargs("custom", "deepseek-r1", None, spec=None) == {
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
        }

    def test_deepseek_family_off_is_binary_disabled(self) -> None:
        assert _kwargs("custom", "deepseek-reasoner", "none", spec=None) == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }

    def test_unknown_family_gets_top_level_only(self) -> None:
        assert _kwargs("custom", "mistral-large", "high", spec=None) == {"reasoning_effort": "high"}

    def test_openai_binding_aimed_at_qwen_gateway(self) -> None:
        # Model-family inference also covers openai bindings pointed at a
        # DeepSeek/Qwen gateway (#1058).
        assert _kwargs("openai", "qwen3-235b-a22b", "high") == {
            "extra_body": {"enable_thinking": True}
        }


class TestBindingConfigOverridesBuiltinTables:
    """Spec-provided style/patterns win over the built-in provider tables."""

    def test_spec_thinking_style_beats_provider_table(self) -> None:
        spec = SimpleNamespace(
            name="deepseek", thinking_style="reasoning_split", reasoning_model_patterns=()
        )
        assert _kwargs("deepseek", "doubao-pro-32k", "high", spec=spec) == {
            "reasoning_effort": "high",
            "extra_body": {"reasoning_split": True},
        }

    def test_spec_patterns_drive_inference(self) -> None:
        spec = SimpleNamespace(
            name="custom", thinking_style="", reasoning_model_patterns=("foo-model",)
        )
        assert _kwargs("custom", "foo-model-v2", None, spec=spec) == {"reasoning_effort": "high"}

    def test_empty_spec_fields_fall_back_to_provider_table(self) -> None:
        spec = SimpleNamespace(name="deepseek", thinking_style="", reasoning_model_patterns=())
        assert _kwargs("deepseek", "deepseek-reasoner", "none", spec=spec) == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }


class TestExplicitOverridesDefaults:
    """Priority: explicit effort > pattern inference > provider default > unset."""

    def test_explicit_low_beats_pattern_inferred_high(self) -> None:
        # deepseek-reasoner would infer "high" from its pattern list; an
        # explicit "low" must win.
        assert _kwargs("deepseek", "deepseek-reasoner", "low") == {
            "reasoning_effort": "low",
            "extra_body": {"thinking": {"type": "enabled"}},
        }

    def test_pattern_inference_beats_provider_default_off(self) -> None:
        # gemini-2.5-flash has a provider default of "none"; a binding that
        # explicitly lists the model as a reasoning model overrides it.
        spec = SimpleNamespace(
            name="gemini",
            thinking_style="",
            reasoning_model_patterns=("gemini-2.5-flash",),
        )
        assert _kwargs("gemini", "gemini-2.5-flash", None, spec=spec) == {
            "reasoning_effort": "high"
        }

    def test_provider_patterns_infer_high_by_default(self) -> None:
        assert _kwargs("dashscope", "qwen3-max", None) == {"extra_body": {"enable_thinking": True}}

    def test_nothing_applies_leaves_request_untouched(self) -> None:
        assert _kwargs("openai", "gpt-4o", None) == {}


class TestUnrecognizedEffortValues:
    """Fallback behavior for values outside the recognized set.

    All cases here are *current-state* pins: the helper does not validate the
    effort value, it normalizes only what it must to keep vendors happy.
    """

    def test_empty_string_means_explicitly_unset(self) -> None:
        assert _kwargs("deepseek", "deepseek-reasoner", "") == {}

    def test_unknown_value_passes_through_unvalidated(self) -> None:
        # Current-state: no validation, "banana" reaches the wire verbatim.
        assert _kwargs("openai", "gpt-4o", "banana") == {"reasoning_effort": "banana"}

    def test_unknown_value_counts_as_thinking_enabled(self) -> None:
        # Current-state: any non-off value enables the binary thinking flag.
        assert _kwargs("deepseek", "deepseek-v4-flash", "banana") == {
            "reasoning_effort": "banana",
            "extra_body": {"thinking": {"type": "enabled"}},
        }

    @pytest.mark.parametrize(
        "effort",
        ["none", "NONE", "None"],
    )
    def test_off_detection_is_case_insensitive(self, effort: str) -> None:
        assert _kwargs("gemini", "gemini-2.5-flash", effort) == {"reasoning_effort": "none"}
        assert _kwargs("deepseek", "deepseek-reasoner", effort) == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }

    def test_minimum_is_normalized_to_the_off_sentinel(self) -> None:
        assert _kwargs("deepseek", "deepseek-reasoner", "minimum") == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }

    def test_minimum_verbatim_when_no_thinking_style(self) -> None:
        # Current-state: the top-level field keeps the caller's raw spelling;
        # only the semantic comparison is normalized.
        assert _kwargs("openai", "gpt-4o", "Minimum") == {"reasoning_effort": "Minimum"}

    def test_whitespace_is_preserved_verbatim(self) -> None:
        # Current-state: only off-detection trims; the wire value is untouched.
        assert _kwargs("openai", "gpt-4o", "  high  ") == {"reasoning_effort": "  high  "}


class TestOffEffortHelpers:
    """The lowest effort each model family accepts as "thinking off" (#734)."""

    @pytest.mark.parametrize(
        "provider, model, expected",
        [
            ("gemini", "gemini-3-pro", "minimal"),
            ("gemini", "gemini-2.5-pro", "minimal"),
            ("gemini", "gemini-2.5-flash", "none"),
            ("openai", "gpt-4o", "none"),
            ("deepseek", "deepseek-reasoner", "none"),
            (None, None, "none"),
            ("GEMINI", "gemini-3-flash", "minimal"),
            (" gemini ", "gemini-2.5-pro", "minimal"),
        ],
    )
    def test_thinking_off_effort_table(
        self, provider: str | None, model: str | None, expected: str
    ) -> None:
        assert thinking_off_effort_for(provider, model) == expected

    @pytest.mark.parametrize(
        "provider, model, expected",
        [
            ("gemini", "gemini-2.5-flash", "none"),
            ("gemini", "gemini-2.5-pro", "minimal"),
            ("volcengine", "doubao-pro-32k", None),
            (" gemini ", "gemini-2.5-flash", "none"),
            ("", "", None),
        ],
    )
    def test_default_effort_table(
        self, provider: str | None, model: str | None, expected: str | None
    ) -> None:
        assert default_reasoning_effort_for(provider, model) == expected

    def test_retry_effort_is_low(self) -> None:
        # Current-state: "low" rather than "minimal" — local/Qwen models via
        # vLLM reject "minimal" (module docstring in reasoning_params).
        assert RETRY_REASONING_EFFORT == "low"


class TestSupportedReasoningEfforts:
    """Choice mapping priority: declared catalog > binary wire mapping >
    family defaults, with a capabilities kill-switch."""

    @pytest.mark.parametrize(
        "binding, model, expected",
        [
            ("deepseek", "deepseek-reasoner", ["minimal", "high"]),
            # Current-state: the binary mapping is spec-level, so every
            # deepseek model — thinking or not — reports the binary choices.
            ("deepseek", "deepseek-v4-chat", ["minimal", "high"]),
            ("openai", "gpt-5", ["minimal", "low", "medium", "high", "xhigh"]),
            ("google", "gemini-3-pro", ["minimal", "low", "medium", "high"]),
            ("claude", "claude-sonnet-4-5", ["none", "low", "medium", "high"]),
        ],
    )
    def test_family_defaults(self, binding: str, model: str, expected: list[str]) -> None:
        assert supported_reasoning_efforts(binding, model) == expected

    def test_declared_catalog_is_filtered_and_ordered(self) -> None:
        levels = supported_reasoning_efforts(
            "openai",
            "gpt-4o",
            metadata={"codex_supported_reasoning_levels": ["high", "medium", "none"]},
        )
        assert levels == ["none", "medium", "high"]

    def test_declared_catalog_is_narrowed_by_binary_mapping(self) -> None:
        levels = supported_reasoning_efforts(
            "deepseek",
            "deepseek-reasoner",
            metadata={"codex_supported_reasoning_levels": ["none", "minimal", "high"]},
        )
        assert levels == ["minimal", "high"]

    def test_capability_reasoning_false_disables_choices(self) -> None:
        levels = supported_reasoning_efforts(
            "openai", "gpt-4o", metadata={"capabilities": {"reasoning": False}}
        )
        assert levels == []

    def test_unknown_provider_and_model_have_no_choices(self) -> None:
        assert supported_reasoning_efforts("nope-provider", "x") == []


def _factory_config(**overrides) -> LLMConfig:
    defaults = dict(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        effective_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
        extra_headers={},
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


class TestProviderFactoryReasoningPlumbing:
    """provider_factory threads the configured effort into GenerationSettings
    and keys the provider pool on it."""

    def test_config_effort_reaches_generation_settings(self) -> None:
        provider = build_isolated_provider(_factory_config(reasoning_effort="high"))
        assert provider.generation.reasoning_effort == "high"

    def test_unset_effort_stays_none(self) -> None:
        provider = build_isolated_provider(_factory_config())
        assert provider.generation.reasoning_effort is None

    def test_pool_cache_key_distinguishes_efforts(self) -> None:
        # Changing only the explicit effort must not reuse a pooled provider.
        loop = SimpleNamespace()  # identity is all the key needs
        high = _provider_cache_key(_factory_config(reasoning_effort="high"), loop)
        none = _provider_cache_key(_factory_config(reasoning_effort=None), loop)
        assert high != none
