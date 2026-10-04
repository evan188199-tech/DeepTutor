"""Tests for the learning-resource provider contract models (#961 slice 1)."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.learning_resources.contracts import (
    Definition,
    Example,
    LookupRequest,
    LookupResult,
    Phonetic,
    ProviderManifest,
    ProviderPermission,
    ProviderType,
    SourceAttribution,
    Translation,
)


def _manifest_data(**overrides):
    data = {
        "name": "example-dictionary",
        "type": "dictionary",
        "version": "1.0.0",
        "languages": ["en", "zh"],
        "offline": True,
        "permissions": [],
    }
    data.update(overrides)
    return data


def test_manifest_accepts_issue_example():
    manifest = ProviderManifest.model_validate(_manifest_data())
    assert manifest.name == "example-dictionary"
    assert manifest.type is ProviderType.DICTIONARY
    assert manifest.version == "1.0.0"
    assert manifest.languages == ["en", "zh"]
    assert manifest.offline is True
    assert manifest.permissions == []


def test_manifest_defaults_description_and_is_typed():
    manifest = ProviderManifest.model_validate(_manifest_data())
    assert manifest.description == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "Bad Name"},
        {"name": "-leading-dash"},
        {"version": "1.0"},
        {"version": "latest"},
        {"languages": []},
        {"languages": ["EN"]},
        {"languages": ["en", ""]},
        {"type": "glossary"},
        {"type": "external_bridge"},
        {"permissions": ["root"]},
    ],
)
def test_manifest_rejects_invalid_fields(overrides):
    with pytest.raises(ValidationError):
        ProviderManifest.model_validate(_manifest_data(**overrides))


def test_manifest_online_provider_must_declare_network_permission():
    with pytest.raises(ValidationError):
        ProviderManifest.model_validate(_manifest_data(offline=False, permissions=[]))

    manifest = ProviderManifest.model_validate(
        _manifest_data(offline=False, permissions=["network"])
    )
    assert ProviderPermission.NETWORK in manifest.permissions


def test_manifest_accepts_wildcard_language():
    manifest = ProviderManifest.model_validate(_manifest_data(languages=["*"]))
    assert manifest.languages == ["*"]


def test_lookup_request_requires_term_and_strips_it():
    with pytest.raises(ValidationError):
        LookupRequest(term="   ")
    request = LookupRequest(term="  Knowledge  ")
    assert request.term == "Knowledge"
    assert request.source_language is None
    assert request.target_language is None


def test_lookup_result_roundtrips_with_full_structure():
    result = LookupResult(
        term="knowledge",
        language="en",
        definitions=[Definition(text="information understood", part_of_speech="noun")],
        phonetics=[Phonetic(value="/ˈnɒlɪdʒ/", notation="IPA")],
        examples=[Example(text="Knowledge is power.", translation="知识就是力量。")],
        translations=[Translation(text="知识", language="zh")],
        source=SourceAttribution(
            provider="example-dictionary", entry="knowledge", license="CC-BY-4.0"
        ),
    )
    dumped = result.model_dump(mode="json")
    restored = LookupResult.model_validate(dumped)
    assert restored == result
    assert restored.found is True
    assert restored.source.provider == "example-dictionary"
    assert restored.translations[0].language == "zh"


def test_lookup_result_miss_has_empty_body():
    result = LookupResult(
        term="zzzz-not-a-word",
        language="en",
        definitions=[],
        phonetics=[],
        examples=[],
        translations=[],
        source=SourceAttribution(provider="example-dictionary"),
        found=False,
    )
    assert result.found is False
    assert result.definitions == []
