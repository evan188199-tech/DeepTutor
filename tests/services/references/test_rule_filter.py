"""Focused tests for the local reference output rule filter (#375)."""

from __future__ import annotations

import json
import logging

import pytest

from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.references import rule_filter
from deeptutor.services.references.rule_filter import (
    DEFAULT_REFERENCE_OUTPUT_FILTERING,
    filter_reference_rows,
    filter_sources_for_display,
    load_reference_output_filtering,
    normalize_settings,
)

_ENABLED = {
    "enabled": True,
    "blocked_domains": ["blocked.example"],
    "trusted_domains": [],
    "blocked_keywords": [],
}

_WEB_ROW = {"type": "web", "url": "https://blocked.example/page", "title": "Blocked"}
_KEEP_ROW = {"type": "web", "url": "https://safe.example/page", "title": "Safe"}


def test_default_policy_returns_same_list_object() -> None:
    rows = [_WEB_ROW, _KEEP_ROW]

    assert filter_reference_rows(rows, {}) is rows
    assert filter_reference_rows(rows, {"enabled": False}) is rows
    assert filter_reference_rows(rows, None) is rows


def test_filter_sources_for_display_default_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_WEB_ROW, _KEEP_ROW]
    monkeypatch.setattr(rule_filter, "load_system_settings", lambda: {})

    assert filter_sources_for_display(rows) is rows
    assert json.dumps(filter_sources_for_display(rows)) == json.dumps(rows)


def test_load_settings_defaults_and_failure_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rule_filter, "load_system_settings", lambda: {})
    assert load_reference_output_filtering()["enabled"] is False

    def _boom() -> dict:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(rule_filter, "load_system_settings", _boom)
    assert load_reference_output_filtering() == dict(DEFAULT_REFERENCE_OUTPUT_FILTERING)


def test_blocked_domain_drops_exact_and_subdomain() -> None:
    rows = [
        {"type": "web", "url": "https://blocked.example/a", "title": "Exact"},
        {"type": "web", "url": "https://sub.BLOCKED.example/a", "title": "Subdomain"},
        _KEEP_ROW,
    ]

    kept = filter_reference_rows(rows, _ENABLED)

    assert kept == [_KEEP_ROW]


def test_trusted_domain_whitelist() -> None:
    rows = [
        {"type": "web", "url": "https://edu.example/a", "title": "Trusted"},
        {"type": "web", "url": "https://other.example/a", "title": "Other"},
        {"type": "web", "url": "https://deep.edu.example/a", "title": "Nested"},
    ]
    empty_policy = {**_ENABLED, "trusted_domains": []}
    assert filter_reference_rows(rows, empty_policy) == rows

    trusted_policy = {**_ENABLED, "trusted_domains": ["edu.example"]}
    assert filter_reference_rows(rows, trusted_policy) == [
        rows[0],
        rows[2],
    ]


def test_blocked_keyword_matches_title_and_url_case_insensitive() -> None:
    rows = [
        {"type": "web", "url": "https://safe.example/a", "title": "Learn MATH today"},
        {"type": "web", "url": "https://safe.example/math/a", "title": "Fine"},
        {"type": "web", "url": "https://safe.example/b", "title": "Unrelated"},
    ]
    policy = {**_ENABLED, "blocked_keywords": ["Math"]}

    assert filter_reference_rows(rows, policy) == [rows[2]]

    multiword = {**_ENABLED, "blocked_keywords": ["math today"]}
    assert filter_reference_rows(rows[:1], multiword) == []


def test_rows_without_url_or_host_pass_through() -> None:
    rows = [
        {"type": "pageindex", "title": "KB page", "kb_name": "kb"},
        {"type": "rag", "source": "kb://doc", "title": "RAG"},
        {"type": "web", "url": "", "title": "Empty URL"},
        {"type": "web", "url": "not a url", "title": "No host"},
        "bare-string-row",
        None,
    ]

    assert filter_reference_rows(list(rows), _ENABLED) == rows


def test_input_list_not_mutated_and_kept_rows_identical() -> None:
    rows = [dict(_WEB_ROW), dict(_KEEP_ROW)]

    kept = filter_reference_rows(rows, _ENABLED)

    assert kept == [rows[1]]
    assert kept[0] is rows[1]
    assert len(rows) == 2


def test_removals_are_logged_without_raising(caplog: pytest.LogCaptureFixture) -> None:
    rows = [
        _WEB_ROW,
        {"type": "web", "url": "https://safe.example/x", "title": "Casino guide"},
    ]
    policy = {**_ENABLED, "blocked_keywords": ["casino"]}

    with caplog.at_level(logging.INFO, logger=rule_filter.__name__):
        kept = filter_reference_rows(rows, policy)

    assert kept == []
    reasons = [record.message for record in caplog.records]
    assert any("reason=blocked_domain" in message for message in reasons)
    assert any("reason=blocked_keyword" in message for message in reasons)


def test_normalize_settings_whitelists_and_coerces() -> None:
    assert normalize_settings(None) == {
        "enabled": False,
        "blocked_domains": (),
        "trusted_domains": (),
        "blocked_keywords": (),
    }
    normalized = normalize_settings(
        {
            "enabled": "true",
            "blocked_domains": "a.example, *.b.example .c.example",
            "trusted_domains": ["D.example", "", None, "d.example"],
            "blocked_keywords": [" Keyword ", "keyword", 5],
            "unknown_key": "dropped",
        }
    )
    assert normalized == {
        "enabled": True,
        "blocked_domains": ("a.example", "b.example", "c.example"),
        "trusted_domains": ("d.example",),
        "blocked_keywords": ("keyword", "5"),
    }
    assert "unknown_key" not in normalized


def test_runtime_settings_defaults_and_roundtrip(tmp_path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings")

    assert service.load_system()["reference_output_filtering"] == {
        "enabled": False,
        "blocked_domains": [],
        "trusted_domains": [],
        "blocked_keywords": [],
    }

    service.save_system(
        {
            "reference_output_filtering": {
                "enabled": True,
                "blocked_domains": ["unsafe.example"],
                "trusted_domains": ["edu.example"],
                "blocked_keywords": ["casino"],
            }
        }
    )
    assert service.load_system()["reference_output_filtering"] == {
        "enabled": True,
        "blocked_domains": ["unsafe.example"],
        "trusted_domains": ["edu.example"],
        "blocked_keywords": ["casino"],
    }


def test_module_makes_no_network_imports() -> None:
    import inspect

    source = inspect.getsource(rule_filter)

    assert "urllib.request" not in source
    assert "httpx" not in source
    assert "aiohttp" not in source
