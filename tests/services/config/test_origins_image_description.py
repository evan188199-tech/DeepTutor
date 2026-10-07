"""Unit coverage for services/config/origins.py and image_description.py."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from deeptutor.services.config.image_description import (
    ImageDescriptionModelSelection,
    normalize_image_description_model,
)
from deeptutor.services.config.origins import normalize_origin, normalize_origins
from deeptutor.services.config.runtime_settings import RuntimeSettingsService

# --------------------------------------------------------------------------
# origins.normalize_origin
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("/", ""),
        ("///", ""),
    ],
)
def test_normalize_origin_blank_values_return_empty_string(value: object, expected: str) -> None:
    assert normalize_origin(value) == expected


@pytest.mark.parametrize("value", ["*", "null"])
def test_normalize_origin_keeps_wildcard_and_null_sentinels(value: str) -> None:
    assert normalize_origin(value) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("localhost:3000", "http://localhost:3000"),
        ("app.example.com", "http://app.example.com"),
        ("APP.example.com", "http://APP.example.com"),
    ],
)
def test_normalize_origin_infers_http_scheme_for_schemeless_hosts(
    value: str, expected: str
) -> None:
    assert normalize_origin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://learn.example.com/path", "https://learn.example.com"),
        ("https://learn.example.com/", "https://learn.example.com"),
        ("http://localhost:8080/", "http://localhost:8080"),
        ("  https://a.example.com  ", "https://a.example.com"),
    ],
)
def test_normalize_origin_strips_paths_and_trailing_slashes(value: str, expected: str) -> None:
    assert normalize_origin(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ftp://files.example.com", "ftp://files.example.com"),
        ("chrome-extension://abc", "chrome-extension://abc"),
        ("http://[", "http://["),
    ],
)
def test_normalize_origin_keeps_non_http_schemes_and_unparseable_values(
    value: str, expected: str
) -> None:
    assert normalize_origin(value) == expected


# --------------------------------------------------------------------------
# origins.normalize_origins
# --------------------------------------------------------------------------


def test_normalize_origins_splits_separators_and_dedupes_in_order() -> None:
    value = "a.example.com, https://b.example.com/;c.example.com\nhttp://a.example.com/"
    assert normalize_origins(value) == [
        "http://a.example.com",
        "https://b.example.com",
        "http://c.example.com",
    ]


def test_normalize_origins_flattens_nested_iterables_and_drops_blank_items() -> None:
    value = [["a.example.com", None], ("https://b.example.com/",), {"c.example.com"}]
    assert normalize_origins(value) == [
        "http://a.example.com",
        "https://b.example.com",
        "http://c.example.com",
    ]


@pytest.mark.parametrize(
    "value",
    [None, "", ",,;", [], (), set(), ["", " ", ";;"]],
)
def test_normalize_origins_blank_inputs_yield_empty_list(value: object) -> None:
    assert normalize_origins(value) == []


# --------------------------------------------------------------------------
# image_description.normalize_image_description_model
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, {}])
def test_image_description_none_and_empty_pass_through_as_none(value: object) -> None:
    assert normalize_image_description_model(value) is None


def test_image_description_selection_strips_whitespace_and_dumps_exact_keys() -> None:
    selection = normalize_image_description_model({"profile_id": " p-1 ", "model_id": "\tm-1\n"})
    assert selection == {"profile_id": "p-1", "model_id": "m-1"}
    assert set(selection) == {"profile_id", "model_id"}


def test_image_description_selection_accepts_the_model_instance() -> None:
    selection = ImageDescriptionModelSelection(profile_id="p-1", model_id="m-1")
    assert normalize_image_description_model(selection) == {
        "profile_id": "p-1",
        "model_id": "m-1",
    }


@pytest.mark.parametrize(
    "value",
    [
        {"profile_id": "p-1"},
        {"model_id": "m-1"},
        {"profile_id": "", "model_id": "m-1"},
        {"profile_id": "   ", "model_id": "m-1"},
        {"profile_id": "p-1", "model_id": ""},
        {"profile_id": "p-1", "model_id": "m-1", "extra": True},
        "m-1",
        42,
        ["p-1", "m-1"],
    ],
)
def test_image_description_selection_rejects_invalid_payloads(value: object) -> None:
    with pytest.raises(ValidationError):
        normalize_image_description_model(value)


# --------------------------------------------------------------------------
# image_description merge / override priority via document_parsing config
# --------------------------------------------------------------------------


def _service(tmp_path: Path) -> RuntimeSettingsService:
    return RuntimeSettingsService(tmp_path / "settings", process_env={})


def test_document_parsing_defaults_carry_no_image_description_model(tmp_path: Path) -> None:
    payload = _service(tmp_path).load_document_parsing(include_process_overrides=False)
    assert payload["image_description_model"] is None
    assert payload["image_caption"] is False


def test_saved_selection_overrides_default_and_absent_key_falls_back(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    selection = {"profile_id": "p-1", "model_id": "m-1"}

    saved = service.save_document_parsing({"image_description_model": selection})
    assert saved["image_description_model"] == selection
    assert (
        service.load_document_parsing(include_process_overrides=False)["image_description_model"]
        == selection
    )

    # An explicit empty dict is an accepted clear signal.
    cleared = service.save_document_parsing({"image_description_model": {}})
    assert cleared["image_description_model"] is None

    # An absent key falls back to the stored/default value instead of clearing.
    untouched = service.save_document_parsing({"image_caption": True})
    assert untouched["image_caption"] is True
    assert untouched["image_description_model"] is None


def test_invalid_selection_save_is_rejected_and_keeps_previous_value(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    selection = {"profile_id": "p-1", "model_id": "m-1"}
    service.save_document_parsing({"image_description_model": selection})
    persisted_before = (service.path_for("document_parsing")).read_text(encoding="utf-8")

    with pytest.raises(ValidationError):
        service.save_document_parsing(
            {"image_description_model": {"profile_id": "p-1", "model_id": ""}}
        )

    payload = service.load_document_parsing(include_process_overrides=False)
    assert payload["image_description_model"] == selection
    assert service.path_for("document_parsing").read_text(encoding="utf-8") == persisted_before
