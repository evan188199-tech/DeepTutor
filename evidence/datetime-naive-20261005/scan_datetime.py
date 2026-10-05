#!/usr/bin/env python3
"""AST scan for naive/aware datetime usage in deeptutor/ (read-only).

Patterns:
  - naive producers: datetime.now() / utcnow() / today() without tz arg,
    date.today(), datetime.fromtimestamp(ts) without tz,
    datetime.fromisoformat() on unknown input (naive-or-aware)
  - aware producers: datetime.now(<tz>), fromtimestamp(ts, tz=...),
    fromisoformat(...).replace(tzinfo=...), .astimezone()
  - mixing points: Compare/BinOp(sub) between expressions of
    different (known) tz-ness.

Outputs JSON to stdout.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("deeptutor")

NAIVE_CALLS = {"utcnow", "today"}          # datetime.<name>() always naive
TZ_MOD_NAMES = {"timezone", "tzutc", "tzlocal", "pytz", "ZoneInfo", "tzinfo"}

files = sorted(ROOT.rglob("*.py"))
# exclude tests inside the package if any
files = [f for f in files if "test" not in f.name and "tests" not in f.parts]


def call_name(node: ast.AST) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return ""


def has_tz_arg(node: ast.Call, *, skip_first: bool = False) -> bool:
    args = node.args[1:] if skip_first else node.args
    if args:
        return True
    return "tz" in [kw.arg for kw in node.keywords if kw.arg]


def tz_in_expr(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in TZ_MOD_NAMES:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in TZ_MOD_NAMES:
            return True
        if isinstance(sub, ast.Call) and (
            "timezone" in call_name(sub) or "astimezone" in call_name(sub)
            or "zoneinfo" in call_name(sub).lower()
        ):
            return True
    return False


def classify_call(node: ast.Call, line_src: str) -> dict | None:
    name = call_name(node)
    info = {"line": node.lineno, "call": name, "src": line_src.strip()[:160]}
    if name == "datetime.now":
        info["kind"] = "naive" if not has_tz_arg(node) else "aware"
        info["pattern"] = "datetime.now()" if not has_tz_arg(node) else "datetime.now(tz)"
        return info
    if name == "datetime.utcnow":
        info["kind"] = "naive-utc"
        info["pattern"] = "datetime.utcnow()"
        return info
    if name == "datetime.today":
        info["kind"] = "naive"
        info["pattern"] = "datetime.today()"
        return info
    if name == "date.today":
        info["kind"] = "naive-date"
        info["pattern"] = "date.today()"
        return info
    if name == "datetime.fromtimestamp":
        aware = has_tz_arg(node, skip_first=True)
        info["kind"] = "aware" if aware else "naive-local"
        info["pattern"] = "fromtimestamp(tz)" if aware else "fromtimestamp(no-tz)"
        return info
    if name == "datetime.utcfromtimestamp":
        info["kind"] = "naive-utc"
        info["pattern"] = "utcfromtimestamp()"
        return info
    if name == "datetime.fromisoformat":
        # aware only if result is .replace(tzinfo=) / .astimezone() chained,
        # or arg statically contains Z/+00:00 replace
        arg = ast.unparse(node.args[0]) if node.args else ""
        if "Z" in arg or "+00:00" in arg:
            info["kind"] = "naive-or-aware"
            info["pattern"] = "fromisoformat(Z-normalized)"
        else:
            info["kind"] = "naive-or-aware"
            info["pattern"] = "fromisoformat(unknown-tz)"
        return info
    if name == "datetime.strptime":
        fmt = ast.unparse(node.args[1]) if len(node.args) > 1 else ""
        info["kind"] = "naive-or-aware" if "%z" not in fmt else "aware"
        info["pattern"] = "strptime(no-%z)" if "%z" not in fmt else "strptime(%z)"
        return info
    if name.endswith(".isoformat") or name.endswith(".timestamp"):
        info["kind"] = "serializer"
        base = node.func.value if isinstance(node.func, ast.Attribute) else None
        if isinstance(base, ast.Call) and call_name(base) == "datetime.fromtimestamp":
            aware = has_tz_arg(base, skip_first=True)
        elif isinstance(base, ast.Call):
            aware = has_tz_arg(base)
        else:
            aware = None
        info["tz"] = {True: "aware", False: "naive", None: "unknown"}[aware]
        info["pattern"] = name
        return info
    return None


results: dict[str, list] = {}
mixing: list[dict] = []

for path in files:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    tree = ast.parse(src)
    items = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            cls = classify_call(node, lines[node.lineno - 1] if node.lineno <= len(lines) else "")
            if cls:
                cls["file"] = str(path)
                items.append(cls)
        # mixing detection: compare or minus between two call-derived datetimes
        if isinstance(node, (ast.Compare, ast.BinOp)):
            ops = []
            if isinstance(node, ast.Compare):
                ops = [type(o).__name__ for o in node.ops]
                sides = [node.left] + list(node.comparators)
            else:
                if isinstance(node.op, ast.Sub):
                    ops = ["Sub"]
                sides = [node.left, node.right]
            if not ops:
                continue
            dt_sides = []
            for s in sides:
                found = None
                for sub in ast.walk(s):
                    if isinstance(sub, ast.Call) and call_name(sub) in {
                        "datetime.now", "datetime.utcnow", "datetime.today",
                        "datetime.fromisoformat", "datetime.fromtimestamp",
                        "date.today", "datetime.strptime",
                    }:
                        found = call_name(sub)
                        break
                if found:
                    dt_sides.append(found)
            if len(set(dt_sides)) >= 2 or (
                len(dt_sides) == 2 and dt_sides[0] == dt_sides[1]
                and any(k in dt_sides[0] for k in ("now", "fromisoformat"))
            ):
                mixing.append({
                    "file": str(path), "line": node.lineno,
                    "ops": ops, "sides": dt_sides,
                    "src": (lines[node.lineno - 1].strip()[:200] if node.lineno <= len(lines) else ""),
                })
    if items:
        results[str(path)] = items

json.dump({"call_sites": results, "mixing_candidates": mixing}, sys.stdout, indent=1, ensure_ascii=False)
