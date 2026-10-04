"""Failure-branch tests for prompt template rendering in the agent loop.

``LoopPromptAssembler`` reads prompt strings out of a pack (with a default
when the pack lacks the entry) and fills ``str.format`` placeholders. These
tests pin the default, fallback and literal-retention behaviour on the edges:
a pack missing a key, a template naming an unknown variable, and
metacharacters that must pass through verbatim rather than being
reinterpreted.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deeptutor.agents.loop import prompt_blocks as prompt_blocks_module
from deeptutor.agents.loop.prompt_blocks import LoopPromptAssembler
from deeptutor.core.context import UnifiedContext

BASE_PROMPTS = {
    "general": "You are DeepTutor.",
    "runtime_policy": "policy",
    "loop": {"system": "loop"},
}

# Pinned in the machine's local timezone so ``.astimezone()`` in the block is
# a no-op and the rendered date is 2026-08-17 regardless of the host's TZ.
FIXED_NOW = datetime(2026, 8, 17, 12).astimezone()


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW
        return FIXED_NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_runtime_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt_blocks_module, "datetime", FrozenDateTime)


def _assembler(prompts: dict, language: str = "en") -> LoopPromptAssembler:
    return LoopPromptAssembler(prompts=prompts, language=language)


class TestLookupDefaults:
    def test_missing_key_returns_default(self) -> None:
        assembler = _assembler(BASE_PROMPTS)
        assert assembler._t("loop.user", default="{user_message}") == "{user_message}"

    def test_missing_intermediate_path_returns_default(self) -> None:
        assembler = _assembler(BASE_PROMPTS)
        assert assembler._t("loop.missing.deeper", default="fallback") == "fallback"

    def test_non_string_leaf_returns_default(self) -> None:
        assembler = _assembler({"loop": {"system": {"not": "a string"}}})
        assert assembler._t("loop.system", default="fallback") == "fallback"

    def test_empty_string_leaf_is_returned_unchanged(self) -> None:
        # Unlike ``prompt_text``, the assembler's ``_t`` treats an empty
        # string as a present value: callers own the empty case.
        assembler = _assembler({"runtime_policy": ""})
        assert assembler._t("runtime_policy", default="fallback") == ""

    def test_exhausted_instruction_default_when_pack_lacks_key(self) -> None:
        assembler = _assembler(BASE_PROMPTS)
        instruction = assembler.finish_exhausted_instruction()
        assert "budget ran out" in instruction


class TestUserMessageSubstitution:
    def test_default_template_wraps_the_user_message(self) -> None:
        content = _assembler(BASE_PROMPTS).user_message(
            context=UnifiedContext(user_message="explain entropy")
        )
        assert content == "explain entropy"

    def test_custom_template_substitutes_variable(self) -> None:
        prompts = {**BASE_PROMPTS, "loop": {**BASE_PROMPTS["loop"], "user": "Q: {user_message}"}}
        content = _assembler(prompts).user_message(
            context=UnifiedContext(user_message="explain entropy")
        )
        assert content == "Q: explain entropy"

    def test_kb_seed_is_appended(self) -> None:
        content = _assembler(BASE_PROMPTS).user_message(
            context=UnifiedContext(user_message="q"), kb_seed="seed text"
        )
        assert content == "q\n\nseed text"


class TestUserMessageMissingVariable:
    def test_unknown_placeholder_falls_back_to_raw_message(self) -> None:
        prompts = {
            **BASE_PROMPTS,
            "loop": {**BASE_PROMPTS["loop"], "user": "Q: {user_message} ctx: {missing}"},
        }
        content = _assembler(prompts).user_message(
            context=UnifiedContext(user_message="explain entropy")
        )
        assert content == "explain entropy"

    def test_positional_placeholder_falls_back_to_raw_message(self) -> None:
        prompts = {**BASE_PROMPTS, "loop": {**BASE_PROMPTS["loop"], "user": "Q: {}"}}
        content = _assembler(prompts).user_message(
            context=UnifiedContext(user_message="explain entropy")
        )
        assert content == "explain entropy"

    def test_braces_inside_the_value_pass_through_unchanged(self) -> None:
        # The user's text is a format *argument*, never a template: braces in
        # it reach the prompt verbatim instead of being interpreted.
        content = _assembler(BASE_PROMPTS).user_message(
            context=UnifiedContext(user_message="what does {x} mean in {lang}?")
        )
        assert content == "what does {x} mean in {lang}?"


class TestRuntimeContextTemplateEdges:
    def _runtime_block(self, prompts: dict) -> str:
        blocks = _assembler(prompts).blocks(
            context=UnifiedContext(user_message="hi"), tool_manifest="- none"
        )
        return next(b.content for b in blocks if b.name == "runtime_context")

    def test_escaped_braces_render_as_literal_braces(self) -> None:
        prompts = {
            **BASE_PROMPTS,
            "runtime_context": "Date {datetime} ({{literal}}).",
        }
        content = self._runtime_block(prompts)
        assert content == "Date 2026-08-17 ({literal})."

    def test_unknown_named_placeholder_uses_fallback_rendering(self) -> None:
        prompts = {
            **BASE_PROMPTS,
            "runtime_context": "Date {datetime}, tz {tz}.",
        }
        content = self._runtime_block(prompts)
        # The malformed template is kept verbatim and the date appended, so
        # the model still learns the real date instead of a leaked placeholder.
        assert content == "Date {datetime}, tz {tz}. 2026-08-17"

    def test_positional_placeholder_uses_fallback_rendering(self) -> None:
        prompts = {**BASE_PROMPTS, "runtime_context": "Date {datetime} at {}."}
        content = self._runtime_block(prompts)
        assert content == "Date {datetime} at {}. 2026-08-17"
