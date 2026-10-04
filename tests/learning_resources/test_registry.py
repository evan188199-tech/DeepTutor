"""Tests for the learning-resource provider registry (#961 slice 1)."""

from __future__ import annotations

import pytest

from deeptutor.learning_resources.builtin import BuiltinDictionaryProvider
from deeptutor.learning_resources.contracts import (
    LearningResourceProvider,
    LookupRequest,
    LookupResult,
    ProviderError,
    ProviderManifest,
    SourceAttribution,
)
from deeptutor.learning_resources.lifecycle import (
    InvalidProviderStateTransition,
    ProviderState,
    ProviderStateStore,
)
from deeptutor.learning_resources.registry import LearningResourceRegistry


def _manifest(**overrides):
    data = {
        "name": "stub-provider",
        "type": "dictionary",
        "version": "1.0.0",
        "languages": ["en"],
        "offline": True,
        "permissions": [],
    }
    data.update(overrides)
    return ProviderManifest.model_validate(data)


def _result(provider: str, *, term: str = "knowledge", found: bool = True) -> LookupResult:
    return LookupResult(
        term=term,
        language="en",
        definitions=[],
        phonetics=[],
        examples=[],
        translations=[],
        source=SourceAttribution(provider=provider),
        found=found,
    )


class _StubProvider(LearningResourceProvider):
    def __init__(self, manifest, *, result=None, error=None):
        self._manifest = manifest
        self._result = result
        self._error = error
        self.lookup_calls = 0

    @property
    def manifest(self):
        return self._manifest

    def lookup(self, request: LookupRequest) -> LookupResult:
        self.lookup_calls += 1
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return _result(self._manifest.name, term=request.term)


class TestRegistration:
    def test_register_starts_installed_and_is_not_queryable(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        status = registry.get_status("builtin-dictionary")
        assert status.state is ProviderState.INSTALLED
        assert registry.lookup("knowledge") == []

    def test_register_duplicate_name_is_rejected(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        with pytest.raises(ValueError):
            registry.register(BuiltinDictionaryProvider())

    def test_register_rejects_non_provider_objects(self):
        registry = LearningResourceRegistry()
        with pytest.raises(TypeError):
            registry.register(object())

    def test_register_rejects_invalid_manifest(self):
        class _BrokenManifestProvider(LearningResourceProvider):
            @property
            def manifest(self):
                return {"name": "broken", "type": "not-a-type"}

            def lookup(self, request):
                raise AssertionError("never called")

        from deeptutor.learning_resources.contracts import InvalidProviderManifest

        registry = LearningResourceRegistry()
        with pytest.raises(InvalidProviderManifest):
            registry.register(_BrokenManifestProvider())

    def test_register_unknown_provider_status_is_none(self):
        registry = LearningResourceRegistry()
        assert registry.get_status("missing") is None


class TestEnableDisable:
    def test_enable_and_disable_roundtrip(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")
        assert registry.get_status("builtin-dictionary").state is ProviderState.ENABLED
        registry.disable("builtin-dictionary")
        assert registry.get_status("builtin-dictionary").state is ProviderState.DISABLED
        registry.enable("builtin-dictionary")
        assert registry.get_status("builtin-dictionary").state is ProviderState.ENABLED

    def test_disabled_provider_is_not_queried(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")
        registry.disable("builtin-dictionary")
        assert registry.lookup("knowledge") == []
        status = registry.get_status("builtin-dictionary")
        assert status.state is ProviderState.DISABLED

    def test_enable_unknown_provider_raises_key_error(self):
        registry = LearningResourceRegistry()
        with pytest.raises(KeyError):
            registry.enable("missing")

    def test_disabling_preserves_persisted_state(self, tmp_path):
        store = ProviderStateStore(tmp_path)
        registry = LearningResourceRegistry(state_store=store)
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")
        registry.disable("builtin-dictionary")

        revived = LearningResourceRegistry(state_store=ProviderStateStore(tmp_path))
        revived.register(BuiltinDictionaryProvider())
        assert revived.get_status("builtin-dictionary").state is ProviderState.DISABLED
        assert revived.lookup("knowledge") == []


class TestLookup:
    def test_builtin_dictionary_returns_structured_result(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")

        results = registry.lookup(LookupRequest(term="knowledge", target_language="zh"))
        assert len(results) == 1
        result = results[0]
        assert result.found is True
        assert result.term == "knowledge"
        assert result.source.provider == "builtin-dictionary"
        assert result.definitions
        assert result.phonetics
        assert result.examples
        assert any(t.language == "zh" for t in result.translations)

    def test_lookup_accepts_plain_term_string(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")
        assert registry.lookup("knowledge")

    def test_miss_returns_found_false_without_error_state(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.enable("builtin-dictionary")

        results = registry.lookup("zzzz-definitely-not-a-word")
        assert len(results) == 1
        assert results[0].found is False
        assert registry.get_status("builtin-dictionary").state is ProviderState.ENABLED

    def test_language_routing_skips_unmatched_providers(self):
        registry = LearningResourceRegistry()
        registry.register(_StubProvider(_manifest(languages=["en"])))
        registry.enable("stub-provider")
        assert registry.lookup(LookupRequest(term="知识", source_language="zh")) == []

    def test_wildcard_language_provider_answers_any_request(self):
        registry = LearningResourceRegistry()
        registry.register(_StubProvider(_manifest(languages=["*"])))
        registry.enable("stub-provider")
        assert registry.lookup(LookupRequest(term="savoir", source_language="fr"))

    def test_named_provider_filter(self):
        registry = LearningResourceRegistry()
        registry.register(_StubProvider(_manifest(name="stub-a")))
        registry.register(_StubProvider(_manifest(name="stub-b")))
        registry.enable("stub-a")
        registry.enable("stub-b")
        results = registry.lookup("knowledge", provider="stub-b")
        assert [r.source.provider for r in results] == ["stub-b"]

    def test_named_provider_not_enabled_returns_nothing(self):
        registry = LearningResourceRegistry()
        registry.register(_StubProvider(_manifest(name="stub-a")))
        assert registry.lookup("knowledge", provider="stub-a") == []


class TestFailureDegradation:
    def test_provider_error_marks_error_state_and_degrades(self):
        registry = LearningResourceRegistry()
        broken = _StubProvider(
            _manifest(name="broken-provider"),
            error=ProviderError("connection failed", reason="network"),
        )
        healthy = _StubProvider(_manifest(name="healthy-provider"))
        registry.register(broken)
        registry.register(healthy)
        registry.enable("broken-provider")
        registry.enable("healthy-provider")

        results = registry.lookup("knowledge")
        assert [r.source.provider for r in results] == ["healthy-provider"]

        status = registry.get_status("broken-provider")
        assert status.state is ProviderState.ERROR
        assert "connection failed" in (status.last_error or "")

    def test_unexpected_exception_also_degrades_to_error(self):
        registry = LearningResourceRegistry()
        broken = _StubProvider(_manifest(name="crashy"), error=RuntimeError("boom"))
        healthy = _StubProvider(_manifest(name="healthy-provider"))
        registry.register(broken)
        registry.register(healthy)
        registry.enable("crashy")
        registry.enable("healthy-provider")

        assert [r.source.provider for r in registry.lookup("knowledge")] == ["healthy-provider"]
        assert registry.get_status("crashy").state is ProviderState.ERROR

    def test_error_provider_can_be_re_enabled_after_fix(self):
        registry = LearningResourceRegistry()
        broken = _StubProvider(_manifest(name="broken-provider"), error=ProviderError("down"))
        registry.register(broken)
        registry.enable("broken-provider")
        registry.lookup("knowledge")
        assert registry.get_status("broken-provider").state is ProviderState.ERROR

        registry.enable("broken-provider")
        assert registry.get_status("broken-provider").state is ProviderState.ENABLED

    def test_mark_error_on_disabled_provider_is_invalid(self):
        registry = LearningResourceRegistry()
        registry.register(_StubProvider(_manifest(name="stub-provider")))
        registry.enable("stub-provider")
        registry.disable("stub-provider")
        with pytest.raises(InvalidProviderStateTransition):
            registry.mark_error("stub-provider", "late failure")


class TestStatusListing:
    def test_status_lists_all_providers_with_state(self):
        registry = LearningResourceRegistry()
        registry.register(BuiltinDictionaryProvider())
        registry.register(_StubProvider(_manifest(name="stub-provider")))
        registry.enable("stub-provider")

        listing = {s.manifest.name: s.state for s in registry.status()}
        assert listing == {
            "builtin-dictionary": ProviderState.INSTALLED,
            "stub-provider": ProviderState.ENABLED,
        }
