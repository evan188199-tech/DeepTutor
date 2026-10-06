#!/usr/bin/env python3
"""Relocate AGEN-370 broad-except baseline rows (ef2d9e5c) on a rescan of f07029cf.

Read-only matching: for each baseline row (file/line/exc_type/handler/function/
try_body_first_line) find the same handler in the fresh scan using the identity
path + function + try-body-first-line, with the documented fallbacks for
renamed functions or changed try bodies (same rules as AGEN-666).

Outputs drift_status.json entries with status one of:
  still        - found at the same line
  line_drift   - found, line moved
  matched_loose- found only via fallback (path + partial identity)
  gone         - no candidate found (needs manual check)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def norm_func(f: str) -> str:
    return (f or "").strip().strip("`")


def main(baseline_path: str, rescan_path: str, out_path: str) -> None:
    baseline = json.loads(Path(baseline_path).read_text())["rows"]
    rescan = json.loads(Path(rescan_path).read_text())["entries"]
    silent = [e for e in rescan if e["silent"]]

    by_key: dict[tuple, list[dict]] = {}
    by_path: dict[str, list[dict]] = {}
    for e in silent:
        by_key.setdefault((e["path"], e["function"], e["try_body_first_line"]), []).append(e)
        by_path.setdefault(e["path"], []).append(e)

    out = []
    counts = {"still": 0, "line_drift": 0, "matched_loose": 0, "gone": 0}
    for row in baseline:
        f = row["file"]
        func = norm_func(row["function"])
        first = row["try_body_first_line"]
        etype = row["exc_type"]
        cand = list(by_key.get((f, func, first), []))
        how = "path+func+try_first"
        if not cand:
            # fallback 1: try body unchanged, function renamed
            cand = [e for e in by_path.get(f, []) if e["try_body_first_line"] == first]
            how = "path+try_first(func renamed)"
            if len(cand) > 1:
                same_body = [e for e in cand if e["handler_body"].strip() == (row["handler"] or "").strip()]
                if len(same_body) == 1:
                    cand, how = same_body, "path+try_first+handler(func renamed)"
        if not cand:
            # fallback 2: function kept, try body changed
            cand = [e for e in by_path.get(f, []) if e["function"] == func]
            how = "path+func(try body changed)"
            if len(cand) > 1:
                same_body = [e for e in cand if e["handler_body"].strip() == (row["handler"] or "").strip()]
                if len(same_body) == 1:
                    cand, how = same_body, "path+func+handler(try body changed)"
        if not cand:
            # fallback 3: same path + same handler body, any function
            cand = [e for e in by_path.get(f, []) if e["handler_body"].strip() == (row["handler"] or "").strip()]
            how = "path+handler"
        status = "gone"
        new_line = None
        new_type = None
        new_func = None
        if cand:
            e = min(cand, key=lambda x: abs(x["line"] - row["line"]))
            new_line = e["line"]
            new_type = e["exc_type"]
            new_func = e["function"]
            if len(cand) > 1:
                how += f" ({len(cand)} candidates, nearest chosen)"
            if new_line == row["line"]:
                status = "still"
            else:
                status = "line_drift"
        counts[status] += 1
        out.append({
            "risk": row["risk"],
            "path": f,
            "line": row["line"],
            "etype": etype,
            "handler": row["handler"],
            "func": func,
            "first": first,
            "status": status,
            "new_line": new_line,
            "new_type": new_type,
            "new_func": new_func,
            "how": how if cand else "no candidate",
        })

    Path(out_path).write_text(json.dumps({"py": out}, ensure_ascii=False, indent=1))
    print(json.dumps(counts))
    for r in out:
        if r["status"] != "still":
            print(r["status"], r["risk"], f"{r['path']}:{r['line']}", "->", r["new_line"], r["how"], file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
