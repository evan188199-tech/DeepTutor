"""Focused DSML stream-parser contract tests.

Complements ``test_dsml_tool_calls.py`` with three branches the live
``DSMLStreamFilter`` and ``extract_dsml_tool_calls`` must survive, using fake
chunk streams only (pure logic, no network):

* segmentation — multi-chunk streams where tags split across arbitrary chunk
  boundaries and nothing may leak before a call completes;
* malformed-tag tolerance — junk tags, the partial-tag length ceiling, and
  lenient/case-insensitive tag matching;
* truncation degradation — a stream cut off mid-call must degrade to
  releasing the buffered text verbatim instead of stalling or losing prose.
"""

from __future__ import annotations

import json

from deeptutor.agents.loop.dsml_tool_calls import (
    _MAX_PARTIAL_TAG_CHARS,
    DSMLStreamFilter,
    extract_dsml_tool_calls,
    has_dsml_tool_calls,
)


def _run(chunks: list[str]) -> tuple[str, list[str]]:
    stream_filter = DSMLStreamFilter()
    partials = [stream_filter.feed(chunk) for chunk in chunks]
    return "".join(partials) + stream_filter.flush(), partials


def _call(name: str, **params: str) -> str:
    inner = "".join(
        f'<｜DSML｜parameter name="{key}" string="true">{value}</｜DSML｜parameter>'
        for key, value in params.items()
    )
    return (
        f'<｜DSML｜tool_calls><｜DSML｜invoke name="{name}">'
        f"{inner}</｜DSML｜invoke></｜DSML｜tool_calls>"
    )


class TestSegmentedStream:
    def test_multiple_calls_across_chunk_boundaries(self) -> None:
        text = "one " + _call("first", q="a") + " two " + _call("second", q="b") + " three"

        assert _run([text])[0] == "one  two  three"

    def test_four_way_split_mid_tag(self) -> None:
        text = "go " + _call("exec", command="ls -la") + " ok"
        quarters = len(text) // 4
        chunks = [text[i * quarters : (i + 1) * quarters] for i in range(3)]
        chunks.append(text[3 * quarters :])

        assert _run(chunks)[0] == "go  ok"

    def test_single_character_chunks_never_leak_call_markup(self) -> None:
        text = "before " + _call("exec", command="echo < b") + " after"
        visible, partials = _run(list(text))

        assert visible == "before  after"
        assert all("DSML" not in piece for piece in partials)

    def test_chunk_split_inside_close_tag_completes_later(self) -> None:
        text = "pre " + _call("exec", command="hi")
        split = text.index("</｜DSML｜tool_calls>") + 4  # mid close tag

        assert _run([text[:split], text[split:]])[0] == "pre "

    def test_nothing_emitted_between_envelope_open_and_close(self) -> None:
        stream_filter = DSMLStreamFilter()
        assert stream_filter.feed('<｜DSML｜tool_calls><｜DSML｜invoke name="a">') == ""
        assert stream_filter.feed("body < more") == ""
        assert stream_filter.feed("</｜DSML｜invoke></｜DSML｜tool_calls>") == ""
        assert stream_filter.flush() == ""

    def test_partial_open_tag_is_held_not_emitted(self) -> None:
        stream_filter = DSMLStreamFilter()
        assert stream_filter.feed("answer <｜DSML｜inv") == "answer "
        assert stream_filter.feed('oke name="x">body') == ""
        assert stream_filter.flush().startswith('<｜DSML｜invoke name="x">body')

    def test_flush_resets_state_for_reuse(self) -> None:
        stream_filter = DSMLStreamFilter()
        assert stream_filter.feed("plain") == "plain"
        assert stream_filter.flush() == ""  # nothing held
        assert stream_filter.feed("more <｜DSML｜invoke") == "more "  # held tag
        assert stream_filter.flush() == "<｜DSML｜invoke"
        assert stream_filter.flush() == ""  # second flush is a no-op
        assert stream_filter.feed("again") == "again"  # fresh state


class TestMalformedTags:
    def test_overlong_unterminated_tag_is_released_not_stalled(self) -> None:
        junk = "<" + "x" * (_MAX_PARTIAL_TAG_CHARS + 128)
        stream_filter = DSMLStreamFilter()

        assert stream_filter.feed(junk) == junk
        assert stream_filter.flush() == ""

    def test_partial_tag_within_ceiling_is_held(self) -> None:
        junk = "<" + "x" * (_MAX_PARTIAL_TAG_CHARS - 1)
        stream_filter = DSMLStreamFilter()

        assert stream_filter.feed(junk) == ""
        assert stream_filter.flush() == junk

    def test_filter_recovers_after_overlong_tag(self) -> None:
        junk = "<" + "y" * (_MAX_PARTIAL_TAG_CHARS + 40)
        stream_filter = DSMLStreamFilter()
        assert stream_filter.feed(junk) == junk

        assert stream_filter.feed(_call("exec", command="go") + " done") == " done"
        assert stream_filter.flush() == ""

    def test_lenient_tag_matching_without_special_token_prefix(self) -> None:
        text = '<invoke name="exec"><parameter name="cmd" string="true">ls</parameter></invoke>'

        calls, cleaned = extract_dsml_tool_calls(text)

        assert [c["name"] for c in calls] == ["exec"]
        assert json.loads(calls[0]["arguments"]) == {"cmd": "ls"}
        assert cleaned == ""

    def test_case_insensitive_and_extra_whitespace_tags(self) -> None:
        text = (
            '<INVOKE NAME="exec" id="7" >'
            '<PARAMETER NAME="cmd" string="True">ls</PARAMETER>'
            "</INVOKE>"
        )

        calls, _ = extract_dsml_tool_calls(text)

        assert [c["name"] for c in calls] == ["exec"]
        assert json.loads(calls[0]["arguments"]) == {"cmd": "ls"}

    def test_single_quoted_string_hint_stays_string(self) -> None:
        text = '<invoke name="w"><parameter name="code" string=\'true\'>[1,2]</parameter></invoke>'

        calls, _ = extract_dsml_tool_calls(text)

        assert json.loads(calls[0]["arguments"])["code"] == "[1,2]"

    def test_empty_invoke_name_yields_no_calls_and_keeps_text(self) -> None:
        text = '<｜DSML｜invoke name="">nothing</｜DSML｜invoke>'

        calls, cleaned = extract_dsml_tool_calls(text)

        assert calls == []
        assert cleaned == text

    def test_unnamed_parameters_are_ignored(self) -> None:
        text = (
            '<invoke name="w">'
            "<parameter>5</parameter>"
            '<parameter name="n" string="true">x</parameter>'
            "</invoke>"
        )

        calls, _ = extract_dsml_tool_calls(text)

        assert json.loads(calls[0]["arguments"]) == {"n": "x"}

    def test_stray_close_envelope_tag_is_dropped(self) -> None:
        assert _run(["a</｜DSML｜tool_calls>b"])[0] == "ab"

    def test_stray_invoke_close_tag_passes_through(self) -> None:
        assert _run(["a</｜DSML｜invoke>b"])[0] == "a</｜DSML｜invoke>b"

    def test_signal_detection_edge_cases(self) -> None:
        assert has_dsml_tool_calls(None) is False
        assert has_dsml_tool_calls("") is False
        assert has_dsml_tool_calls('<dsml｜invoke name="x">') is True
        assert has_dsml_tool_calls('<invoke name="x">') is True


class TestTruncation:
    def test_truncated_mid_parameter_released_verbatim(self) -> None:
        # No complete invoke anywhere → the envelope open tag and the partial
        # parameter are all released verbatim at flush; nothing is lost.
        fragment = '<｜DSML｜tool_calls><｜DSML｜invoke name="exec"><｜DSML｜parameter name="c'

        visible, _ = _run(["before " + fragment])

        assert visible == "before " + fragment

    def test_truncated_after_complete_invoke_suppresses_it_and_releases_rest(self) -> None:
        done = (
            '<｜DSML｜invoke name="a">'
            '<｜DSML｜parameter name="p" string="true">1</｜DSML｜parameter>'
            "</｜DSML｜invoke>"
        )
        partial = '<｜DSML｜invoke name="b'

        visible, _ = _run(["before <｜DSML｜tool_calls>" + done + partial])

        assert visible == "before " + partial
        assert 'invoke name="a"' not in visible

    def test_truncated_mid_close_tag_releases_remainder_at_flush(self) -> None:
        text = "pre " + _call("exec", command="hi")
        stream_filter = DSMLStreamFilter()
        out = stream_filter.feed(text[:-1]) + stream_filter.flush()

        assert out == "pre </｜DSML｜tool_calls"

    def test_extract_returns_original_when_truncated_before_any_close(self) -> None:
        text = (
            "<｜DSML｜tool_calls>"
            '<｜DSML｜invoke name="exec">'
            '<｜DSML｜parameter name="c" string="true">hi'
        )

        assert extract_dsml_tool_calls(text) == ([], text)
