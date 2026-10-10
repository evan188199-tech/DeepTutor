#!/usr/bin/env python3
"""Read-only secret-hygiene scan of the DeepTutor repo.

Axes (per card):
  A. hardcoded default credentials / sample keys in defaults
  B. debug / permissive configuration enabled by default
  C. key file on-disk locations and permissions (inventory)
  D. call sites that may log key fragments

Output: findings.candidates.json (machine triage input; neutral — no secret
values are captured). Final graded list is findings.json (hand-triaged from
these candidates plus manual review), rendered into report.md.

Dedup (referenced, not re-reported):
  - scan-log-exception-bodies  — exception-body leakage in log messages
  - fix-provider-body-leak     — provider response bodies in user-facing errors
  - test-secret-files          — tests/utils/test_secret_files_helpers.py scope
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "findings.candidates.json"

SECRET_NAME_RE = re.compile(
    r"(api[_-]?key|apikey|secret|password|passwd|token|credential|auth[_-]?header|bearer)",
    re.IGNORECASE,
)
KEY_LITERAL_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
    r"|AKIA[A-Z0-9]{12,}|AIza[A-Za-z0-9_-]{20,}|xox[bap]-[A-Za-z0-9-]{10,})"
)
PLACEHOLDER_RE = re.compile(
    r"^(\$\{.*\}|<.*>|\{\{.*\}\}|sk-no-key-required|no-key|changeme|change-me"
    r"|your[-_a-z0-9]*|example[-_a-z0-9]*|test|placeholder|xxx+|\*+|_{3,})$",
    re.IGNORECASE,
)
SENTINELS = {"sk-no-key-required", "no-key", ""}

EXCLUDE_DIRS = {
    ".git", "node_modules", ".next", "dist", "build", "__pycache__",
    ".pytest_cache", ".mypy_cache", "evidence", "data", "logs", "backups",
    "home=", "docs-for-user", "assets",
}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".yaml", ".yml", ".json", ".toml", ".example", ".env"}


def iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.suffix in SOURCE_SUFFIXES or path.name.startswith(".env"):
            yield path, rel


def is_test(rel: Path) -> bool:
    return any(part in {"tests", "test", "__tests__", "e2e"} for part in rel.parts)


candidates: list[dict] = []


def add(rule: str, axis: str, rel: Path, line: int, severity: str, note: str):
    candidates.append(
        {
            "rule": rule,
            "axis": axis,
            "location": f"{rel.as_posix()}:{line}",
            "severity": severity,
            "note": note,
        }
    )


# ---------------------------------------------------------------- axis A
def scan_axis_a():
    # A1: os.getenv(NAME, "<literal>") with secret-ish NAME and non-placeholder default
    getenv_re = re.compile(
        r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Za-z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN)[A-Za-z0-9_]*)[\"']\s*,\s*[\"']([^\"']*)[\"']",
        re.IGNORECASE,
    )
    # A2: dict/kwarg style default  key="literal"  in config modules
    assign_re = re.compile(
        r"[\"']?([A-Za-z0-9_]*(?:api_key|apikey|secret|password|passwd|token)[A-Za-z0-9_]*)[\"']?\s*[:=]\s*[\"']([^\"']{6,})[\"']",
        re.IGNORECASE,
    )
    for path, rel in iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if is_test(rel):
                continue
            m = getenv_re.search(line)
            if m and m.group(2).strip() and not PLACEHOLDER_RE.match(m.group(2).strip()):
                add("A1-env-secret-default", "A", rel, i, "high", "secret-named env var with non-empty literal default")
            for m in assign_re.finditer(line):
                val = m.group(2).strip()
                if PLACEHOLDER_RE.match(val) or val in SENTINELS:
                    continue
                if KEY_LITERAL_RE.search(val):
                    add("A2-hardcoded-key-literal", "A", rel, i, "high", "provider-key-shaped literal in source")
                elif not is_test(rel) and m.group(1).lower() in {"api_key", "secret", "password", "token", "client_secret"} and val.lower() not in {"true", "false"}:
                    add("A2-hardcoded-key-literal", "A", rel, i, "medium", "secret-named field with literal value")
            for m in KEY_LITERAL_RE.finditer(line):
                add("A3-provider-key-prefix", "A", rel, i, "high", "provider key prefix pattern in source")


# ---------------------------------------------------------------- axis B
B_PATTERNS = [
    (r"allow_origin_regex\s*=\s*None if .*\s*else\s*r?['\"]https?://", "B2-cors-permissive-when-auth-off", "medium"),
    (r"[\"']enabled[\"']\s*:\s*False", "B1-auth-disabled-default", "info"),
    (r"cookie_secure[\"']?\s*:\s*False", "B5-cookie-secure-default-false", "low"),
    (r"sandbox_allow_subprocess[\"']?\s*:\s*True", "B7-sandbox-subprocess-default-on", "info"),
    (r"verify=False", "B6-tls-verify-false-site", "low"),
    (r"FastAPI\(", "B4-fastapi-default-docs", "info"),
    (r"^\s*-?\s*[\"']?\$\{[A-Z_]*(?:PORT|BACKEND|FRONTEND|POCKETBASE)[A-Z_]*[^}]*\}:\d+", "B3-compose-port-no-loopback", "medium"),
]


def scan_axis_b():
    for path, rel in iter_files():
        if is_test(rel):
            continue
        name = rel.name
        if not (name.endswith(".py") or "compose" in name or "Dockerfile" in name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, rule, sev in B_PATTERNS:
                if re.search(pat, line):
                    add(rule, "B", rel, i, sev, "pattern match (see report for context)")


# ---------------------------------------------------------------- axis C
C_WRITES = re.compile(
    r"(write_secret_text|atomic_write_(?:text|json)|\.write_text\(|json\.dump\(|\.open\(\s*[\"']w|os\.chmod|\.chmod\()"
)


def scan_axis_c():
    for path, rel in iter_files():
        if path.suffix != ".py" or is_test(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if C_WRITES.search(line):
                add("C1-persist-site", "C", rel, i, "info", "file-write call site (inventory; triage for secret-bearing payloads)")


# ---------------------------------------------------------------- axis D
class LogSecretVisitor(ast.NodeVisitor):
    def __init__(self, rel: Path, src: str):
        self.rel = rel
        self.lines = src.splitlines()
        self.hits: list[tuple[int, str]] = []

    def _expr_mentions_secret(self, node) -> str | None:
        if isinstance(node, ast.Name):
            return node.id if SECRET_NAME_RE.search(node.id) else None
        if isinstance(node, ast.Attribute):
            return node.attr if SECRET_NAME_RE.search(node.attr) else None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value if SECRET_NAME_RE.search(node.value) else None
        if isinstance(node, ast.JoinedStr):  # f-string
            for val in node.values:
                name = self._expr_mentions_secret(val)
                if name:
                    return name
            return None
        if isinstance(node, ast.FormattedValue):
            return self._expr_mentions_secret(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"str", "repr", "format"}:
            for arg in node.args:
                name = self._expr_mentions_secret(arg)
                if name:
                    return name
        return None

    def visit_Call(self, node: ast.Call):
        func = node.func
        is_log = False
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            is_log = func.attr in {"debug", "info", "warning", "error", "exception", "critical", "print"}
        elif isinstance(func, ast.Name):
            is_log = func.id == "print"
        if is_log:
            for arg in node.args:
                name = self._expr_mentions_secret(arg)
                if name:
                    line = getattr(node, "lineno", 0)
                    snippet = self.lines[line - 1].strip()[:160] if line else ""
                    self.hits.append((line, snippet))
                    break
        self.generic_visit(node)


def scan_axis_d():
    for path, rel in iter_files():
        if path.suffix != ".py" or is_test(rel):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        visitor = LogSecretVisitor(rel, src)
        visitor.visit(tree)
        for line, _snippet in visitor.hits:
            add("D1-log-secret-candidate", "D", rel, line, "info", "logging call mentions secret-named identifier (triage)")


def main() -> int:
    scan_axis_a()
    scan_axis_b()
    scan_axis_c()
    scan_axis_d()
    OUT.write_text(json.dumps(candidates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for c in candidates:
        counts[c["rule"]] = counts.get(c["rule"], 0) + 1
    print(json.dumps(counts, indent=2))
    print(f"total candidates: {len(candidates)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
