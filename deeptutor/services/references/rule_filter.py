"""Local rule filter for reference rows surfaced to users (#375).

A bounded, purely local slice of the reference-compliance work: before
reference rows are emitted for display (the deep-solve sources event and
the question generator's output chain), a domain blacklist/whitelist plus
keyword rules can withhold entries. No external API is consulted here —
moderation and URL-reputation services stay in the web-search source
filter where they already exist. The policy defaults to disabled, in which
case the input list is returned untouched so emitted output stays
byte-identical to the unfiltered behavior.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from deeptutor.services.config.runtime_settings import load_system_settings

_logger = logging.getLogger(__name__)

SETTINGS_KEY = "reference_output_filtering"

DEFAULT_REFERENCE_OUTPUT_FILTERING: dict[str, Any] = {
    "enabled": False,
    "blocked_domains": [],
    "trusted_domains": [],
    "blocked_keywords": [],
}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _domain_list(value: Any) -> tuple[str, ...]:
    """Normalize a configured domain list into lowercase registry hosts."""
    rows: Any
    if isinstance(value, str):
        rows = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple)):
        rows = value
    else:
        return ()
    normalized: list[str] = []
    for row in rows:
        host = str(row or "").strip().lower()
        if host.startswith("*."):
            host = host[1:]
        host = host.strip(".")
        if host and host not in normalized:
            normalized.append(host)
    return tuple(normalized)


def _keyword_list(value: Any) -> tuple[str, ...]:
    """Normalize configured keywords; a bare string stays one keyword."""
    rows: Any
    if isinstance(value, (list, tuple)):
        rows = value
    elif isinstance(value, str):
        rows = (value,)
    else:
        return ()
    keywords: list[str] = []
    for row in rows:
        keyword = str(row or "").strip().lower()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return tuple(keywords)


def normalize_settings(raw: Any) -> dict[str, Any]:
    """Coerce an untrusted policy mapping into the whitelisted shape."""
    settings = raw if isinstance(raw, dict) else {}
    return {
        "enabled": _as_bool(settings.get("enabled"), False),
        "blocked_domains": _domain_list(settings.get("blocked_domains")),
        "trusted_domains": _domain_list(settings.get("trusted_domains")),
        "blocked_keywords": _keyword_list(settings.get("blocked_keywords")),
    }


def _host_of(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""
    if not host:
        return ""
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def _matches_domain(host: str, patterns: tuple[str, ...]) -> bool:
    return any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns)


def _rejection(row: Any, policy: dict[str, Any]) -> tuple[str, str]:
    """Return ``(reason, detail)`` for a row the policy withholds."""
    if not isinstance(row, dict):
        return "", ""
    url = row.get("url")
    if not isinstance(url, str) or not url.strip():
        return "", ""
    host = _host_of(url.strip())
    if not host:
        return "", ""
    if _matches_domain(host, policy["blocked_domains"]):
        return "blocked_domain", host
    if policy["trusted_domains"] and not _matches_domain(host, policy["trusted_domains"]):
        return "untrusted_domain", host
    haystack = f"{str(row.get('title') or '')}\n{url}".lower()
    for keyword in policy["blocked_keywords"]:
        if keyword in haystack:
            return "blocked_keyword", keyword
    return "", ""


def filter_reference_rows(rows: Any, settings: Any) -> Any:
    """Return the reference rows that survive the local rule policy.

    Only URL-bearing mapping rows are considered; knowledge-base, page-index
    and notebook rows pass through untouched, as do rows whose URL carries no
    parseable host. Withheld rows are logged, never raised. The input list is
    never mutated; when the policy is disabled the very same list object is
    returned so downstream output stays byte-identical.
    """
    policy = normalize_settings(settings)
    if not policy["enabled"]:
        return rows
    if not isinstance(rows, list):
        return rows
    kept: list[Any] = []
    for row in rows:
        reason, detail = _rejection(row, policy)
        if reason:
            _logger.info(
                "Reference row withheld before display: reason=%s detail=%s",
                reason,
                detail,
            )
        else:
            kept.append(row)
    return kept


def load_reference_output_filtering() -> dict[str, Any]:
    """Resolve the display-side reference policy from runtime system JSON."""
    try:
        system = load_system_settings()
    except Exception as exc:  # noqa: BLE001 — policy loading must never break a turn
        _logger.warning("Could not load reference output policy: %s", exc)
        return dict(DEFAULT_REFERENCE_OUTPUT_FILTERING)
    return normalize_settings(system.get(SETTINGS_KEY, {}))


def filter_sources_for_display(rows: Any) -> Any:
    """Apply the local reference policy to rows about to be surfaced."""
    return filter_reference_rows(rows, load_reference_output_filtering())


__all__ = [
    "DEFAULT_REFERENCE_OUTPUT_FILTERING",
    "SETTINGS_KEY",
    "filter_reference_rows",
    "filter_sources_for_display",
    "load_reference_output_filtering",
    "normalize_settings",
]
