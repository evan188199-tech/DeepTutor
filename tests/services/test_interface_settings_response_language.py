"""Response-language negotiation: priority ladder, fallback branches, caller contract.

The settings layer negotiates what prompt assembly ultimately sends: a stored
``response_language`` wins over defaults, labels and region variants are
normalized onto a supported base code, and anything unrecognised falls back
instead of leaking through. These tests pin that ladder — and that its output
always stays inside ``SUPPORTED_RESPONSE_LANGUAGES``, the same tuple the core
validator and the settings-router API enforce — so prompt assembly can never
emit a language either caller would reject.
"""

from __future__ import annotations

import json
import typing

import pytest

from deeptutor.core.response_languages import (
    SUPPORTED_RESPONSE_LANGUAGES,
    validate_reply_language_override,
)
from deeptutor.services.settings import interface_settings
from deeptutor.services.settings.interface_settings import (
    _normalize_response_language,
    get_response_language,
    resolve_languages,
)

#: The negotiation ladder, most specific first: an alias label, then an exact
#: supported code (any case/spacing/underscore spelling), then a region
#: variant reduced to its supported base, then the fallback chain.
NORMALIZATION_CASES = [
    # Label aliases (case-insensitive, copied from issues or other deployments).
    ("english", "en", "en"),
    ("Simplified Chinese", "en", "zh"),
    ("traditional chinese", "en", "zh-tw"),
    ("Bahasa Melayu", "en", "ms"),
    # Exact supported codes, verbatim spelling.
    ("zh-tw", "en", "zh-tw"),
    # Case / whitespace / underscore spellings of supported codes.
    ("  EN  ", "en", "en"),
    ("ZH-TW", "en", "zh-tw"),
    ("zh_TW", "en", "zh-tw"),
    # Region variants collapse onto their supported base code.
    ("zh-HK", "en", "zh"),
    ("pt-BR", "en", "pt"),
    ("de-AT-DE", "en", "de"),
    # Unrecognised values fall back — and the fallback itself is normalized.
    ("klingon", "fr", "fr"),
    ("klingon", "Chinese", "zh"),
    ("klingon", "klingon", "en"),
    # Missing / blank / non-string inputs all fall back.
    (None, "fr", "fr"),
    ("", "fr", "fr"),
    ("   ", "en", "en"),
    (42, "ja", "ja"),
    (["zh"], "es", "es"),
    (None, None, "en"),
]

#: Junk stored in interface.json must resolve through the fallback chain, and
#: whatever comes out has to be a language the core validator accepts — prompt
#: assembly reads this value and hands it to the model.
_JUNK_INPUTS = ["klingon", "", None, 42, "zh-XX-KLINGON", "  ", {"code": "zh"}]


def test_negotiation_ladder_prefers_exact_then_base_then_fallback() -> None:
    for raw, default, expected in NORMALIZATION_CASES:
        assert _normalize_response_language(raw, default) == expected, (raw, default)


@pytest.mark.parametrize("code", SUPPORTED_RESPONSE_LANGUAGES)
def test_every_supported_language_round_trips_verbatim(code: str) -> None:
    assert _normalize_response_language(code, "en") == code


@pytest.mark.parametrize("raw", _JUNK_INPUTS)
def test_negotiation_output_always_stays_inside_supported_languages(raw) -> None:
    resolved = _normalize_response_language(raw, "en")
    assert resolved in SUPPORTED_RESPONSE_LANGUAGES
    # The settings output and the explicit-override validator agree: whatever
    # prompt assembly negotiated is a language the core layer accepts too.
    assert validate_reply_language_override(resolved) == resolved


def _isolate_settings_file(monkeypatch: pytest.MonkeyPatch, tmp_path, payload) -> None:
    settings_file = tmp_path / "interface.json"
    if payload is not None:
        settings_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(interface_settings, "_interface_settings_file", lambda: settings_file)


@pytest.mark.parametrize("code", SUPPORTED_RESPONSE_LANGUAGES)
def test_stored_response_language_beats_the_caller_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path, code: str
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path, {"response_language": code})
    assert get_response_language(default="fr") == code


def test_legacy_file_without_response_language_inherits_interface_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path, {"theme": "snow", "language": "zh"})
    assert get_response_language() == "zh"


def test_missing_settings_file_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path, None)
    assert get_response_language() == "en"
    # The defaults merge always carries a normalized "en" response language, so
    # it shadows the caller's default argument on the empty-file path too.
    assert get_response_language(default="zh") == "en"


def test_stored_junk_resolves_before_the_caller_default_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # The file layer normalizes an unsupported stored value to the interface
    # language before prompt assembly's own default ever gets consulted.
    _isolate_settings_file(monkeypatch, tmp_path, {"response_language": "klingon"})
    assert get_response_language(default="fr") == "en"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # Legacy split: only "language" on disk → response inherits it.
        ({"language": "zh"}, {"language": "zh", "response_language": "zh"}),
        # An explicit choice beats the inheritance.
        (
            {"language": "zh", "response_language": "fr"},
            {"language": "zh", "response_language": "fr"},
        ),
        # Interface language missing → en, but an explicit response choice stands.
        ({"response_language": "ja"}, {"language": "en", "response_language": "ja"}),
        # Region variant of the interface language resolves to the same base.
        ({"response_language": "zh-HK"}, {"language": "en", "response_language": "zh"}),
        # Junk / blank / non-string response choices fall back to the interface language.
        (
            {"language": "uk", "response_language": "klingon"},
            {"language": "uk", "response_language": "uk"},
        ),
        (
            {"language": "uk", "response_language": None},
            {"language": "uk", "response_language": "uk"},
        ),
        (
            {"language": "uk", "response_language": ""},
            {"language": "uk", "response_language": "uk"},
        ),
        ({"response_language": 42}, {"language": "en", "response_language": "en"}),
        # Nothing stored → both defaults.
        ({}, {"language": "en", "response_language": "en"}),
    ],
)
def test_resolve_languages_priority(stored: dict, expected: dict) -> None:
    assert resolve_languages(stored) == expected


def test_settings_router_literal_matches_the_core_language_tuple() -> None:
    """The API's accepted response languages must equal the core tuple exactly.

    ``settings.py`` declares its own ``Literal``; if either side changes alone,
    the API would accept or serve a language the negotiated pipeline cannot
    honor. This assert is the drift guard between the two declarations.
    """

    from deeptutor.api.routers import settings as settings_router

    assert typing.get_args(settings_router.ResponseLanguage) == SUPPORTED_RESPONSE_LANGUAGES
