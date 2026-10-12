#!/usr/bin/env python3
"""Three-way parity scan for DeepTutor built-in tools.

Compares:
  A. declarations    - deeptutor/tools/builtin_specs.py BUILTIN_TOOL_SPECS
  B. registry        - deeptutor/runtime/registry/tool_registry.py consumption
  C. implementations - the BaseTool subclasses the specs point at (plus an
                       orphan sweep over tools/capabilities tool modules)

Also cross-checks enabled-state surfaces (USER_TOGGLEABLE_TOOL_NAMES,
CONFIGURABLE_BUILTIN_TOOL_NAMES, PARTNER_BUILTIN_TOOL_NAMES, TOOL_ALIASES,
tool_composition mount tables) against the declared names.

Read-only: static analysis uses AST only; dynamic probes run per-tool in
subprocesses with timeouts and never mutate the tree.

Usage (from anywhere):
    python3 evidence/scan-builtin-tool-parity-20261012/scan_builtin_tool_parity.py \
        [--repo /path/to/DeepTutor] [--python /path/to/probe-interpreter] [--skip-probes]

Outputs (next to this script): parity_table.md, findings.md,
scan_result.json, SHA256SUMS.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = Path(__file__).resolve().parent

SPECS_FILE = "deeptutor/tools/builtin_specs.py"
BUILTIN_INIT = "deeptutor/tools/builtin/__init__.py"
TOOL_REGISTRY = "deeptutor/runtime/registry/tool_registry.py"
TOOL_COMPOSITION = "deeptutor/agents/_shared/tool_composition.py"
PARTNER_MEMORY = "deeptutor/tools/partner_memory.py"

PROBE_TIMEOUT_S = 30

# Where implementation classes may live (orphan sweep scope).
IMPL_GLOBS = [
    "deeptutor/tools/**/*.py",
    "deeptutor/capabilities/**/tools.py",
    "deeptutor/visualizers/tool.py",
]


@dataclass
class SpecEntry:
    name: str
    class_path: str
    line: int


@dataclass
class ImplEntry:
    module: str
    class_name: str
    line: int
    name_attr: str | None = None
    deferred_attr: bool = False


@dataclass
class Finding:
    severity: str  # ERROR / WARN / INFO
    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    suggestion: str = ""


def load_tree(rel: str) -> tuple[ast.Module, str]:
    path = REPO / rel
    source = path.read_text(encoding="utf-8")
    return ast.parse(source), source


def parse_specs() -> tuple[list[SpecEntry], dict]:
    tree, _ = load_tree(SPECS_FILE)
    specs: list[SpecEntry] = []
    aliases: dict[str, str] = {}
    alias_line = 0
    partner_names: list[str] = []
    partner_line = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        value = node.value
        if value is None or not isinstance(target, ast.Name):
            continue
        if target.id == "BUILTIN_TOOL_SPECS" and isinstance(value, ast.Tuple):
            for elt in value.elts:
                if isinstance(elt, ast.Starred):
                    elt = elt.value
                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "_specs":
                    module = elt.args[0].value
                    for pair in elt.args[1].elts:
                        specs.append(SpecEntry(pair.elts[0].value, f"{module}:{pair.elts[1].value}", pair.lineno))
                elif isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "BuiltinToolSpec":
                    specs.append(SpecEntry(elt.args[0].value, elt.args[1].value, elt.lineno))
        elif target.id == "TOOL_ALIASES" and isinstance(value, ast.Dict):
            alias_line = node.lineno
            for k, v in zip(value.keys, value.values):
                if isinstance(v, ast.Tuple) and v.elts:
                    aliases[k.value] = v.elts[0].value
        elif target.id == "PARTNER_BUILTIN_TOOL_NAMES" and isinstance(value, ast.Tuple):
            partner_line = node.lineno
            partner_names = [e.value for e in value.elts]
    return specs, {
        "aliases": aliases,
        "alias_line": alias_line,
        "partner_names": partner_names,
        "partner_line": partner_line,
    }


def parse_name_list(tree: ast.Module, wanted: tuple[str, ...]) -> dict[str, tuple[list[str], int]]:
    out: dict[str, tuple[list[str], int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, value = node.targets[0], node.value
        else:
            continue
        if value is None or not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        if target.id in wanted and target.id not in out:
            if isinstance(value, ast.Tuple):
                out[target.id] = ([e.value for e in value.elts if isinstance(e, ast.Constant)], node.lineno)
            else:
                out[target.id] = ([], node.lineno)
    return out


def parse_composition() -> dict[str, tuple[object, int]]:
    tree, _ = load_tree(TOOL_COMPOSITION)
    out: dict[str, tuple[object, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            value = node.value
            if value is None or not isinstance(target, ast.Name):
                continue
            tid = target.id
            if tid == "_CONDITIONAL_MOUNT_FLAGS" and isinstance(value, ast.Dict):
                out[tid] = ({k.value: v.value for k, v in zip(value.keys, value.values)}, node.lineno)
            elif tid in ("WORKSPACE_BASELINE_TOOLS", "_KB_COEXISTING_TOOLS") and isinstance(value, ast.Tuple):
                out[tid] = ([e.value for e in value.elts], node.lineno)
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            names = [e.value for e in node.iter.elts if isinstance(e, ast.Constant)]
            if {"write_memory", "learning_status", "learning_update"} <= set(names):
                out["ALWAYS_ON"] = (names, node.lineno)
    return out


def parse_partner_memory_names() -> tuple[list[str], int]:
    tree, _ = load_tree(PARTNER_MEMORY)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "PARTNER_BUILTIN_TOOL_NAMES" and isinstance(node.value, ast.Tuple):
                return [e.value for e in node.value.elts], node.lineno
    return [], 0


class ModuleContext:
    """Parsed module with its local import map (local name -> dotted module)."""

    def __init__(self, rel: str, tree: ast.Module):
        self.rel = rel
        self.tree = tree
        self.classes: dict[str, ast.ClassDef] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        self.imports: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = alias.name


class ImplResolver:
    """Cross-module BaseTool subclass and class-location resolver (AST only)."""

    def __init__(self):
        self._cache: dict[str, ModuleContext] = {}
        self.unreadable: dict[str, str] = {}

    def context(self, rel: str) -> ModuleContext | None:
        if rel in self._cache:
            return self._cache[rel]
        try:
            tree, _ = load_tree(rel)
        except (OSError, SyntaxError) as exc:
            self.unreadable[rel] = str(exc)
            self._cache[rel] = None
            return None
        ctx = ModuleContext(rel, tree)
        self._cache[rel] = ctx
        return ctx

    def _resolve_class(self, mod: str, cls_name: str, seen: set[str]) -> tuple[str, ast.ClassDef] | None:
        """Locate the defining (module, ClassDef) following re-export imports."""
        key = (mod, cls_name)
        if key in seen:
            return None
        seen.add(key)
        rel = module_to_file(mod)
        ctx = self.context(rel)
        if ctx is None:
            return None
        if cls_name in ctx.classes:
            return rel, ctx.classes[cls_name]
        target_mod = ctx.imports.get(cls_name)
        if target_mod and target_mod.startswith("deeptutor"):
            return self._resolve_class(target_mod, cls_name, seen)
        return None

    def _inherits_basetool(self, ctx: ModuleContext, cls: ast.ClassDef, seen: set[str]) -> bool:
        for base in cls.bases:
            bname = base.id if isinstance(base, ast.Name) else (base.attr if isinstance(base, ast.Attribute) else None)
            if bname is None:
                continue
            if bname.split(".")[-1] == "BaseTool":
                return True
            if bname in seen:
                continue
            seen.add(bname)
            local = ctx.classes.get(bname)
            if local is not None:
                if self._inherits_basetool(ctx, local, seen):
                    return True
                continue
            target_mod = ctx.imports.get(bname)
            if target_mod and target_mod.startswith("deeptutor"):
                found = self._resolve_class(target_mod, bname, set())
                if found is not None:
                    brel, bcls = found
                    bctx = self.context(brel)
                    if bctx is not None and self._inherits_basetool(bctx, bcls, seen):
                        return True
        return False

    @staticmethod
    def _name_literal(cls: ast.ClassDef):
        """Codebase convention: `name` surfaces as a keyword literal (ToolDefinition(name=...))."""
        for node in ast.walk(cls):
            if isinstance(node, ast.keyword) and node.arg == "name" and isinstance(node.value, ast.Constant):
                return node.value.value
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == "name" and isinstance(node.value, ast.Constant):
                        return node.value.value
        return None

    def locate(self, mod: str, cls_name: str) -> tuple[str, ast.ClassDef] | None:
        return self._resolve_class(mod, cls_name, set())

    def subclass_entry(self, rel: str, cls: ast.ClassDef) -> ImplEntry | None:
        ctx = self.context(rel)
        if ctx is None or not self._inherits_basetool(ctx, cls, {cls.name}):
            return None
        return ImplEntry(
            module=ctx.rel,
            class_name=cls.name,
            line=cls.lineno,
            name_attr=self._name_literal(cls),
            deferred_attr=self._deferred_literal(cls),
        )

    @staticmethod
    def _deferred_literal(cls: ast.ClassDef) -> bool:
        for node in ast.walk(cls):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == "deferred" and isinstance(node.value, ast.Constant):
                        return bool(node.value.value)
        return False

    def scan_module_subclasses(self, rel: str) -> dict[str, ImplEntry]:
        ctx = self.context(rel)
        if ctx is None:
            return {}
        out: dict[str, ImplEntry] = {}
        for name, cls in ctx.classes.items():
            if name.startswith("_"):
                continue
            entry = self.subclass_entry(rel, cls)
            if entry is not None:
                out[name] = entry
        return out


def registry_static_facts() -> list[tuple[str, int]]:
    source = (REPO / TOOL_REGISTRY).read_text(encoding="utf-8")
    patterns = [
        ("load_builtins seeds _builtin_specs from BUILTIN_TOOL_SPEC_BY_NAME", r"self\._builtin_specs\.update\(BUILTIN_TOOL_SPEC_BY_NAME\)"),
        ("plugin load guard skips names owned by the builtin catalog", r"candidate\.name in BUILTIN_TOOL_SPEC_BY_NAME"),
        ("plugin register guard skips names owned by the builtin catalog", r"tool\.name not in BUILTIN_TOOL_SPEC_BY_NAME"),
        ("list_tools orders built-ins by BUILTIN_TOOL_NAMES", r"for name in BUILTIN_TOOL_NAMES if name in self\._builtin_specs"),
        ("alias resolution consults TOOL_ALIASES", r"TOOL_ALIASES\.get\(name"),
    ]
    facts = []
    for label, pat in patterns:
        m = __import__("re").search(pat, source)
        if m:
            facts.append((f"{TOOL_REGISTRY}: {label}", source[: m.start()].count("\n") + 1))
    return facts


def run_probe(python: str, spec_name: str) -> dict:
    code = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME as B\n"
        "s = B[%r]\n"
        "try:\n"
        "    t = s.create()\n"
        "    d = t.get_definition()\n"
        "    print(json.dumps({'ok': True, 'name': t.name, 'def_name': d.name, "
        "'deferred': bool(getattr(t, 'deferred', False))}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'ok': False, 'err_type': type(e).__name__, "
        "'err': str(e).splitlines()[0][:200]}))" % (str(REPO), spec_name)
    )
    try:
        proc = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
        out = proc.stdout.strip().splitlines()
        if out:
            return json.loads(out[-1])
        tail = proc.stderr.strip().splitlines()[-1][:200] if proc.stderr else "no output"
        return {"ok": False, "err_type": "SubprocessError", "err": tail}
    except subprocess.TimeoutExpired:
        return {"ok": False, "err_type": "Timeout", "err": f"probe exceeded {PROBE_TIMEOUT_S}s"}
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "err_type": type(exc).__name__, "err": str(exc)[:200]}


def module_to_file(mod: str) -> str:
    """Resolve a dotted module path to its repo-relative file (package-aware)."""
    base = mod.replace(".", "/")
    direct = REPO / (base + ".py")
    if direct.is_file():
        return base + ".py"
    return base + "/__init__.py"


def spec_impl_files(specs: list[SpecEntry]) -> list[str]:
    return sorted({module_to_file(s.class_path.rsplit(":", 1)[0]) for s in specs})


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--python", default="")
    ap.add_argument("--skip-probes", action="store_true")
    args = ap.parse_args()
    REPO = Path(args.repo).resolve()

    probe_python = args.python
    if not probe_python:
        candidate = REPO / ".venv" / "bin" / "python"
        probe_python = str(candidate) if candidate.exists() else sys.executable

    findings: list[Finding] = []

    specs, extra = parse_specs()
    spec_names = [s.name for s in specs]
    spec_by_name = {s.name: s for s in specs}
    aliases, alias_line = extra["aliases"], extra["alias_line"]
    partner_specs, partner_line = extra["partner_names"], extra["partner_line"]

    bi_tree, _ = load_tree(BUILTIN_INIT)
    lists = parse_name_list(bi_tree, (
        "USER_TOGGLEABLE_TOOL_NAMES", "CONFIGURABLE_BUILTIN_TOOL_NAMES", "COMING_SOON_TOOL_NAMES",
    ))
    user_toggleable, user_line = lists["USER_TOGGLEABLE_TOOL_NAMES"]
    configurable, conf_line = lists["CONFIGURABLE_BUILTIN_TOOL_NAMES"]
    coming_soon, coming_line = lists["COMING_SOON_TOOL_NAMES"]

    comp = parse_composition()
    conditional, cond_line = comp["_CONDITIONAL_MOUNT_FLAGS"]
    workspace_baseline, ws_line = comp["WORKSPACE_BASELINE_TOOLS"]
    kb_coexisting, kb_line = comp["_KB_COEXISTING_TOOLS"]
    always_on, always_line = comp["ALWAYS_ON"]

    partner_memory_names, pm_line = parse_partner_memory_names()

    # 1. catalog integrity
    if len(set(spec_names)) != len(spec_names):
        dupes = sorted({n for n in spec_names if spec_names.count(n) > 1})
        findings.append(Finding("ERROR", "Duplicate names in BUILTIN_TOOL_SPECS",
                                f"names {dupes} appear more than once",
                                [f"{SPECS_FILE}:240"], "deduplicate the catalog"))

    # 2. implementation surface (AST, cross-module aware)
    resolver = ImplResolver()
    sweep_rels = set(spec_impl_files(specs))
    for pattern in IMPL_GLOBS:
        for p in sorted(REPO.glob(pattern)):
            if p.is_file():
                sweep_rels.add(str(p.relative_to(REPO)))
    for rel in sorted(sweep_rels):
        resolver.scan_module_subclasses(rel)
    for rel, err in sorted(resolver.unreadable.items()):
        if rel in sweep_rels:
            findings.append(Finding("WARN", f"Scanner could not parse {rel}",
                                    f"{err}; classes in this module are invisible to the static sweep",
                                    [f"{rel}:1"], "fix the syntax error so the sweep can read the module"))

    orphan_candidates: dict[tuple[str, str], ImplEntry] = {}
    for rel in sorted(sweep_rels):
        for cn, entry in resolver.scan_module_subclasses(rel).items():
            orphan_candidates.setdefault((rel, cn), entry)

    reexports: list[tuple[SpecEntry, str]] = []
    for s in specs:
        mod, cls = s.class_path.rsplit(":", 1)
        found = resolver.locate(mod, cls)
        if found is None:
            findings.append(Finding("ERROR", "Declared class missing or not a BaseTool subclass",
                                    f"{s.class_path} was not found as a BaseTool subclass by static analysis",
                                    [f"{SPECS_FILE}:{s.line}", f"{module_to_file(mod)}:1"],
                                    "create/restore the class or fix the class_path"))
            continue
        rel, clsdef = found
        impl = resolver.subclass_entry(rel, clsdef)
        if impl is None:
            findings.append(Finding("ERROR", "Declared class is not a BaseTool subclass",
                                    f"{s.class_path} resolves to {rel}:{cls.lineno} but does not inherit BaseTool",
                                    [f"{SPECS_FILE}:{s.line}", f"{rel}:{clsdef.lineno}"],
                                    "make the class inherit BaseTool or fix the class_path"))
            continue
        if rel != module_to_file(mod):
            reexports.append((s, rel))
        if impl.name_attr is None:
            findings.append(Finding("WARN", "Implementation lacks a literal `name`",
                                    f"{s.class_path} sets name dynamically; static parity for this entry is unverifiable "
                                    "(runtime probe still checks it)",
                                    [f"{SPECS_FILE}:{s.line}", f"{rel}:{impl.line}"],
                                    "surface name as a static literal so static analysis can verify it"))
        elif impl.name_attr != s.name:
            findings.append(Finding("ERROR", "Name drift: spec vs implementation",
                                    f"spec declares {s.name!r} but the implementation surface name is {impl.name_attr!r}",
                                    [f"{SPECS_FILE}:{s.line}", f"{rel}:{impl.line}"],
                                    "align the implementation `name` with the spec name"))
        orphan_candidates.pop((rel, cls), None)

    for s, actual_rel in reexports:
        mod, cls = s.class_path.rsplit(":", 1)
        findings.append(Finding("INFO", "Spec class_path points at a re-export",
                                f"{s.class_path} is imported into {module_to_file(mod)} but defined in {actual_rel}; "
                                "import resolution works, but the catalog indirection is one hop deeper than it looks",
                                [f"{SPECS_FILE}:{s.line}", f"{actual_rel}:1"],
                                "consider pointing the spec at the defining module"))

    # 3. orphans (with reachability check)
    def runtime_importers(rel: str) -> list[str]:
        """deeptutor/ files (excluding tests and the module itself) that import *rel*."""
        dotted = rel[:-3].replace("/", ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        pkg, leaf = dotted.rsplit(".", 1)
        importers: list[str] = []
        for p in sorted(REPO.glob("deeptutor/**/*.py")):
            other = str(p.relative_to(REPO))
            if other == rel:
                continue
            try:
                tree, _ = load_tree(other)
            except (OSError, SyntaxError):
                continue
            hit = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == dotted or node.module.startswith(dotted + "."):
                        hit = True
                    elif node.module == pkg and any((a.asname or a.name) == leaf for a in node.names):
                        hit = True
                elif isinstance(node, ast.Import):
                    if any(a.name == dotted or a.name.startswith(dotted + ".") for a in node.names):
                        hit = True
                if hit:
                    break
            if hit:
                importers.append(other)
        return importers

    for (rel, cn), entry in sorted(orphan_candidates.items()):
        importers = runtime_importers(rel)
        if importers:
            detail = (f"class {cn} (name={entry.name_attr!r}) inherits BaseTool but has no BUILTIN_TOOL_SPECS "
                      f"entry; module is imported by runtime code: {', '.join(importers[:5])}")
            suggestion = "confirm whether it should be declared in builtin_specs.py"
        else:
            detail = (f"class {cn} (name={entry.name_attr!r}) inherits BaseTool but has no BUILTIN_TOOL_SPECS entry; "
                      "its module is imported nowhere in deeptutor/ runtime code (tests only), so the registry "
                      "can never serve it")
            suggestion = "declare it in builtin_specs.py or remove the dead implementation (+ its test)"
        findings.append(Finding("WARN", "Orphan BaseTool subclass not declared in the catalog",
                                detail, [f"{rel}:{entry.line}"], suggestion))

    # 4. enabled-state surfaces
    def check_list(label: str, names: list[str], anchor: str) -> None:
        for n in names:
            if n not in spec_by_name:
                findings.append(Finding("ERROR", f"{label} references unknown tool",
                                        f"{label} lists {n!r} but BUILTIN_TOOL_SPECS has no such name",
                                        [anchor], "remove it or add the spec"))

    check_list("USER_TOGGLEABLE_TOOL_NAMES", user_toggleable, f"{BUILTIN_INIT}:{user_line}")
    check_list("CONFIGURABLE_BUILTIN_TOOL_NAMES", configurable, f"{BUILTIN_INIT}:{conf_line}")
    check_list("PARTNER_BUILTIN_TOOL_NAMES (specs copy)", partner_specs, f"{SPECS_FILE}:{partner_line}")
    check_list("PARTNER_BUILTIN_TOOL_NAMES (partner_memory copy)", partner_memory_names, f"{PARTNER_MEMORY}:{pm_line}")
    check_list("WORKSPACE_BASELINE_TOOLS", workspace_baseline, f"{TOOL_COMPOSITION}:{ws_line}")
    check_list("_KB_COEXISTING_TOOLS", kb_coexisting, f"{TOOL_COMPOSITION}:{kb_line}")
    check_list("always-on mount tuple", always_on, f"{TOOL_COMPOSITION}:{always_line}")
    for alias, target in sorted(aliases.items()):
        if target not in spec_by_name:
            findings.append(Finding("ERROR", "TOOL_ALIASES target unknown",
                                    f"alias {alias!r} resolves to {target!r} which is not declared",
                                    [f"{SPECS_FILE}:{alias_line}"], "point the alias at a declared tool"))

    if partner_specs != partner_memory_names:
        findings.append(Finding("ERROR", "PARTNER_BUILTIN_TOOL_NAMES defined twice with different content",
                                f"specs copy {partner_specs} != partner_memory copy {partner_memory_names}",
                                [f"{SPECS_FILE}:{partner_line}", f"{PARTNER_MEMORY}:{pm_line}"],
                                "keep one definition and import it"))
    else:
        findings.append(Finding("INFO", "PARTNER_BUILTIN_TOOL_NAMES duplicated but currently in sync",
                                "two hand-maintained copies match today; a future edit on one side would silently diverge",
                                [f"{SPECS_FILE}:{partner_line}", f"{PARTNER_MEMORY}:{pm_line}"],
                                "single-source the tuple (one module defines it, the other imports)"))

    set_configurable, set_cond, set_always = set(configurable), set(conditional), set(always_on)
    missing_mount = set_configurable - set_cond - set_always
    if missing_mount:
        findings.append(Finding("ERROR", "CONFIGURABLE tools with no mount rule",
                                f"tools {sorted(missing_mount)} are in CONFIGURABLE_BUILTIN_TOOL_NAMES but appear in "
                                "neither _CONDITIONAL_MOUNT_FLAGS nor the always-on tuple, so the default chat "
                                "composition can never mount them",
                                [f"{BUILTIN_INIT}:{conf_line}", f"{TOOL_COMPOSITION}:{cond_line}",
                                 f"{TOOL_COMPOSITION}:{always_line}"],
                                "add a mount rule or move the tool to another surface"))
    extra_mount = (set_cond | set_always) - set_configurable
    if extra_mount:
        findings.append(Finding("WARN", "Mount rules reference tools outside CONFIGURABLE",
                                f"tools {sorted(extra_mount)} have mount rules but are not members of CONFIGURABLE_BUILTIN_TOOL_NAMES",
                                [f"{TOOL_COMPOSITION}:{cond_line}"],
                                "confirm membership is intentional (AUTO_MOUNTED_TOOLS derives from CONFIGURABLE)"))
    overlap = set(user_toggleable) & set_configurable
    if overlap:
        findings.append(Finding("WARN", "USER_TOGGLEABLE overlaps CONFIGURABLE",
                                f"tools {sorted(overlap)} appear on both surfaces; default_optional_tools() also "
                                "filters AUTO_MOUNTED_TOOLS, so the CONFIGURABLE membership wins and hides the toggle",
                                [f"{BUILTIN_INIT}:{user_line}", f"{BUILTIN_INIT}:{conf_line}",
                                 f"{TOOL_COMPOSITION}:40"],
                                "keep the two surfaces disjoint"))

    # docs parity: AGENTS.md user-toggleable table vs USER_TOGGLEABLE_TOOL_NAMES
    agents = REPO / "AGENTS.md"
    if agents.exists():
        text = agents.read_text(encoding="utf-8")
        m = __import__("re").search(r"### Level 1 — Tools.*?(?=###|\Z)", text, __import__("re").S)
        if m:
            section = m.group(0)
            for n in user_toggleable:
                if f"`{n}`" not in section:
                    sec_line = text[: text.index(section)].count("\n") + 1
                    findings.append(Finding("WARN", "AGENTS.md toggle table missing a user-toggleable tool",
                                            f"USER_TOGGLEABLE_TOOL_NAMES lists {n!r} but the AGENTS.md Level 1 table omits it",
                                            [f"{BUILTIN_INIT}:{user_line}", f"AGENTS.md:{sec_line}"],
                                            "update the doc table (or the tuple if the doc is right)"))

    # 5. registry surface
    reg_facts = registry_static_facts()
    if len(reg_facts) < 5:
        findings.append(Finding("ERROR", "tool_registry.py consumption anchors incomplete",
                                f"only {len(reg_facts)}/5 expected consumption points of the specs catalog were found",
                                [f"{TOOL_REGISTRY}:1"],
                                "restore BUILTIN_TOOL_SPEC_BY_NAME/BUILTIN_TOOL_NAMES usage"))

    probes: dict[str, dict] = {}
    reg_probe: dict = {}
    if not args.skip_probes:
        reg_code = (
            "import sys, json; sys.path.insert(0, %r); "
            "from deeptutor.runtime.registry.tool_registry import ToolRegistry; "
            "from deeptutor.tools.builtin_specs import BUILTIN_TOOL_NAMES, TOOL_ALIASES; "
            "r = ToolRegistry(); r.load_builtins(); "
            "listed = r.list_tools(); "
            "missing = [n for n in BUILTIN_TOOL_NAMES if n not in listed]; "
            "bad_alias = [a for a, (t, _) in TOOL_ALIASES.items() if t not in BUILTIN_TOOL_NAMES]; "
            "defs = r.get_definitions(None); "
            "print(json.dumps({'ok': True, 'list_len': len(listed), 'missing': missing, "
            "'bad_alias': bad_alias, 'def_count': len(defs)}))" % (str(REPO),)
        )
        try:
            proc = subprocess.run([probe_python, "-c", reg_code], capture_output=True, text=True,
                                  timeout=PROBE_TIMEOUT_S * 4)
            out = proc.stdout.strip().splitlines()
            reg_probe = json.loads(out[-1]) if out else {"ok": False, "err": proc.stderr[-300:]}
        except Exception as exc:  # noqa: BLE001
            reg_probe = {"ok": False, "err_type": type(exc).__name__, "err": str(exc)[:200]}
        for s in specs:
            probes[s.name] = run_probe(probe_python, s.name)
        drift = [n for n, p in probes.items() if p.get("ok") and p.get("name") != n]
        if drift:
            findings.append(Finding("ERROR", "Runtime name drift via spec.create()",
                                    f"spec.create() produced tools with names {drift} that differ from their spec names",
                                    [f"{SPECS_FILE}:34"], "fix the class `name` attributes"))
        failed = {n: p for n, p in probes.items() if not p.get("ok")}
        env_like = {n: p for n, p in failed.items() if p.get("err_type") == "ModuleNotFoundError"}
        code_like = {n: p for n, p in failed.items() if p.get("err_type") != "ModuleNotFoundError"}
        if code_like:
            findings.append(Finding("ERROR", "Instantiation failures at runtime",
                                    "; ".join(f"{n}: {p.get('err_type')}: {p.get('err')}" for n, p in sorted(code_like.items())),
                                    [f"{SPECS_FILE}:{spec_by_name[n].line}" for n in sorted(code_like)],
                                    "fix the failing tools so the registry can load them"))
        if env_like:
            findings.append(Finding("INFO", "Probe environment missing optional dependencies",
                                    "; ".join(f"{n}: {p.get('err')}" for n, p in sorted(env_like.items())) +
                                    f" (probe interpreter: {probe_python})",
                                    [f"{SPECS_FILE}:{spec_by_name[n].line}" for n in sorted(env_like)],
                                    "install the missing deps in the probe environment; not a code defect"))

    # 6. outputs
    spec_impl: dict[str, tuple[str, ImplEntry | None]] = {}
    for s in specs:
        mod, cls = s.class_path.rsplit(":", 1)
        found = resolver.locate(mod, cls)
        if found is None:
            spec_impl[s.name] = (module_to_file(mod), None)
            continue
        rel, clsdef = found
        spec_impl[s.name] = (rel, resolver.subclass_entry(rel, clsdef))
    write_outputs(specs, spec_impl, lists, comp, partner_specs, partner_line,
                  partner_memory_names, pm_line, aliases, alias_line, reg_facts,
                  findings, probes, reg_probe, probe_python)
    return 0


def write_outputs(specs, spec_impl, lists, comp, partner_specs, partner_line,
                  partner_memory_names, pm_line, aliases, alias_line, reg_facts,
                  findings, probes, reg_probe, probe_python) -> None:
    user_toggleable, _ = lists["USER_TOGGLEABLE_TOOL_NAMES"]
    configurable, _ = lists["CONFIGURABLE_BUILTIN_TOOL_NAMES"]
    coming_soon, _ = lists["COMING_SOON_TOOL_NAMES"]
    conditional, _ = comp["_CONDITIONAL_MOUNT_FLAGS"]
    workspace_baseline, _ = comp["WORKSPACE_BASELINE_TOOLS"]
    kb_coexisting, _ = comp["_KB_COEXISTING_TOOLS"]
    always_on, _ = comp["ALWAYS_ON"]

    def surface_of(name: str) -> str:
        bits = []
        if name in user_toggleable:
            bits.append("user-toggleable")
        if name in configurable:
            bits.append("auto/configurable")
        if name in always_on:
            bits.append("always-on")
        if name in conditional:
            bits.append(f"conditional:{conditional[name]}")
        if name in workspace_baseline:
            bits.append("workspace-baseline")
        if name in kb_coexisting:
            bits.append("kb-coexisting")
        if name in partner_specs:
            bits.append("partner-forced")
        if name in coming_soon:
            bits.append("coming-soon")
        return "; ".join(bits) or "capability-owned / off toggle surfaces"

    lines = [
        "# Built-in tool three-way parity table",
        "",
    ]
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        lines.append(f"Repo snapshot: origin/main @ `{head}` (scanned in place; static AST + subprocess probes)")
    except Exception:  # noqa: BLE001
        lines.append(f"Repo snapshot: `{REPO}` (scanned in place; static AST + subprocess probes)")
    lines += [
        f"Probe interpreter: `{probe_python}`",
        "",
        "| # | tool | spec declaration | class_path | implementation | impl `name` | deferred | enabled-state surface | probe |",
        "|---|------|------------------|------------|----------------|-------------|----------|-----------------------|-------|",
    ]
    ok_probes = sum(1 for p in probes.values() if p.get("ok"))
    for i, s in enumerate(specs, 1):
        rel, impl = spec_impl.get(s.name, ("", None))
        impl_loc = f"`{rel}:{impl.line}`" if impl else "**MISSING**"
        impl_name = impl.name_attr if impl and impl.name_attr else "?"
        deferred = "yes" if impl and impl.deferred_attr else "no"
        if s.name in probes:
            p = probes[s.name]
            probe = "ok" if p.get("ok") else f"FAIL({p.get('err_type', '?')})"
        else:
            probe = "skipped"
        lines.append(
            f"| {i} | `{s.name}` | `{SPECS_FILE}:{s.line}` | `{s.class_path}` | {impl_loc} | `{impl_name}` | {deferred} | {surface_of(s.name)} | {probe} |"
        )

    lines += ["", "## Registry consumption anchors", ""]
    for label, line_no in reg_facts:
        lines.append(f"- {label} (`{TOOL_REGISTRY}:{line_no}`)")
    lines.append(f"- PARTNER_BUILTIN_TOOL_NAMES: specs copy `{SPECS_FILE}:{partner_line}`, "
                 f"partner_memory copy `{PARTNER_MEMORY}:{pm_line}`")
    lines.append(f"- TOOL_ALIASES ({len(aliases)} entries): `{SPECS_FILE}:{alias_line}`")
    if reg_probe.get("ok"):
        lines.append(
            f"- Dynamic registry check: `list_tools()` len={reg_probe['list_len']}, "
            f"missing built-ins={reg_probe['missing']}, bad alias targets={reg_probe['bad_alias']}, "
            f"`get_definitions(None)` count={reg_probe['def_count']}"
        )
    else:
        lines.append(f"- Dynamic registry check FAILED: {reg_probe}")
    lines += [
        "",
        f"Probes: {ok_probes}/{len(probes)} tools instantiated OK in isolated subprocesses.",
        "",
    ]
    (EVIDENCE_DIR / "parity_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    fl = ["# Findings — builtin tool specs / registry / implementation parity", ""]
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    errors = [f for f in findings if f.severity == "ERROR"]
    if not errors:
        fl.append("**No ERROR-level drift found between specs, registry consumption and implementations.**")
        fl.append("")
    for f in sorted(findings, key=lambda x: order.get(x.severity, 3)):
        fl.append(f"## [{f.severity}] {f.title}")
        fl.append("")
        fl.append(f.detail)
        fl.append("")
        for ev in f.evidence:
            fl.append(f"- evidence: `{ev}`")
        if f.suggestion:
            fl.append(f"- fix: {f.suggestion}")
        fl.append("")
    (EVIDENCE_DIR / "findings.md").write_text("\n".join(fl) + "\n", encoding="utf-8")

    result = {
        "repo": str(REPO),
        "probe_python": probe_python,
        "total_specs": len(specs),
        "probes_total": len(probes),
        "probes_ok": ok_probes,
        "probes_failed": {k: v for k, v in probes.items() if not v.get("ok")},
        "registry_dynamic": reg_probe,
        "counts": {
            "user_toggleable": len(user_toggleable),
            "configurable": len(configurable),
            "always_on": len(always_on),
            "conditional_mounts": len(conditional),
            "workspace_baseline": len(workspace_baseline),
            "kb_coexisting": len(kb_coexisting),
            "aliases": len(aliases),
            "coming_soon": len(coming_soon),
        },
        "findings": [
            {"severity": f.severity, "title": f.title, "detail": f.detail,
             "evidence": f.evidence, "suggestion": f.suggestion}
            for f in findings
        ],
    }
    (EVIDENCE_DIR / "scan_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
