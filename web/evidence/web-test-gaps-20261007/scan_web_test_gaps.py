#!/usr/bin/env python3
"""Static test-coverage gap scanner for the web/ frontend.

Maps source modules under web/ to the existing test corpus using pure
static reference matching. No test suite is executed.

Test corpus and runners (static facts, from web/package.json and configs):
  - vitest (`npm run test:unit`): vitest.config.mts include rule
    "tests/**/*.spec.ts" + "tests/**/*.spec.tsx" (jsdom, setup
    tests/setup/rendered.ts).
  - node runner (`npm run test:node`): scripts/run-node-tests.mjs compiles
    tsconfig.node-tests.json ("tests/**/*.ts") and executes compiled
    tests/**/*.test.js; source form is tests/**/*.test.ts.
  - playwright (`npm run audit`, test:e2e:*): playwright.config.ts
    testDir ./tests, testMatch **/*.audit.ts.

Reference detection per source file:
  - path_ref: any test file's text contains the source's web-root-relative
    POSIX path without extension (matches "@/...", "../...", "./..." and
    dynamic import specifiers). For index.ts/index.tsx the directory path
    without extension is used instead.
  - base_ref: word-boundary match of the file basename, skipped for generic
    Next.js names (index/page/layout/route/...) that would match everything.

Classification (static judgement, deterministic):
  - covered : at least one path_ref from a non-meta vitest or node test.
  - weak    : referenced somewhere, but never by path from a non-meta
              unit/node test (e.g. only playwright audit files, only
              meta/contract tests, or basename-only mentions); or not
              referenced directly at all, but re-exported through a
              nearest barrel (index.ts/index.tsx in the same category
              directory) that is itself covered.
  - zero    : no references in any test file and no covered barrel
              re-exports it.

Meta tests (structural/contract checks that read sources as text rather
than exercise module behaviour): architecture-contracts, no-* static
import-boundary tests, internal-route-contract, generated-contracts,
design-token-parity, tooling-config, i18n-audit, i18n-placeholders.
(route-params.test.ts is excluded from the meta list: it behaviourally
imports ../lib/route-params.)

Usage: python3 scan_web_test_gaps.py [--web-root PATH]
Writes summary.json next to this script. Same tree in -> same bytes out.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

CODE_EXTS = {".ts", ".tsx", ".mts", ".mjs", ".js", ".jsx"}
GENERIC_BASES = {
    "index",
    "page",
    "layout",
    "route",
    "loading",
    "error",
    "template",
    "globals",
    "not-found",
    "default",
}
META_TESTS = {
    "architecture-contracts.test.ts",
    "no-page-module-imports.test.ts",
    "no-unified-chat-context.test.ts",
    "no-v1-chat-surface.test.ts",
    "internal-route-contract.test.ts",
    "generated-contracts.test.ts",
    "design-token-parity.test.ts",
    "tooling-config.test.ts",
    "i18n-audit.spec.ts",
    "i18n-placeholders.test.ts",
}
SOURCE_DIRS = [
    "app",
    "components",
    "context",
    "contracts",
    "eslint",
    "features",
    "hooks",
    "i18n",
    "lib",
    "scripts",
    "shared",
]
ACTIONABLE_CATEGORIES = {
    "app",
    "components",
    "context",
    "contracts",
    "features",
    "hooks",
    "i18n",
    "lib",
    "scripts",
    "shared",
}
CATEGORY_WEIGHT = {
    "lib": 5.0,
    "hooks": 4.0,
    "shared": 4.0,
    "context": 4.0,
    "contracts": 3.0,
    "features": 3.0,
    "i18n": 3.0,
    "scripts": 2.0,
    "components": 1.5,
    "app": 1.0,
    "root": 1.0,
    "eslint": 0.0,
    "types": 0.0,
    "config": 0.0,
}


def kind_of(name: str) -> str | None:
    if name.endswith((".spec.ts", ".spec.tsx")):
        return "vitest"
    if name.endswith(".test.ts"):
        return "node"
    if name.endswith(".audit.ts"):
        return "playwright"
    return None


def collect_sources(web_root: Path) -> list[dict]:
    sources: list[dict] = []
    seen: set[Path] = set()

    def add(path: Path, category: str, actionable: bool) -> None:
        rel = path.relative_to(web_root)
        posix_rel = rel.as_posix()
        if posix_rel.startswith("contracts/generated/"):
            return
        if path.name.endswith(".d.ts"):
            return
        if path in seen:
            return
        seen.add(path)
        is_index = path.stem == "index"
        stem = path.stem
        base_generic = stem.lower() in GENERIC_BASES
        sources.append(
            {
                "path": posix_rel,
                "category": category,
                "loc": len(path.read_text(encoding="utf-8", errors="replace").splitlines()),
                "ext": path.suffix,
                "is_index": is_index,
                "match_key": rel.with_suffix("").as_posix() if not is_index else rel.parent.as_posix(),
                "base": None if base_generic or is_index else stem,
                "actionable": actionable,
            }
        )

    for cat in SOURCE_DIRS:
        base_dir = web_root / cat
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*")):
            if not path.is_file() or path.suffix not in CODE_EXTS:
                continue
            actionable = cat in ACTIONABLE_CATEGORIES
            add(path, cat, actionable)

    for path in sorted(web_root.glob("*")):
        if not path.is_file() or path.suffix not in CODE_EXTS:
            continue
        if path.name.startswith("next-env"):
            continue
        if re.search(r"\.(config|rc)\.", path.name) or path.name == "eslint.config.mjs":
            add(path, "config", False)
        else:
            add(path, "root", True)

    return sources


def collect_tests(web_root: Path) -> list[dict]:
    tests: list[dict] = []
    tests_dir = web_root / "tests"
    for path in sorted(tests_dir.rglob("*")):
        if not path.is_file():
            continue
        kind = kind_of(path.name)
        if kind is None:
            continue
        rel = path.relative_to(web_root).as_posix()
        tests.append(
            {
                "path": rel,
                "kind": kind,
                "meta": path.name in META_TESTS,
                "content": path.read_text(encoding="utf-8", errors="replace"),
            }
        )
    return tests


def classify(sources: list[dict], tests: list[dict]) -> list[dict]:
    results = []
    for src in sources:
        match_key = src["match_key"]
        base = src["base"]
        base_re = re.compile(rf"\b{re.escape(base)}\b") if base else None
        path_ref_kinds: Counter = Counter()
        base_ref_kinds: Counter = Counter()
        refs_by_kind: dict[str, list[str]] = {}
        for test in tests:
            hit_path = match_key in test["content"]
            hit_base = bool(base_re and base_re.search(test["content"]))
            if not (hit_path or hit_base):
                continue
            bucket = test["kind"] if not test["meta"] else "meta"
            if hit_path:
                path_ref_kinds[bucket] += 1
            if hit_base and not hit_path:
                base_ref_kinds[bucket] += 1
            refs_by_kind.setdefault(bucket, []).append(test["path"])

        unit_or_node_path = path_ref_kinds["vitest"] + path_ref_kinds["node"]
        any_ref = sum(path_ref_kinds.values()) + sum(base_ref_kinds.values())
        if unit_or_node_path > 0:
            status = "covered"
        elif any_ref > 0:
            status = "weak"
        else:
            status = "zero"

        basis_bits = []
        if path_ref_kinds:
            basis_bits.append(
                "path-refs: " + ", ".join(f"{k}={v}" for k, v in sorted(path_ref_kinds.items()))
            )
        if base_ref_kinds:
            basis_bits.append(
                "basename-only refs: " + ", ".join(f"{k}={v}" for k, v in sorted(base_ref_kinds.items()))
            )
        if not basis_bits:
            basis = "no test file references this path or basename"
        else:
            basis = "; ".join(basis_bits)

        results.append(
            {
                "path": src["path"],
                "category": src["category"],
                "loc": src["loc"],
                "ext": src["ext"],
                "status": status,
                "actionable": src["actionable"],
                "basis": basis,
                "refs": refs_by_kind if status != "covered" else {},
            }
        )
    return results


def top_candidates(results: list[dict], limit: int = 10) -> list[dict]:
    import math

    pool = [r for r in results if r["actionable"] and r["status"] in ("zero", "weak")]

    def score(r: dict) -> float:
        status_w = 2.0 if r["status"] == "zero" else 1.0
        cat_w = CATEGORY_WEIGHT.get(r["category"], 1.0)
        loc_w = math.log10(r["loc"] + 10)
        return status_w * cat_w * loc_w

    pool.sort(key=lambda r: (-score(r), r["path"]))
    out = []
    for r in pool[:limit]:
        reason = r["basis"]
        out.append(
            {
                "path": r["path"],
                "category": r["category"],
                "status": r["status"],
                "loc": r["loc"],
                "reason": reason,
            }
        )
    return out


def barrel_path(web_root: Path, src_rel: Path) -> Path | None:
    """Nearest barrel (index.ts/index.tsx) walking up within the category dir."""
    for parent in src_rel.parents:
        if parent == Path("."):
            break
        for barrel in (parent / "index.tsx", parent / "index.ts"):
            if (web_root / barrel).is_file():
                return barrel
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    web_root = Path(args.web_root).resolve()

    sources = collect_sources(web_root)
    tests = collect_tests(web_root)
    results = classify(sources, tests)

    by_match_key = {r["path"]: r for r in results}
    for r in results:
        if r["status"] != "zero" or not r["actionable"]:
            continue
        barrel = barrel_path(web_root, Path(r["path"]))
        if barrel is None:
            continue
        barrel_result = by_match_key.get(barrel.as_posix())
        if barrel_result is None or barrel_result["status"] != "covered":
            continue
        r["status"] = "weak"
        r["basis"] = (
            f"no direct test references; re-exported via covered barrel {barrel.as_posix()}"
            " (indirect reachability only)"
        )
        r["refs"] = {"barrel": [barrel.as_posix()]}

    by_status = Counter(r["status"] for r in results)
    by_cat_status: dict[str, Counter] = {}
    for r in results:
        by_cat_status.setdefault(r["category"], Counter())[r["status"]] += 1

    zero = sorted(
        (
            {
                "path": r["path"],
                "category": r["category"],
                "loc": r["loc"],
                "actionable": r["actionable"],
                "basis": r["basis"],
            }
            for r in results
            if r["status"] == "zero"
        ),
        key=lambda x: x["path"],
    )
    weak = sorted(
        (
            {
                "path": r["path"],
                "category": r["category"],
                "loc": r["loc"],
                "actionable": r["actionable"],
                "basis": r["basis"],
                "refs": r["refs"],
            }
            for r in results
            if r["status"] == "weak"
        ),
        key=lambda x: x["path"],
    )

    summary = {
        "scan": "web-test-gaps",
        "scope": "web/ (static file-level mapping; no tests executed)",
        "excluded": [
            "web/tests (test corpus itself)",
            "node_modules, dist, .next, vendor",
            "contracts/generated (generated)",
            "*.d.ts declarations",
            "tests/setup (fixtures)",
        ],
        "classification_rules": {
            "covered": "path referenced by at least one non-meta vitest (*.spec.*) or node (*.test.ts) test",
            "weak": "referenced somewhere but never by path from a non-meta unit/node test (audit-only, meta-only or basename-only)",
            "zero": "no references in any test file",
        },
        "totals": {
            "source_files": len(results),
            "covered": by_status["covered"],
            "weak": by_status["weak"],
            "zero": by_status["zero"],
            "test_files": len(tests),
            "by_kind": dict(Counter(t["kind"] for t in tests)),
            "actionable_zero_weak": sum(
                1 for r in results if r["actionable"] and r["status"] in ("zero", "weak")
            ),
        },
        "by_category": {
            cat: {k: v for k, v in sorted(counter.items())}
            for cat, counter in sorted(by_cat_status.items())
        },
        "top_candidates": top_candidates(results),
        "zero": zero,
        "weak": weak,
    }

    out_path = Path(__file__).resolve().parent / "summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"sources={len(results)} covered={by_status['covered']} weak={by_status['weak']} zero={by_status['zero']} tests={len(tests)}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
