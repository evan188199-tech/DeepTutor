#!/usr/bin/env python3
"""AGEN-856 helper: per-directory .py inventory + type-ignore density (stdlib only).

Read-only: only walks the tree and reads files.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?!\s*:)")  # bare + [code] forms
EXCLUDE_RE = re.compile(r"^(tests/|scripts/|deeptutor/agents/|deeptutor/services/rag/|deeptutor/api/routers/)")


def dir_key(rel: str) -> str:
    parts = rel.split(os.sep)
    if parts[0] == "deeptutor":
        return "deeptutor/" + parts[1] if len(parts) > 2 else "deeptutor"
    if parts[0] == "deeptutor_cli":
        return "deeptutor_cli/" + parts[1] if len(parts) > 2 else "deeptutor_cli"
    return parts[0]


def main() -> None:
    stats: dict[str, dict] = {}
    for base in ("deeptutor", "deeptutor_cli"):
        for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                key = dir_key(rel)
                d = stats.setdefault(key, {"files": 0, "loc": 0, "type_ignores": 0})
                d["files"] += 1
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        for line in f:
                            d["loc"] += 1
                            if IGNORE_RE.search(line):
                                d["type_ignores"] += 1
                except OSError:
                    pass
    out = {}
    for key in sorted(stats):
        d = stats[key]
        rel_probe = key  # directory-level; exclude regex applies to file paths
        out[key] = {
            **d,
            "type_ignores_per_kloc": round(d["type_ignores"] * 1000 / d["loc"], 2) if d["loc"] else 0.0,
            "in_precommit_gate": not EXCLUDE_RE.match(rel_probe + "/"),
            "note": "tools.* has pyproject override ignore_errors; services/rag, api/routers, agents, tests, scripts excluded by pre-commit",
        }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
