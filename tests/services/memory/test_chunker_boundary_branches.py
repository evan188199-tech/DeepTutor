"""Boundary-branch supplements for the character-based chunker.

Complements ``tests/services/memory/test_chunker.py`` by pinning the
clamp guards, the hard-cap non-boundary cut, CJK/quoted sentence
boundaries, and the ``ChunkSpan`` value contract.
"""

from __future__ import annotations

import dataclasses

import pytest

from deeptutor.services.memory.consolidator.chunker import (
    Boundary,
    ChunkSpan,
    chunk_with_boundary,
)


def _para_text(paras: int, para_len: int = 60) -> str:
    return "\n\n".join("p" * para_len for _ in range(paras))


def test_budget_below_one_clamps_to_one() -> None:
    text = _para_text(6)
    kwargs = dict(
        overlap_ratio=0.0,
        min_chunk_chars=50,
        max_chunk_chars=10_000,
        boundary="paragraph",
    )
    for bad_budget in (0, -3):
        assert chunk_with_boundary(text, budget=bad_budget, **kwargs) == (
            chunk_with_boundary(text, budget=1, **kwargs)
        )


def test_target_clamped_to_min_short_circuits_single_chunk() -> None:
    text = "x" * 50
    chunks = chunk_with_boundary(
        text,
        budget=2,
        overlap_ratio=0.1,
        min_chunk_chars=50,
        max_chunk_chars=1000,
    )
    assert len(chunks) == 1
    assert (chunks[0].index, chunks[0].start, chunks[0].end) == (0, 0, 50)
    assert chunks[0].text == text


def test_target_clamped_to_max_yields_multiple_chunks() -> None:
    text = _para_text(40, para_len=100)
    chunks = chunk_with_boundary(
        text,
        budget=1,
        overlap_ratio=0.0,
        min_chunk_chars=10,
        max_chunk_chars=300,
    )
    assert len(chunks) > 1
    assert all(c.end - c.start <= 300 for c in chunks)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)


def test_negative_overlap_ratio_clamps_to_zero_no_overlap() -> None:
    text = _para_text(8, para_len=80)
    chunks = chunk_with_boundary(
        text,
        budget=3,
        overlap_ratio=-0.5,
        min_chunk_chars=100,
        max_chunk_chars=500,
    )
    assert len(chunks) >= 2
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start == prev.end


def test_oversized_overlap_ratio_never_stalls_or_repeats() -> None:
    text = _para_text(12, para_len=100)
    chunks = chunk_with_boundary(
        text,
        budget=4,
        overlap_ratio=5.0,
        min_chunk_chars=100,
        max_chunk_chars=400,
    )
    assert chunks
    starts = [c.start for c in chunks]
    assert starts == sorted(starts)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start >= prev.start + 1
    assert chunks[-1].end == len(text)


def test_degenerate_input_without_boundaries_is_cut_at_hard_cap() -> None:
    text = "a" * 20_000
    max_chars = 1000
    chunks = chunk_with_boundary(
        text,
        budget=10,
        overlap_ratio=0.0,
        min_chunk_chars=100,
        max_chunk_chars=max_chars,
    )
    assert len(chunks) == 20
    for chunk in chunks:
        assert chunk.end - chunk.start == max_chars
    assert sum(c.end - c.start for c in chunks) == len(text)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_boundary_beyond_hard_cap_accepts_non_boundary_cut() -> None:
    text = "b" * 900 + "\n\n" + "c" * 900
    chunks = chunk_with_boundary(
        text,
        budget=2,
        overlap_ratio=0.0,
        min_chunk_chars=100,
        max_chunk_chars=500,
    )
    assert len(chunks) > 1
    assert all(c.end - c.start <= 500 for c in chunks)
    assert chunks[-1].end == len(text)


def test_paragraph_regex_spans_whitespace_between_blank_lines() -> None:
    text = "A" * 80 + "\n \t\n" + "B" * 80 + "\n\n" + "C" * 80
    chunks = chunk_with_boundary(
        text,
        budget=3,
        overlap_ratio=0.0,
        min_chunk_chars=10,
        max_chunk_chars=200,
    )
    assert len(chunks) >= 2
    for chunk in chunks[:-1]:
        assert chunk.text.endswith("\n")
        assert chunk.text.startswith(("A", "B", "C"))
    assert chunks[-1].end == len(text)


@pytest.mark.parametrize("closer", ['"', ")", "」", "』", "»"])
def test_sentence_boundary_includes_trailing_closer(closer: str) -> None:
    sentence = "这是一个测试句子。" + closer
    text = " ".join(sentence for _ in range(30))
    chunks = chunk_with_boundary(
        text,
        budget=4,
        overlap_ratio=0.0,
        min_chunk_chars=20,
        max_chunk_chars=200,
        boundary="sentence",
    )
    assert len(chunks) >= 2
    for chunk in chunks[:-1]:
        stripped = chunk.text.rstrip()
        assert stripped[-1] in '.!?。！？")»」』'
    assert chunks[-1].end == len(text)


def test_cjk_and_ascii_sentence_boundaries_mix_cleanly() -> None:
    parts = ["Alpha beta gamma.", "中文句子一。", "Watch out!", "疑问？"] * 10
    text = " ".join(parts)
    chunks = chunk_with_boundary(
        text,
        budget=5,
        overlap_ratio=0.1,
        min_chunk_chars=40,
        max_chunk_chars=200,
        boundary="sentence",
    )
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for chunk in chunks[:-1]:
        assert chunk.text.rstrip()[-1] in ".!?。！？"


def test_last_chunk_covers_tail_when_target_end_passes_input_end() -> None:
    text = _para_text(5, para_len=90)
    chunks = chunk_with_boundary(
        text,
        budget=3,
        overlap_ratio=0.2,
        min_chunk_chars=100,
        max_chunk_chars=400,
    )
    assert chunks[-1].end == len(text)
    assert text[chunks[-1].start : chunks[-1].end] == chunks[-1].text


def test_chunk_span_is_frozen_value_type() -> None:
    span = ChunkSpan(index=0, start=0, end=3, text="abc")
    assert span == ChunkSpan(index=0, start=0, end=3, text="abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.start = 5


def test_chunk_indices_are_sequential_from_zero() -> None:
    text = _para_text(15, para_len=100)
    chunks = chunk_with_boundary(
        text,
        budget=4,
        overlap_ratio=0.1,
        min_chunk_chars=100,
        max_chunk_chars=300,
    )
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_boundary_literal_exports_are_stable() -> None:
    assert set(Boundary.__args__) == {"paragraph", "sentence"}
