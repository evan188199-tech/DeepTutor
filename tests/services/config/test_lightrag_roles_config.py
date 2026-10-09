"""Credential-free LightRAG role configuration contracts (config/lightrag_roles).

Covers the parse-time contracts of the role settings models: selection
validation, execution-limit boundaries, mode/selection coupling rules, and the
selection_for() fallback chain from role override to base model.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deeptutor.services.config.lightrag_roles import (
    LightRagIndexingSelection,
    LightRagIndexingVision,
    LightRagModelSelection,
    LightRagRoleModel,
    LightRagRoleModels,
    LightRagVisionModel,
)

REASONING_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "adaptive"]


def selection(number: int = 1, **overrides) -> dict:
    payload = {"profile_id": f"p{number}", "model_id": f"m{number}"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LightRagModelSelection
# ---------------------------------------------------------------------------


def test_model_selection_strips_whitespace_and_defaults_effort() -> None:
    parsed = LightRagModelSelection.model_validate(
        {"profile_id": "  prof  ", "model_id": " model-x "}
    )
    assert parsed.profile_id == "prof"
    assert parsed.model_id == "model-x"
    assert parsed.reasoning_effort is None


@pytest.mark.parametrize("effort", REASONING_EFFORTS)
def test_model_selection_accepts_every_reasoning_effort(effort: str) -> None:
    parsed = LightRagModelSelection.model_validate(
        {**selection(), "reasoning_effort": effort}
    )
    assert parsed.reasoning_effort == effort


def test_model_selection_rejects_unknown_reasoning_effort() -> None:
    with pytest.raises(ValidationError):
        LightRagModelSelection.model_validate({**selection(), "reasoning_effort": "ultra"})


@pytest.mark.parametrize("field", ["profile_id", "model_id"])
@pytest.mark.parametrize("bad", ["", " ", "x" * 129])
def test_model_selection_rejects_empty_and_overlong_ids(field: str, bad: str) -> None:
    payload = {"profile_id": "p", "model_id": "m"}
    payload[field] = bad
    with pytest.raises(ValidationError):
        LightRagModelSelection.model_validate(payload)


def test_model_selection_rejects_missing_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LightRagModelSelection.model_validate({"profile_id": "p"})
    with pytest.raises(ValidationError):
        LightRagModelSelection.model_validate({**selection(), "surprise": True})


# ---------------------------------------------------------------------------
# LightRagRoleModel
# ---------------------------------------------------------------------------


def test_role_model_defaults_are_inherit_without_selection() -> None:
    parsed = LightRagRoleModel()
    assert parsed.mode == "inherit"
    assert parsed.selection is None
    assert parsed.reasoning_effort is None
    assert parsed.max_async == 4
    assert parsed.timeout == 240


def test_role_model_rejects_disabled_mode() -> None:
    with pytest.raises(ValidationError):
        LightRagRoleModel.model_validate({"mode": "disabled"})


def test_role_model_mode_model_requires_selection() -> None:
    with pytest.raises(ValidationError, match="explicit model role requires"):
        LightRagRoleModel.model_validate({"mode": "model"})


def test_role_model_inherit_mode_rejects_selection() -> None:
    with pytest.raises(ValidationError, match="explicit model role requires"):
        LightRagRoleModel.model_validate({"mode": "inherit", "selection": selection()})


def test_role_model_rejects_effort_on_nested_selection() -> None:
    with pytest.raises(ValidationError, match="role reasoning_effort"):
        LightRagRoleModel.model_validate(
            {"mode": "model", "selection": {**selection(), "reasoning_effort": "low"}}
        )


@pytest.mark.parametrize("bad", [0, 33, "4", 4.5, True, None])
def test_role_model_rejects_out_of_bounds_and_non_strict_max_async(bad) -> None:
    with pytest.raises(ValidationError):
        LightRagRoleModel.model_validate({"max_async": bad})


@pytest.mark.parametrize("bad", [0, 3601, "240", 240.0, False, None])
def test_role_model_rejects_out_of_bounds_and_non_strict_timeout(bad) -> None:
    with pytest.raises(ValidationError):
        LightRagRoleModel.model_validate({"timeout": bad})


@pytest.mark.parametrize("value", [1, 32])
def test_role_model_accepts_max_async_bounds(value: int) -> None:
    assert LightRagRoleModel.model_validate({"max_async": value}).max_async == value


@pytest.mark.parametrize("value", [1, 3600])
def test_role_model_accepts_timeout_bounds(value: int) -> None:
    assert LightRagRoleModel.model_validate({"timeout": value}).timeout == value


def test_role_model_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LightRagRoleModel.model_validate({"mode": "inherit", "role": "extract"})


# ---------------------------------------------------------------------------
# LightRagVisionModel
# ---------------------------------------------------------------------------


def test_vision_model_defaults_to_disabled() -> None:
    parsed = LightRagVisionModel()
    assert parsed.mode == "disabled"
    assert parsed.selection is None
    assert parsed.reasoning_effort is None


def test_vision_model_disabled_rejects_effort_override() -> None:
    with pytest.raises(ValidationError, match="disabled vision role"):
        LightRagVisionModel.model_validate({"mode": "disabled", "reasoning_effort": "high"})


def test_vision_model_inherit_accepts_effort_without_selection() -> None:
    parsed = LightRagVisionModel.model_validate(
        {"mode": "inherit", "reasoning_effort": "high"}
    )
    assert parsed.mode == "inherit"
    assert parsed.selection is None
    assert parsed.reasoning_effort == "high"


def test_vision_model_accepts_explicit_selection() -> None:
    parsed = LightRagVisionModel.model_validate(
        {"mode": "model", "selection": selection(9), "max_async": 2}
    )
    assert parsed.mode == "model"
    assert parsed.selection is not None and parsed.selection.profile_id == "p9"
    assert parsed.max_async == 2


# ---------------------------------------------------------------------------
# LightRagRoleModels.selection_for()
# ---------------------------------------------------------------------------


def test_role_models_require_base_and_reject_unknown_roles() -> None:
    with pytest.raises(ValidationError):
        LightRagRoleModels.model_validate({})
    with pytest.raises(ValidationError):
        LightRagRoleModels.model_validate({"base": selection(), "vision": {}})


def test_role_models_default_roles_fall_back_to_base() -> None:
    models = LightRagRoleModels.model_validate({"base": selection(1)})
    assert models.extract.mode == "inherit"
    assert models.keyword.mode == "inherit"
    assert models.query.mode == "inherit"
    assert models.vlm.mode == "disabled"
    assert models.selection_for("extract") is models.base
    assert models.selection_for("keyword") is models.base
    assert models.selection_for("query") is models.base
    assert models.selection_for("vlm") is None


def test_role_models_explicit_role_resolves_own_selection() -> None:
    models = LightRagRoleModels.model_validate(
        {
            "base": selection(1),
            "keyword": {"mode": "model", "selection": selection(2)},
        }
    )
    resolved = models.selection_for("keyword")
    assert resolved is not models.base
    assert resolved is not None
    assert resolved.profile_id == "p2"
    assert resolved.reasoning_effort is None


def test_role_models_effort_override_copies_base_without_mutation() -> None:
    models = LightRagRoleModels.model_validate(
        {"base": {**selection(1), "reasoning_effort": "low"}, "extract": {"reasoning_effort": "high"}}
    )
    resolved = models.selection_for("extract")
    assert resolved is not None
    assert resolved.reasoning_effort == "high"
    assert resolved.profile_id == "p1"
    assert models.base.reasoning_effort == "low"


def test_role_models_effort_override_applies_to_explicit_selection() -> None:
    models = LightRagRoleModels.model_validate(
        {
            "base": selection(1),
            "query": {"mode": "model", "selection": selection(3), "reasoning_effort": "medium"},
        }
    )
    resolved = models.selection_for("query")
    assert resolved is not None
    assert resolved.profile_id == "p3"
    assert resolved.reasoning_effort == "medium"
    assert resolved is not models.query.selection


def test_role_models_unknown_role_raises() -> None:
    models = LightRagRoleModels.model_validate({"base": selection()})
    with pytest.raises(AttributeError):
        models.selection_for("nonexistent")


# ---------------------------------------------------------------------------
# Indexing selection contracts
# ---------------------------------------------------------------------------


def test_indexing_vision_defaults_disabled() -> None:
    parsed = LightRagIndexingVision()
    assert parsed.mode == "disabled"
    assert parsed.selection is None


def test_indexing_vision_selection_required_exactly_when_enabled() -> None:
    with pytest.raises(ValidationError, match="enabled vision indexing requires"):
        LightRagIndexingVision.model_validate({"mode": "enabled"})
    with pytest.raises(ValidationError, match="enabled vision indexing requires"):
        LightRagIndexingVision.model_validate({"mode": "disabled", "selection": selection()})
    enabled = LightRagIndexingVision.model_validate({"mode": "enabled", "selection": selection()})
    assert enabled.selection is not None


def test_indexing_selection_requires_extract_and_defaults_vision() -> None:
    with pytest.raises(ValidationError):
        LightRagIndexingSelection.model_validate({})
    parsed = LightRagIndexingSelection.model_validate({"extract": selection(5)})
    assert parsed.extract.profile_id == "p5"
    assert parsed.vlm.mode == "disabled"
    with pytest.raises(ValidationError):
        LightRagIndexingSelection.model_validate({"extract": selection(5), "extra": {}})
