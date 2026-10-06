#!/usr/bin/env python3
"""Read-only inventory of error-boundary coverage in the web/ frontend.

Axes (A):
  A1  Next.js App Router convention boundaries (error.tsx / global-error.tsx)
  A2  React class boundaries (componentDidCatch / getDerivedStateFromError /
      "ErrorBoundary" identifiers) and third-party boundary libs
  A3  Route inventory: every app/**/page.tsx mapped to a route path and
      annotated with the nearest boundary that would catch a render-time
      throw in its subtree (App Router semantics: an error.tsx covers its
      own directory and everything below it)
  A4  Suspense fallbacks (loading mitigation, not error recovery) and
      global window error / unhandledrejection handlers

Deterministic: sorted walks, no timestamps, JSON to stdout.
Usage: python3 scan_error_boundaries.py <repo-root>
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {"node_modules", ".next", "coverage", "dist", ".turbo", ".git"}
WEB = "web"
BOUNDARY_FILES = ("error.tsx", "error.jsx", "error.ts", "error.js",
                  "global-error.tsx", "global-error.jsx")
INFORMATIONAL_FILES = ("not-found.tsx", "loading.tsx")
CLASS_SIGNALS = {
    "componentDidCatch": re.compile(r"\bcomponentDidCatch\b"),
    "getDerivedStateFromError": re.compile(r"\bgetDerivedStateFromError\b"),
    "errorBoundaryIdentifier": re.compile(r"\bErrorBoundary\b"),
    "reactErrorBoundaryLib": re.compile(r"""from\s+["']react-error-boundary["']"""),
}
GLOBAL_HANDLER = re.compile(
    r"addEventListener\(\s*['\"](?:error|unhandledrejection)['\"]"
)
ROUTE_GROUP = re.compile(r"\([^)]+\)")
DYNAMIC_SEGMENT = re.compile(r"\[([^\]]+)\]")


def iter_source_files(root: Path):
    web_root = root / WEB
    for path in sorted(web_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            yield rel


def route_path_from_page(page_rel: Path) -> str:
    parts = page_rel.parts[2:-1]  # strip web/app prefix and page.tsx
    kept = []
    for part in parts:
        if ROUTE_GROUP.fullmatch(part):
            continue  # route group: no URL segment
        kept.append(part)
    out = []
    for part in kept:
        out.append(":" + DYNAMIC_SEGMENT.fullmatch(part).group(1)
                   if DYNAMIC_SEGMENT.fullmatch(part) else part)
    return "/" + "/".join(out) if out else "/"


def main(repo_root: str) -> None:
    root = Path(repo_root).resolve()
    result = {
        "scan": "web-error-boundaries",
        "web_root": WEB,
        "a1_next_convention_boundaries": [],
        "a1_informational_convention_files": [],
        "a2_class_boundary_signals": [],
        "a2_boundary_lib_dependency": None,
        "a3_route_inventory": [],
        "a3_route_summary": {},
        "a4_suspense_fallbacks": [],
        "a4_global_window_handlers": [],
        "source_file_count": 0,
    }

    for rel in iter_source_files(root):
        result["source_file_count"] += 1
        name = rel.name
        if name in BOUNDARY_FILES:
            result["a1_next_convention_boundaries"].append(str(rel))
        elif name in INFORMATIONAL_FILES:
            result["a1_informational_convention_files"].append(str(rel))
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for signal, rx in CLASS_SIGNALS.items():
            if rx.search(text):
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        result["a2_class_boundary_signals"].append(
                            {"file": str(rel), "line": i, "signal": signal})
        if re.search(r"<Suspense\b", text):
            count = len(re.findall(r"<Suspense\b", text))
            result["a4_suspense_fallbacks"].append(
                {"file": str(rel), "count": count})
        if GLOBAL_HANDLER.search(text):
            for i, line in enumerate(text.splitlines(), 1):
                if GLOBAL_HANDLER.search(line):
                    result["a4_global_window_handlers"].append(
                        {"file": str(rel), "line": i})

    pkg = json.loads((root / WEB / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    result["a2_boundary_lib_dependency"] = {
        "react-error-boundary": deps.get("react-error-boundary"),
    }

    # Route inventory and boundary-ancestor resolution.
    boundary_dirs = {Path(p).parent for p in result["a1_next_convention_boundaries"]}
    pages = []
    web_root = root / WEB / "app"
    for page in sorted(web_root.rglob("page.tsx")):
        pages.append(page.relative_to(root))
    for page_rel in pages:
        page_dir = page_rel.parent
        covering = None
        for cand in boundary_dirs:
            if page_dir == cand or cand in page_dir.parents:
                covering = str(cand)
                break
        result["a3_route_inventory"].append({
            "route": route_path_from_page(page_rel),
            "page_file": str(page_rel),
            "covered_by_boundary": covering,
        })
    covered = sum(1 for r in result["a3_route_inventory"]
                  if r["covered_by_boundary"])
    total = len(result["a3_route_inventory"])
    result["a3_route_summary"] = {
        "routes_total": total,
        "routes_covered_by_boundary": covered,
        "routes_uncovered": total - covered,
    }

    for key in ("a4_suspense_fallbacks",):
        result[key].sort(key=lambda e: (e["file"], e["count"]))

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
