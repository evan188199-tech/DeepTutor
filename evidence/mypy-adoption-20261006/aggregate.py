#!/usr/bin/env python3
"""AGEN-856 helper: aggregate mypy raw outputs into stats.json (stdlib only).

Covers runs A-G (see run_inventory.sh). For gate-surface runs (E/F/G) both the
raw total and the pre-commit-exclude-filtered surface are reported.
"""
import json
import os
import re
from collections import Counter, defaultdict

EV = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(EV, "raw")
ERR_RE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+): error: (?P<msg>.*) \[(?P<code>[\w-]+)\]$")
EXCLUDE_RE = re.compile(r"^(tests/|scripts/|deeptutor/agents/|deeptutor/services/rag/|deeptutor/api/routers/)")

RUNS = {
    "A_baseline": "mypy_runA_baseline.txt",
    "B_firststep": "mypy_runB_firststep.txt",
    "C_annotations": "mypy_runC_annotations.txt",
    "D_baseline_no_strict_optional": "mypy_runD_gate.txt",
    "E_truegate_no_stubs": "mypy_runE_truegate.txt",
    "F_hookenv": "mypy_runF_hookenv.txt",
    "G_hookenv_strict_optional": "mypy_runG_nostrictsoff.txt",
}


def dir_key(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "deeptutor":
        return "deeptutor/" + parts[1] if len(parts) > 2 else "deeptutor"
    if parts[0] == "deeptutor_cli":
        return "deeptutor_cli/" + parts[1] if len(parts) > 2 else "deeptutor_cli"
    return parts[0]


def parse(name: str) -> tuple[dict, Counter, list]:
    per_dir = defaultdict(lambda: {"errors": 0, "files": set(), "codes": Counter()})
    codes = Counter()
    gate_surface = defaultdict(int)
    rows = []
    with open(os.path.join(RAW, name), encoding="utf-8") as f:
        for line in f:
            m = ERR_RE.match(line.strip())
            if not m:
                continue
            path = m.group("path")
            rel = os.path.relpath(path) if os.path.isabs(path) else path
            key = dir_key(rel)
            per_dir[key]["errors"] += 1
            per_dir[key]["files"].add(rel)
            per_dir[key]["codes"][m.group("code")] += 1
            codes[m.group("code")] += 1
            if not EXCLUDE_RE.match(rel):
                gate_surface[key] += 1
            rows.append({"path": rel, "line": int(m.group("line")), "code": m.group("code")})
    out = {}
    for key, d in per_dir.items():
        out[key] = {
            "errors": d["errors"],
            "error_files": len(d["files"]),
            "codes": dict(d["codes"].most_common(5)),
            "gate_would_surface": gate_surface.get(key, 0),
        }
    return out, codes, rows


def main() -> None:
    stats: dict = {"runs": {}}
    for run, fname in RUNS.items():
        per_dir, codes, rows = parse(fname)
        gate = sum(d["gate_would_surface"] for d in per_dir.values())
        stats["runs"][run] = {
            "total_errors": sum(d["errors"] for d in per_dir.values()),
            "precommit_surface_errors": gate,
            "error_codes_total": dict(codes.most_common()),
            "per_directory": dict(sorted(per_dir.items(), key=lambda kv: -kv[1]["errors"])),
        }
        with open(os.path.join(RAW, f"errors_{run.split('_')[0]}.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
    with open(os.path.join(EV, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    for run, s in stats["runs"].items():
        print(f"{run}: total={s['total_errors']} precommit_surface={s['precommit_surface_errors']}")


if __name__ == "__main__":
    main()
