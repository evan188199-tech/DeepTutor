#!/usr/bin/env python3
"""Static import-cost scanner for DeepTutor (read-only, stdlib only).

Builds the local import graph from declared entry modules, locates top-level
vs lazy (function-body) imports of heavy third-party packages, and emits
deferral candidates with a qualitative benefit grade.

Usage:
    python scan_import_cost.py [--repo PATH] [--out PATH]

No product code is imported or executed; only ``ast`` parsing of source.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

# Heavy third-party top-level packages, grouped by qualitative import weight.
HEAVY_PACKAGES: dict[str, str] = {
    # native / ML runtimes (very heavy)
    "lightrag": "very_heavy",
    "llama_index": "very_heavy",
    "llama-index": "very_heavy",
    "docling": "very_heavy",
    "torch": "very_heavy",
    "torchvision": "very_heavy",
    "faiss": "very_heavy",
    "cv2": "very_heavy",
    "fitz": "very_heavy",
    "pymupdf": "very_heavy",
    "playwright": "very_heavy",
    "selenium": "very_heavy",
    "matplotlib": "very_heavy",
    "pandas": "very_heavy",
    "numpy": "very_heavy",
    "scipy": "very_heavy",
    "sklearn": "very_heavy",
    "numba": "very_heavy",
    "onnxruntime": "very_heavy",
    "moviepy": "very_heavy",
    "imageio": "very_heavy",
    "sentence_transformers": "very_heavy",
    "whisper": "very_heavy",
    "PIL": "heavy",
    "reportlab": "heavy",
    "lxml": "heavy",
    "PIL.Image": "heavy",
    # service SDKs (moderate)
    "openai": "moderate",
    "anthropic": "moderate",
    "google": "moderate",
    "tiktoken": "moderate",
    "pydantic": "moderate",
    "fastapi": "moderate",
    "uvicorn": "moderate",
    "aiohttp": "moderate",
    "httpx": "moderate",
    "requests": "moderate",
    "bs4": "moderate",
    "typer": "moderate",
    "rich": "moderate",
    "prompt_toolkit": "moderate",
    "yaml": "moderate",
    "jinja2": "moderate",
}

# Alternative import spellings -> canonical heavy key.
ALIASES = {
    "llamaindex": "llama_index",
    "sklearn": "sklearn",
    "PyMuPDF": "pymupdf",
    "bs4": "bs4",
    "PIL": "PIL",
    "yaml": "yaml",
}

FIRST_PARTY_ROOTS = ("deeptutor", "deeptutor_cli")

# Declared entry modules (console scripts, -m targets, server starters).
ENTRIES = [
    ("deeptutor_cli.main", "console script: deeptutor"),
    ("deeptutor.api.contracts.export", "console script: deeptutor-export-frontend-contracts"),
    ("deeptutor.__main__", "python -m deeptutor"),
    ("deeptutor_cli.__main__", "python -m deeptutor_cli"),
    ("deeptutor.api.run_server", "API server starter (uvicorn)"),
    ("deeptutor.api.main", "FastAPI app module"),
    ("scripts.start_web", "manual web launcher"),
]


@dataclass
class ImportRecord:
    module: str          # local module path or third-party top package
    top: str             # top-level package as written
    line: int
    col: int             # 0 == module top level statement column
    kind: str            # "top" | "lazy" | "guarded"
    scope: str           # "" for top-level, else enclosing function qualname
    source: str = ""


@dataclass
class ModuleInfo:
    name: str
    path: str
    imports: list[ImportRecord] = field(default_factory=list)
    # eager edges only: top-level + module-level guarded imports execute at
    # import time; function-body (lazy) imports must not join the graph.
    local_deps: set[str] = field(default_factory=set)
    lazy_deps: set[str] = field(default_factory=set)
    side_effects: list[str] = field(default_factory=list)


class Scanner:
    def __init__(self, repo: Path):
        self.repo = repo
        self.modules: dict[str, ModuleInfo] = {}
        self._index_local_modules()

    # ---------- module discovery ----------

    def _index_local_modules(self) -> None:
        for root in FIRST_PARTY_ROOTS:
            base = self.repo / root
            if not base.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in
                               ("__pycache__", "node_modules", ".venv", "build", "dist")]
                for fn in filenames:
                    if not fn.endswith(".py"):
                        continue
                    full = Path(dirpath) / fn
                    rel = full.relative_to(self.repo).with_suffix("")
                    parts = list(rel.parts)
                    if parts[-1] == "__init__":
                        parts = parts[:-1]
                    name = ".".join(parts)
                    self.modules[name] = ModuleInfo(name=name, path=str(rel) + ".py")
        # scripts/ entries
        scripts_dir = self.repo / "scripts"
        if scripts_dir.is_dir():
            for fn in scripts_dir.glob("*.py"):
                name = "scripts." + fn.stem
                self.modules.setdefault(
                    name, ModuleInfo(name=name, path=str(fn.relative_to(self.repo))))

    # ---------- parsing ----------

    def scan(self) -> None:
        for name, info in list(self.modules.items()):
            full = self.repo / info.path
            if not full.exists():
                continue
            try:
                tree = ast.parse(full.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            self._walk(info, tree)

    def _walk(self, info: ModuleInfo, tree: ast.AST) -> None:
        # module-level statements (col_offset == 0 at statement level)
        for node in tree.body:
            self._collect_stmt(info, node, kind="top", scope="")
            # guarded: import inside module-level if/try (but not loop/with)
            if isinstance(node, (ast.If, ast.Try, ast.TryStar, ast.With)):
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        self._record(info, sub, kind="guarded", scope="")
            # module-level side effects: bare calls at top level
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                info.side_effects.append(f"line {node.lineno}: {ast.unparse(node.value)[:90]}")
            if isinstance(node, ast.Assign):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        info.side_effects.append(
                            f"line {node.lineno}: {ast.unparse(sub)[:90]}")
                        break
        # function/method bodies -> lazy (dedupe nested double-walks by line)
        seen_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)) and sub.lineno not in seen_lines:
                        seen_lines.add(sub.lineno)
                        self._record(info, sub, kind="lazy", scope=node.name)

    def _collect_stmt(self, info: ModuleInfo, node: ast.AST, kind: str, scope: str) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._record(info, node, kind=kind, scope=scope)

    def _record(self, info: ModuleInfo, node, kind: str, scope: str) -> None:
        eager = kind in ("top", "guarded")
        targets: list[tuple[str, str, str]] = []  # (resolved, top-as-written)
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append((self._resolve(info, alias.name, 0), alias.name.split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            level = node.level or 0
            resolved_base = self._resolve(info, base, level)
            for alias in node.names:
                if level > 0:
                    top = resolved_base.split(".")[0] if resolved_base else "local"
                else:
                    top = (base or alias.name).split(".")[0]
                resolved = resolved_base
                if alias.name != "*":
                    candidate = f"{resolved_base}.{alias.name}" if resolved_base else alias.name
                    if candidate in self.modules:
                        resolved = candidate
                targets.append((resolved, top))
        for resolved, top in targets:
            info.imports.append(ImportRecord(
                module=resolved, top=top, line=node.lineno, col=node.col_offset,
                kind=kind, scope=scope))
            if resolved in self.modules:
                (info.local_deps if eager else info.lazy_deps).add(resolved)

    def _resolve(self, info: ModuleInfo, name: str, level: int) -> str:
        if level == 0:
            return name
        # relative import: anchor on the importing module's package.
        # __init__ modules are stored under the package name itself.
        if info.path.endswith("__init__.py"):
            pkg = info.name.split(".")
        else:
            parts = info.name.split(".")
            pkg = parts[:-1] if len(parts) > 1 else []
        for _ in range(level - 1):
            if pkg:
                pkg = pkg[:-1]
        anchor = ".".join(pkg)
        if not name:
            return anchor or info.name
        return f"{anchor}.{name}" if anchor else name


# ---------- graph metrics ----------


def reachable(scanner: Scanner, entry: str) -> tuple[set[str], dict[str, int]]:
    seen: set[str] = set()
    depth: dict[str, int] = {entry: 0}
    q = deque([entry])
    while q:
        cur = q.popleft()
        info = scanner.modules.get(cur)
        if info is None:
            continue
        for dep in info.local_deps:
            if dep not in seen:
                seen.add(dep)
                depth[dep] = depth[cur] + 1
                q.append(dep)
    return seen, depth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "import_cost.json"))
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    sc = Scanner(repo)
    sc.scan()

    result: dict = {
        "generated_by": "scan_import_cost.py (static AST analysis, no code execution)",
        "repo_head": _git_head(repo),
        "entries": {},
        "heavy_imports": {},
        "lazy_heavy": {},
        "guarded_heavy": {},
        "side_effect_modules": [],
        "graph": {name: sorted(info.local_deps) for name, info in sorted(sc.modules.items())
                  if info.local_deps},
        "lazy_edges": {name: sorted(info.lazy_deps) for name, info in sorted(sc.modules.items())
                       if info.lazy_deps},
        "module_top_third_party": {},
    }

    # per-entry reachability + transitive top-level heavy packages
    mod_top_heavy: dict[str, set[str]] = {}
    for name, info in sc.modules.items():
        for rec in info.imports:
            if rec.kind != "top":
                continue
            canon = _canonical(rec.top)
            if canon in HEAVY_PACKAGES:
                mod_top_heavy.setdefault(info.path, set()).add(canon)
    result["module_top_third_party"] = {k: sorted(v) for k, v in sorted(mod_top_heavy.items())}

    def bfs_chain(start: str, target_path: str) -> list[str]:
        """Shortest local import chain from entry module to a module file."""
        target = None
        for mname, minfo in sc.modules.items():
            if minfo.path == target_path:
                target = mname
                break
        if target is None:
            return []
        prev: dict[str, str | None] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == target:
                break
            for dep in sc.modules.get(cur, ModuleInfo("", "")).local_deps:
                if dep not in prev:
                    prev[dep] = cur
                    q.append(dep)
        if target not in prev:
            return []
        chain, cur = [], target
        while cur is not None:
            chain.append(cur)
            cur = prev[cur]
        return list(reversed(chain))

    for entry, label in ENTRIES:
        if entry not in sc.modules:
            continue
        seen, depth = reachable(sc, entry)
        max_depth = max(depth.values(), default=0)
        reachable_paths = {sc.modules[m].path for m in seen | {entry} if m in sc.modules}
        heavy_on_path: dict[str, list[str]] = {}
        for p in reachable_paths:
            for pkg in mod_top_heavy.get(p, ()):
                heavy_on_path.setdefault(pkg, []).append(p)
        chains = {}
        for pkg, paths in sorted(heavy_on_path.items()):
            if len(chains) >= 4:
                break
            best = min(paths, key=len)
            ch = bfs_chain(entry, best)
            if ch:
                chains[pkg] = {"via": best, "chain": ch[:6]}
        result["entries"][entry] = {
            "label": label,
            "modules_reachable": len(seen),
            "max_import_depth": max_depth,
            "depth_histogram": _hist(depth),
            "heavy_packages_loaded": {k: sorted(v) for k, v in sorted(heavy_on_path.items())},
            "heavy_chain_examples": chains,
        }

    # heavy third-party usage
    heavy_by_key: dict[str, dict[str, list]] = {}
    for name, info in sc.modules.items():
        for rec in info.imports:
            canon = _canonical(rec.top)
            if canon not in HEAVY_PACKAGES:
                continue
            weight = HEAVY_PACKAGES[canon]
            bucket = rec.kind  # top / lazy / guarded
            heavy_by_key.setdefault(canon, {}).setdefault(bucket, []).append({
                "file": info.path, "line": rec.line, "scope": rec.scope,
                "weight": weight, "stmt": _excerpt(repo / info.path, rec.line),
            })

    for canon, buckets in sorted(heavy_by_key.items()):
        result["heavy_imports"][canon] = {
            "top_level": buckets.get("top", []),
            "lazy": buckets.get("lazy", []),
            "guarded": buckets.get("guarded", []),
        }

    # side-effect modules of interest (startup path)
    interesting = ("deeptutor_cli.main", "deeptutor.api.main", "deeptutor.api.run_server",
                   "deeptutor.runtime.launcher")
    for name in interesting:
        info = sc.modules.get(name)
        if info and info.side_effects:
            result["side_effect_modules"].append({
                "module": name, "path": info.path, "side_effects": info.side_effects[:12],
            })

    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"wrote {out}")
    print(f"modules indexed: {len(sc.modules)}")
    for entry, meta in result["entries"].items():
        print(f"  {entry}: reachable={meta['modules_reachable']} max_depth={meta['max_import_depth']}")
    return 0


def _git_head(repo: Path) -> str:
    head = repo / ".git"
    try:
        if head.is_file():
            ref = head.read_text().split(":")[-1].strip()
            return (repo / ref).read_text().strip()[:12]
    except OSError:
        pass
    return "unknown"


def _hist(depth: dict[str, int]) -> dict[str, int]:
    h: dict[str, int] = {}
    for d in depth.values():
        h[str(d)] = h.get(str(d), 0) + 1
    return dict(sorted(h.items(), key=lambda kv: int(kv[0])))


def _canonical(top: str) -> str:
    top = ALIASES.get(top, top)
    return top


def _excerpt(path: Path, line: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return text[line - 1].strip() if 0 < line <= len(text) else ""
    except OSError:
        return ""


if __name__ == "__main__":
    sys.exit(main())
