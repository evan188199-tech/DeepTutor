"""Contract and boundary tests for AudioOverviewRequestConfig (Top100 #56)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deeptutor.capabilities.audio_overview.capability import AudioOverviewCapability
from deeptutor.capabilities.audio_overview.request_config import AudioOverviewRequestConfig


def test_defaults_match_capability_manifest_config_defaults() -> None:
    config = AudioOverviewRequestConfig()
    assert config.model_dump() == {
        "topic": "",
        "target_minutes": 5,
        "host_voice": None,
        "expert_voice": None,
        "max_context_chunks": 6,
    }
    assert AudioOverviewCapability.manifest.config_defaults == config.model_dump()


def test_explicit_config_preserves_all_fields() -> None:
    config = AudioOverviewRequestConfig(
        topic="Fourier transform",
        target_minutes=10,
        host_voice="alloy",
        expert_voice="nova",
        max_context_chunks=9,
    )
    assert config.topic == "Fourier transform"
    assert config.target_minutes == 10
    assert config.host_voice == "alloy"
    assert config.expert_voice == "nova"
    assert config.max_context_chunks == 9


@pytest.mark.parametrize("value", [1, 5, 15])
def test_target_minutes_accepts_inclusive_bounds(value: int) -> None:
    assert AudioOverviewRequestConfig(target_minutes=value).target_minutes == value


@pytest.mark.parametrize("value", [0, -1, 16])
def test_target_minutes_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AudioOverviewRequestConfig(target_minutes=value)
    assert any(error["loc"] == ("target_minutes",) for error in exc_info.value.errors())


@pytest.mark.parametrize("value", [1, 6, 12])
def test_max_context_chunks_accepts_inclusive_bounds(value: int) -> None:
    assert AudioOverviewRequestConfig(max_context_chunks=value).max_context_chunks == value


@pytest.mark.parametrize("value", [0, -3, 13])
def test_max_context_chunks_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AudioOverviewRequestConfig(max_context_chunks=value)
    assert any(error["loc"] == ("max_context_chunks",) for error in exc_info.value.errors())


def test_topic_accepts_empty_and_max_length_boundary() -> None:
    assert AudioOverviewRequestConfig(topic="").topic == ""
    boundary = "a" * 500
    assert AudioOverviewRequestConfig(topic=boundary).topic == boundary


def test_topic_rejects_over_limit_and_non_string() -> None:
    with pytest.raises(ValidationError) as over_limit:
        AudioOverviewRequestConfig(topic="a" * 501)
    assert any(
        error["loc"] == ("topic",) and error["type"] == "string_too_long"
        for error in over_limit.value.errors()
    )

    with pytest.raises(ValidationError) as not_a_string:
        AudioOverviewRequestConfig(topic=123)
    assert any(error["loc"] == ("topic",) for error in not_a_string.value.errors())


@pytest.mark.parametrize("field", ["host_voice", "expert_voice"])
@pytest.mark.parametrize("value", [None, "a", "a" * 64])
def test_voice_fields_accept_none_and_boundary_lengths(field: str, value: str | None) -> None:
    config = AudioOverviewRequestConfig(**{field: value})
    assert getattr(config, field) == value


@pytest.mark.parametrize("field", ["host_voice", "expert_voice"])
@pytest.mark.parametrize("value", ["", "a" * 65])
def test_voice_fields_reject_empty_and_overlong(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AudioOverviewRequestConfig(**{field: value})
    assert any(error["loc"] == (field,) for error in exc_info.value.errors())


def test_unknown_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AudioOverviewRequestConfig(target_minutes=5, tempo="fast")
    extra_errors = [error for error in exc_info.value.errors() if error["type"] == "extra_forbidden"]
    assert extra_errors
    assert ("tempo",) in [error["loc"] for error in extra_errors]


def test_coerces_string_overrides_from_config_payloads() -> None:
    config = AudioOverviewRequestConfig.model_validate(
        {"target_minutes": "8", "max_context_chunks": "3"}
    )
    assert config.target_minutes == 8
    assert config.max_context_chunks == 3


def test_non_numeric_overrides_fail_closed() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AudioOverviewRequestConfig.model_validate({"target_minutes": "abc"})
    assert any(error["loc"] == ("target_minutes",) for error in exc_info.value.errors())


def test_none_overrides_are_rejected_like_capability_guards_with_or_empty() -> None:
    with pytest.raises(ValidationError):
        AudioOverviewRequestConfig.model_validate(None)
    assert AudioOverviewRequestConfig.model_validate({}) == AudioOverviewRequestConfig()


def test_roundtrip_dump_revalidates() -> None:
    original = AudioOverviewRequestConfig(
        topic="KB overview",
        target_minutes=15,
        host_voice="alloy",
        expert_voice=None,
        max_context_chunks=12,
    )
    restored = AudioOverviewRequestConfig.model_validate(original.model_dump())
    assert restored == original
