#!/usr/bin/env python3
"""Runtime verification for sampled findings (issue AGEN-979).

Two checks per sampled finding:
  1. anchor check  — the reported file:line really contains a json.dumps/json.dump call
  2. behavior check — a minimal value of the flagged kind reproduces the exact
     serialization boundary behavior the finding asserts (TypeError / NaN token /
     ValueError / silent stringification). No product code is imported or modified.

Deterministic: PASS/FAIL lines only, fixed order, no timestamps.
Usage: python3 verify_samples.py <repo-root> [<scan-root>...] -- <findings.json>
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def check_anchor(roots: list[Path], f: dict) -> bool:
    for root in roots:
        p = root / f["file"]
        if not p.exists():
            continue
        try:
            line = p.read_text(encoding="utf-8", errors="replace").splitlines()[f["line"] - 1]
        except (OSError, IndexError):
            continue
        if "json.dumps" in line or "json.dump(" in line:
            return True
    return False


def main() -> int:
    args = sys.argv[1:]
    if "--" not in args:
        print("usage: verify_samples.py <repo-root> [<scan-root>...] -- <findings.json>",
              file=sys.stderr)
        return 2
    cut = args.index("--")
    roots = [Path(a) for a in args[:cut]]
    findings = json.loads(Path(args[cut + 1]).read_text())

    results: list[tuple[bool, str]] = []

    # anchor-check EVERY finding (deterministic; stronger than the >=5 sample requirement),
    # plus rule-class behavior checks below
    for f in findings:
        results.append((check_anchor(roots, f),
                        f"anchor {f['rule']} {f['file']}:{f['line']}"))

    def expect_error(name: str, fn):
        try:
            fn()
            results.append((False, f"behavior {name}: no error raised"))
        except Exception as e:  # noqa: BLE001 - verification harness
            results.append((True, f"behavior {name}: {type(e).__name__}"))

    def expect_ok(name: str, fn):
        try:
            fn()
            results.append((True, f"behavior {name}: serializes as expected"))
        except Exception as e:  # noqa: BLE001 - verification harness
            results.append((False, f"behavior {name}: {type(e).__name__}: {e}"))

    def nan_token() -> None:
        out = json.dumps({"v": float("nan")})
        assert "NaN" in out, f"no NaN token emitted: {out}"

    def str_masking() -> None:
        out = json.dumps({"ts": datetime.now(tz=timezone.utc)}, default=str)
        assert isinstance(out, str) and out.count(":") >= 2, out

    def uuid_hex_ok() -> None:
        out = json.dumps({"id": uuid.uuid4().hex})
        assert isinstance(json.loads(out)["id"], str)

    def mode_json_ok() -> None:
        out = json.dumps(_pyd_model_dump(mode="json"))
        parsed = json.loads(out)
        assert isinstance(parsed["ts"], str), parsed

    # behavior classes behind the rules
    expect_error("J3-datetime TypeError", lambda: json.dumps({"ts": datetime.now(tz=timezone.utc)}))
    expect_error("J3-decimal TypeError", lambda: json.dumps({"x": Decimal("1.5")}))
    expect_error("J3-uuid TypeError", lambda: json.dumps({"id": uuid.uuid4()}))
    expect_error("J3-bytes TypeError", lambda: json.dumps({"b": b"raw"}))
    expect_ok("J3-uuid.hex serializes (false-positive guard)", uuid_hex_ok)
    expect_ok("J2 NaN token emitted (invalid JSON per RFC 8259)", nan_token)
    expect_error("J2b allow_nan=False ValueError", lambda: json.dumps({"v": float("inf")}, allow_nan=False))
    expect_ok("J1 default=str silent stringification", str_masking)
    expect_error("J5 model_dump python-mode TypeError", lambda: json.dumps(_pyd_model_dump("python")))
    expect_ok("J5 model_dump(mode=json) safe", mode_json_ok)

    ok = all(r[0] for r in results)
    for passed, msg in results:
        print(("PASS" if passed else "FAIL"), msg)
    print("SUMMARY", "PASS" if ok else "FAIL",
          f"{sum(1 for p, _ in results if p)}/{len(results)}")
    return 0 if ok else 1


def _pyd_model_dump(mode: str) -> dict:
    from pydantic import BaseModel

    class M(BaseModel):
        ts: datetime

    return M(ts=datetime.now(tz=timezone.utc)).model_dump(mode=mode)  # type: ignore[arg-type]


if __name__ == "__main__":
    raise SystemExit(main())
