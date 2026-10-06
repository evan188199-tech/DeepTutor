from __future__ import annotations

import pytest

from deeptutor.core import response_languages as core_response_languages
import deeptutor.response_languages as public_response_languages


def test_public_module_reexports_the_core_language_contract() -> None:
    assert (
        public_response_languages.SUPPORTED_RESPONSE_LANGUAGES
        is core_response_languages.SUPPORTED_RESPONSE_LANGUAGES
    )
    assert (
        public_response_languages.validate_reply_language_override
        is core_response_languages.validate_reply_language_override
    )


def test_public_module_exports_only_the_documented_names() -> None:
    assert set(public_response_languages.__all__) == {
        "SUPPORTED_RESPONSE_LANGUAGES",
        "validate_reply_language_override",
    }


def test_public_module_validator_behaves_like_the_core_one() -> None:
    assert public_response_languages.validate_reply_language_override("zh") == "zh"
    assert public_response_languages.validate_reply_language_override(None) is None
    with pytest.raises(ValueError):
        public_response_languages.validate_reply_language_override("xx")
