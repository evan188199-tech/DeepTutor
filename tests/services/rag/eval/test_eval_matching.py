"""Tests for gold-passage matching."""

from __future__ import annotations

from collections import Counter

import pytest

from deeptutor.services.rag.eval import (
    MatchPolicy,
    MatchResult,
    RelevanceMatcher,
    normalize_text,
    source_text,
)
from deeptutor.services.rag.eval.matching import (
    DEFAULT_MIN_RATIO,
    DEFAULT_MIN_TOKENS,
    GoldPassage,
    tokenize,
)

GOLD = "Transformers stack self-attention layers to model long-range dependencies in sequences."
GOLD_TOKENS = "alpha beta gamma delta epsilon zeta eta theta"


def test_a_chunk_holding_the_gold_verbatim_matches() -> None:
    chunk = f"Introduction. {GOLD} The section then moves on."
    result = RelevanceMatcher([GOLD]).match(chunk)

    assert result
    assert result.indices == (0,)
    assert result.ratio == 1.0


def test_case_and_whitespace_differences_do_not_break_containment() -> None:
    chunk = (
        "TRANSFORMERS   STACK SELF-ATTENTION LAYERS TO MODEL LONG-RANGE DEPENDENCIES IN SEQUENCES."
    )
    assert RelevanceMatcher([GOLD]).match(chunk).indices == (0,)


def test_a_truncated_citation_inside_a_longer_gold_still_matches() -> None:
    """LlamaIndex and GraphRAG cap ``content`` at 200 characters."""
    truncated = GOLD[:60]
    assert len(tokenize(truncated)) >= 4

    result = RelevanceMatcher([GOLD]).match(truncated)

    assert result.indices == (0,)
    assert result.ratio == 1.0


def test_an_unrelated_chunk_does_not_match() -> None:
    result = RelevanceMatcher([GOLD]).match("Boiling pasta needs salted water and fresh tomatoes.")

    assert not result
    assert result.indices == ()
    assert result.ratio == 0.0


def test_partial_token_overlap_above_the_ratio_matches() -> None:
    chunk = "alpha beta gamma delta zeta eta theta iota"
    result = RelevanceMatcher([GOLD_TOKENS]).match(chunk)

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(0.875)


def test_a_short_overlap_below_the_token_floor_is_rejected() -> None:
    """``alpha beta gamma iota`` covers 3 of 4 own tokens but only 3 shared ones."""
    matcher = RelevanceMatcher([GOLD_TOKENS])

    assert not matcher.match("alpha beta gamma iota")


def test_the_token_floor_can_be_lowered_for_a_smaller_corpus() -> None:
    matcher = RelevanceMatcher([GOLD_TOKENS], MatchPolicy(min_ratio=0.5, min_tokens=3))

    assert matcher.match("gamma delta epsilon").indices == (0,)


def test_the_ratio_floor_can_reject_a_loose_overlap() -> None:
    """Half of a four-token chunk overlapping is below a stricter ratio."""
    strict = RelevanceMatcher([GOLD_TOKENS], MatchPolicy(min_ratio=0.9, min_tokens=2))

    assert not strict.match("alpha beta iota kappa")


def test_each_gold_passage_is_matched_independently() -> None:
    matcher = RelevanceMatcher([GOLD, GOLD_TOKENS])

    result = matcher.match("alpha beta gamma delta zeta eta theta iota")

    assert result.indices == (1,)
    assert matcher.gold_count == 2


def test_one_chunk_can_cover_two_gold_passages() -> None:
    matcher = RelevanceMatcher(["alpha beta gamma", "delta epsilon zeta"])

    assert matcher.match("alpha beta gamma delta epsilon zeta").indices == (0, 1)


def test_cjk_text_is_compared_character_by_character() -> None:
    gold = "注意力机制让模型对每个词加权"
    matcher = RelevanceMatcher([gold])

    assert len(tokenize("注意力机制")) == 5
    assert matcher.match(f"{gold}，这是核心思想。").indices == (0,)


def test_blank_input_never_matches() -> None:
    matcher = RelevanceMatcher([GOLD])

    assert not matcher.match("")
    assert not matcher.match("   ")


def test_a_matcher_without_usable_gold_never_matches() -> None:
    matcher = RelevanceMatcher(["", "   "])

    assert matcher.gold_count == 0
    assert not matcher.match(GOLD)


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Mixed\nCASE   text ") == "mixed case text"


def test_match_policy_rejects_impossible_thresholds() -> None:
    with pytest.raises(ValueError):
        MatchPolicy(min_ratio=0.0)
    with pytest.raises(ValueError):
        MatchPolicy(min_ratio=1.5)
    with pytest.raises(ValueError):
        MatchPolicy(min_tokens=0)


def test_match_result_truthiness_follows_the_matched_indices() -> None:
    assert MatchResult((0,), 1.0)
    assert not MatchResult()


def test_source_text_reads_the_engines_citation_shape() -> None:
    assert source_text({"content": "excerpt"}) == "excerpt"
    assert source_text({"content": "   ", "text": "fallback"}) == "fallback"
    assert source_text({"content": "", "snippet": "snippet wins"}) == "snippet wins"
    assert source_text({"summary": "community report"}) == "community report"
    assert source_text({}) == ""
    assert source_text("not a mapping") == ""
    assert source_text(None) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", []),
        ("!!! ??? ...", []),
        ("Model-7B", ["model", "7b"]),
        ("Alpha, BETA!", ["alpha", "beta"]),
        ("注意力", ["注", "意", "力"]),
        ("alpha 注意力 42", ["alpha", "注", "意", "力", "42"]),
    ],
)
def test_tokenize_handles_degenerate_and_mixed_input(
    value: str | None, expected: list[str]
) -> None:
    assert tokenize(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        (" \n\t  ", ""),
    ],
)
def test_normalize_text_tolerates_missing_and_blank_input(value: str | None, expected: str) -> None:
    assert normalize_text(value) == expected


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"content": "content text", "text": "text text"}, "content text"),
        ({"text": "text text", "excerpt": "excerpt text"}, "text text"),
        ({"content": 42}, ""),
        ({"text": 42, "snippet": "snippet text"}, "snippet text"),
        ({"content": "  ", "text": 7}, ""),
        ({"excerpt": "  padded  "}, "  padded  "),
    ],
)
def test_source_text_key_precedence_and_non_string_values(
    record: dict[str, object], expected: str
) -> None:
    assert source_text(record) == expected


def test_default_policy_thresholds_are_the_module_constants() -> None:
    assert MatchPolicy().min_ratio == DEFAULT_MIN_RATIO
    assert MatchPolicy().min_tokens == DEFAULT_MIN_TOKENS


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_ratio": 0.001},
        {"min_ratio": 0.5},
        {"min_ratio": 1.0},
        {"min_tokens": 1},
        {"min_tokens": 100},
        {"min_ratio": 1.0, "min_tokens": 1},
    ],
)
def test_match_policy_accepts_boundary_thresholds(kwargs: dict[str, float]) -> None:
    policy = MatchPolicy(**kwargs)

    assert 0.0 < policy.min_ratio <= 1.0
    assert policy.min_tokens >= 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_ratio": 0.0},
        {"min_ratio": -0.5},
        {"min_ratio": 1.5},
        {"min_tokens": 0},
        {"min_tokens": -3},
    ],
)
def test_match_policy_rejects_invalid_thresholds(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        MatchPolicy(**kwargs)


def test_exact_ratio_equality_with_min_ratio_is_accepted() -> None:
    matcher = RelevanceMatcher(
        ["alpha beta gamma delta epsilon"], MatchPolicy(min_ratio=0.6, min_tokens=3)
    )

    result = matcher.match("alpha beta gamma iota kappa")

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(0.6)


def test_a_too_short_citation_inside_gold_is_rejected_by_the_token_floor() -> None:
    matcher = RelevanceMatcher([GOLD_TOKENS])

    assert not matcher.match("alpha beta")

    lowered = RelevanceMatcher([GOLD_TOKENS], MatchPolicy(min_ratio=0.5, min_tokens=2))

    result = lowered.match("alpha beta")

    assert result.indices == (0,)
    assert result.ratio == 1.0


def test_repeated_chunk_tokens_are_clamped_by_the_gold_counts() -> None:
    """Three ``alpha`` against five gold ``alpha`` share only three tokens."""
    gold = "alpha alpha alpha alpha alpha"
    matcher = RelevanceMatcher([gold], MatchPolicy(min_ratio=0.5, min_tokens=3))

    result = matcher.match("alpha alpha alpha zeta zeta zeta zeta zeta")

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(0.6)


def test_a_long_chunk_fully_covering_gold_scores_against_the_shorter_side() -> None:
    chunk = "alpha extra beta extra gamma extra delta"
    matcher = RelevanceMatcher(["alpha beta gamma delta"])

    result = matcher.match(chunk)

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(1.0)


def test_partial_overlap_ratio_is_rounded_to_four_decimals() -> None:
    matcher = RelevanceMatcher([GOLD_TOKENS])

    result = matcher.match("alpha beta gamma delta epsilon extra words")

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(0.7143)


def test_identical_gold_passages_are_both_reported_on_a_tie() -> None:
    matcher = RelevanceMatcher([GOLD, GOLD])

    result = matcher.match(f"Prefix. {GOLD}")

    assert result.indices == (0, 1)
    assert result.ratio == 1.0


def test_ratio_reports_the_best_match_across_gold_passages() -> None:
    chunk = "alpha beta gamma delta epsilon extra words. " + GOLD
    matcher = RelevanceMatcher([GOLD_TOKENS, GOLD])

    result = matcher.match(chunk)

    assert result.indices == (0, 1)
    assert result.ratio == 1.0


def test_a_punctuation_only_gold_matches_only_by_containment() -> None:
    matcher = RelevanceMatcher(["!!!"])

    assert matcher.match("Wow !!! Amazing.").indices == (0,)
    assert not matcher.match("No punctuation mark here")


def test_non_string_gold_entries_are_dropped_and_indices_preserved() -> None:
    matcher = RelevanceMatcher([None, GOLD, 42, GOLD_TOKENS, "   "])

    assert matcher.gold_count == 2

    assert matcher.match(f"Intro. {GOLD_TOKENS}").indices == (3,)


def test_match_tolerates_a_none_chunk() -> None:
    matcher = RelevanceMatcher([GOLD])

    result = matcher.match(None)

    assert not result
    assert result.indices == ()
    assert result.ratio == 0.0


def test_gold_passage_precomputes_normalized_and_token_data() -> None:
    passage = GoldPassage.from_text(2, "  Hello   WORLD 注意力 ")

    assert passage.index == 2
    assert passage.normalized == "hello world 注意力"
    assert passage.token_count == 5
    assert passage.tokens == Counter({"hello": 1, "world": 1, "注": 1, "意": 1, "力": 1})
