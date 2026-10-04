"""Unit tests for the shared prompt-pack lookup default contract.

``prompt_text`` is the one walker every prompt-pack caller shares: the string
at a path, or a fallback when the path is missing, holds a mapping, or holds
an empty string. These tests pin when the default wins and when the value is
returned.
"""

from __future__ import annotations

from deeptutor.services.prompt.lookup import prompt_text

PROMPTS = {
    "general": "You are DeepTutor.",
    "loop": {"system": "loop text", "empty": "", "nested": {"leaf": 7}},
}


class TestPromptText:
    def test_returns_string_at_path(self) -> None:
        assert prompt_text(PROMPTS, ("general",)) == "You are DeepTutor."

    def test_walks_nested_path(self) -> None:
        assert prompt_text(PROMPTS, ("loop", "system")) == "loop text"

    def test_missing_key_returns_default(self) -> None:
        assert prompt_text(PROMPTS, ("missing",), default="fallback") == "fallback"

    def test_missing_nested_key_returns_default(self) -> None:
        assert prompt_text(PROMPTS, ("loop", "missing"), default="fallback") == "fallback"

    def test_empty_string_returns_default(self) -> None:
        assert prompt_text(PROMPTS, ("loop", "empty"), default="fallback") == "fallback"

    def test_non_string_leaf_returns_default(self) -> None:
        assert prompt_text(PROMPTS, ("loop", "nested", "leaf"), default="fallback") == ("fallback")

    def test_non_dict_intermediate_returns_default(self) -> None:
        assert prompt_text(PROMPTS, ("general", "deeper"), default="fallback") == "fallback"

    def test_default_defaults_to_empty_string(self) -> None:
        assert prompt_text(PROMPTS, ("missing",)) == ""
