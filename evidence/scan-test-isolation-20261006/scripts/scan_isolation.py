#!/usr/bin/env python3
"""Static scan for test-isolation risks in DeepTutor Python tests.

Categories:
  ENV_MUTATION        direct os.environ writes/pops without guaranteed restore
  TMP_LITERAL_WRITE   filesystem ops targeting literal /tmp paths
  TMP_UNMANAGED       mkdtemp / NamedTemporaryFile(delete=False) without visible cleanup
  TMP_NO_CTX          TemporaryDirectory used without a `with` context
  GLOBAL_MUTATION     cross-module / singleton attribute writes in test code
  MONKEYPATCH_UNDO    monkeypatch.undo() can revert fixture redirections
  FIXTURE_SCOPE_RISK  session/module-scoped fixtures that share state across tests
  CWD_WRITE           literal relative-path filesystem writes polluting the CWD

Out of scope (dedup with sibling scan cards): timing/sleep flakiness
(scan-flaky-tests) and dangling async tasks (scan-async-tasks).

Usage: python3 scan_isolation.py <repo_root> <out_dir>
Output is deterministic: sorted paths, sorted findings, no timestamps.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

WRITE_OPEN_MODES = {"w", "a", "x", "w+", "a+", "x+", "wb", "ab", "xb",
                    "wt", "at", "xt", "w+b", "a+b", "x+b"}
TMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/")
SINGLETON_ATTRS = {"_instance", "_singleton", "_shared", "_cache", "_registry",
                   "_global_state", "_state", "_shared_instance", "_default_instance"}
ENV_CALLS = {"pop", "setdefault", "update", "clear"}
WRITE_ATTRS = {"write_text", "write_bytes", "touch", "mkdir", "makedirs", "open",
               "unlink", "rmtree", "copy", "copytree", "move", "remove"}
OUTPUT_KWARGS = {"output_dir", "output_path", "out_dir", "cache_dir", "save_dir",
                 "export_dir", "media_dir", "target_dir", "dest_dir", "directory",
                 "kb_base_dir", "working_dir", "workdir", "storage_dir", "root_dir"}
EXCLUDED_DIR_PARTS = {".git", "node_modules", "evidence"}
RE_MUTABLE_RETURN = re.compile(r"return\s*(\[\s*\]|\{\s*\}|\(\s*\))")

REC_ENV = ("Use monkeypatch.setenv/delenv or patch.dict(os.environ) so pytest "
           "restores state automatically; if a raw write is unavoidable, restore "
           "in a finally block or fixture teardown.")
REC_TMP = ("Use pytest tmp_path/tmp_path_factory, or wrap in a TemporaryDirectory "
           "context; register addCleanup(shutil.rmtree, ...) when created outside "
           "a context manager.")
REC_GLOB = ("Patch via monkeypatch.setattr(obj, 'attr', value) (auto-restored) "
            "instead of assigning module/singleton attributes directly; otherwise "
            "save the original and restore in a finally block or fixture teardown.")


def rel(repo: Path, p: Path) -> str:
    return p.relative_to(repo).as_posix()


def snippet_of(source: str, node: ast.AST) -> str:
    lines = source.splitlines()
    try:
        line = lines[node.lineno - 1]
    except (IndexError, AttributeError):
        return ""
    return line.strip()[:160]


def build_module_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                for a in node.names:
                    aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def resolve_module(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Resolve an Attribute/Name chain to a dotted module path, if it is one."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        base = aliases.get(cur.id)
        if base is None:
            return None
        return ".".join([base] + list(reversed(parts)))
    return None


def call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    if isinstance(call.func, ast.Name):
        return aliases.get(call.func.id, call.func.id)
    return resolve_module(call.func, aliases)


def collect_function_spans(tree: ast.Module) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append((child.lineno, child.end_lineno, f"{prefix}{child.name}"))
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")

    walk(tree, "")
    return spans


def innermost_function(spans: list[tuple[int, int, str]],
                       lineno: int) -> tuple[int, int, str] | None:
    candidates = [s for s in spans if s[0] <= lineno <= s[1]]
    if not candidates:
        return None
    return min(candidates, key=lambda s: (s[1] - s[0], s[0]))


def env_mitigated(lines: list[str], span: tuple[int, int, str] | None) -> bool:
    if span is None:
        return False
    body = "\n".join(lines[span[0] - 1:span[1]])
    return ("patch.dict" in body) or ("monkeypatch" in body)


def glob_mitigated(lines: list[str], span: tuple[int, int, str] | None) -> bool:
    """Heuristic: same function saves an 'original' and has a finally block."""
    if span is None:
        return False
    body = "\n".join(lines[span[0] - 1:span[1]])
    return "finally" in body and "original" in body


def build_parents(tree: ast.Module) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def is_tmp_literal(value: object) -> bool:
    return isinstance(value, str) and any(value.startswith(p) for p in TMP_PREFIXES)


def scan_file(repo: Path, path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8", errors="replace")
    findings: list[dict] = []

    def add(category: str, severity: str, node: ast.AST, detail: str,
            recommendation: str, ctx: str, mitigation: str = "none") -> None:
        findings.append({
            "category": category,
            "severity": severity,
            "path": rel(repo, path),
            "line": getattr(node, "lineno", 0),
            "context": ctx,
            "detail": detail,
            "snippet": snippet_of(source, node),
            "recommendation": recommendation,
            "mitigation": mitigation,
        })

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings
    lines = source.splitlines()
    aliases = build_module_aliases(tree)
    spans = collect_function_spans(tree)
    parents = build_parents(tree)

    for node in ast.walk(tree):
        ctx_node = innermost_function(spans, getattr(node, "lineno", 0))
        ctx = ctx_node[2] if ctx_node else "<module>"

        # --- ENV_MUTATION -------------------------------------------------
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) \
                else [node.target]
            for t in targets:
                tgt = t.value if isinstance(t, ast.Subscript) else t
                if isinstance(tgt, ast.Attribute) and tgt.attr == "environ" \
                        and resolve_module(tgt.value, aliases) == "os":
                    sev = "medium" if env_mitigated(lines, ctx_node) else "high"
                    if ctx == "<module>":
                        sev = "high"
                    add("ENV_MUTATION", sev, node,
                        f"direct os.environ mutation ({type(node).__name__}) in '{ctx}'",
                        REC_ENV, ctx)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ENV_CALLS:
            base = node.func.value
            if isinstance(base, ast.Attribute) and base.attr == "environ" \
                    and resolve_module(base.value, aliases) == "os":
                sev = "medium" if env_mitigated(lines, ctx_node) else "high"
                if ctx == "<module>":
                    sev = "high"
                add("ENV_MUTATION", sev, node,
                    f"os.environ.{node.func.attr}() without visible restore in '{ctx}'",
                    REC_ENV, ctx)
        if isinstance(node, ast.Call) and call_name(node, aliases) == "os.putenv":
            add("ENV_MUTATION", "high", node, "os.putenv() bypasses pytest restore",
                REC_ENV, ctx)

        # --- TMP / CWD writes ----------------------------------------------
        if isinstance(node, ast.Call):
            fname = call_name(node, aliases)
            if fname in ("open", "io.open") and node.args:
                arg0 = node.args[0]
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    p = arg0.value
                    if is_tmp_literal(p):
                        if mode == "" or mode in WRITE_OPEN_MODES:
                            add("TMP_LITERAL_WRITE", "medium", node,
                                f"open() on literal tmp path '{p[:60]}'", REC_TMP, ctx)
                    elif not p.startswith("/") and mode in WRITE_OPEN_MODES:
                        add("CWD_WRITE", "low", node,
                            f"relative-path write '{p[:60]}' lands in the CWD",
                            "Write under tmp_path instead of a relative path that "
                            "depends on pytest's cwd.", ctx)
            if isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_ATTRS \
                    and isinstance(node.func.value, ast.Call) \
                    and call_name(node.func.value, aliases) == "Path":
                for a in node.func.value.args:
                    if is_tmp_literal(getattr(a, "value", None)):
                        add("TMP_LITERAL_WRITE", "medium", node,
                            f"Path('{a.value[:50]}').{node.func.attr}() targets a "
                            "shared tmp path", REC_TMP, ctx)
            # output-target kwargs pointed at shared /tmp (needs review)
            for kw in node.keywords:
                if kw.arg in OUTPUT_KWARGS and is_tmp_literal(getattr(kw.value, "value", None)):
                    add("TMP_LITERAL_WRITE", "medium", node,
                        f"'{kw.arg}={kw.value.value[:50]}' hands a shared tmp path to "
                        "production code — verify no real write happens there",
                        REC_TMP, ctx)
            if fname == "tempfile.mkdtemp":
                var = None
                assign = parents.get(id(node))
                if isinstance(assign, ast.Assign) and isinstance(assign.targets[0], ast.Name):
                    var = assign.targets[0].id
                cleaned = bool(var and f"rmtree({var}" in source) or "addCleanup(" in source
                if not cleaned:
                    add("TMP_UNMANAGED", "medium", node,
                        f"tempfile.mkdtemp() without visible rmtree/addCleanup in this "
                        f"file (target '{var or 'non-local'}')", REC_TMP, ctx)
            if fname == "tempfile.NamedTemporaryFile":
                for kw in node.keywords:
                    if kw.arg == "delete" and isinstance(kw.value, ast.Constant) \
                            and kw.value.value is False:
                        add("TMP_UNMANAGED", "medium", node,
                            "NamedTemporaryFile(delete=False) leaves the file behind "
                            "unless removed manually",
                            "Delete in finally/addCleanup, or use delete=True.", ctx)
            if fname == "tempfile.TemporaryDirectory":
                parent = parents.get(id(node))
                if not isinstance(parent, ast.withitem) \
                        and ".cleanup()" not in source and "addCleanup(" not in source:
                    add("TMP_NO_CTX", "medium", node,
                        "TemporaryDirectory() not used as a context manager and no "
                        "visible .cleanup()",
                        "Use `with tempfile.TemporaryDirectory() as d:` or register "
                        "addCleanup(d.cleanup).", ctx)

        # --- GLOBAL_MUTATION ------------------------------------------------
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute):
                    base = t.value
                    base_mod = None
                    if isinstance(base, ast.Name):
                        base_mod = aliases.get(base.id)
                    if base_mod:
                        mit = "finally-restore" if glob_mitigated(lines, ctx_node) else "none"
                        sev = "medium" if mit != "none" else "high"
                        add("GLOBAL_MUTATION", sev, node,
                            f"test writes attribute on imported module '{base_mod}.{t.attr}'",
                            REC_GLOB, ctx, mit)
                    elif t.attr in SINGLETON_ATTRS:
                        mit = "finally-restore" if glob_mitigated(lines, ctx_node) else "none"
                        sev = "medium" if mit != "none" else "high"
                        add("GLOBAL_MUTATION", sev, node,
                            f"assignment to singleton-style attribute '.{t.attr}'",
                            REC_GLOB, ctx, mit)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "setattr" and node.args:
            if isinstance(node.args[0], ast.Name):
                mod = aliases.get(node.args[0].id)
                if mod and "." in mod:
                    add("GLOBAL_MUTATION", "high", node,
                        f"setattr() on imported module '{mod}'", REC_GLOB, ctx)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "undo" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "monkeypatch":
            add("MONKEYPATCH_UNDO", "low", node,
                "monkeypatch.undo() also reverts fixture-installed monkeypatches "
                "(documented footgun); verify no autouse fixture relies on monkeypatch here",
                "Scope the temporary patch manually (try/finally) instead of a global undo().",
                ctx)
        if isinstance(node, ast.Global):
            add("GLOBAL_MUTATION", "medium", node,
                f"'global {', '.join(node.names)}' statement in test code", REC_GLOB, ctx)

    # --- FIXTURE_SCOPE_RISK ---------------------------------------------------
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                        and dec.func.attr == "fixture":
                    scope = ""
                    for kw in dec.keywords:
                        if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                            scope = str(kw.value.value)
                    if scope in ("session", "module"):
                        body_src = "\n".join(lines[node.lineno - 1:node.end_lineno])
                        traits = []
                        if "os.environ" in body_src:
                            traits.append("touches os.environ")
                        if "yield" not in body_src and "return" in body_src:
                            traits.append("no yield/teardown")
                        if "rmtree" in body_src or "TemporaryDirectory" in body_src:
                            traits.append("owns tmp dirs")
                        if RE_MUTABLE_RETURN.search(body_src):
                            traits.append("returns empty container literal")
                        add("FIXTURE_SCOPE_RISK", "medium", dec,
                            f"{scope}-scoped fixture '{node.name}': "
                            + ("; ".join(traits) or "state shared across tests"),
                            "Keep session/module fixtures read-only and immutable; "
                            "deep-copy returned state; document reset expectations.",
                            f"fixture:{node.name}")

    return findings


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    all_py = sorted(p for p in repo.rglob("*.py")
                    if not EXCLUDED_DIR_PARTS.intersection(p.parts))
    test_files: list[Path] = []
    skipped_prod: list[Path] = []
    for p in all_py:
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            src = p.read_text(encoding="utf-8", errors="replace")
            has_tests = "def test_" in src or "class Test" in src
            # Production modules named test_*.py (e.g. deeptutor/services/config/
            # test_runner.py) live in the package but outside any tests/ segment.
            in_package_no_tests_dir = ("deeptutor" in p.parts
                                       and "tests" not in p.parts)
            if has_tests and not in_package_no_tests_dir:
                test_files.append(p)
            else:
                skipped_prod.append(p)

    findings: list[dict] = []
    total_lines = 0
    cat_counter: Counter = Counter()
    sev_counter: Counter = Counter()
    dir_counter: Counter = Counter()
    files_with: set[str] = set()
    hygiene: Counter = Counter()

    for p in test_files:
        src = p.read_text(encoding="utf-8", errors="replace")
        total_lines += src.count("\n") + 1
        hygiene["monkeypatch.setenv"] += src.count("monkeypatch.setenv")
        hygiene["monkeypatch.setattr"] += src.count("monkeypatch.setattr")
        hygiene["patch.dict"] += src.count("patch.dict")
        hygiene["tmp_path referenced lines"] += sum(
            1 for line in src.splitlines() if "tmp_path" in line)
        hygiene["cache_clear() calls"] += src.count("cache_clear()")

        findings.extend(scan_file(repo, p))

    findings.sort(key=lambda f: (f["path"], f["line"], f["category"], f["detail"]))
    for f in findings:
        cat_counter[f["category"]] += 1
        sev_counter[f["severity"]] += 1
        dir_counter["/".join(f["path"].split("/")[:-1])] += 1
        files_with.add(f["path"])

    coverage = {
        "path_convention": "paths relative to scanned worktree root",
        "python_files_total": len(all_py),
        "test_files_scanned": len(test_files),
        "prod_or_harness_files_skipped": [rel(repo, p) for p in skipped_prod],
        "test_code_lines": total_lines,
        "findings_total": len(findings),
        "by_category": dict(sorted(cat_counter.items())),
        "by_severity": dict(sorted(sev_counter.items())),
        "files_with_findings": len(files_with),
        "by_directory_top15": dict(sorted(dir_counter.items(),
                                          key=lambda kv: (-kv[1], kv[0]))[:15]),
        "hygiene_signals": dict(sorted(hygiene.items())),
        "out_of_scope": ["timing/sleep flakiness (scan-flaky-tests)",
                          "dangling async tasks (scan-async-tasks)"],
    }

    (out_dir / "findings.json").write_text(
        json.dumps({"findings": findings}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"scanned={len(test_files)} findings={len(findings)} files_with={len(files_with)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
