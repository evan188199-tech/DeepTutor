"""Cross-chunk sharding and malformed input for the protocol-label probe.

The streaming probe runs once per chunk over a growing buffer, so a label
rarely arrives whole: `` ``FIN `` `` + ``ISH`` `` must not commit early, and
must commit exactly when the closing chunk completes the wrapper. These
tests replay the buffer growth chunk by chunk, plus the degenerate buffers
(invisible prefixes, empty input, CRLF tails) the probe is expected to
tolerate.
"""

from __future__ import annotations

from deeptutor.runtime.agentic.labels import (
    LABEL_PROBE_MAX_CHARS,
    LABEL_UNKNOWN,
    classify_label,
    find_inline_labels,
    recover_finished_label,
    strip_label_probe_prefix,
)

_ALLOWED = ("FINISH", "TOOL", "THINK", "PAUSE")


def test_wrapped_label_split_across_chunks_commits_only_once_complete() -> None:
    chunks = ["``", "FIN", "ISH``", " then act"]
    buffer = ""
    seen: list[tuple[str, str] | None] = []
    for chunk in chunks:
        buffer += chunk
        seen.append(classify_label(buffer, allowed_labels=_ALLOWED))
    # A partial wrapper never commits; the closed wrapper with an empty tail
    # may commit at once because body text may follow without a separator.
    assert seen[:2] == [None, None]
    assert seen[2] == ("FINISH", "")
    assert seen[3] == ("FINISH", "then act")


def test_wrapped_label_with_empty_tail_commits_at_closing_chunk() -> None:
    assert classify_label("``TO", allowed_labels=_ALLOWED) is None
    assert classify_label("``TOOL``", allowed_labels=_ALLOWED) == ("TOOL", "")


def test_bare_label_split_across_chunks_waits_for_separator() -> None:
    buffer = ""
    results: list[tuple[str, str] | None] = []
    for chunk in ["FI", "NIS", "H", "\n"]:
        buffer += chunk
        results.append(classify_label(buffer, allowed_labels=_ALLOWED))
    assert results == [None, None, None, ("FINISH", "")]


def test_label_hidden_behind_invisible_prefix_chunk_is_probed_through() -> None:
    leading = "﻿​‌‍"
    assert strip_label_probe_prefix(leading + "``FINISH``\nok") == "``FINISH``\nok"
    buffer = ""
    results: list[tuple[str, str] | None] = []
    for chunk in [leading, "``FINISH", "``\n", "ok"]:
        buffer += chunk
        results.append(classify_label(buffer, allowed_labels=_ALLOWED))
    assert results[:2] == [None, None]
    assert results[2] == ("FINISH", "")
    assert results[3] == ("FINISH", "ok")


def test_strip_label_probe_prefix_tolerates_degenerate_input() -> None:
    assert strip_label_probe_prefix(None) == ""
    assert strip_label_probe_prefix("") == ""
    assert strip_label_probe_prefix("  \t\n ​ ") == ""
    assert strip_label_probe_prefix("body") == "body"
    assert strip_label_probe_prefix(LABEL_UNKNOWN) == LABEL_UNKNOWN


def test_crlf_and_dash_separators_are_eaten_after_the_label() -> None:
    assert classify_label("THINK\r\nsecret reasoning", allowed_labels=_ALLOWED) == (
        "THINK",
        "secret reasoning",
    )
    assert classify_label("FINISH — all done", allowed_labels=_ALLOWED) == (
        "FINISH",
        "all done",
    )


def test_bare_label_followed_by_cjk_is_not_accepted_even_at_stream_end() -> None:
    assert classify_label("FINISH你好", allowed_labels=_ALLOWED) is None
    assert classify_label("FINISH你好", allowed_labels=_ALLOWED, final=True) is None


def test_probe_gives_up_past_the_probe_window_without_a_match() -> None:
    filler = "x" * (LABEL_PROBE_MAX_CHARS + 8)
    assert classify_label(filler, allowed_labels=_ALLOWED) is None
    assert classify_label(filler, allowed_labels=_ALLOWED, final=True) is None


def test_recover_finished_label_accepts_exact_bare_label_and_keeps_next_line_fence() -> None:
    assert recover_finished_label("FINISH", allowed_labels=_ALLOWED) == ("FINISH", "")
    # The fence on the next line is body text; only the separating newline
    # is eaten, matching the finished-report recovery behaviour.
    recovered = recover_finished_label(
        "``SECTION\n```python\nprint(1)",
        allowed_labels=("SECTION",),
    )
    assert recovered == ("SECTION", "```python\nprint(1)")


def test_find_inline_labels_tolerates_empty_text_and_empty_label_set() -> None:
    assert find_inline_labels("", allowed_labels=_ALLOWED) == []
    assert find_inline_labels("FINISH\nTOOL", allowed_labels=()) == []
    assert find_inline_labels(None, allowed_labels=_ALLOWED) == []  # type: ignore[arg-type]


def test_find_inline_labels_detects_crlf_and_indented_lines_only() -> None:
    text = "intro\r\n  `PAUSE`\r\nFINISH\r\nprose mentions ``THINK`` inline"
    assert find_inline_labels(text, allowed_labels=_ALLOWED) == ["PAUSE", "FINISH"]
