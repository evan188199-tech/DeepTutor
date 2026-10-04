#!/usr/bin/env python3
"""Extract the 118 broad-except rows from DT-22 Appendix A into baseline JSON."""

import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8")
rows = []
pat = re.compile(r"^\| (HIGH|MEDIUM|LOW)\s*\| `([^`]+)`\s*\| ([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\|", re.M)
for m in pat.finditer(src):
    risk, loc, exc, body, func, tryline = [g.strip() for g in m.groups()]
    exc = exc.strip("` ")
    if exc in ("Exception", "BaseException"):
        f, _, ln = loc.rpartition(":")
        rows.append({
            "risk": risk, "file": f, "line": int(ln), "exc_type": exc,
            "handler": body.strip(), "function": func.strip(),
            "try_body_first_line": tryline.strip(),
        })
print(json.dumps({"count": len(rows), "rows": rows}, ensure_ascii=False, indent=1))
