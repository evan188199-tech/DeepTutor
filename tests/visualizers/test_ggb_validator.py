"""Tests for GeoGebra command validator fatal-pattern checks."""

import json

from deeptutor.tools.vision.ggb_validator import (
    _is_boolean_argument,
    _is_explicit_scalar_expression,
    _is_point_argument,
    _is_scalar_argument,
    _split_command_args,
    fix_brackets,
    fix_common_mistakes,
    get_command_help,
    validate_command,
    validate_equation_format,
    validate_ggbscript,
    validate_text_command,
)
from deeptutor.visualizers.builtin import bundled_visualizers


class TestTextArity:
    def test_scalar_text_coordinates_are_combined(self):
        # The fatal pattern from #1324: Text["str", expr, expr]
        command = 'T9=Text["$(a+b)^2=a^2+2ab+b^2$",(a+b)/2,a+b+0.8]'
        result = validate_command(command)
        assert not result.is_valid
        assert result.errors == []
        assert result.fixed == ('T9=Text["$(a+b)^2=a^2+2ab+b^2$",((a+b)/2,a+b+0.8)]')
        assert any("Combined scalar" in warning for warning in result.warnings)

    def test_text_with_2_args_passes(self):
        command = 'T1=Text["$a^2$",(a/2,a/2)]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_4_args_passes(self):
        command = 'T2=Text["$ab$",(a+b/2,a/2),true,true]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_object_point_and_boolean_passes(self):
        command = 'T1=Text["$a^2$",P,true]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_non_text_commands_unaffected(self):
        command = "S1=Segment[E,F]"
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_point_and_non_boolean_third_argument_is_rejected(self):
        command = 'T1=Text["$a^2$",(1,2),3]'
        result = validate_command(command)
        assert not result.is_valid
        assert any("Invalid 3-argument Text[] signature" in error for error in result.errors)

    def test_uppercase_point_arguments_are_not_combined(self):
        command = 'T1=Text["label",P,Q]'
        result = validate_command(command)
        # Q could be a named Boolean. Static validation cannot infer its type.
        assert result.is_valid
        assert result.fixed == command

    def test_text_with_five_arguments_is_rejected(self):
        command = 'T1=Text["$a^2$",(1,2),true,true,5]'
        result = validate_command(command)
        assert not result.is_valid
        assert any("one to four arguments, or six" in error for error in result.errors)

    def test_text_with_six_alignment_arguments_passes(self):
        command = 'T1=Text["$a^2$",(1,2),true,true,-1,0]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_named_boolean_third_argument_is_preserved(self):
        command = 'T1=Text["label",P,showVariables]'
        result = validate_command(command)
        assert result.is_valid
        assert result.fixed == command


class TestLaTeXBalance:
    def test_unbalanced_dollar_is_rejected(self):
        command = 'T1=Text["$a^2,(a/2,a/2)]'
        result = validate_command(command)
        assert not result.is_valid
        assert len(result.errors) > 0

    def test_balanced_dollar_passes(self):
        command = 'T1=Text["$a^2+b^2$",(a/2,a/2)]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []


class TestScriptLevel:
    def test_visualizer_payload_normalizes_repaired_text_command(self):
        visualizer = next(
            plugin for plugin in bundled_visualizers() if plugin.manifest.id == "geogebra"
        )
        payload = json.dumps(
            {
                "app_name": "geometry",
                "commands": [
                    "A=(0,0)",
                    'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
                ],
                "view": {"x_min": -1, "x_max": 2, "y_min": -1, "y_max": 2},
            }
        )

        is_valid, normalized, error = visualizer.validator(payload)

        assert is_valid
        assert error == ""
        assert normalized["commands"][-1] == ('T9=Text["$(a+b)^2$",((a+b)/2,a+b+0.8)]')
        assert normalized["validation_warnings"] == [
            "Line 2: Combined scalar x and y arguments into a Text[] point argument"
        ]

    def test_geogebra_prompt_documents_text_signatures(self):
        visualizer = next(
            plugin for plugin in bundled_visualizers() if plugin.manifest.id == "geogebra"
        )
        prompt = visualizer.manifest.prompt

        assert "Text[<object>, <point>, <boolean>]" in prompt
        assert 'Text["$x^2$", ((a+b)/2, a+b+0.8)]' in prompt
        assert 'Text["$x^2$", (a+b)/2, a+b+0.8]' in prompt

    def test_scalar_coordinates_are_repaired_with_line_warning(self):
        script = "\n".join(
            [
                "a=Slider(1,5,0.1)",
                "b=Slider(1,5,0.1)",
                'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
            ]
        )
        fixed, warnings, errors = validate_ggbscript(script)
        assert errors == []
        assert 'T9=Text["$(a+b)^2$",((a+b)/2,a+b+0.8)]' in fixed.splitlines()
        assert warnings == [
            "Line 3: Combined scalar x and y arguments into a Text[] point argument"
        ]

    def test_mixed_script_reports_line_number(self):
        script = "\n".join(
            [
                "a=Slider(1,5,0.1)",
                "b=Slider(1,5,0.1)",
                'T9=Text["$(a+b)^2$",(1,2),3]',
            ]
        )
        _, _, errors = validate_ggbscript(script)
        assert len(errors) == 1
        assert errors[0].startswith("Line 3:")

    def test_clean_script_has_no_errors(self):
        script = "\n".join(
            [
                "A=(0,0)",
                "B=(1,1)",
                'T1=Text["$x$",(0.5,0.5)]',
            ]
        )
        _, warnings, errors = validate_ggbscript(script)
        assert errors == []


class TestFixBrackets:
    def test_known_command_converted_with_warning(self):
        fixed, warnings = fix_brackets("Circle((0,0),2)")
        assert fixed == "Circle[(0,0),2]"
        assert warnings == ["Changed Circle(...) to Circle[...]"]

    def test_nested_paren_arguments_survive(self):
        fixed, warnings = fix_brackets("Intersect(f(x), g(x))")
        assert fixed == "Intersect[f(x), g(x)]"
        assert len(warnings) == 1

    def test_matching_is_case_insensitive(self):
        fixed, _ = fix_brackets("circle((0,0),2)")
        assert fixed == "circle[(0,0),2]"

    def test_unknown_function_left_alone(self):
        fixed, warnings = fix_brackets("f(x)=x^2")
        assert fixed == "f(x)=x^2"
        assert warnings == []

    def test_bracket_fix_is_idempotent(self):
        once, _ = fix_brackets("Circle((0,0),2)")
        twice, warnings = fix_brackets(once)
        assert twice == once
        assert warnings == []


class TestFixCommonMistakes:
    def test_point_brace_arguments_flattened(self):
        fixed, warnings = fix_common_mistakes("A=Point({1,2})")
        assert fixed == "A=(1,2)"
        assert len(warnings) == 1
        assert warnings[0].startswith("Fixed pattern:")

    def test_log_base_ten_converted_to_lg(self):
        fixed, warnings = fix_common_mistakes("f(x)=log(10,x)+1")
        assert fixed == "f(x)=lg(x)+1"
        assert len(warnings) == 1

    def test_log_with_other_base_not_converted(self):
        fixed, warnings = fix_common_mistakes("f(x)=log(2,x)")
        assert fixed == "f(x)=log(2,x)"
        assert warnings == []

    def test_comment_line_removed(self):
        fixed, warnings = fix_common_mistakes("# just a note")
        assert fixed == ""
        assert len(warnings) == 1


class TestEquationFormat:
    def test_fractional_coefficient_warns_without_change(self):
        fixed, warnings = validate_equation_format("x^2/4 + y^2/9 = 1")
        assert fixed == "x^2/4 + y^2/9 = 1"
        assert len(warnings) == 1
        assert "fractional coefficients" in warnings[0]

    def test_integer_form_has_no_warning(self):
        fixed, warnings = validate_equation_format("9x^2 + 4y^2 = 36")
        assert fixed == "9x^2 + 4y^2 = 36"
        assert warnings == []


class TestSplitCommandArgs:
    def test_comma_inside_string_literal(self):
        assert _split_command_args('"a,b", c') == ['"a,b"', "c"]

    def test_comma_inside_nested_parens(self):
        assert _split_command_args("(1,(2,3)), x") == ["(1,(2,3))", "x"]

    def test_comma_inside_nested_brackets(self):
        assert _split_command_args("Circle[(0,0),2], B") == ["Circle[(0,0),2]", "B"]

    def test_escaped_quote_inside_string(self):
        assert _split_command_args('"a\\"b", c') == ['"a\\"b"', "c"]

    def test_empty_input_yields_no_arguments(self):
        assert _split_command_args("") == []

    def test_arguments_are_trimmed(self):
        assert _split_command_args("  a ,  b  ") == ["a", "b"]

    def test_trailing_comma_drops_empty_tail(self):
        assert _split_command_args("a,") == ["a"]


class TestArgumentClassifiers:
    def test_boolean_words_only(self):
        assert _is_boolean_argument("true")
        assert _is_boolean_argument("FALSE")
        assert not _is_boolean_argument("1")

    def test_point_argument_shape(self):
        assert _is_point_argument("(1,2)")
        assert not _is_point_argument("(1)")
        assert not _is_point_argument("()")
        assert not _is_point_argument("(1,)")
        assert not _is_point_argument("1,2")

    def test_scalar_argument_rules(self):
        assert _is_scalar_argument("3.5")
        assert _is_scalar_argument("a+b")
        assert not _is_scalar_argument("P")
        assert not _is_scalar_argument("true")
        assert not _is_scalar_argument("")
        assert not _is_scalar_argument('"text"')
        assert not _is_scalar_argument("(1,2)")

    def test_explicit_scalar_expression(self):
        assert _is_explicit_scalar_expression("a+b+0.8")
        assert _is_explicit_scalar_expression("3.5")
        assert not _is_explicit_scalar_expression("x")


class TestValidateCommandBoundaries:
    def test_empty_command_is_valid_noop(self):
        result = validate_command("")
        assert result.is_valid
        assert result.fixed == ""
        assert result.warnings == []
        assert result.errors == []

    def test_whitespace_only_command_is_valid_noop(self):
        result = validate_command("   ")
        assert result.is_valid
        assert result.fixed == "   "

    def test_comment_line_replaced_with_warning(self):
        result = validate_command("# note")
        assert result.is_valid
        assert result.fixed == ""
        assert result.warnings == ["Removed comment line (GeoGebra doesn't support # comments)"]

    def test_repaired_command_marks_invalid_without_errors(self):
        result = validate_command("A=Point({1,2})")
        assert not result.is_valid
        assert result.fixed == "A=(1,2)"
        assert result.errors == []
        assert len(result.warnings) == 1

    def test_original_is_preserved_unchanged(self):
        command = "A=Point({1,2})"
        result = validate_command(command)
        assert result.original == command

    def test_already_valid_command_is_untouched(self):
        command = 'T1=Text["$x$",(0.5,0.5)]'
        result = validate_command(command)
        assert result.is_valid
        assert result.fixed == command
        assert result.warnings == []

    def test_bracket_fix_marks_command_invalid(self):
        result = validate_command("C1=Circle((0,0),2)")
        assert not result.is_valid
        assert result.fixed == "C1=Circle[(0,0),2]"


class TestValidateTextBoundaries:
    def test_text_with_no_arguments_does_not_crash(self):
        fixed, warnings, errors = validate_text_command("Text[]")
        assert fixed == "Text[]"
        assert warnings == []
        assert errors == []

    def test_non_text_command_is_ignored(self):
        fixed, warnings, errors = validate_text_command("A=(0,0)")
        assert fixed == "A=(0,0)"
        assert warnings == []
        assert errors == []


class TestScriptLevelBehavior:
    def test_empty_script(self):
        assert validate_ggbscript("") == ("", [], [])

    def test_whitespace_only_script_is_preserved(self):
        assert validate_ggbscript("\n  \n") == ("\n  \n", [], [])

    def test_empty_and_whitespace_lines_are_preserved(self):
        script = "A=(0,0)\n\n   \nB=(1,1)"
        fixed, warnings, errors = validate_ggbscript(script)
        assert fixed == script
        assert warnings == []
        assert errors == []

    def test_comment_lines_removed_from_output(self):
        fixed, warnings, _ = validate_ggbscript("A=(0,0)\n# note\nB=(1,1)")
        assert fixed.splitlines() == ["A=(0,0)", "B=(1,1)"]
        assert any("Removed comment line" in warning for warning in warnings)

    def test_indentation_preserved_on_fix(self):
        fixed, warnings, errors = validate_ggbscript("  Circle((0,0),2)")
        assert fixed == "  Circle[(0,0),2]"
        assert warnings == ["Line 1: Changed Circle(...) to Circle[...]"]
        assert errors == []

    def test_warning_and_error_line_numbers_are_locatable(self):
        script = "\n".join(
            [
                "A=(0,0)",
                "C1=Circle((0,0),2)",
                'T1=Text["abc]',
            ]
        )
        fixed, warnings, errors = validate_ggbscript(script)
        assert any(warning.startswith("Line 2:") for warning in warnings)
        assert any(error.startswith("Line 3:") for error in errors)
        assert "C1=Circle[(0,0),2]" in fixed.splitlines()

    def test_unterminated_string_error_quotes_the_argument(self):
        _, _, errors = validate_ggbscript('T1=Text["abc]')
        assert len(errors) == 1
        assert '"abc' in errors[0]

    def test_repeated_calls_are_deterministic(self):
        script = "\n".join(
            [
                "A=Point({1,2})",
                'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
            ]
        )
        assert validate_ggbscript(script) == validate_ggbscript(script)

    def test_large_script_is_processed_completely(self):
        lines = [f"P{i}=({i},{i})" for i in range(200)]
        lines.append('T=Text["done",(0,0)]')
        fixed, warnings, errors = validate_ggbscript("\n".join(lines))
        assert len(fixed.splitlines()) == 201
        assert warnings == []
        assert errors == []


class TestGetCommandHelp:
    def test_known_command_returns_signature(self):
        help_text = get_command_help("Circle")
        assert help_text is not None
        assert "Circle[" in help_text

    def test_unknown_command_returns_none(self):
        assert get_command_help("NoSuchCommand") is None
