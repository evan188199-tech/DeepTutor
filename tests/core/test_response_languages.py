from __future__ import annotations

import pytest

from deeptutor.core.response_languages import (
    SUPPORTED_RESPONSE_LANGUAGES,
    validate_reply_language_override,
)


def test_supported_languages_are_unique_nonempty_lowercase_codes() -> None:
    assert SUPPORTED_RESPONSE_LANGUAGES
    assert len(SUPPORTED_RESPONSE_LANGUAGES) == len(set(SUPPORTED_RESPONSE_LANGUAGES))
    for code in SUPPORTED_RESPONSE_LANGUAGES:
        assert isinstance(code, str)
        assert code
        assert code == code.lower()


def test_none_follows_the_account_default() -> None:
    assert validate_reply_language_override(None) is None


@pytest.mark.parametrize("code", SUPPORTED_RESPONSE_LANGUAGES)
def test_each_supported_language_passes_through(code: str) -> None:
    assert validate_reply_language_override(code) == code


@pytest.mark.parametrize(
    "code",
    ["xx", "EN", "ZH", "zh-TW", "zh_cn", "", "中文", "english"],
)
def test_unsupported_language_is_rejected(code: str) -> None:
    with pytest.raises(ValueError, match="Unsupported reply language"):
        validate_reply_language_override(code)
