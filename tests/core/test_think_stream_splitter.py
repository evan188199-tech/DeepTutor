"""Tests for :mod:`deeptutor.runtime.agentic.think_stream`.

Covers the three behaviors the coverage scan flagged as untested
(``runtime.agentic.think_stream``, 93 LOC, ``n_cover=0``):

1. Aggregation — reasoning wrapped in ``<think>``/``<thinking>`` tags is
   reassembled correctly even when tags arrive split across stream chunks,
   in any case, and with attributes.
2. Boundaries — empty chunks, very long untagged chunks, tags at the very
   start/end of a chunk, adjacent tags, and non-tag look-alikes
   (``<thinkless>``) must all round-trip without losing or corrupting text.
3. Cancel/cleanup semantics — when the downstream consumer cancels the
   stream, ``flush()`` must release the partial tag held back for
   tag-boundary detection (nothing silently dropped) and stay idempotent.
"""

from __future__ import annotations

import pytest

from deeptutor.runtime.agentic.think_stream import (
    InlineThinkFilter,
    split_inline_think,
)


def _drain(filt: InlineThinkFilter, chunks: list[str]) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for chunk in chunks:
        segments.extend(filt.feed(chunk))
    segments.extend(filt.flush())
    return segments


def _text(segments: list[tuple[str, str]]) -> str:
    return "".join(text for _kind, text in segments)


def _normalized(segments: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Merge adjacent same-kind segments (feed emits per chunk, unmerged)."""
    merged: list[tuple[str, str]] = []
    for kind, text in segments:
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return merged


class TestAggregation:
    """Chunked streams reassemble into content/thinking segments."""

    def test_open_and_close_tags_split_across_chunks(self) -> None:
        chunks = ["<thi", "nk>reasoning", "</th", "ink>answer"]
        segments = _drain(InlineThinkFilter(), chunks)
        assert segments == [("thinking", "reasoning"), ("content", "answer")]

    def test_case_insensitive_and_thinking_variant(self) -> None:
        assert split_inline_think("A<THINK>r</think>B") == [
            ("content", "A"),
            ("thinking", "r"),
            ("content", "B"),
        ]
        assert split_inline_think("A<Thinking>r</THINKING>B") == [
            ("content", "A"),
            ("thinking", "r"),
            ("content", "B"),
        ]

    def test_open_tag_with_attributes(self) -> None:
        segments = split_inline_think('A<think type="private">r</think>B')
        assert segments == [("content", "A"), ("thinking", "r"), ("content", "B")]

    def test_multiple_blocks_with_surrounding_text(self) -> None:
        segments = split_inline_think("A<think>x</think>B<thinking>y</thinking>C")
        assert segments == [
            ("content", "A"),
            ("thinking", "x"),
            ("content", "B"),
            ("thinking", "y"),
            ("content", "C"),
        ]

    def test_incremental_matches_one_shot(self) -> None:
        text = "pre<think>mid thought</think>post<thinking>more</thinking>tail"
        by_char = _drain(InlineThinkFilter(), list(text))
        one_shot = split_inline_think(text)
        assert _normalized(by_char) == one_shot
        # Tags are stripped from the routed segments.
        assert _text(by_char) == "premid thoughtpostmoretail"

    def test_reassembly_preserves_text_exactly(self) -> None:
        text = "before<think>a < b and i > j</think>after"
        chunks = [text[i : i + 7] for i in range(0, len(text), 7)]
        segments = _drain(InlineThinkFilter(), chunks)
        # Chunks split mid-thought ('a < b...') emit separately; after
        # merging adjacent same-kind segments the text is reassembled.
        assert _normalized(segments) == [
            ("content", "before"),
            ("thinking", "a < b and i > j"),
            ("content", "after"),
        ]


class TestBoundaries:
    """Degenerate chunk shapes must not lose or corrupt text."""

    def test_empty_chunk_is_a_noop(self) -> None:
        filt = InlineThinkFilter()
        assert filt.feed("") == []
        assert filt.feed("hi") == [("content", "hi")]
        assert filt.flush() == []

    def test_empty_string_split(self) -> None:
        assert split_inline_think("") == []

    def test_long_untagged_chunk_emitted_whole(self) -> None:
        chunk = "q" * 5000
        filt = InlineThinkFilter()
        assert filt.feed(chunk) == [("content", chunk)]
        assert filt.flush() == []

    def test_lone_less_than_released_as_content(self) -> None:
        filt = InlineThinkFilter()
        assert filt.feed("a < b") == [("content", "a ")]
        # A later long stretch with no '>' releases the held-back '< b'.
        filler = "x" * 100
        segments = filt.feed(filler)
        assert segments == [("content", "< b" + filler)]
        assert filt.flush() == []

    def test_tag_like_word_without_boundary_is_content(self) -> None:
        # '<thinkless>' has no word boundary after 'think', so it is not an
        # open tag; the completed '>' makes it safe to emit immediately.
        filt = InlineThinkFilter()
        assert filt.feed("<thinkless>visible") == [("content", "<thinkless>visible")]
        assert filt.flush() == []

    def test_adjacent_tags_produce_no_empty_segments(self) -> None:
        assert split_inline_think("x<think></think>y") == [
            ("content", "x"),
            ("content", "y"),
        ]
        assert split_inline_think("<think></think>") == []

    def test_unterminated_block_routes_to_thinking(self) -> None:
        # No closing tag ever arrives: everything after <think> stays on the
        # thinking channel and the buffer drains before flush().
        segments = _drain(InlineThinkFilter(), ["hello<think>secret"])
        assert segments == [("content", "hello"), ("thinking", "secret")]

    def test_no_tags_passthrough_single_segment(self) -> None:
        text = "plain answer without any markers"
        assert split_inline_think(text) == [("content", text)]


class TestCancelCleanup:
    """flush() is the cancel path: held-back text must be released."""

    def test_flush_releases_heldback_partial_tag_with_current_kind(self) -> None:
        filt = InlineThinkFilter()
        assert filt.feed("done<think>hidden</thi") == [
            ("content", "done"),
            ("thinking", "hidden"),
        ]
        assert filt.feed("") == []
        # '</thi' was held back for tag-boundary detection; a cancel must
        # still deliver it (on the thinking channel) instead of dropping it.
        assert filt.flush() == [("thinking", "</thi")]

    def test_flush_is_idempotent(self) -> None:
        filt = InlineThinkFilter()
        assert filt.feed("<thi") == []
        assert filt.flush() == [("content", "<thi")]
        assert filt.flush() == []
        assert filt.flush() == []

    def test_flush_on_empty_filter_is_empty(self) -> None:
        assert InlineThinkFilter().flush() == []

    def test_flush_with_pending_content_prefix(self) -> None:
        filt = InlineThinkFilter()
        assert filt.feed("part") == [("content", "part")]
        assert filt.feed("<think open") == []
        # An open tag cut off before '>' never completes, so the state is
        # still content when the cancel flush releases it.
        assert filt.flush() == [("content", "<think open")]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no markers at all",
        "<think>only thinking",
        "only content</think>",
        "a<think>b</think>c<think>d</think>e",
    ],
)
def test_one_shot_matches_incremental(text: str) -> None:
    assert split_inline_think(text) == _normalized(_drain(InlineThinkFilter(), list(text)))
