#!/usr/bin/env python3
"""Static scan: prompt-template placeholders vs call-site format arguments.

Read-only analysis of a DeepTutor checkout. Emits JSON with:
- template inventory (placeholder sets per file)
- call-site inventory (load_prompts / get_prompt / .format sites)
- pairings and drift classification (missing / extra / naming-drift)
"""
from __future__ import annotations

import ast
import json
import re
import string
import sys
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
PKG = REPO / "deeptutor"

FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\]|\['[^']+'\]|\[\"[^\"]+\"\])*$")


def extract_fields(text: str):
    named, positional, invalid = set(), set(), []
    try:
        for lit, field, spec, conv in string.Formatter().parse(text):
            if field is None:
                continue
            base = field.split(".")[0].split("[")[0]
            if field == "" or base.isdigit():
                positional.add(field)
            elif FIELD_RE.match(field):
                named.add(field)
            else:
                invalid.append(field)
    except ValueError as e:
        invalid.append(f"<unparseable: {e}>")
    return named, positional, invalid


def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v)


def template_inventory():
    import yaml

    items = []
    for d in sorted(PKG.rglob("prompts")):
        if "test" in str(d.relative_to(REPO)):
            continue
        for f in sorted(list(d.rglob("*.yaml")) + list(d.rglob("*.yml")) + list(d.rglob("*.md"))):
            rel = f.relative_to(REPO).as_posix()
            named, positional, invalid = set(), set(), []
            str_count = 0
            try:
                if f.suffix in (".yaml", ".yml"):
                    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    strs = list(walk_strings(data))
                    str_count = len(strs)
                    for s in strs:
                        n, p, i = extract_fields(s)
                        named |= n
                        positional |= p
                        invalid += i
                else:
                    text = f.read_text(encoding="utf-8")
                    str_count = 1
                    named, positional, invalid = extract_fields(text)
            except Exception as e:  # noqa: BLE001
                invalid.append(f"<file unparseable: {e}>")
            items.append({
                "file": rel,
                "strings": str_count,
                "named": sorted(named),
                "positional": sorted(positional),
                "invalid": invalid,
            })
    return items


# ---------------- call-site analysis ----------------

class FuncScope:
    def __init__(self, name, node):
        self.name = name
        self.node = node
        self.bindings = {}  # name -> expr AST (last assignment)


def qual_call(node):
    """Return dotted name of func if it's a simple attribute chain."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def literal_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class Analyzer(ast.NodeVisitor):
    def __init__(self, rel):
        self.rel = rel
        self.loaders = []       # {module,agent,subdir,line}
        self.fetches = []       # {key,line,receiver}
        self.formats = []       # {receiver_desc,kwargs,pos,keys,line,scope}
        self.scopes = [FuncScope("<module>", None)]
        self.replace_sites = [] # .replace("{name}", ...) on likely templates
        self.t_calls = []       # _t("key", default=..., kw=val) i18n-style fetch+format

    # scope helpers -----------------------------------------------------
    def bind(self, name, value):
        if isinstance(name, ast.Name):
            self.scopes[-1].bindings[name.id] = value

    def lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc.bindings:
                return sc.bindings[name]
        return None

    def resolve_receiver(self, node, depth=0):
        """Resolve .format() receiver to a descriptor string."""
        if depth > 3 or node is None:
            return None
        if isinstance(node, ast.Call):
            q = qual_call(node.func)
            if q and q.split(".")[-1] in ("get_prompt", "prompt_text"):
                return "fetch:" + q
            if q and q.endswith("load_prompts"):
                return "load_prompts"
            return None
        if isinstance(node, ast.Subscript):
            base = self.resolve_receiver(node.value, depth + 1)
            if base and base.startswith("var:"):
                sl = node.slice
                key = literal_str(sl) if isinstance(sl, ast.Constant) else (
                    literal_str(sl.value) if isinstance(sl, ast.Index) and isinstance(sl.value, ast.Constant) else None
                )
                if key:
                    return base + "[" + key + "]"
            return base
        if isinstance(node, ast.Name):
            bound = self.lookup(node.id)
            if bound is not None:
                r = self.resolve_receiver(bound, depth + 1)
                if r:
                    return r
            # heuristics: names that look like prompt/template holders
            if re.search(r"prompt|template", node.id, re.I):
                return "var:" + node.id
            return None
        if isinstance(node, ast.Attribute):
            r = self.resolve_receiver(node.value, depth + 1)
            if r:
                return r + "." + node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            return self.resolve_receiver(node.func.value, depth + 1)
        return None

    # visitors ----------------------------------------------------------
    def visit_FunctionDef(self, node):
        self.scopes.append(FuncScope(node.name, node))
        self.generic_visit(node)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name):
                self.bind(t.id, node.value)
            elif isinstance(t, ast.Tuple):
                pass
        self.generic_visit(node)

    def visit_Call(self, node):
        q = qual_call(node.func) or ""

        # loader: X.load_prompts(module, agent, language=..., subdirectory=...)
        if q.endswith("load_prompts") and len(node.args) >= 2:
            mod, agent = literal_str(node.args[0]), literal_str(node.args[1])
            sub = None
            for kw in node.keywords:
                if kw.arg == "subdirectory":
                    sub = literal_str(kw.value)
            self.loaders.append({"module": mod, "agent": agent, "subdir": sub,
                                 "line": node.lineno, "args_literal": bool(mod and agent)})

        # fetch: X.get_prompt(key[, default]) — method form: args[0] is the key,
        # any further positional args are fallback text, not nested fields.
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get_prompt":
            key = literal_str(node.args[0]) if node.args else None
            if key is not None:
                self.fetches.append({"key": key, "line": node.lineno})

        # learning prompt_text(language, "path")
        if q.endswith("prompt_text") and len(node.args) >= 2:
            p = literal_str(node.args[1])
            if p:
                self.fetches.append({"key": p, "line": node.lineno, "learning": True})

        # .format(...) sites (method call only)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            kws, pos = [], []
            for a in node.args:
                if isinstance(a, ast.Name):
                    pos.append(a.id)
                elif isinstance(a, ast.Starred):
                    pos.append("*" + (a.value.id if isinstance(a.value, ast.Name) else "?"))
                else:
                    pos.append("<expr>")
            for kw in node.keywords:
                if kw.arg:
                    kws.append(kw.arg)
                else:
                    kws.append("**" + (kw.value.id if isinstance(kw.value, ast.Name) else "?"))
            recv = self.resolve_receiver(node.func.value)
            self.formats.append({
                "receiver": recv, "kwargs": kws, "pos": pos,
                "line": node.lineno, "scope": self.scopes[-1].name,
            })

        # .replace("{name}", ...) sites (manual substitution renderers)
        if q.endswith("replace") and node.args:
            lit = literal_str(node.args[0])
            m = re.fullmatch(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lit) if lit else None
            if m:
                recv = self.resolve_receiver(node.func.value)
                self.replace_sites.append({"var": m.group(1), "receiver": recv, "line": node.lineno})

        # i18n-style helper: self._t("key", default=..., kw=val, ...) -> fetch+format
        leaf = q.split(".")[-1]
        if leaf in ("_t", "t", "translate") and node.args:
            key = literal_str(node.args[0])
            if key:
                kws = [kw.arg for kw in node.keywords if kw.arg and kw.arg != "default"]
                if kws:
                    self.t_calls.append({"key": key, "kwargs": kws, "line": node.lineno,
                                         "scope": self.scopes[-1].name})

        self.generic_visit(node)


def call_inventory():
    out = {}
    for f in sorted(PKG.rglob("*.py")):
        rel = f.relative_to(REPO).as_posix()
        if "/tests/" in rel or rel.endswith("_test.py") or "learning/tests/" in rel:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        an = Analyzer(rel)
        an.visit(tree)
        if an.loaders or an.fetches or an.formats or an.replace_sites:
            out[rel] = {
                "loaders": an.loaders,
                "fetches": an.fetches,
                "formats": an.formats,
                "replace_sites": an.replace_sites,
                "t_calls": an.t_calls,
            }
    return out


def main():
    data = {
        "templates": template_inventory(),
        "calls": call_inventory(),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"templates={len(data['templates'])} call_files={len(data['calls'])}")


if __name__ == "__main__":
    main()
