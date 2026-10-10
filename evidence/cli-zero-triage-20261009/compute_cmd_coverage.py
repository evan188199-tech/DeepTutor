#!/usr/bin/env python3
"""Command-level coverage for deeptutor_cli command modules.

Deterministic and reproducible. For every module under ``deeptutor_cli``
that registers typer commands it derives:

- the CLI group name(s) from ``main.py`` (``add_typer(VAR, name="G")`` +
  ``register_alias(VAR)`` + ``from .MODULE import register as register_alias``),
- registered command names (regex ``@VAR.command("name")``),
- which (group, command) pairs are invoked anywhere under ``tests/``:
  every ``.invoke(`` call is paren-matched to its closing paren and all
  quoted string literals inside the argument list are collected; a group
  command counts as invoked iff the group name appears in the list and
  the command name appears after it in the same list. Root-level
  commands (registered on ``app`` directly) count iff the command name
  appears in any list.
- ``uncovered_cmds`` = registered - invoked.

Non-command modules report ``None`` for command fields; their uncovered
surface is counted separately in the report (public symbols with no
direct test reference).

Usage: python compute_cmd_coverage.py <repo-root> [out.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def parse_groups(main_py: str) -> dict[str, list[str]]:
    """module file stem -> group names, derived from main.py wiring."""
    alias_to_module: dict[str, str] = {}
    for m in re.finditer(
        r"from \.(\w+) import register as register_(\w+)", main_py
    ):
        alias_to_module[m.group(2)] = m.group(1)
    var_to_groups: dict[str, list[str]] = {}
    for m in re.finditer(r'add_typer\((\w+_app), name="(\w+)"\)', main_py):
        var_to_groups.setdefault(m.group(1), []).append(m.group(2))
    module_groups: dict[str, list[str]] = {}
    for m in re.finditer(r"register_(\w+)\((\w+)\)", main_py):
        alias, var = m.group(1), m.group(2)
        if alias in alias_to_module and var in var_to_groups:
            module_groups.setdefault(alias_to_module[alias], []).extend(
                var_to_groups[var]
            )
    return module_groups


def invoke_string_lists(text: str) -> list[list[str]]:
    """All quoted-string literals inside each paren-matched .invoke(...) call."""
    out: list[list[str]] = []
    for m in re.finditer(r"\.invoke\(", text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        body = text[m.end() : i - 1]
        out.append(re.findall(r'"([^"]*)"', body))
    return out


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    pkg = root / "deeptutor_cli"

    main_py = (pkg / "main.py").read_text(encoding="utf-8")
    groups = parse_groups(main_py)

    test_invocations: list[list[str]] = []
    for tf in sorted((root / "tests").rglob("*.py")):
        if "__pycache__" in tf.parts:
            continue
        text = tf.read_text(encoding="utf-8", errors="replace")
        test_invocations.extend(invoke_string_lists(text))

    def invoked(group: str, cmd: str) -> bool:
        for strings in test_invocations:
            if group == "":  # root-level command
                if cmd in strings:
                    return True
            elif group in strings:
                rest = strings[strings.index(group) + 1 :]
                if cmd in rest:
                    return True
        return False

    rows = []
    for path in sorted(pkg.glob("*.py")):
        if path.name.startswith("__"):
            continue
        stem = path.stem
        text = path.read_text(encoding="utf-8", errors="replace")
        cmds = re.findall(r'@(\w+)\.command\("?([\w-]+)"?\)', text)
        if not cmds:
            rows.append({
                "module": stem,
                "groups": groups.get(stem, []),
                "commands": [],
                "invoked": [],
                "uncovered_cmds": None,
                "uncovered": [],
            })
            continue
        group_names = groups.get(stem, [])
        if not group_names:
            group_names = [""]  # doctor / init register on the root app
        reg = [cmd for _var, cmd in cmds]
        inv = [
            cmd for cmd in reg
            if any(invoked(g, cmd) for g in group_names)
        ]
        rows.append({
            "module": stem,
            "groups": [g for g in group_names if g],
            "commands": reg,
            "invoked": inv,
            "uncovered_cmds": len(set(reg) - set(inv)),
            "uncovered": sorted(set(reg) - set(inv)),
        })

    rows.sort(key=lambda r: (
        -(r["uncovered_cmds"] if r["uncovered_cmds"] is not None else -1),
        r["module"],
    ))
    payload = {"invoke_calls_scanned": len(test_invocations), "modules": rows}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
