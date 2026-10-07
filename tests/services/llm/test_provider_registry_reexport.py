"""Tests for the ``services.llm.provider_registry`` compatibility re-export."""

from __future__ import annotations

import pytest

import deeptutor.services.llm.provider_registry as llm_registry
import deeptutor.services.provider_registry as canonical


@pytest.mark.parametrize("name", canonical.__all__)
def test_every_public_name_is_reexported_from_the_canonical_module(name: str) -> None:
    assert getattr(llm_registry, name) is getattr(canonical, name), name


def test_registry_objects_are_shared_not_copied() -> None:
    assert llm_registry.PROVIDERS is canonical.PROVIDERS
    assert llm_registry.PROVIDER_ALIASES is canonical.PROVIDER_ALIASES


def test_calls_through_the_reexport_match_canonical_behavior() -> None:
    assert llm_registry.canonical_provider_name("Claude") == "anthropic"
    spec = llm_registry.find_by_name("claude")
    assert spec is canonical.find_by_name("claude")
    assert spec is not None
    assert spec.name == "anthropic"
    assert llm_registry.find_by_model("gpt-5-mini") is canonical.find_by_model("gpt-5-mini")
