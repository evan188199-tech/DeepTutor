"""Tests for the LaTeX verbalizer pre-layer.

Direct coverage for ``deeptutor.services.voice.speech_text``: math island
scanning, TeX-to-speech verbalization, Unicode math symbols, malformed TeX
degradation, and the ``math_speak=False`` unwrap-only mode. Complements the
end-to-end ``strip_markdown_for_speech`` cases in ``tests/services/test_voice.py``
without repeating them.
"""

from __future__ import annotations

import time

import pytest

from deeptutor.services.voice.speech_text import verbalize_latex_for_speech


def test_empty_input_returns_empty() -> None:
    assert verbalize_latex_for_speech("") == ""
    assert verbalize_latex_for_speech("", math_speak=False) == ""


def test_plain_prose_fast_path_untouched() -> None:
    text = "Read chapter 3 before class, see my_file_name.txt for notes."
    assert verbalize_latex_for_speech(text) == text
    # Bare underscores outside math are never treated as subscript scripts.
    assert verbalize_latex_for_speech("value of total_count is high") == (
        "value of total_count is high"
    )


def test_unicode_math_symbols_verbalized() -> None:
    out = verbalize_latex_for_speech("x ≤ 5, y ≠ 0, and √9 approaches ∞ plus ±1")
    assert "less than or equal to" in out
    assert "not equal to" in out
    assert "square root of 9" in out
    assert "infinity" in out
    assert "plus or minus 1" in out
    assert "≤" not in out and "√" not in out and "∞" not in out and "±" not in out


def test_math_speak_false_strips_delimiters_keeps_tex() -> None:
    out = verbalize_latex_for_speech(r"value $\frac{1}{2}$ stays", math_speak=False)
    assert "$" not in out
    assert r"\frac{1}{2}" in out  # inner TeX untouched
    assert "1 over" not in out  # not verbalized

    # The no-island fast path must skip Unicode replacement in this mode too.
    plain = verbalize_latex_for_speech("x ≤ 5", math_speak=False)
    assert plain == "x ≤ 5"


def test_multiple_islands_all_verbalized() -> None:
    out = verbalize_latex_for_speech(r"$\alpha$ mid $\beta$ tail")
    assert "alpha" in out and "beta" in out and "tail" in out
    assert "$" not in out and "\\" not in out


def test_display_and_align_environments_verbalized() -> None:
    out = verbalize_latex_for_speech(r"\begin{equation} E = mc^2 \end{equation} done")
    assert "E = mc squared" in out
    assert "equation" not in out

    out = verbalize_latex_for_speech("before \\begin{align} a &< b \\\\ c &> d \\end{align} after")
    assert "a < b" in out and "c > d" in out
    assert "&" not in out and "align" not in out


def test_cases_environment_verbalized() -> None:
    out = verbalize_latex_for_speech(r"\begin{cases} x>0 \\ y<1 \end{cases} end")
    assert "x>0" in out and "y<1" in out
    assert "cases" not in out and "\\" not in out


def test_binom_and_limit_verbalized() -> None:
    out = verbalize_latex_for_speech(r"count $\binom{n}{k}$ ways")
    assert "n choose k" in out

    out = verbalize_latex_for_speech(r"as $\lim_{x \to 0} f$ holds")
    assert "limit as x to 0" in out
    assert "_" not in out


def test_superscript_special_tokens() -> None:
    assert "inverse" in verbalize_latex_for_speech(r"$A^{-1}$ works")
    assert "transpose" in verbalize_latex_for_speech(r"$M^T$ too")
    # Braced subscripts verbalize their inner command cleanly.
    out = verbalize_latex_for_speech(r"$x_{\alpha}$ here")
    assert "x sub alpha" in out


def test_mathbb_and_style_commands_unwrapped() -> None:
    out = verbalize_latex_for_speech(r"$x \in \mathbb{R}$ yes")
    assert "the reals" in out and "in" in out

    out = verbalize_latex_for_speech(r"$\mathbf{F} = m \mathbf{a}$ ok")
    assert "F = m a" in out
    assert "mathbf" not in out and "\\" not in out


def test_accent_bar_verbalized() -> None:
    out = verbalize_latex_for_speech(r"$\bar{x}$ mean")
    assert "x bar" in out


def test_prose_transform_applied_outside_islands_only() -> None:
    out = verbalize_latex_for_speech(
        r"**bold** words and $\frac{1}{2}$ end",
        prose_transform=lambda s: s.replace("**", ""),
    )
    assert "**" not in out
    assert "bold words and" in out
    assert "1 over 2" in out  # island output bypasses the prose transform


def test_escaped_dollar_does_not_open_island() -> None:
    out = verbalize_latex_for_speech(r"cost \$5 and \$10 total")
    assert "$" not in out  # leftover dollars are never spoken
    assert "cost" in out and "total" in out
    assert "5" in out and "10" in out


def test_unclosed_islands_do_not_crash_or_leak_dollars() -> None:
    out = verbalize_latex_for_speech(r"broken $$\frac{1}{2 with no end")
    assert "$" not in out
    assert "1 over" in out  # prose fallback still verbalizes known commands
    assert "with no end" in out

    out = verbalize_latex_for_speech(r"oops $\sqrt{x forever")
    assert "square root of x forever" in out
    assert "$" not in out


def test_malformed_commands_degrade_quietly() -> None:
    # Dangling \frac with no operands: dropped without raising.
    out = verbalize_latex_for_speech(r"$\frac$ alone")
    assert "alone" in out
    assert "\\" not in out and "frac" not in out

    # Unknown command: command name dropped, group contents kept.
    out = verbalize_latex_for_speech(r"$\foo{bar}$ end")
    assert "bar" in out and "end" in out
    assert "foo" not in out and "\\" not in out

    # Unclosed brace inside an island: braces dissolve, content survives.
    out = verbalize_latex_for_speech(r"$\sqrt{x$ tail")
    assert "square root of x" in out
    assert "tail" in out
    assert "{" not in out and "}" not in out


def test_windows_path_preserved_next_to_math() -> None:
    out = verbalize_latex_for_speech(r"open C:\Users\foo\bar then $\alpha$ appears")
    assert r"C:\Users\foo\bar" in out
    assert "alpha" in out
    assert "appears" in out


def test_extra_long_text_completes_quickly() -> None:
    prose = "In this section we discuss the result "
    long_text = (prose + r"$\frac{a}{b}$ and $\sqrt{x^2+1}$ ") * 2000
    start = time.perf_counter()
    out = verbalize_latex_for_speech(long_text)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
    assert "$" not in out and "\\frac" not in out and "\\sqrt" not in out
    assert out.count("over") == 2000
    assert out.count("square root of") == 2000


@pytest.mark.parametrize(
    "text",
    [
        r"$\frac{1}{$",
        r"$$",
        r"\begin{equation} unclosed",
        r"$\lim_$",
        r"$\sqrt[$",
        "$ $ $",
    ],
)
def test_degenerate_inputs_return_without_error(text: str) -> None:
    out = verbalize_latex_for_speech(text)
    assert isinstance(out, str)
