"""Locale contracts for the api/routers user-visible copy (E13 follow-up).

Four router files were moved onto the ``t()`` pipeline: ``auth.py``,
``book.py``, ``knowledge.py`` and ``mastery_path.py``. These tests keep them
there and make the pattern replicable for the remaining routers:

1. no authored English prose may reappear as a literal ``HTTPException``
   detail or a literal response ``message``/``note`` value in those files;
2. every ``t()`` key a router references must exist in *both* locales and
   must actually differ between them, so switching the UI language switches
   the API copy rather than silently falling back to English;
3. parameterized templates must format cleanly in both locales.

Runtime behaviour is pinned by switching ``get_ui_language`` and asserting
the same helper raises a different detail per locale.
"""

from __future__ import annotations

import ast
import pathlib
import re

from fastapi import HTTPException
import pytest

pytest.importorskip("fastapi")

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.api.routers import knowledge as knowledge_router
from deeptutor.api.routers import mastery_path as mastery_router
from deeptutor.services.i18n import _MESSAGES, t
from deeptutor.services.settings import interface_settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ROUTER_DIR = REPO_ROOT / "deeptutor" / "api" / "routers"

#: The router files this card moved onto t(); extend as follow-up cards land.
COVERED_ROUTERS = ["auth.py", "book.py", "knowledge.py", "mastery_path.py"]
COVERED_MODULES = [auth_router, book_router, knowledge_router, mastery_router]

_FIELD_RE = re.compile(r"\{(\w+)(?:!r|!s)?\}")


def _literal_details(filename: str) -> list[str]:
    """Literal (non-``t()``) HTTPException details in one router file."""
    src = (ROUTER_DIR / filename).read_text(encoding="utf-8")
    findings = []
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "HTTPException"
        ):
            for kw in node.keywords:
                if kw.arg == "detail" and isinstance(kw.value, (ast.Constant, ast.JoinedStr)):
                    findings.append(f"{filename}:{kw.value.lineno}")
    return findings


def _literal_status_messages(filename: str) -> list[str]:
    """Literal ``message``/``note`` dict values in one router file."""
    src = (ROUTER_DIR / filename).read_text(encoding="utf-8")
    findings = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in {"message", "note"}
                    and isinstance(value, ast.Constant)
                ):
                    findings.append(f"{filename}:{value.lineno}")
    return findings


def _t_keys(module) -> set[str]:
    """Every literal ``t("...")`` key referenced by a router module."""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    keys = set()
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "t"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
    return keys


def test_no_hardcoded_httpexception_details_remain() -> None:
    findings = [line for name in COVERED_ROUTERS for line in _literal_details(name)]
    assert not findings, f"literal HTTPException details bypass t(): {findings}"


def test_no_hardcoded_status_messages_remain() -> None:
    findings = [line for name in COVERED_ROUTERS for line in _literal_status_messages(name)]
    assert not findings, f"literal response messages bypass t(): {findings}"


@pytest.mark.parametrize(
    "module", COVERED_MODULES, ids=[m.__name__.rsplit(".", 1)[-1] for m in COVERED_MODULES]
)
def test_router_keys_exist_in_both_locales(module) -> None:
    missing = _t_keys(module) - set(_MESSAGES["en"])
    assert not missing, f"keys missing from the catalog: {sorted(missing)}"
    missing_zh = _t_keys(module) - set(_MESSAGES["zh"])
    assert not missing_zh, f"keys missing a zh translation: {sorted(missing_zh)}"


@pytest.mark.parametrize(
    "module", COVERED_MODULES, ids=[m.__name__.rsplit(".", 1)[-1] for m in COVERED_MODULES]
)
def test_router_keys_change_with_locale(module) -> None:
    """A zh entry identical to English means the locale switch is a no-op."""
    identical = {
        key: _MESSAGES["en"][key]
        for key in _t_keys(module)
        if _MESSAGES["zh"][key] == _MESSAGES["en"][key]
    }
    assert not identical, f"zh copy identical to en (locale switch invisible): {identical}"


def test_catalog_placeholders_match_between_locales() -> None:
    mismatched = {
        key: (sorted(_FIELD_RE.findall(_MESSAGES["en"][key])), sorted(_FIELD_RE.findall(_MESSAGES["zh"][key])))
        for key in _MESSAGES["en"]
        if key in _MESSAGES["zh"]
        and _FIELD_RE.findall(_MESSAGES["en"][key]) != _FIELD_RE.findall(_MESSAGES["zh"][key])
    }
    assert not mismatched, f"placeholder sets diverge between locales: {mismatched}"


@pytest.mark.parametrize(
    ("key", "params"),
    [
        ("knowledge.kb_not_found", {"name": "demo"}),
        ("knowledge.invalid_search_mode", {"mode": "mix", "engine": "llamaindex", "modes": "local, global"}),
        ("knowledge.provider_mismatch", {"requested": "lightrag", "current": "llamaindex"}),
        ("auth.import_too_many_rows", {"max_rows": 500}),
        ("book.invalid_transition", {"current": "drafted", "next": "captured"}),
        ("mastery.invalid_mode", {"modes": "guided, free"}),
    ],
)
def test_parameterized_messages_render_in_both_locales(key: str, params: dict) -> None:
    for language in ("en", "zh"):
        rendered = t(key, language=language, **params)
        for value in params.values():
            assert str(value) in rendered, f"{key} lost a parameter in {language}: {rendered}"


@pytest.mark.parametrize("language", ["en", "zh"])
def test_router_error_details_follow_ui_language(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    """Switching the UI language switches the detail the router raises."""
    monkeypatch.setattr(interface_settings, "get_ui_language", lambda default="en": language)

    with pytest.raises(HTTPException) as exc_info:
        book_router._coerce_block_type("definitely-not-a-block")
    assert exc_info.value.detail == t("book.unknown_block_type", name="definitely-not-a-block")

    with pytest.raises(HTTPException) as exc_info:
        mastery_router._validate_book_id("../traversal")
    assert exc_info.value.detail == t("mastery.invalid_book_id")

    with pytest.raises(HTTPException) as exc_info:
        knowledge_router._sanitize_rel_subdir("../escape")
    assert exc_info.value.detail == t("knowledge.invalid_folder_path")

    # The three families must not coincide across locales — that would make
    # the switch above unobservable.
    assert t("book.unknown_block_type", language="en") != t(
        "book.unknown_block_type", language="zh"
    )
