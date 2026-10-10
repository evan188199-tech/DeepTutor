from deeptutor.runtime.agentic.labels import (
    LABEL_UNKNOWN,
    classify_label,
    find_inline_labels,
    recover_finished_label,
    strip_label_probe_prefix,
)
from deeptutor.runtime.agentic.loop import LabelProtocol, _protocol_violation
from deeptutor.runtime.agentic.labeled_step import LabeledStepResult

_ALLOWED = ("FINISH", "TOOL", "THINK", "PAUSE")


def test_classify_label_accepts_common_wrapper_variants() -> None:
    assert classify_label("`FINISH`\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert classify_label("```FINISH```\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert classify_label("FINISH：Done", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_classify_label_accepts_body_adjacent_to_wrapped_label() -> None:
    assert classify_label("``FINISH``你好！", allowed_labels=_ALLOWED) == (
        "FINISH",
        "你好！",
    )
    assert classify_label("``THINK``I need one private step.", allowed_labels=_ALLOWED) == (
        "THINK",
        "I need one private step.",
    )


def test_classify_label_waits_for_unambiguous_bare_label_until_final() -> None:
    assert classify_label("FINISH", allowed_labels=_ALLOWED) is None
    assert classify_label("FINISH", allowed_labels=_ALLOWED, final=True) == (
        "FINISH",
        "",
    )
    assert classify_label("FINISHED", allowed_labels=_ALLOWED, final=True) is None


def test_classify_label_does_not_accept_split_wrapped_label_too_early() -> None:
    assert classify_label("``FINISH`", allowed_labels=_ALLOWED) is None
    assert classify_label("``FINISH```", allowed_labels=_ALLOWED) is None
    assert classify_label("``FINISH``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_streaming_probe_rejects_unclosed_and_overwide_fences() -> None:
    """Mid-stream routing cannot commit to a fence that may still close."""
    assert classify_label("```SECTION\n## 4. Findings", allowed_labels=("SECTION",)) is None
    assert classify_label("``FINISH```\nDone", allowed_labels=_ALLOWED) is None
    assert classify_label("```FINISH``\nDone", allowed_labels=_ALLOWED) is None


def test_finished_reply_recovery_accepts_unclosed_and_overwide_fences() -> None:
    assert recover_finished_label(
        "```SECTION\n## 4. Findings\n\nBody.",
        allowed_labels=("SECTION",),
    ) == ("SECTION", "## 4. Findings\n\nBody.")
    assert recover_finished_label("``FINISH```\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert recover_finished_label("```FINISH``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert recover_finished_label("``FINISH`", allowed_labels=_ALLOWED) == (
        "FINISH",
        "",
    )


def test_finished_reply_recovery_requires_an_exact_allowed_label() -> None:
    assert recover_finished_label("```SECTIONAL\nnope", allowed_labels=("SECTION",)) is None
    assert recover_finished_label("FINISHED", allowed_labels=_ALLOWED) is None
    # Heading-number recovery is report-specific and needs the section the
    # step was asked to write; the generic helper must not invent a label.
    assert recover_finished_label("## 4. Findings\n\nBody.", allowed_labels=("SECTION",)) is None


def test_find_inline_labels_detects_tolerated_label_variants() -> None:
    assert find_inline_labels(
        "draft\n`THINK`\nmore\n```TOOL```\nFINISH：again",
        allowed_labels=_ALLOWED,
    ) == ["THINK", "TOOL", "FINISH"]


def test_find_inline_labels_ignores_prose_mentions() -> None:
    assert (
        find_inline_labels(
            "I should use ``TOOL`` next, then finish with ``FINISH``.",
            allowed_labels=_ALLOWED,
        )
        == []
    )


def test_strip_label_probe_prefix_strips_only_the_leading_invisible_run() -> None:
    # Whitespace and zero-width characters interleave in the prefix, so the
    # strip loop needs several passes before it stabilises.
    prefix = " ​ ﻿\t​"
    assert strip_label_probe_prefix(prefix + "FINISH body") == "FINISH body"
    # Invisible characters inside the buffer are content, not decoration.
    assert strip_label_probe_prefix("FIN​ISH") == "FIN​ISH"
    assert strip_label_probe_prefix("keep") == "keep"


def test_classify_label_is_case_sensitive_for_wrapped_and_bare_forms() -> None:
    assert classify_label("``finish``\nDone", allowed_labels=_ALLOWED) is None
    assert classify_label("finish\nDone", allowed_labels=_ALLOWED, final=True) is None
    assert recover_finished_label("``finish\nDone", allowed_labels=_ALLOWED) is None
    assert find_inline_labels("finish\nDone", allowed_labels=_ALLOWED) == []


def test_classify_label_tolerates_none_buffer_and_empty_label_set() -> None:
    assert classify_label(None, allowed_labels=_ALLOWED) is None  # type: ignore[arg-type]
    assert classify_label("FINISH\nDone", allowed_labels=()) is None
    assert classify_label("FINISH\nDone", allowed_labels=(), final=True) is None
    # An empty vocabulary can never flag an inline repeat either.
    assert find_inline_labels("``FINISH``", allowed_labels=()) == []


def test_classify_label_disambiguates_prefix_shadowed_labels() -> None:
    shadowed = ("FIN", "FINISH")
    assert classify_label("FIN: go", allowed_labels=shadowed) == ("FIN", "go")
    assert classify_label("``FIN`` go", allowed_labels=shadowed) == ("FIN", "go")
    # The shorter allowed label must not swallow the longer one's reply.
    assert classify_label("FINISH\nbody", allowed_labels=shadowed) == ("FINISH", "body")
    assert classify_label("FINISHED", allowed_labels=shadowed, final=True) is None


def test_classify_label_escapes_regex_metacharacters_in_labels() -> None:
    labels = ("FINISH", "A+B")
    assert classify_label("``A+B``? no", allowed_labels=labels) == ("A+B", "? no")
    # "AxB" must not match the pattern even though ``x`` reads like "any char".
    assert classify_label("``AxB``\nno", allowed_labels=labels) is None
    assert recover_finished_label("``A+B\nx", allowed_labels=("A+B",)) == ("A+B", "x")


def test_classify_label_tolerates_whitespace_inside_wrapper() -> None:
    assert classify_label("`` FINISH ``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert classify_label("``` TOOL ```\ngo", allowed_labels=_ALLOWED) == ("TOOL", "go")
    assert classify_label("`` FINISH ``你好", allowed_labels=_ALLOWED) == (
        "FINISH",
        "你好",
    )


def test_classify_label_keeps_next_line_code_fence_in_body() -> None:
    # The over-closed-wrapper guard only fires on a backtick *immediately*
    # after the label; a fence that starts on the next line is body text.
    assert classify_label("``FINISH``\n```python\nprint(1)", allowed_labels=_ALLOWED) == (
        "FINISH",
        "```python\nprint(1)",
    )


def test_classify_label_commits_only_to_the_first_leading_label() -> None:
    # A repeated label on a later line is routed as body text; the inline
    # label scan (not the probe) is what flags it for protocol repair.
    assert classify_label("``TOOL``\nFINISH", allowed_labels=_ALLOWED) == (
        "TOOL",
        "FINISH",
    )


def test_find_inline_labels_line_start_boundaries() -> None:
    # A label on the final line (no trailing newline) is still detected.
    assert find_inline_labels("step done\nFINISH", allowed_labels=_ALLOWED) == ["FINISH"]
    # Mid-line bare mentions and suffixed words are not action labels.
    assert find_inline_labels("plain FINISH inline\nx", allowed_labels=_ALLOWED) == []
    assert find_inline_labels("FINISHED state\nx", allowed_labels=_ALLOWED) == []


def test_find_inline_labels_preserves_duplicates_in_order() -> None:
    # No dedup contract: callers only branch on truthiness, and each
    # violation site (wrapped line + bare line) is reported separately.
    assert find_inline_labels("``TOOL``\nTOOL again", allowed_labels=_ALLOWED) == [
        "TOOL",
        "TOOL",
    ]


def test_recover_finished_label_accepts_unclosed_double_tick_fence() -> None:
    assert recover_finished_label("``FINISH\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_recover_finished_label_accepts_mismatched_and_overwide_closers() -> None:
    assert recover_finished_label("`FINISH``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    assert recover_finished_label("``FINISH````\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )


def test_recover_finished_label_rejects_run_on_label_tail() -> None:
    assert recover_finished_label("``FINISHextra", allowed_labels=_ALLOWED) is None
    assert recover_finished_label("FINISHextra\nx", allowed_labels=_ALLOWED) is None


def test_recover_finished_label_fast_path_and_prefixed_unclosed_fence() -> None:
    # A well-formed wrap resolves through the plain final-pass classifier.
    assert recover_finished_label("``FINISH``\nDone", allowed_labels=_ALLOWED) == (
        "FINISH",
        "Done",
    )
    # Leading whitespace/invisible noise does not hide an unclosed fence.
    assert recover_finished_label(
        " ​```SECTION\nbody",
        allowed_labels=("SECTION",),
    ) == ("SECTION", "body")


def _protocol(tool_label: str | None = "TOOL") -> LabelProtocol:
    return LabelProtocol(
        allowed=_ALLOWED,
        terminal=frozenset({"FINISH"}),
        intermediate=frozenset({"TOOL", "THINK", "PAUSE"}),
        final=frozenset({"FINISH", "PAUSE"}),
        tool_label=tool_label,
    )


def test_protocol_violation_reports_missing_label_and_compliance() -> None:
    step = LabeledStepResult(label=LABEL_UNKNOWN, text="the model just talked")
    assert _protocol_violation(step, _protocol()) == "missing_label"
    assert (
        _protocol_violation(
            LabeledStepResult(label="FINISH", text="All done."), _protocol()
        )
        is None
    )
    assert (
        _protocol_violation(
            LabeledStepResult(label="TOOL", text="", tool_calls=[{"name": "search"}]),
            _protocol(),
        )
        is None
    )


def test_protocol_violation_reports_inline_label_repeats() -> None:
    step = LabeledStepResult(label="FINISH", text="first answer\n`TOOL`\nmore")
    assert _protocol_violation(step, _protocol()) == "multiple_labels"
    # A mention that never starts a line is prose, not a second label.
    clean = LabeledStepResult(label="FINISH", text="use TOOL later, then relax")
    assert _protocol_violation(clean, _protocol()) is None


def test_protocol_violation_reports_tool_label_mismatches() -> None:
    assert (
        _protocol_violation(
            LabeledStepResult(label="TOOL", text=""), _protocol()
        )
        == "tool_without_calls"
    )
    assert (
        _protocol_violation(
            LabeledStepResult(label="FINISH", text="ok", tool_calls=[{"name": "x"}]),
            _protocol(),
        )
        == "finish_with_tools"
    )
    # Non-canonical vocabularies get their own ``{label}_with_tools`` key.
    assert (
        _protocol_violation(
            LabeledStepResult(label="PAUSE", text="hm", tool_calls=[{"name": "x"}]),
            _protocol(),
        )
        == "pause_with_tools"
    )
    # Protocols without a tool label never report tool mismatches.
    step = LabeledStepResult(label="FINISH", text="ok", tool_calls=[{"name": "x"}])
    assert _protocol_violation(step, _protocol(tool_label=None)) is None
