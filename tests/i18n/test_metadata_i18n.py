"""Behavior tests for the localized metadata tables in ``metadata_i18n``.

Covers the three public helpers: known/unknown lookups for capabilities and
tools, the copy semantics of the returned mapping, the language fallback
chain of ``localized_description``, and a full-table enumeration asserting
every catalogued entry carries non-empty en/zh copy for a capability that
still exists. Deliberately avoids hardcoding snapshots of the tables so
adding or rewording entries never breaks this suite.
"""

from __future__ import annotations

import pytest

import deeptutor.i18n.metadata_i18n as metadata_i18n
from deeptutor.i18n.metadata_i18n import (
    capability_description_i18n,
    localized_description,
    tool_description_i18n,
)
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS

_KNOWN_CAPABILITY = "chat"
_UNKNOWN = "__not_catalogued__"


# ---------------------------------------------------------------------------
# capability_description_i18n
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(metadata_i18n._CAPABILITY_DESCRIPTIONS))
def test_known_capability_returns_en_and_zh(name: str) -> None:
    values = capability_description_i18n(name)
    assert "en" in values and "zh" in values
    assert values["en"].strip()
    assert values["zh"].strip()


def test_known_capability_is_actually_localized() -> None:
    values = capability_description_i18n(_KNOWN_CAPABILITY)
    assert values["zh"] != values["en"]


def test_unknown_capability_falls_back_for_both_languages() -> None:
    assert capability_description_i18n(_UNKNOWN, "fallback text") == {
        "en": "fallback text",
        "zh": "fallback text",
    }


def test_unknown_capability_without_fallback_is_empty() -> None:
    assert capability_description_i18n(_UNKNOWN) == {"en": "", "zh": ""}


def test_capability_catalog_names_are_builtin_capabilities() -> None:
    stale = set(metadata_i18n._CAPABILITY_DESCRIPTIONS) - set(BUILTIN_CAPABILITY_SPECS)
    assert not stale, f"catalogued capabilities that no longer exist: {sorted(stale)}"


def test_returned_capability_mapping_is_a_copy() -> None:
    values = capability_description_i18n(_KNOWN_CAPABILITY)
    values["en"] = "mutated"
    assert capability_description_i18n(_KNOWN_CAPABILITY)["en"] != "mutated"


# ---------------------------------------------------------------------------
# tool_description_i18n
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(metadata_i18n._TOOL_DESCRIPTIONS))
def test_known_tool_returns_en_and_zh(name: str) -> None:
    values = tool_description_i18n(name)
    assert "en" in values and "zh" in values
    assert values["en"].strip()
    assert values["zh"].strip()


def test_known_tool_is_actually_localized() -> None:
    values = tool_description_i18n("web_search")
    assert values["zh"] != values["en"]


def test_unknown_tool_falls_back_for_both_languages() -> None:
    assert tool_description_i18n(_UNKNOWN, "fallback text") == {
        "en": "fallback text",
        "zh": "fallback text",
    }


def test_unknown_tool_without_fallback_is_empty() -> None:
    assert tool_description_i18n(_UNKNOWN) == {"en": "", "zh": ""}


def test_returned_tool_mapping_is_a_copy() -> None:
    values = tool_description_i18n("exec")
    values["zh"] = "mutated"
    assert tool_description_i18n("exec")["zh"] != "mutated"


# ---------------------------------------------------------------------------
# localized_description
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["zh", "zh-CN", "zh_TW", "ZH"])
def test_chinese_language_variants_pick_zh(language: str) -> None:
    values = {"en": "English copy", "zh": "中文文案"}
    assert localized_description(values, language) == "中文文案"


@pytest.mark.parametrize("language", ["en", "EN", "de", "fr", ""])
def test_non_chinese_languages_pick_en(language: str) -> None:
    values = {"en": "English copy", "zh": "中文文案"}
    assert localized_description(values, language) == "English copy"


def test_none_language_defaults_to_en() -> None:
    values = {"en": "English copy", "zh": "中文文案"}
    assert localized_description(values, None) == "English copy"


def test_missing_zh_falls_back_to_en() -> None:
    assert localized_description({"en": "English copy"}, "zh") == "English copy"


def test_missing_en_falls_back_to_zh() -> None:
    assert localized_description({"zh": "中文文案"}, "en") == "中文文案"


def test_empty_zh_falls_back_to_en() -> None:
    values = {"en": "English copy", "zh": ""}
    assert localized_description(values, "zh") == "English copy"


def test_empty_table_yields_empty_string() -> None:
    assert localized_description({}, "zh") == ""
    assert localized_description({}, "en") == ""


def test_both_values_empty_yields_empty_string() -> None:
    values = {"en": "", "zh": ""}
    assert localized_description(values, "zh") == ""
