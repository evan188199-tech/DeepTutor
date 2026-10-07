"""Core response-language contract: the single source both entry points validate against.

``deeptutor/core/response_languages.py`` owns the supported-language tuple and the
explicit per-conversation override validator; ``deeptutor/response_languages.py``
re-exports it for the Settings/API layers. These tests pin the validator's
priority ladder (``None`` sentinel → verbatim passthrough → hard reject) and the
identity between the public shim and the core module, so the two layers cannot
drift into accepting different languages.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.core import response_languages as core_module
from deeptutor.core.response_languages import (
    SUPPORTED_RESPONSE_LANGUAGES,
    validate_reply_language_override,
)
from deeptutor.core.turn_request import TurnRequest
import deeptutor.response_languages as public_shim

#: Values an explicit session selector must never accept. Region and locale
#: variants ("zh-CN", "en_US") are resolved by the settings layer only — the
#: selector demands an exact supported code — and blank/cased/fancy labels are
#: junk that must fail loudly instead of silently falling back.
INVALID_OVERRIDE_VALUES = [
    "",
    "xx",
    "French",
    "zh-CN",
    "en_US",
    " EN ",
    "EN",
    "__default__",
]


def test_supported_languages_are_well_formed() -> None:
    assert isinstance(SUPPORTED_RESPONSE_LANGUAGES, tuple)
    assert SUPPORTED_RESPONSE_LANGUAGES
    for code in SUPPORTED_RESPONSE_LANGUAGES:
        assert isinstance(code, str)
        assert code
        assert code == code.strip().lower()


def test_supported_languages_have_no_duplicates() -> None:
    assert len(set(SUPPORTED_RESPONSE_LANGUAGES)) == len(SUPPORTED_RESPONSE_LANGUAGES)


@pytest.mark.parametrize("code", SUPPORTED_RESPONSE_LANGUAGES)
def test_valid_override_passes_through_verbatim(code: str) -> None:
    # Identity, not normalization: "zh-tw" must survive exactly.
    assert validate_reply_language_override(code) is code


def test_none_sentinel_means_follow_account_default() -> None:
    assert validate_reply_language_override(None) is None


@pytest.mark.parametrize("value", INVALID_OVERRIDE_VALUES)
def test_invalid_override_raises_instead_of_falling_back(value: str) -> None:
    with pytest.raises(ValueError, match="Unsupported reply language"):
        validate_reply_language_override(value)


def test_public_shim_reexports_the_core_contract() -> None:
    assert public_shim.SUPPORTED_RESPONSE_LANGUAGES is core_module.SUPPORTED_RESPONSE_LANGUAGES
    assert (
        public_shim.validate_reply_language_override is core_module.validate_reply_language_override
    )
    assert set(public_shim.__all__) == {
        "SUPPORTED_RESPONSE_LANGUAGES",
        "validate_reply_language_override",
    }


@pytest.mark.parametrize("code", SUPPORTED_RESPONSE_LANGUAGES)
def test_turn_request_accepts_every_supported_override(code: str) -> None:
    assert TurnRequest(content="hi", reply_language_override=code).reply_language_override == code


@pytest.mark.parametrize("value", INVALID_OVERRIDE_VALUES)
def test_turn_request_rejects_invalid_override(value: str) -> None:
    with pytest.raises(ValidationError):
        TurnRequest(content="hi", reply_language_override=value)


def test_turn_request_keeps_none_sentinel_after_validation() -> None:
    request = TurnRequest(content="hi", reply_language_override=None)
    assert request.reply_language_override is None
    payload = request.to_payload()
    assert payload["reply_language_override"] is None
