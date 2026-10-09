"""Branch coverage for the math animator request-config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deeptutor.agents.math_animator.request_config import (
    MathAnimatorRequestConfig,
    validate_math_animator_request_config,
)


def test_accepts_fully_specified_config() -> None:
    config = validate_math_animator_request_config(
        {
            "output_mode": "image",
            "quality": "high",
            "style_hint": "chalkboard look",
        }
    )

    assert isinstance(config, MathAnimatorRequestConfig)
    assert config.output_mode == "image"
    assert config.quality == "high"
    assert config.style_hint == "chalkboard look"


def test_accepts_partial_config_and_fills_defaults() -> None:
    config = validate_math_animator_request_config({"output_mode": "image"})

    assert config.output_mode == "image"
    assert config.quality == "medium"
    assert config.style_hint == ""


def test_accepts_empty_dict_as_all_defaults() -> None:
    config = validate_math_animator_request_config({})

    assert config == MathAnimatorRequestConfig()


def test_accepts_style_hint_at_max_length_boundary() -> None:
    hint = "x" * 500

    config = validate_math_animator_request_config({"style_hint": hint})

    assert config.style_hint == hint


def test_model_rejects_extra_fields_at_type_level() -> None:
    with pytest.raises(ValidationError):
        MathAnimatorRequestConfig(output_mode="video", unexpected=1)


def test_rejects_non_dict_string_payload() -> None:
    with pytest.raises(ValueError, match="must be an object") as excinfo:
        validate_math_animator_request_config("video")  # type: ignore[arg-type]

    assert excinfo.value.__cause__ is None


def test_rejects_non_dict_list_payload() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        validate_math_animator_request_config(["video"])  # type: ignore[arg-type]


def test_rejects_invalid_output_mode_with_detail_path() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_math_animator_request_config({"output_mode": "gif"})

    message = str(excinfo.value)
    assert message.startswith("Invalid math animator config: output_mode: ")
    assert isinstance(excinfo.value.__cause__, ValidationError)


def test_rejects_invalid_quality_with_detail_path() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_math_animator_request_config({"quality": "ultra"})

    assert "Invalid math animator config: quality: " in str(excinfo.value)


def test_rejects_style_hint_over_max_length() -> None:
    with pytest.raises(ValueError, match="Invalid math animator config: style_hint: "):
        validate_math_animator_request_config({"style_hint": "x" * 501})


def test_rejects_non_string_style_hint() -> None:
    with pytest.raises(ValueError, match="Invalid math animator config: style_hint: "):
        validate_math_animator_request_config({"style_hint": 123})


def test_error_details_join_multiple_errors_with_semicolons() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_math_animator_request_config(
            {"output_mode": "gif", "quality": "ultra", "style_hint": 123}
        )

    details = str(excinfo.value).removeprefix("Invalid math animator config: ")
    sections = [section.strip() for section in details.split(";")]
    assert sections[0].startswith("output_mode: ")
    assert sections[1].startswith("quality: ")
    assert sections[2].startswith("style_hint: ")
