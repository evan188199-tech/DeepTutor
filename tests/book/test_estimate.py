"""Generation estimates: chapter_basis input normalisation, scaling, defaults.

``chapter_basis`` derives what one chapter costs to build from the Section
Architect's own templates, so these tests pin the arithmetic (depth scaling,
prose vs. support block timing, word-sum normalisation) and the free-overview
override rather than the template contents themselves.
"""

from __future__ import annotations

import pytest

from deeptutor.book import estimate
from deeptutor.book.agents.page_planner import _TEMPLATES_V2
from deeptutor.book.estimate import chapter_basis
from deeptutor.book.models import BlockType, ContentType

#: Mirrors the estimator's prose classification, pinned here so a silent
#: change to which block types count as prose has to be reviewed.
_PROSE_TYPES = frozenset({BlockType.SECTION, BlockType.TEXT})
_SECONDS_PER_PROSE_BLOCK = 45.0
_SECONDS_PER_SUPPORT_BLOCK = 15.0

#: (depth, expected multiplier) — None and "" both fall through to "standard".
_DEPTH_CASES = [
    (None, 1.0),
    ("standard", 1.0),
    ("brief", 0.5),
    ("deep", 1.6),
    ("totally-unknown-depth", 1.0),  # tolerant fallback branch in depth_scale
    ("", 1.0),
]

_TEMPLATE_CONTENT_TYPES = sorted(t.value for t in _TEMPLATES_V2)


def _raw_target_words(content_type: ContentType) -> float:
    """Independent re-sum of the template's numeric target_words."""
    return float(
        sum(
            params["target_words"]
            for _, params in _TEMPLATES_V2[content_type]
            if isinstance(params.get("target_words"), (int, float))
        )
    )


def _raw_seconds(content_type: ContentType) -> float:
    """Independent re-computation of the per-block time budget."""
    seconds = 0.0
    for block_type, _ in _TEMPLATES_V2[content_type]:
        if block_type in _PROSE_TYPES:
            seconds += _SECONDS_PER_PROSE_BLOCK
        else:
            seconds += _SECONDS_PER_SUPPORT_BLOCK
    return seconds


# ── Normal: default depth and content-type coverage ─────────────────────


def test_no_depth_defaults_to_standard() -> None:
    assert chapter_basis() == chapter_basis("standard")
    assert chapter_basis(None) == chapter_basis("standard")


def test_every_content_type_has_a_basis_entry() -> None:
    basis = chapter_basis("standard")

    assert sorted(basis) == sorted(t.value for t in ContentType)
    for content_type in _TEMPLATE_CONTENT_TYPES:
        entry = basis[content_type]
        assert entry["blocks"] == float(len(_TEMPLATES_V2[content_type])) > 0
        assert entry["words"] > 0
        assert entry["seconds"] > 0


def test_theory_basis_is_exact_at_standard_depth() -> None:
    # theory template: 3 prose (1200 + 1600 + 800 words) + 5 support blocks.
    basis = chapter_basis("standard")

    assert basis["theory"] == {"blocks": 8.0, "words": 3600.0, "seconds": 210.0}


# ── Normal: depth scaling ────────────────────────────────────────────────


@pytest.mark.parametrize("depth,scale", _DEPTH_CASES)
def test_words_follow_depth_scale_and_time_does_not(depth: str | None, scale: float) -> None:
    basis = chapter_basis(depth)

    for content_type in _TEMPLATE_CONTENT_TYPES:
        entry = basis[content_type]
        assert entry["words"] == round(_raw_target_words(content_type) * scale)
        assert entry["seconds"] == round(_raw_seconds(content_type))
        assert entry["blocks"] == float(len(_TEMPLATES_V2[content_type]))


def test_blocks_and_seconds_are_depth_invariant() -> None:
    bases = [chapter_basis(depth) for depth in (None, "brief", "deep", "nonsense")]

    for content_type in _TEMPLATE_CONTENT_TYPES:
        shapes = {(b[content_type]["blocks"], b[content_type]["seconds"]) for b in bases}
        assert len(shapes) == 1


# ── Extreme: unknown depth and free overview ─────────────────────────────


def test_unknown_depth_matches_standard_exactly() -> None:
    assert chapter_basis("nonsense-depth") == chapter_basis("standard")


def test_overview_is_free_at_every_depth() -> None:
    free = {"blocks": 3.0, "words": 0.0, "seconds": 0.0}

    assert ContentType.OVERVIEW not in _TEMPLATES_V2
    for depth in (None, "brief", "deep", "totally-unknown-depth", ""):
        assert chapter_basis(depth)[ContentType.OVERVIEW.value] == free


# ── Input normalisation: non-numeric and missing target_words ────────────


def test_non_numeric_and_missing_targets_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    templates = {
        ContentType.THEORY: [
            (BlockType.TEXT, {"target_words": 1000}),  # prose, numeric
            (BlockType.SECTION, {"target_words": 250.25}),  # prose, float
            (BlockType.QUIZ, {"target_words": "500"}),  # string → ignored
            (BlockType.CALLOUT, {}),  # no target → ignored
        ],
        ContentType.OVERVIEW: [(BlockType.TEXT, {"target_words": 999})],
    }
    monkeypatch.setattr(estimate, "_TEMPLATES_V2", templates)

    basis = chapter_basis("standard")

    assert basis["theory"] == {
        "blocks": 4.0,
        "words": round(1000.0 + 250.25),
        "seconds": 45.0 + 45.0 + 15.0 + 15.0,
    }
    # The overview override wins even when a patched template claims words.
    assert basis["overview"] == {"blocks": 3.0, "words": 0.0, "seconds": 0.0}
