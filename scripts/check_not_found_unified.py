#!/usr/bin/env python3
"""Fail if any api router still hardcodes a 404 detail literal.

Every ``HTTPException`` raised with a 404 status under ``deeptutor/api/routers``
must build its detail via the canonical helper (``deeptutor.api.errors.not_found``)
or the i18n ``t()`` keys. Details that merely forward a service-layer exception
message (``str(exc)``, local variables) carry no router-owned wording and are
reported as passthrough, not residuals.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "deeptutor" / "api" / "routers"

# 404 details that are NOT "resource missing" lookups (empty config / invalid
# content semantics). They may stay as literals; extend only after checking the
# wording cannot be expressed with not_found(). Entries are exact ast.unparse
# renderings so the match stays mechanical.
ALLOWED_NON_NOT_FOUND_DETAILS = {
    "'No default knowledge base is configured'",
    "f\"No retrieval modes for engine '{provider}'.\"",
    "f\"No '{payload.kind}' models configured.\"",
    "'Snapshot image is invalid.'",
}


def _status_is_404(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant) and expr.value == 404:
        return True
    return isinstance(expr, ast.Attribute) and expr.attr == "HTTP_404_NOT_FOUND"


def _detail_expr(call: ast.Call) -> ast.expr | None:
    for arg in call.args[1:2]:
        return arg
    for kw in call.keywords:
        if kw.arg == "detail":
            return kw.value
    return None


def scan(routers_dir: Path = ROUTERS_DIR) -> tuple[list[str], list[str]]:
    """Return (residuals, passthrough) descriptions for 404 details."""
    residuals: list[str] = []
    passthrough: list[str] = []
    for path in sorted(routers_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "HTTPException":
                continue
            status_expr = None
            for kw in node.keywords:
                if kw.arg == "status_code":
                    status_expr = kw.value
            if status_expr is None or not _status_is_404(status_expr):
                continue
            detail = _detail_expr(node)
            if detail is None:
                continue
            if isinstance(detail, (ast.JoinedStr, ast.Constant)):
                rendered = ast.unparse(detail)
                if rendered not in ALLOWED_NON_NOT_FOUND_DETAILS:
                    residuals.append(f"{path.name}:{node.lineno} detail={rendered}")
            else:
                passthrough.append(f"{path.name}:{node.lineno} detail={ast.unparse(detail)}")
    return residuals, passthrough


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--routers-dir",
        type=Path,
        default=ROUTERS_DIR,
        help="directory holding the router modules (default: deeptutor/api/routers)",
    )
    args = parser.parse_args()

    residuals, passthrough = scan(args.routers_dir)
    if residuals:
        print(f"not_found template residuals: {len(residuals)}")
        for line in residuals:
            print(f"  {line}")
        print("Replace hardcoded 404 details with deeptutor.api.errors.not_found().")
        return 1
    print(f"not_found template residuals: 0 (passthrough details: {len(passthrough)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
