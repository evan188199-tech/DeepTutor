"""Unit tests for ``deeptutor.tools.vision.block_parser``.

Focus: layout block splitting — rule hits, boundary adhesion, malformed
headers, ordering stability, and validator propagation. The GGB validator
dependency is faked so these tests exercise only the parser logic.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.tools.vision import block_parser
from deeptutor.tools.vision.block_parser import (
    BlockType,
    StreamingBlockParser,
    parse_ggb_blocks,
)


def _passthrough_validator(script: str) -> tuple[str, list[str], list[str]]:
    return script, [], []


def _fixing_validator(script: str) -> tuple[str, list[str], list[str]]:
    # Deterministic "fix": append a marker plus one warning per call.
    return script + "\n//FIXED", [f"fixed {len(script)} chars"], []


@pytest.fixture(autouse=True)
def _fake_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the validator so tests never depend on GGB syntax rules."""
    monkeypatch.setattr(block_parser, "validate_ggbscript", _passthrough_validator)


class TestParseGGBBlocks:
    @pytest.mark.parametrize(
        ("text", "expected_segments", "expected_blocks"),
        [
            pytest.param("", [], [], id="empty_input"),
            pytest.param("   \n\t  \n", [], [], id="whitespace_only_input"),
            pytest.param(
                "just prose, no fences", ["just prose, no fences"], [], id="plain_text_no_block"
            ),
            pytest.param(
                "before ```ggbscript[p1;Title]\nA=(1,2)\n```\nafter",
                ["before", "after"],
                [("p1", "Title", BlockType.GGBSCRIPT, "A=(1,2)")],
                id="single_block_with_title",
            ),
            pytest.param(
                "```GEOGEBRA[pg]\nA=(1,2)\n```",
                [],
                [("pg", "Untitled", BlockType.GEOGEBRA, "A=(1,2)")],
                id="geogebra_keyword_case_insensitive",
            ),
            pytest.param(
                "```ggbscript[p1]\nA=(1,2)\n```",
                [],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "A=(1,2)")],
                id="missing_title_defaults_untitled",
            ),
            pytest.param(
                "```ggbscript[p1;]\nA=(1,2)\n```",
                [],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "A=(1,2)")],
                id="empty_title_after_semicolon_defaults_untitled",
            ),
            pytest.param(
                "```ggbscript[p1;quadratic intro]\nf(x)=x^2\n```",
                [],
                [("p1", "quadratic intro", BlockType.GGBSCRIPT, "f(x)=x^2")],
                id="title_with_spaces_preserved",
            ),
            pytest.param(
                "```ggbscript[]\nA=(1,2)\n```",
                ["```ggbscript[]\nA=(1,2)\n```"],
                [],
                id="malformed_empty_page_id_is_not_a_block",
            ),
            pytest.param(
                "```ggbscript[p1;p2]\nA=(1,2)\n```",
                [],
                [("p1", "p2", BlockType.GGBSCRIPT, "A=(1,2)")],
                id="semicolon_splits_page_id_and_title",
            ),
            pytest.param(
                "```ggbscript[ p1 ; t ]\nA=(1,2)\n```",
                ["```ggbscript[ p1 ; t ]\nA=(1,2)\n```"],
                [],
                id="malformed_spaces_in_header_not_matched",
            ),
            pytest.param(
                "```ggbscript[;t]\nA=(1,2)\n```",
                ["```ggbscript[;t]\nA=(1,2)\n```"],
                [],
                id="malformed_semicolon_only_page_id_not_matched",
            ),
            pytest.param(
                "```ggbscript[p1]\nA=(1,2)",
                [],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "A=(1,2)")],
                id="unclosed_block_consumes_rest_of_text",
            ),
            pytest.param(
                "```ggbscript[p1] trailing words",
                [],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "trailing words")],
                id="header_without_newline_content_on_same_line",
            ),
            pytest.param(
                "```ggbscript[p1]\nA=(1,2)\n```python\nprint()\n```\ntail",
                ["tail"],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "A=(1,2)\n```python\nprint()")],
                id="fence_needs_newline_python_fence_glued_to_content",
            ),
            pytest.param(
                "a ```ggbscript[p1]\nA=(1,2)\n```\nb ```ggbscript[p2]\nB=(3,4)\n```\nc",
                ["a", "b", "c"],
                [
                    ("p1", "Untitled", BlockType.GGBSCRIPT, "A=(1,2)"),
                    ("p2", "Untitled", BlockType.GGBSCRIPT, "B=(3,4)"),
                ],
                id="inline_text_split_around_two_blocks",
            ),
            pytest.param(
                "```ggbscript[p1]\nA\n```\n```ggbscript[p2]\nB\n```",
                [],
                [
                    ("p1", "Untitled", BlockType.GGBSCRIPT, "A"),
                    ("p2", "Untitled", BlockType.GGBSCRIPT, "B"),
                ],
                id="adjacent_blocks_no_text_between",
            ),
            pytest.param(
                "```ggbscript[p1]\nA\n``` ```ggbscript[p2]\nB\n```",
                [],
                [("p1", "Untitled", BlockType.GGBSCRIPT, "A\n``` ```ggbscript[p2]\nB")],
                id="same_line_fence_after_close_does_not_terminate_block",
            ),
        ],
    )
    def test_table(
        self,
        text: str,
        expected_segments: list[str],
        expected_blocks: list[tuple[str, str, BlockType, str]],
    ) -> None:
        result = parse_ggb_blocks(text)

        assert result.text_segments == expected_segments
        assert [
            (b.page_id, b.title, b.block_type, b.content) for b in result.ggb_blocks
        ] == expected_blocks

    def test_multiple_blocks_keep_document_order(self) -> None:
        text = (
            "intro\n"
            "```ggbscript[c]\nC1\n```\n"
            "mid\n"
            "```ggbscript[a]\nA1\n```\n"
            "```ggbscript[b]\nB1\n```\n"
            "outro"
        )

        result = parse_ggb_blocks(text)

        assert [b.page_id for b in result.ggb_blocks] == ["c", "a", "b"]
        assert result.text_segments == ["intro", "mid", "outro"]

    def test_duplicate_page_ids_keep_insertion_order(self) -> None:
        text = "```ggbscript[same]\nfirst\n```\n```ggbscript[same]\nsecond\n```"

        result = parse_ggb_blocks(text)

        assert [b.content for b in result.ggb_blocks] == ["first", "second"]

    def test_parse_is_deterministic(self) -> None:
        text = "x ```ggbscript[p1;T]\nA=(1,2)\n``` y ```geogebra[p2]\nB\n```"

        first = parse_ggb_blocks(text)
        second = parse_ggb_blocks(text)

        assert first == second

    def test_validator_fixes_are_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(block_parser, "validate_ggbscript", _fixing_validator)

        result = parse_ggb_blocks("```ggbscript[p1]\nA=(1,2)\n```")

        (block,) = result.ggb_blocks
        assert block.content == "A=(1,2)\n//FIXED"
        assert block.original_content == "A=(1,2)"
        assert block.validation_warnings == ["fixed 7 chars"]

    def test_validator_passthrough_leaves_original_empty(self) -> None:
        result = parse_ggb_blocks("```ggbscript[p1]\nA=(1,2)\n```")

        (block,) = result.ggb_blocks
        assert block.content == "A=(1,2)"
        assert block.original_content == ""
        assert block.validation_warnings == []


class TestStreamingBlockParser:
    @pytest.mark.parametrize(
        ("chunks", "expected_events"),
        [
            pytest.param(
                ["plain text only"],
                [{"type": "text", "content": "plain text only"}],
                id="text_only_single_feed_flush",
            ),
            pytest.param(
                ["```ggbscript[p1;T]\nA=(1,2)\n```", " tail"],
                [
                    {
                        "type": "ggb_block",
                        "page_id": "p1",
                        "title": "T",
                        "content": "A=(1,2)",
                        "original_content": "",
                        "validation_warnings": [],
                    },
                    {"type": "text", "content": " tail"},
                ],
                id="single_feed_complete_block",
            ),
            pytest.param(
                ["intro ```ggb", "script[p1;T]\nA=(1,2)\n``", "`\ntail "],
                [
                    {"type": "text", "content": "intro "},
                    {
                        "type": "ggb_block",
                        "page_id": "p1",
                        "title": "T",
                        "content": "A=(1,2)",
                        "original_content": "",
                        "validation_warnings": [],
                    },
                    {"type": "text", "content": "tail "},
                ],
                id="chunked_feed_split_mid_header_and_fence",
            ),
            pytest.param(
                ["```ggbscript[p9]\nA=(1,2)"],
                [
                    {
                        "type": "ggb_block",
                        "page_id": "p9",
                        "title": "Untitled",
                        "content": "A=(1,2)",
                        "original_content": "",
                        "validation_warnings": [],
                    }
                ],
                id="incomplete_block_flushed_as_block",
            ),
            pytest.param(
                ["abc ```"],
                [{"type": "text", "content": "abc "}, {"type": "text", "content": "```"}],
                id="lone_fence_held_then_flushed_as_text",
            ),
            pytest.param(
                ["```ggbscript[p1]\nA\n```", "```ggbscript[p2]\nB\n```", "end"],
                [
                    {
                        "type": "ggb_block",
                        "page_id": "p1",
                        "title": "Untitled",
                        "content": "A",
                        "original_content": "",
                        "validation_warnings": [],
                    },
                    {
                        "type": "ggb_block",
                        "page_id": "p2",
                        "title": "Untitled",
                        "content": "B",
                        "original_content": "",
                        "validation_warnings": [],
                    },
                    {"type": "text", "content": "end"},
                ],
                id="two_blocks_across_feeds",
            ),
        ],
    )
    def test_table(
        self,
        chunks: list[str],
        expected_events: list[dict[str, Any]],
    ) -> None:
        parser = StreamingBlockParser()

        events: list[dict[str, Any]] = []
        for chunk in chunks:
            events.extend(parser.feed(chunk))
        events.extend(parser.flush())

        assert events == expected_events

    def test_flush_is_idempotent_after_reset(self) -> None:
        parser = StreamingBlockParser()
        parser.feed("```ggbscript[p1]\nA=(1,2)")
        parser.flush()

        assert parser.flush() == []
        assert parser.feed("more text") == [{"type": "text", "content": "more text"}]

    def test_block_events_match_batch_parse_across_line_feeds(self) -> None:
        text = (
            "intro\n"
            "```ggbscript[p1;Alpha]\n"
            "A=(1,2)\n"
            "```\n"
            "between\n"
            "```geogebra[p2]\n"
            "B=(3,4)\n"
            "```\n"
            "outro"
        )
        batch = parse_ggb_blocks(text)
        parser = StreamingBlockParser()

        events: list[dict[str, Any]] = []
        for line in text.splitlines(keepends=True):
            events.extend(parser.feed(line))
        events.extend(parser.flush())

        blocks = [e for e in events if e["type"] == "ggb_block"]
        assert [(e["page_id"], e["title"], e["content"]) for e in blocks] == [
            (b.page_id, b.title, b.content) for b in batch.ggb_blocks
        ]
        assert [b.page_id for b in batch.ggb_blocks] == ["p1", "p2"]

    def test_long_unmatched_header_tail_emitted_as_text(self) -> None:
        parser = StreamingBlockParser()

        events = parser.feed("x```ggbscript-" + "a" * 60)

        assert events == [{"type": "text", "content": "x```ggbscript-" + "a" * 60}]

    def test_validator_fixes_are_recorded_streaming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(block_parser, "validate_ggbscript", _fixing_validator)
        parser = StreamingBlockParser()

        events = parser.feed("```ggbscript[p1]\nA=(1,2)\n```") + parser.flush()

        (block_event,) = [e for e in events if e["type"] == "ggb_block"]
        assert block_event["content"] == "A=(1,2)\n//FIXED"
        assert block_event["original_content"] == "A=(1,2)"
        assert block_event["validation_warnings"] == ["fixed 7 chars"]
