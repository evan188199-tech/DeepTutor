"""Docstring default table vs ``Field`` defaults in ``deeptutor/config/settings.py``.

The module docstring documents the ``LLM_RETRY__*`` environment variables with
a ``(default: ...)`` note per variable, and those notes drifted from the
actual ``Field(default=...)`` values before (scan/env-config-drift §A,
re-confirmed 2026-10-06). This guard parses both sides with the ``ast``
module and compares them field by field, so a future edit to either side
fails here with a readable diff instead of shipping another silent drift.

The module under test is never imported: the comparison must be independent
of whatever environment the interpreter happens to run in.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "deeptutor" / "config" / "settings.py"

# Pre-existing drift entries recorded by scan/env-config-drift-20261005 §A and
# re-confirmed on 2026-10-06. The docs card (docs-env-config-drift) owns the
# fix; the marks are strict, so once either side is corrected the marked test
# starts xpassing and the suite fails until the entry is removed from here.
KNOWN_DRIFT = {
    "LLM_RETRY__MAX_RETRIES",
    "LLM_RETRY__BASE_DELAY",
}

SECTION_HEADER = re.compile(r"^([A-Z][A-Za-z ]*):\s*$")
ENV_ENTRY = re.compile(r"^\s+([A-Z][A-Z0-9_]+):\s*(.+?)\s*$")
DEFAULT_NOTE = re.compile(r"\(default:\s*([^)]+)\)\s*$")

LITERAL = "literal"
FACTORY = "factory"
MISSING = "missing"
UNKNOWN = "unknown"


def _parse_literal(node: ast.expr):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _default_of(value: ast.expr) -> tuple[str, object]:
    """Classify a field's assigned expression.

    Returns ``(kind, payload)`` where kind is one of LITERAL, FACTORY
    (payload: the nested model class name), MISSING (no default given) or
    UNKNOWN (a default that cannot be read statically).
    """
    if isinstance(value, ast.Call):
        func = value.func
        called = getattr(func, "id", None) or getattr(func, "attr", None)
        if called == "Field":
            for keyword in value.keywords:
                if keyword.arg == "default":
                    literal = _parse_literal(keyword.value)
                    if literal is None and not isinstance(keyword.value, ast.Constant):
                        return UNKNOWN, None
                    return LITERAL, literal
                if keyword.arg == "default_factory" and isinstance(keyword.value, ast.Name):
                    return FACTORY, keyword.value.id
            return MISSING, None
    literal = _parse_literal(value)
    if literal is None and not isinstance(value, ast.Constant):
        return UNKNOWN, None
    return LITERAL, literal


def _load_parity() -> dict:
    """Parse the settings module once: docstring table plus field tree."""
    tree = ast.parse(SETTINGS_PATH.read_text(encoding="utf-8"), filename=str(SETTINGS_PATH))
    docstring = ast.get_docstring(tree) or ""
    models: dict[str, ast.ClassDef] = {}
    settings_name = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {
            getattr(base, "id", None) or getattr(base, "attr", None) for base in node.bases
        }
        if base_names & {"BaseModel", "BaseSettings"}:
            models[node.name] = node
            if "BaseSettings" in base_names:
                settings_name = node.name
    assert settings_name, "no BaseSettings subclass found in settings.py"
    prefix, delimiter = "", "__"
    for stmt in models[settings_name].body:
        if not (
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "model_config"
                for target in stmt.targets
            )
        ):
            continue
        if isinstance(stmt.value, ast.Call):
            for keyword in stmt.value.keywords:
                if keyword.arg == "env_prefix" and isinstance(keyword.value, ast.Constant):
                    prefix = keyword.value.value
                elif keyword.arg == "env_nested_delimiter" and isinstance(
                    keyword.value, ast.Constant
                ):
                    delimiter = keyword.value.value
    return {
        "documented": _documented_defaults(docstring),
        "models": models,
        "settings_name": settings_name,
        "prefix": prefix,
        "delimiter": delimiter,
    }


def _documented_defaults(docstring: str) -> dict[str, str]:
    """The ``Environment Variables`` table: env var name -> note text."""
    documented: dict[str, str] = {}
    in_section = False
    for line in docstring.splitlines():
        header = SECTION_HEADER.match(line.strip())
        if header:
            in_section = header.group(1) == "Environment Variables"
            continue
        if not in_section:
            continue
        entry = ENV_ENTRY.match(line)
        if entry:
            documented[entry.group(1)] = entry.group(2)
    return documented


def _docstring_default(note: str):
    match = DEFAULT_NOTE.search(note)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


PARITY = _load_parity()


def _class_fields(model: ast.ClassDef) -> dict[str, ast.expr]:
    fields: dict[str, ast.expr] = {}
    for stmt in model.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
        ):
            fields[stmt.target.id] = stmt.value
    return fields


def _resolve_field(env_name: str) -> tuple[str, str, str, object, str]:
    """Map an env var name to its field.

    Returns (model class, field name, default kind, default payload, dotted
    path) and raises AssertionError with a readable reason when the name does
    not correspond to a real field path.
    """
    prefix, delimiter = PARITY["prefix"], PARITY["delimiter"]
    if not env_name.startswith(prefix):
        raise AssertionError(
            f"{env_name}: documented env var does not use the "
            f"{PARITY['settings_name']} env_prefix {prefix!r}"
        )
    segments = env_name[len(prefix) :].lower().split(delimiter)
    model_name = PARITY["settings_name"]
    dotted: list[str] = []
    for segment in segments[:-1]:
        fields = _class_fields(PARITY["models"][model_name])
        if segment not in fields:
            raise AssertionError(f"{env_name}: no field {segment!r} on {model_name}")
        kind, payload = _default_of(fields[segment])
        if kind != FACTORY:
            raise AssertionError(
                f"{env_name}: intermediate segment {segment!r} on {model_name} "
                f"is not a nested model (kind={kind})"
            )
        model_name = payload
        dotted.append(segment)
    leaf = segments[-1]
    fields = _class_fields(PARITY["models"][model_name])
    if leaf not in fields:
        raise AssertionError(f"{env_name}: no field {leaf!r} on {model_name}")
    kind, payload = _default_of(fields[leaf])
    dotted.append(leaf)
    return model_name, leaf, kind, payload, ".".join(dotted)


def _values_agree(doc_value, field_value) -> bool:
    """Equal values, with bool/int kept distinct (True != 1 here)."""
    if isinstance(doc_value, bool) != isinstance(field_value, bool):
        return False
    return doc_value == field_value


def test_environment_variables_section_is_present() -> None:
    assert PARITY["documented"], (
        "the module docstring no longer contains an 'Environment Variables' "
        "table; the parity guard has nothing left to compare"
    )


@pytest.mark.parametrize("env_name", sorted(KNOWN_DRIFT))
def test_known_drift_entries_are_still_documented(env_name: str) -> None:
    assert env_name in PARITY["documented"], (
        f"{env_name} is listed as known drift but no longer appears in the "
        "docstring table; remove it from KNOWN_DRIFT"
    )


@pytest.mark.parametrize("env_name", sorted(PARITY["documented"]))
def test_documented_default_matches_field_default(
    env_name: str, request: pytest.FixtureRequest
) -> None:
    if env_name in KNOWN_DRIFT:
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                reason=(
                    "known pre-existing docstring/Field drift, "
                    "tracked for fix by docs-env-config-drift"
                ),
            )
        )
    model_name, field_name, kind, field_default, dotted = _resolve_field(env_name)
    assert kind == LITERAL, (
        f"{env_name} -> {model_name}.{dotted}: Field default is not a static "
        f"literal (kind={kind}); cannot be described by a docstring note"
    )
    doc_default = _docstring_default(PARITY["documented"][env_name])
    assert doc_default is not None, (
        f"{env_name} -> {model_name}.{dotted}: docstring entry has no "
        f"'(default: ...)' note: {PARITY['documented'][env_name]!r}"
    )
    assert _values_agree(doc_default, field_default), (
        f"{env_name} -> {model_name}.{dotted}: docstring default "
        f"{doc_default!r} != Field default {field_default!r}"
    )


def test_every_literal_default_field_of_documented_models_is_documented() -> None:
    """Reverse direction: literal-defaulted fields must appear in the table."""

    def expected_names(model_name: str, parents: list[str]) -> dict[str, str]:
        expected: dict[str, str] = {}
        for field_name, value in _class_fields(PARITY["models"][model_name]).items():
            kind, payload = _default_of(value)
            if kind == FACTORY and payload in PARITY["models"]:
                expected.update(expected_names(payload, parents + [field_name]))
            elif kind == LITERAL:
                env = (PARITY["prefix"] + PARITY["delimiter"].join(parents + [field_name])).upper()
                expected[env] = f"{model_name}.{field_name}"
        return expected

    expected = expected_names(PARITY["settings_name"], [])
    undocumented = {
        env: owner for env, owner in expected.items() if env not in PARITY["documented"]
    }
    assert not undocumented, (
        "fields with literal defaults missing from the docstring table: "
        + ", ".join(f"{env} ({owner})" for env, owner in sorted(undocumented.items()))
    )
