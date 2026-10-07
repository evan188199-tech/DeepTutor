"""Tests for the DeepSeek DSML text-format tool-call fallback parser (issue #666)."""

from __future__ import annotations

import json
import re

from deeptutor.agents.loop.dsml_tool_calls import (
    _MAX_PENDING_BLOCK_CHARS,
    DSMLStreamFilter,
    extract_dsml_tool_calls,
    has_dsml_tool_calls,
)

# The exact markup from the issue report — fullwidth ｜ special-token bars.
_ISSUE_PAYLOAD = (
    '<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="exec"> '
    '<｜｜DSML｜｜parameter name="command" string="true">'
    "python -c \"from pptx import Presentation; prs=Presentation(); prs.save('test.pptx')\""
    "</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke> </｜｜DSML｜｜tool_calls>"
)


def test_extracts_issue_payload_into_tool_call() -> None:
    calls, cleaned = extract_dsml_tool_calls(_ISSUE_PAYLOAD)
    assert len(calls) == 1
    assert calls[0]["name"] == "exec"
    args = json.loads(calls[0]["arguments"])
    assert args["command"].startswith("python -c")
    # All markup consumed — nothing left to masquerade as the answer.
    assert cleaned == ""


def test_extracts_mastery_grade_payload_from_issue_672() -> None:
    # Verbatim markup from issue #672 — DeepSeek grading a Mastery Path
    # answer as DSML text instead of a native tool call.
    text = (
        "<｜｜DSML｜｜tool_calls>\n"
        '<｜｜DSML｜｜invoke name="mastery_grade">\n'
        '<｜｜DSML｜｜parameter name="answer" string="true">C</｜｜DSML｜｜parameter>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    calls, cleaned = extract_dsml_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "mastery_grade"
    assert json.loads(calls[0]["arguments"]) == {"answer": "C"}
    assert cleaned == ""


def test_multiple_invokes_and_leading_prose() -> None:
    text = (
        "Let me run two steps.\n"
        '<｜DSML｜invoke name="exec">'
        '<｜DSML｜parameter name="command" string="true">echo one</｜DSML｜parameter>'
        "</｜DSML｜invoke>"
        '<｜DSML｜invoke name="read_skill">'
        '<｜DSML｜parameter name="name" string="true">pptx</｜DSML｜parameter>'
        "</｜DSML｜invoke>"
    )
    calls, cleaned = extract_dsml_tool_calls(text)
    assert [c["name"] for c in calls] == ["exec", "read_skill"]
    assert json.loads(calls[1]["arguments"]) == {"name": "pptx"}
    # Leading prose is preserved; only the markup is stripped.
    assert cleaned == "Let me run two steps."


def test_non_string_parameter_is_json_coerced() -> None:
    text = (
        '<｜DSML｜invoke name="widget">'
        '<｜DSML｜parameter name="count">3</｜DSML｜parameter>'
        '<｜DSML｜parameter name="label" string="true">3</｜DSML｜parameter>'
        "</｜DSML｜invoke>"
    )
    calls, _ = extract_dsml_tool_calls(text)
    args = json.loads(calls[0]["arguments"])
    assert args["count"] == 3  # unmarked scalar parsed as JSON
    assert args["label"] == "3"  # string="true" kept verbatim


def test_string_marked_json_containers_follow_tool_schema() -> None:
    text = (
        '<｜DSML｜invoke name="ask_user">'
        '<｜DSML｜parameter name="questions" string="true">'
        '[{"id":"q1","prompt":"Pick one"}]'
        "</｜DSML｜parameter>"
        '<｜DSML｜parameter name="context" string="true">'
        '{"source":"lesson"}'
        "</｜DSML｜parameter>"
        '<｜DSML｜parameter name="literal" string="true">[not JSON]</｜DSML｜parameter>'
        "</｜DSML｜invoke>"
    )
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "questions": {"type": "array", "items": {"type": "object"}},
                        "context": {"type": "object"},
                        "literal": {"type": "string"},
                    },
                },
            },
        }
    ]

    calls, _ = extract_dsml_tool_calls(text, schemas)
    args = json.loads(calls[0]["arguments"])

    assert args["questions"] == [{"id": "q1", "prompt": "Pick one"}]
    assert args["context"] == {"source": "lesson"}
    assert args["literal"] == "[not JSON]"


def test_string_marked_json_container_stays_string_without_schema() -> None:
    text = (
        '<｜DSML｜invoke name="ask_user">'
        '<｜DSML｜parameter name="questions" string="true">["A", "B"]'
        "</｜DSML｜parameter>"
        "</｜DSML｜invoke>"
    )

    calls, _ = extract_dsml_tool_calls(text)

    assert json.loads(calls[0]["arguments"])["questions"] == '["A", "B"]'


def test_schema_container_type_must_match_parsed_value() -> None:
    text = (
        '<｜DSML｜invoke name="ask_user">'
        '<｜DSML｜parameter name="questions" string="true">{"not":"a list"}'
        "</｜DSML｜parameter>"
        "</｜DSML｜invoke>"
    )
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "parameters": {
                    "type": "object",
                    "properties": {"questions": {"type": "array"}},
                },
            },
        }
    ]

    calls, _ = extract_dsml_tool_calls(text, schemas)

    assert json.loads(calls[0]["arguments"])["questions"] == '{"not":"a list"}'


def test_plain_text_is_untouched() -> None:
    text = "Here is your answer. No tools needed."
    assert has_dsml_tool_calls(text) is False
    calls, cleaned = extract_dsml_tool_calls(text)
    assert calls == []
    assert cleaned is text


def test_prose_mentioning_tool_calls_is_not_a_false_positive() -> None:
    # Merely discussing the word must not trip detection — only a real
    # ``<...invoke name="`` / ``<...DSML...>`` tag counts.
    text = "You can trigger tool_calls by asking me to run something."
    assert has_dsml_tool_calls(text) is False
    assert extract_dsml_tool_calls(text) == ([], text)


def test_malformed_envelope_without_close_yields_no_calls() -> None:
    # Signal present but no well-formed invoke block → treat as not-a-DSML-round
    # so the caller falls through unchanged rather than losing the text.
    text = '<｜DSML｜invoke name="exec"> unterminated ...'
    calls, cleaned = extract_dsml_tool_calls(text)
    assert calls == []
    assert cleaned == text


class TestDSMLStreamFilter:
    @staticmethod
    def _run(chunks: list[str]) -> str:
        stream_filter = DSMLStreamFilter()
        visible = "".join(stream_filter.feed(chunk) for chunk in chunks)
        return visible + stream_filter.flush()

    def test_preserves_prose_before_and_after_call(self) -> None:
        text = (
            "Great job! "
            '<｜DSML｜tool_calls><｜DSML｜invoke name="ask_user">'
            '<｜DSML｜parameter name="questions" string="true">[]'
            "</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>"
            " Choose what to study next."
        )

        assert self._run([text]) == "Great job!  Choose what to study next."

    def test_handles_every_split_boundary(self) -> None:
        text = (
            "Before "
            '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="exec">'
            '<｜｜DSML｜｜parameter name="command" string="true">echo hi'
            "</｜｜DSML｜｜parameter></｜｜DSML｜｜invoke>"
            "</｜｜DSML｜｜tool_calls> after"
        )

        for split_at in range(len(text) + 1):
            assert self._run([text[:split_at], text[split_at:]]) == "Before  after"

        tiny_chunks = [text[index : index + 3] for index in range(0, len(text), 3)]
        assert self._run(tiny_chunks) == "Before  after"

    def test_incomplete_invoke_is_not_silently_discarded(self) -> None:
        text = '<｜DSML｜invoke name="exec">unterminated'
        assert self._run([text[:8], text[8:]]) == text

    def test_malformed_envelope_is_not_partially_discarded(self) -> None:
        text = "before <｜DSML｜tool_calls>not an invoke after"
        assert self._run([text[:20], text[20:]]) == text

    def test_envelope_without_close_still_cleans_complete_invoke(self) -> None:
        text = 'before <｜DSML｜tool_calls><｜DSML｜invoke name="exec"></｜DSML｜invoke> after'
        assert self._run([text[:20], text[20:]]) == "before  after"

    def test_plain_angle_brackets_are_untouched(self) -> None:
        assert self._run(["1 < 2 and <b>", "bold</b>"]) == "1 < 2 and <b>bold</b>"

    def test_overlong_unclosed_block_streams_verbatim_without_rescanning(self, monkeypatch) -> None:
        # A pending block with no close tag used to be re-scanned in full on
        # every chunk while the buffer grew without bound — quadratic work
        # across the round. Past the pending ceiling the block must come out
        # verbatim, and the pending-close search must stop touching already
        # searched bytes: doubling the stream must not meaningfully grow the
        # number of characters scanned (the quadratic path would grow ~4x).
        from deeptutor.agents.loop import dsml_tool_calls as dsml_module

        original_close_re = dsml_module._INVOKE_CLOSE_TAG_RE
        scanned = 0

        class _CountingPattern:
            def search(self, text: str) -> re.Match[str] | None:
                nonlocal scanned
                scanned += len(text)
                return original_close_re.search(text)

        monkeypatch.setattr(dsml_module, "_INVOKE_CLOSE_TAG_RE", _CountingPattern())

        open_tag = '<｜DSML｜invoke name="exec">'
        chunk_size = 256

        def _run_stream(total_chars: int) -> tuple[str, int]:
            text = open_tag + "a" * (total_chars - len(open_tag))
            stream_filter = DSMLStreamFilter()
            chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
            visible = [stream_filter.feed(chunk) for chunk in chunks]
            return "".join(visible) + stream_filter.flush(), scanned

        small_total = _MAX_PENDING_BLOCK_CHARS * 3
        large_total = _MAX_PENDING_BLOCK_CHARS * 6

        visible_small, _ = _run_stream(small_total)
        assert visible_small == open_tag + "a" * (small_total - len(open_tag))

        scanned_before_large = scanned
        visible_large, _ = _run_stream(large_total)
        assert visible_large == open_tag + "a" * (large_total - len(open_tag))

        scanned_large = scanned - scanned_before_large
        assert scanned_large <= scanned_before_large * 1.5

    def test_parsing_recovers_after_overlong_unclosed_block(self) -> None:
        filler = "b" * (_MAX_PENDING_BLOCK_CHARS + 65536)
        text = (
            '<｜DSML｜invoke name="exec">' + filler + '<｜DSML｜invoke name="exec">'
            '<｜DSML｜parameter name="command" string="true">echo hi'
            "</｜DSML｜parameter></｜DSML｜invoke> tail"
        )
        open_len = len('<｜DSML｜invoke name="exec">')
        first = open_len + _MAX_PENDING_BLOCK_CHARS // 2  # held pending
        # Still pure filler, but past the ceiling: the release path fires.
        second = first + _MAX_PENDING_BLOCK_CHARS // 2 + 2048
        stream_filter = DSMLStreamFilter()
        visible = (
            stream_filter.feed(text[:first])
            + stream_filter.feed(text[first:second])
            + stream_filter.feed(text[second:])
        )
        # The unclosed block is released verbatim once past the ceiling, and
        # the well-formed call that follows is still suppressed.
        assert visible + stream_filter.flush() == (
            '<｜DSML｜invoke name="exec">' + filler + " tail"
        )

    def test_complete_call_larger_than_ceiling_passes_through_verbatim(self) -> None:
        # Past the ceiling a complete-but-huge call is no longer worth
        # buffering for suppression: it streams out as-is. The dispatcher
        # still parses the full round text separately, so the call is not
        # lost — only its live markup suppression is.
        body = "c" * (_MAX_PENDING_BLOCK_CHARS + 200000)
        text = '<｜DSML｜invoke name="exec">' + body + "</｜DSML｜invoke> tail"
        stream_filter = DSMLStreamFilter()
        chunks = [text[i : i + 65536] for i in range(0, len(text), 65536)]
        visible = "".join(stream_filter.feed(chunk) for chunk in chunks)
        assert visible + stream_filter.flush() == text
