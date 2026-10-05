"""Tests for the stable identity rules in
:mod:`deeptutor.learning.identity` — the single place a Mastery Path id is
resolved, so the runtime, capability, tools, and persistence all lease the
same path within a turn.

These protect the resolution order and its failure fallbacks:

* explicit configuration wins over anything else and is never session-owned;
* the first usable book reference is next (string, or dict with
  ``book_id``/``id``), malformed or empty references are skipped;
* only when neither exists does the session id become a session-owned path;
* anything that sanitizes to empty falls back to ``default`` instead of an
  unusable storage id.
"""

from __future__ import annotations

from deeptutor.learning.identity import (
    MasteryPathBinding,
    resolve_mastery_path_binding,
    sanitize_mastery_path_id,
)


class TestSanitizeMasteryPathId:
    def test_replaces_unsafe_characters_with_underscores(self):
        assert sanitize_mastery_path_id("book 42/ed:2") == "book_42_ed_2"
        assert sanitize_mastery_path_id("id-with-dash_and_underscore") == (
            "id-with-dash_and_underscore"
        )

    def test_strips_leading_and_trailing_underscores(self):
        assert sanitize_mastery_path_id("??path??") == "path"
        assert sanitize_mastery_path_id("  id  ") == "id"

    def test_non_ascii_characters_are_sanitized_away(self):
        assert sanitize_mastery_path_id("路径") == "default"

    def test_empty_or_blank_input_falls_back_to_default(self):
        assert sanitize_mastery_path_id("") == "default"
        assert sanitize_mastery_path_id("///") == "default"

    def test_none_like_input_falls_back_to_default(self):
        assert sanitize_mastery_path_id(str(None or "")) == "default"


class TestResolveMasteryPathBinding:
    def test_configured_path_wins_over_books_and_session(self):
        binding = resolve_mastery_path_binding(
            configured_path_id="chap-1",
            book_references=["bk-9"],
            session_id="s-1",
        )
        assert binding == MasteryPathBinding(path_id="chap-1", owned_by_session=False)

    def test_configured_path_is_sanitized(self):
        binding = resolve_mastery_path_binding(configured_path_id="My Path/1")
        assert binding.path_id == "My_Path_1"
        assert binding.owned_by_session is False

    def test_blank_configured_path_is_ignored(self):
        binding = resolve_mastery_path_binding(
            configured_path_id="   ",
            book_references=["bk-2"],
        )
        assert binding.path_id == "bk-2"
        assert binding.owned_by_session is False

    def test_first_string_book_reference_is_used(self):
        binding = resolve_mastery_path_binding(book_references=["bk-2", "bk-3"])
        assert binding == MasteryPathBinding(path_id="bk-2", owned_by_session=False)

    def test_dict_book_reference_prefers_book_id_then_id(self):
        binding = resolve_mastery_path_binding(book_references=[{"book_id": " bk9 "}])
        assert binding.path_id == "bk9"

        binding = resolve_mastery_path_binding(book_references=[{"id": "bk8"}])
        assert binding.path_id == "bk8"

    def test_only_the_first_reference_is_considered(self):
        binding = resolve_mastery_path_binding(
            book_references=[{"other": 1}, {"book_id": "bk-real"}]
        )
        assert binding.owned_by_session is True
        assert binding.path_id != "bk-real"

    def test_unusable_book_references_fall_through_to_session(self):
        for unusable in (None, [], ["   "], [{"other": 1}], [42], [""], "not-a-list"):
            binding = resolve_mastery_path_binding(book_references=unusable, session_id="s-1")
            assert binding == MasteryPathBinding(path_id="s-1", owned_by_session=True), unusable

    def test_book_reference_id_is_sanitized(self):
        binding = resolve_mastery_path_binding(book_references=["bk/9 x"])
        assert binding.path_id == "bk_9_x"
        assert binding.owned_by_session is False

    def test_session_fallback_is_session_owned_and_sanitized(self):
        binding = resolve_mastery_path_binding(session_id="session/1")
        assert binding == MasteryPathBinding(path_id="session_1", owned_by_session=True)

    def test_nothing_given_defaults_to_default_path(self):
        binding = resolve_mastery_path_binding()
        assert binding == MasteryPathBinding(path_id="default", owned_by_session=True)
