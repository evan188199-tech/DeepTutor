"""Focused pure-logic tests for deeptutor.reading.vocabulary internals."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from deeptutor.reading.extensions import ReadingContext
from deeptutor.reading.vocabulary import (
    VocabularyExtension,
    _normalise,
    _term_comes_from_selection,
    _vocabulary,
)

# --- _normalise ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Verified", "verified"),
        ("  verified   phrase ", "verified phrase"),
        ("Word\twith\nnewlines", "word with newlines"),
        ("MIXED Case WORDS", "mixed case words"),
    ],
)
def test_normalise_casefolds_and_collapses_whitespace(raw, expected):
    assert _normalise(raw) == expected


# --- _term_comes_from_selection -----------------------------------------------


@pytest.mark.parametrize(
    ("term", "selection", "expected"),
    [
        ("phrase", "a verified phrase here", True),
        ("phrase", "all the phrases here", False),
        ("verified phrase", "the VERIFIED PHRASE stands", True),
        ("verified  phrase", "the verified phrase stands", True),
        ("end", "reach the end.", True),
        ("start", "Start of the passage", True),
        ("well-known", "a well-known idea", True),
        ("learner's", "the learner's goal", True),
        ("sentence 1999", "this is sentence 1999 in order", True),
        ("missing", "a verified phrase here", False),
        ("phrase here gone", "a verified phrase here", False),
    ],
)
def test_ascii_terms_match_on_word_boundaries(term, selection, expected):
    assert _term_comes_from_selection(term, selection) is expected


@pytest.mark.parametrize(
    ("term", "selection", "expected"),
    [
        ("量子", "量子力学很有趣", True),
        ("力学", "量子力学很有趣", True),
        ("词组", "量子力学很有趣", False),
        ("量子 力学", "量子力学很有趣", False),
    ],
)
def test_non_ascii_terms_fall_back_to_substring_matching(term, selection, expected):
    assert _term_comes_from_selection(term, selection) is expected


# --- _vocabulary validation and degradation -----------------------------------


def test_vocabulary_accepts_grounded_terms_and_preserves_raw_text():
    selection = "the learner's verified phrase stands"
    vocabulary = _vocabulary(
        {"terms": [{"term": "  Verified phrase  ", "meaning": "Supported by the passage.", "usage": "Used as the main claim."}]},
        selection,
    )

    assert [term.model_dump() for term in vocabulary.terms] == [
        {
            "term": "Verified phrase",
            "meaning": "Supported by the passage.",
            "usage": "Used as the main claim.",
        }
    ]


@pytest.mark.parametrize("data", [None, [], "terms", {}])
def test_vocabulary_rejects_non_dict_or_empty_payloads(data):
    with pytest.raises(ValueError, match="invalid JSON"):
        _vocabulary(data, "a verified phrase")


@pytest.mark.parametrize(
    "payload",
    [
        {"other": 1},
        {"terms": None},
        {"terms": []},
        {"terms": [{"term": "a", "meaning": "Supported by passage.", "usage": "Used as a claim."}]},
        {
            "terms": [
                {
                    "term": "verified phrase",
                    "meaning": "short",
                    "usage": "Used as the main claim here.",
                }
            ]
        },
        {"terms": [{"term": "verified phrase"}]},
    ],
)
def test_vocabulary_rejects_invalid_shapes(payload):
    with pytest.raises(ValueError, match="invalid shape"):
        _vocabulary(payload, "a verified phrase")


def test_vocabulary_rejects_more_than_five_terms():
    selection = "word one two three four five six"
    payload = {
        "terms": [
            {"term": "word", "meaning": "Supported by the passage.", "usage": "Used as a claim."}
            for _ in range(6)
        ]
    }

    with pytest.raises(ValueError, match="invalid shape"):
        _vocabulary(payload, selection)


def test_vocabulary_rejects_terms_unique_only_after_normalisation():
    from deeptutor.reading.vocabulary import _Vocabulary

    term = {
        "term": "verified phrase",
        "meaning": "Supported by the passage.",
        "usage": "Used as the main claim.",
    }
    duplicate = {
        "term": "VERIFIED   PHRASE",
        "meaning": "Supported by the passage.",
        "usage": "Used as the main claim.",
    }

    with pytest.raises(ValidationError, match="must be unique"):
        _Vocabulary.model_validate({"terms": [term, duplicate]})

    with pytest.raises(ValueError, match="invalid shape"):
        _vocabulary({"terms": [term, duplicate]}, "the verified phrase stands")


def test_vocabulary_rejects_terms_absent_from_the_selection():
    term = {
        "term": "outside term",
        "meaning": "Supported by the passage.",
        "usage": "Used as the main claim.",
    }

    with pytest.raises(ValueError, match="must come from the selection"):
        _vocabulary({"terms": [term]}, "a verified phrase")


# --- VocabularyExtension branches ---------------------------------------------


def _context(selection: str, locale: str = "en") -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=1,
        locale=locale,
        selection=selection,
        visible_text=f"Before context {selection} after context",
    )


@pytest.mark.asyncio
async def test_unsupported_action_fails_before_an_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("unsupported action must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    with pytest.raises(ValueError, match="Unsupported vocabulary action"):
        await VocabularyExtension().run_action("translate", _context("verified phrase"))


@pytest.mark.asyncio
async def test_whitespace_only_selection_fails_before_an_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("blank selection must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    with pytest.raises(ValueError, match="requires selected text"):
        await VocabularyExtension().run_action("explain", _context("   \n\t "))


@pytest.mark.asyncio
async def test_chinese_locale_routes_chinese_prompts_and_reader_text(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "terms": [
                    {
                        "term": "量子力学",
                        "meaning": "选文用它描述微观世界的物理规律。",
                        "usage": "选文将它作为整段论述的核心概念。",
                    }
                ]
            }
        )

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    result = await VocabularyExtension().run_action(
        "explain",
        _context("量子力学改变了现代物理", locale="zh"),
    )

    assert result.type == "card"
    assert result.title == "词汇帮助"
    assert result.message == "释义基于所选段落。"
    assert "只返回 JSON" in calls[0]["system_prompt"]
    assert result.payload["terms"][0]["term"] == "量子力学"


@pytest.mark.asyncio
async def test_english_locale_routes_the_english_system_prompt(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "terms": [
                    {
                        "term": "verified phrase",
                        "meaning": "Supported by the selected passage.",
                        "usage": "Used as the passage's main claim.",
                    }
                ]
            }
        )

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    await VocabularyExtension().run_action("explain", _context("verified phrase"))

    assert "Return only JSON" in calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_locale_falls_back_to_english_for_unknown_locales(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "terms": [
                    {
                        "term": "verified phrase",
                        "meaning": "Supported by the selected passage.",
                        "usage": "Used as the passage's main claim.",
                    }
                ]
            }
        )

    monkeypatch.setattr("deeptutor.reading.vocabulary.complete", complete)
    await VocabularyExtension().run_action("explain", _context("verified phrase", locale="fr"))

    assert "Return only JSON" in calls[0]["system_prompt"]
