"""Unit tests for ``render_message_template`` (i18next-style ``{{name}}``).

The renderer is the single place progress lines get their English fallback:
the wire carries the template plus its values and this function fills it for
every consumer without i18n of its own. These tests pin the substitution,
default and literal-retention behaviour of the pure function itself.
"""

from __future__ import annotations

from deeptutor.knowledge.progress_tracker import render_message_template


class TestReplacement:
    def test_single_parameter(self) -> None:
        assert render_message_template("Indexing {{name}}", {"name": "physics"}) == (
            "Indexing physics"
        )

    def test_multiple_parameters(self) -> None:
        out = render_message_template(
            "{{current}}/{{total}}: {{file}}",
            {"current": 3, "total": 7, "file": "a.pdf"},
        )
        assert out == "3/7: a.pdf"

    def test_repeated_placeholder_replaced_everywhere(self) -> None:
        out = render_message_template(
            "{{name}} started; {{name}} finished",
            {"name": "kb"},
        )
        assert out == "kb started; kb finished"

    def test_non_string_values_are_coerced(self) -> None:
        out = render_message_template(
            "{{i}} {{f}} {{b}} {{n}}",
            {"i": 3, "f": 0.5, "b": True, "n": None},
        )
        assert out == "3 0.5 True None"

    def test_unused_parameters_are_ignored(self) -> None:
        out = render_message_template("static text", {"name": "unused"})
        assert out == "static text"


class TestDefaults:
    def test_empty_params_leaves_template_unchanged(self) -> None:
        template = "Processing {{name}} ({{percent}}%)"
        assert render_message_template(template, {}) == template

    def test_template_without_placeholders_is_verbatim(self) -> None:
        assert render_message_template("plain progress line", {"x": 1}) == "plain progress line"


class TestMissingVariables:
    def test_unknown_placeholder_stays_literal(self) -> None:
        out = render_message_template("Hello {{name}}", {})
        assert out == "Hello {{name}}"

    def test_partial_params_replace_only_known_names(self) -> None:
        out = render_message_template(
            "{{current}}/{{total}} done",
            {"current": 2},
        )
        assert out == "2/{{total}} done"

    def test_repeated_unknown_placeholder_stays_literal(self) -> None:
        out = render_message_template("{{missing}} and {{missing}}", {"other": 1})
        assert out == "{{missing}} and {{missing}}"


class TestSpecialCharactersAreLiteral:
    """The renderer must treat templates and values as literal text.

    It fills with ``str.replace``, so format-string and percent-format
    metacharacters pass through verbatim instead of being reinterpreted.
    These assertions only pin the escaped/literal output contract.
    """

    def test_braces_in_template_are_untouched(self) -> None:
        template = "Map {key} and dict {} and {{kept}} with {{name}}"
        out = render_message_template(template, {"name": "v"})
        assert out == "Map {key} and dict {} and {{kept}} with v"

    def test_percent_markers_in_template_are_untouched(self) -> None:
        out = render_message_template("Progress: {{p}}% (fmt %s)", {"p": 50})
        assert out == "Progress: 50% (fmt %s)"

    def test_metacharacters_in_values_pass_through(self) -> None:
        out = render_message_template("Value: {{v}}", {"v": "{x} %s {y}"})
        assert out == "Value: {x} %s {y}"

    def test_backslashes_in_values_pass_through(self) -> None:
        out = render_message_template("Path {{p}}", {"p": "a\\b\\c"})
        assert out == "Path a\\b\\c"

    def test_brace_like_marker_with_spaces_is_not_a_variable(self) -> None:
        out = render_message_template("{{ name }} stays", {"name": "v"})
        assert out == "{{ name }} stays"
