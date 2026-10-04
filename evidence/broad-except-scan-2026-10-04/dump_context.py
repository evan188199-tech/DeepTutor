#!/usr/bin/env python3
"""Dump readable code context for every site in the classification worklist."""

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    worklist = json.loads(Path(sys.argv[2]).read_text())
    out = Path(sys.argv[3])
    lines = []
    for item in worklist:
        src_path = root / item["path"]
        src_lines = src_path.read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(0, item["line"] - 16)
        hi = min(len(src_lines), item["end_line"] + 4)
        lines.append(
            f"\n===== [{item['idx']}] {item['risk']} {item['path']}:{item['line']} "
            f"exc={item['exc_type']} func={item['function']} silent={item.get('silent')} ====="
        )
        for n in range(lo, hi):
            marker = ">>" if n + 1 == item["line"] else "  "
            lines.append(f"{marker} {n+1:5d}| {src_lines[n]}")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(worklist)} contexts to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
