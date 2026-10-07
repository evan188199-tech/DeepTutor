#!/usr/bin/env python3
"""Three-way consistency scan: docstring claims vs annotations vs actual returns.

Universe: public functions inside the fanin-ranked modules listed in
``fanin_top50.json`` (exported from scan/coverage-gaps-det-20261006),
crossed with the current main checkout.

Static pass (deterministic, AST-only):
  - docstring structured sections (Google Args/Returns, NumPy Parameters/Returns,
    RST :param:/:rtype:) parsed into declared params/return type
  - docstring param names vs signature params
  - docstring declared return type vs return annotation (token equivalence)
  - signature required params documented or not
  - ``-> None`` annotation vs body ``return <expr>``

Runtime pass (sampled, subprocess-isolated, safe-arg construction only):
  - call pure-candidate functions with trivially safe scalar args
  - compare observed return structure against annotation and docstring claims

Outputs (written next to this script by default):
  - drift_report.json : raw machine-readable entries
  - report.md         : human-readable drift table with path:line anchors

Usage:
  python3 scan_annotation_drift.py --repo-root <repo> --fanin fanin_top50.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Type-token handling
# --------------------------------------------------------------------------

BASE_EQUIV: dict[str, set[str]] = {
    "str": {"str", "text", "string", "path", "pathstr"},
    "bool": {"bool", "boolean"},
    "int": {"int", "integer"},
    "float": {"float", "number", "num"},
    "dict": {"dict", "mapping", "dict[str,any]", "dictionary"},
    "list": {"list", "sequence", "seq", "array"},
    "tuple": {"tuple"},
    "set": {"set", "frozenset"},
    "bytes": {"bytes"},
    "none": {"none", "no", "noreturn"},
    "callable": {"callable", "function", "func"},
}

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def norm_token(token: str) -> str:
    token = token.strip().strip("`\"'").strip()
    token = re.sub(r"^(typing\.)", "", token)
    token = token.rstrip(".").lower()
    return token


def base_of(token: str) -> str:
    token = norm_token(token)
    token = re.sub(r"^optional\[(.+)\]$", r"\1", token)
    token = token.split("|")[0].strip()
    m = IDENT_RE.match(token)
    if not m:
        return token or "unknown"
    return m.group(0).lower()


def tokens_equiv(doc_token: str, ann_token: str) -> bool:
    d, a = base_of(doc_token), base_of(ann_token)
    if d == a:
        return True
    deq = BASE_EQUIV.get(d, {d})
    aeq = BASE_EQUIV.get(a, {a})
    return bool(deq & aeq)


ANN_BASE: dict[str, str] = {
    "str": "str", "bool": "bool", "int": "int", "float": "float",
    "bytes": "bytes", "dict": "dict", "list": "list", "tuple": "tuple",
    "set": "set", "frozenset": "set", "Path": "path", "None": "none",
    "NoReturn": "none", "Any": "unknown", "object": "unknown",
    "Mapping": "dict", "MutableMapping": "dict", "Sequence": "list",
    "Iterable": "list", "Iterator": "iterator", "Generator": "iterator",
    "AsyncIterator": "aiter", "Callable": "callable", "type": "type",
    "BaseModel": "pydantic", "Literal": "literal",
}


def ann_bases(ann_src: str) -> set[str]:
    """Approximate the set of runtime base kinds an annotation admits."""
    src = re.sub(r"^(typing\.)", "", ann_src.strip())
    if src in ("", "unknown"):
        return {"unknown"}
    if src in ANN_BASE:
        return {ANN_BASE[src]}
    m = re.match(r"^(Optional|Union)\[(.+)\]$", src)
    if m:
        inner, out = m.group(2), set()
        depth = 0
        parts, cur = [], ""
        for ch in inner:
            if ch in "[(":
                depth += 1
            elif ch in "])":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for p in parts:
            out |= ann_bases(p.strip())
        return out
    if "|" in src and "[" not in src:
        out = set()
        for p in src.split("|"):
            out |= ann_bases(p.strip())
        return out
    m = re.match(r"^([A-Za-z_][A-Za-z_0-9]*)\[", src)
    if m:
        head = m.group(1)
        if head in ("dict", "Mapping", "MutableMapping", "Dict"):
            return {"dict"}
        if head in ("list", "List", "Sequence", "Iterable"):
            return {"list"}
        if head in ("tuple", "Tuple"):
            return {"tuple"}
        if head in ("set", "Set", "FrozenSet"):
            return {"set"}
        if head == "Literal":
            return {"str"}
        if head in ("Iterator", "Generator"):
            return {"iterator"}
        if head == "Callable":
            return {"callable"}
        if head in ("Coroutine",):
            return {"coro"}
        return {ANN_BASE.get(head, head.lower())}
    m = re.match(r"^([A-Za-z_][A-Za-z_0-9\.]*)$", src)
    if m:
        head = m.group(1).split(".")[-1]
        return {ANN_BASE.get(head, head.lower())}
    return {"unknown"}


def observed_kind(value: object) -> dict:
    if value is None:
        return {"kind": "none"}
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}
    if isinstance(value, int):
        return {"kind": "int"}
    if isinstance(value, float):
        return {"kind": "float"}
    if isinstance(value, str):
        return {"kind": "str", "len": len(value)}
    if isinstance(value, bytes):
        return {"kind": "bytes", "len": len(value)}
    if isinstance(value, dict):
        keys = [k for k in value.keys() if isinstance(k, str)][:12]
        return {"kind": "dict", "len": len(value), "keys": sorted(keys)}
    if isinstance(value, (list, tuple)):
        el = ""
        if len(value):
            el = type(value[0]).__name__
        return {"kind": type(value).__name__, "len": len(value), "elem": el}
    if isinstance(value, (set, frozenset)):
        return {"kind": "set", "len": len(value)}
    import collections.abc as abc
    if isinstance(value, (abc.Iterator, abc.Generator)):
        return {"kind": "iterator"}
    tn = type(value).__name__
    if tn in ("PosixPath", "WindowsPath"):
        return {"kind": "path"}
    return {"kind": "object:" + tn}


def kind_matches(kind: str, bases: set[str]) -> bool:
    if "unknown" in bases:
        return True
    base_set = {b.lower() for b in bases}
    if kind.lower() in base_set:
        return True
    if kind.startswith("object:") and kind.split(":", 1)[1].lower() in base_set:
        return True
    if kind == "bool" and "int" in base_set:
        return True
    if kind == "int" and "float" in base_set:
        return True
    if kind == "path" and "str" in base_set:
        return True
    return False


# --------------------------------------------------------------------------
# Docstring parsing
# --------------------------------------------------------------------------

SECTION_HEAD = re.compile(
    r"^\s*(Args|Arguments|Parameters|Params|Returns?|Return|Yields|Raises|Note|Notes|Example|Examples)\s*:?\s*$",
    re.IGNORECASE,
)
GOOGLE_PARAM = re.compile(
    r"^\s{2,}(\*{0,2}[A-Za-z_][A-Za-z_0-9]*)\s*(?:\(([^)]*)\))?\s*(?::|--|\u2013)\s*(.*)$"
)
NUMPY_DASHES = re.compile(r"^\s*(-{3,}|={3,})\s*$")
NUMPY_PARAM = re.compile(r"^\s{2,}(\*{0,2}[A-Za-z_][A-Za-z_0-9]*)\s*:\s*(\S.*)$")
RST_PARAM = re.compile(r":(?:param|parameter|keyword|arg)\s+(?:([A-Za-z_][A-Za-z_0-9.*\[\] ]+?)\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*:")
RST_RTYPE = re.compile(r":(?:rtype|returns|return)\s*:?\s*(.*)")

# a type token: identifier, optional [..] generic, optional unions of the same
TYPE_RE = re.compile(
    r"^[A-Za-z_][A-Za-z_0-9]*(\[[^\]]*\])?(\s*\|\s*[A-Za-z_][A-Za-z_0-9]*(\[[^\]]*\])?)*$"
)
TYPE_WORDS = {
    "str", "text", "string", "bool", "boolean", "int", "float", "number", "num",
    "dict", "mapping", "list", "sequence", "seq", "tuple", "set", "frozenset",
    "bytes", "none", "path", "object", "callable", "iterator", "generator",
    "optional", "any", "json", "type", "literal", "datetime", "date", "dictionary",
}


def maybe_type(tok: str | None) -> str | None:
    """Return a normalized type token, or None when tok is free prose."""
    if not tok:
        return None
    tok = tok.strip().strip("`\"'").strip().rstrip(".")
    if not tok:
        return None
    if TYPE_RE.match(tok):
        return norm_token(tok)
    first = re.match(r"^([A-Za-z_][A-Za-z_0-9.]*)\b", tok)
    if first and first.group(1).lower() in TYPE_WORDS:
        return norm_token(first.group(1))
    return None


@dataclass
class DocClaims:
    params: dict[str, str | None] = field(default_factory=dict)  # name -> declared type or None
    returns: str | None = None
    structured: bool = False
    mentioned_names: set[str] = field(default_factory=set)


def parse_docstring(doc: str) -> DocClaims:
    claims = DocClaims()
    if not doc:
        return claims
    lines = doc.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        head = SECTION_HEAD.match(line)
        if head:
            title = head.group(1).lower()
            if title in ("args", "arguments", "parameters", "params"):
                claims.structured = True
                j = i + 1
                while j < n and not SECTION_HEAD.match(lines[j]):
                    m = GOOGLE_PARAM.match(lines[j])
                    mn = NUMPY_PARAM.match(lines[j])
                    if m:
                        name = m.group(1).lstrip("*")
                        ptype = m.group(2)
                        if not ptype and m.group(3):
                            ptype = maybe_type(m.group(3).strip().split(". ")[0])
                        claims.params[name] = norm_token(ptype) if ptype else None
                    elif mn:
                        name = mn.group(1).lstrip("*")
                        claims.params[name] = maybe_type(mn.group(2))
                    j += 1
                i = j
                continue
            if title in ("returns", "return"):
                claims.structured = True
                j = i + 1
                body: list[str] = []
                while j < n and not SECTION_HEAD.match(lines[j]):
                    body.append(lines[j])
                    j += 1
                text = "\n".join(body).strip()
                if text:
                    first_line = text.splitlines()[0].strip()
                    claims.returns = maybe_type(first_line)
                i = j
                continue
            # other sections: skip to end of section
            j = i + 1
            while j < n and not SECTION_HEAD.match(lines[j]):
                j += 1
            i = j
            continue
        for rm in RST_PARAM.finditer(line):
            claims.structured = True
            claims.params[rm.group(2)] = maybe_type(rm.group(1))
        rt = RST_RTYPE.search(line)
        if rt and rt.group(1).strip():
            token = maybe_type(rt.group(1))
            if token:
                claims.structured = True
                claims.returns = token
        i += 1
    for name in re.findall(r"[`*]{1,2}([a-z_][a-z_0-9]{2,})[`*]{1,2}", doc):
        claims.mentioned_names.add(name)
    for name in re.findall(r"\b([a-z_][a-z_0-9]{2,})\b", doc):
        claims.mentioned_names.add(name)
    return claims


# --------------------------------------------------------------------------
# AST analysis
# --------------------------------------------------------------------------

@dataclass
class FuncInfo:
    module: str
    fanin: int
    qualname: str
    name: str
    path: str
    lineno: int
    end_lineno: int
    is_method: bool
    is_static: bool
    is_async: bool
    params: list[dict]
    ret_ann: str
    ret_ann_lineno: int
    doc: str
    doc_start: int


@dataclass
class ClassInfo:
    name: str
    module: str
    lineno: int
    bases: list[str]
    doc_claims: DocClaims = field(default_factory=DocClaims)
    init_fn: FuncInfo | None = None
    methods: dict[str, FuncInfo] = field(default_factory=dict)


def analyze_module(rel_path: str, module: str, fanin: int) -> tuple[list[FuncInfo], list[ClassInfo]]:
    src = open(rel_path, "r", encoding="utf-8").read()
    tree = ast.parse(src, filename=rel_path)
    out: list[FuncInfo] = []
    classes: list[ClassInfo] = []

    def sig_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
        a = node.args
        items = []
        pos = list(a.posonlyargs) + list(a.args)
        for idx, p in enumerate(pos):
            items.append({
                "name": p.arg,
                "ann": ast.unparse(p.annotation) if p.annotation else "",
                "required": idx >= len(a.defaults),
                "kind": "pos",
            })
        if a.vararg:
            items.append({"name": "*" + a.vararg.arg, "ann": "", "required": False, "kind": "vararg"})
        for p, d in zip(a.kwonlyargs, a.kw_defaults):
            items.append({
                "name": p.arg,
                "ann": ast.unparse(p.annotation) if p.annotation else "",
                "required": d is None,
                "kind": "kw",
            })
        if a.kwarg:
            items.append({"name": "**" + a.kwarg.arg, "ann": "", "required": False, "kind": "varkw"})
        return items

    def add_func(node, qual_prefix: str, is_method: bool, is_static: bool) -> FuncInfo | None:
        if node.name.startswith("_") and node.name != "__init__":
            return None
        doc = ast.get_docstring(node) or ""
        ret_ann = ""
        ret_ln = node.lineno
        if node.returns is not None:
            ret_ann = ast.unparse(node.returns)
            ret_ln = node.returns.lineno
        fi = FuncInfo(
            module=module,
            fanin=fanin,
            qualname=qual_prefix + node.name,
            name=node.name,
            path=rel_path,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            is_method=is_method,
            is_static=is_static,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            params=sig_params(node),
            ret_ann=ret_ann,
            ret_ann_lineno=ret_ln,
            doc=doc,
            doc_start=(node.body[0].lineno if node.body and isinstance(node.body[0], ast.Expr) else node.lineno),
        )
        out.append(fi)
        return fi

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_func(node, "", False, False)
        elif isinstance(node, ast.ClassDef):
            ci = ClassInfo(
                name=node.name,
                module=module,
                lineno=node.lineno,
                bases=[ast.unparse(b).split(".")[-1] for b in node.bases],
                doc_claims=parse_docstring(ast.get_docstring(node) or ""),
            )
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_static = any(
                        isinstance(d, ast.Name) and d.id == "staticmethod"
                        or isinstance(d, ast.Attribute) and d.attr == "staticmethod"
                        for d in sub.decorator_list
                    )
                    fi = add_func(sub, node.name + ".", True, is_static)
                    if fi is None:
                        continue
                    if not sub.name.startswith("_") or sub.name == "__init__":
                        ci.methods[sub.name] = fi
                    if sub.name == "__init__":
                        ci.init_fn = fi
            classes.append(ci)
    return out, classes


def class_docstring_vs_init(ci: ClassInfo) -> list[dict]:
    """Class docstring structured Args vs __init__ signature."""
    drifts: list[dict] = []
    if not ci.doc_claims.structured or not ci.init_fn:
        return drifts
    init_params = {}
    for p in ci.init_fn.params:
        bare = p["name"].lstrip("*")
        if bare in SELF_NAMES or p["kind"] in ("vararg", "varkw"):
            continue
        init_params[bare] = p
    for dname, dtype in ci.doc_claims.params.items():
        if dname in init_params:
            p = init_params[dname]
            if dtype and p["ann"] and not tokens_equiv(dtype, p["ann"]):
                drifts.append({
                    "kind": "class_docstring_param_type_vs_init",
                    "severity": "medium",
                    "anchor": f"{ci.init_fn.path}:{ci.init_fn.lineno}",
                    "detail": f"{ci.name}.__init__ param '{dname}': class docstring type "
                              f"'{dtype}' vs annotation '{p['ann']}'",
                })
        elif dname in ("kwargs", "args"):
            continue
        else:
            drifts.append({
                "kind": "class_docstring_param_not_in_init",
                "severity": "medium",
                "anchor": f"{ci.init_fn.path}:{ci.init_fn.lineno}",
                "detail": f"{ci.name} class docstring documents param '{dname}' "
                          f"absent from __init__ ({', '.join(sorted(init_params)) or 'no params'})",
            })
    return drifts


def override_signature_drifts(classes: list[ClassInfo]) -> list[dict]:
    """Public methods whose signature drifted from the same method on a base
    class defined in the scanned universe (LSP-facing doc/annotation drift)."""
    by_name: dict[str, ClassInfo] = {c.name: c for c in classes}
    rows: dict[tuple, dict] = {}
    for c in classes:
        for bname in c.bases:
            base = by_name.get(bname)
            if base is None or base is c:
                continue
            for mname, child_fn in c.methods.items():
                base_fn = base.methods.get(mname)
                if base_fn is None:
                    continue

                def req_key(fi: FuncInfo) -> list[str]:
                    keys = []
                    for p in fi.params:
                        bare = p["name"].lstrip("*")
                        if bare in SELF_NAMES or p["kind"] in ("vararg", "varkw"):
                            continue
                        if p["required"]:
                            keys.append(bare + (":kw" if p["kind"] == "kw" else ""))
                    return keys

                a, b = req_key(child_fn), req_key(base_fn)
                if a == b:
                    continue
                key = (c.name, bname, mname)
                if key in rows:
                    continue
                rows[key] = {
                    "kind": "override_signature_mismatch",
                    "severity": "medium",
                    "anchor": f"{child_fn.path}:{child_fn.lineno}",
                    "detail": f"{c.name}.{mname} required params {a or '[]'} != "
                              f"{bname}.{mname} required params {b or '[]'}",
                }
    return sorted(rows.values(), key=lambda r: r["anchor"])


def body_returns_value(node) -> bool:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, ast.Return) and child.value is not None:
            if not (isinstance(child.value, ast.Constant) and child.value.value is None):
                return True
        if body_returns_value(child):
            return True
    return False


# --------------------------------------------------------------------------
# Static drift per function
# --------------------------------------------------------------------------

SELF_NAMES = {"self", "cls"}


def static_checks(fi: FuncInfo) -> list[dict]:
    drifts: list[dict] = []
    claims = parse_docstring(fi.doc)

    # ghost params: structured docstring param not in signature
    sig_names = {p["name"].lstrip("*") for p in fi.params} - SELF_NAMES
    for dname in claims.params:
        if dname in sig_names:
            continue
        if dname in ("kwargs", "args", "kwds"):
            continue
        drifts.append({
            "kind": "doc_param_not_in_signature",
            "severity": "medium",
            "anchor": f"{fi.path}:{fi.doc_start}",
            "detail": f"docstring documents param '{dname}' absent from signature "
                      f"({', '.join(sorted(sig_names)) or 'no params'})",
        })

    # required params undocumented (function has a docstring)
    if fi.doc.strip():
        for p in fi.params:
            bare = p["name"].lstrip("*")
            if bare in SELF_NAMES or p["kind"] in ("vararg", "varkw"):
                continue
            if not p["required"]:
                continue
            if bare in claims.params:
                continue
            if bare in claims.mentioned_names:
                continue
            drifts.append({
                "kind": "required_param_undocumented",
                "severity": "low",
                "anchor": f"{fi.path}:{fi.lineno}",
                "detail": f"required param '{bare}' not documented in docstring",
            })

    # docstring return type vs annotation
    if claims.returns and fi.ret_ann:
        if not tokens_equiv(claims.returns, fi.ret_ann):
            drifts.append({
                "kind": "docstring_return_vs_annotation",
                "severity": "medium",
                "anchor": f"{fi.path}:{fi.ret_ann_lineno}",
                "detail": f"docstring Returns '{claims.returns}' vs annotation '-> {fi.ret_ann}'",
            })
    elif claims.returns and not fi.ret_ann:
        drifts.append({
            "kind": "docstring_return_unannotated",
            "severity": "low",
            "anchor": f"{fi.path}:{fi.lineno}",
            "detail": f"docstring declares return '{claims.returns}' but function is unannotated",
        })

    # structured docstring param type vs annotation
    for p in fi.params:
        bare = p["name"].lstrip("*")
        declared = claims.params.get(bare)
        if declared and p["ann"] and not tokens_equiv(declared, p["ann"]):
            drifts.append({
                "kind": "docstring_param_type_vs_annotation",
                "severity": "medium",
                "anchor": f"{fi.path}:{fi.lineno}",
                "detail": f"param '{bare}': docstring type '{declared}' vs annotation '{p['ann']}'",
            })

    # -> None but body returns values
    if fi.ret_ann in ("None", "NoReturn"):
        tree = ast.parse(open(fi.path, encoding="utf-8").read(), filename=fi.path)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == fi.lineno and node.name == fi.name:
                target = node
                break
        if target is not None and body_returns_value(target):
            drifts.append({
                "kind": "annot_none_but_returns_value",
                "severity": "high",
                "anchor": f"{fi.path}:{fi.lineno}",
                "detail": "annotated '-> None' but body contains 'return <value>'",
            })
    return drifts


# --------------------------------------------------------------------------
# Runtime sampling
# --------------------------------------------------------------------------

SAFE_DEFAULTS = {
    "str": "''", "int": "0", "float": "0.0", "bool": "False",
    "bytes": "b''", "list": "[]", "dict": "{}", "set": "set()",
    "tuple": "()", "path": "''", "literal": "''", "none": "None",
}

NAME_DENY = re.compile(
    r"(ensure|install|register|unregister|initialize|migrate|reload|clear|reset"
    r"|submit|stage|publish|create_|delete_|remove_|teardown)",
    re.IGNORECASE,
)

BODY_FORBID = re.compile(
    r"\b(open|mkdir|makedirs|unlink|rmtree|remove|rename|replace|touch|symlink"
    r"|write|writelines|chmod|chown|copyfile|move|shutil|system|popen"
    r"|subprocess|environ|getenv|sleep|random|uuid|utcnow|now|today|datetime"
    r"|requests|urlopen|httpx|socket|Session|connect|execute|Thread|Process"
    r"|emit|broadcast|publish|send|time)\b"
)

RUNTIME_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "",  # filled at call time
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "LC_ALL": "C",
}


def runtime_candidate(fi: FuncInfo) -> tuple[bool, str]:
    if fi.is_async:
        return False, "async"
    if fi.is_method and not fi.is_static:
        return False, "instance-method"
    if NAME_DENY.search(fi.name):
        return False, "name-stateful"
    src = open(fi.path, encoding="utf-8").read()
    tree = ast.parse(src, filename=fi.path)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == fi.lineno and node.name == fi.name:
            target = node
            break
    if target is None:
        return False, "not-found"
    for d in target.decorator_list:
        dname = d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
        if dname in ("contextmanager", "asynccontextmanager"):
            return False, "contextmanager"
    for p in fi.params:
        bare = p["name"].lstrip("*")
        if bare in SELF_NAMES:
            continue
        if p["kind"] in ("vararg", "varkw"):
            continue
        if p["required"]:
            bases = ann_bases(p["ann"]) if p["ann"] else {"unknown"}
            if bases == {"unknown"} or not (bases & set(SAFE_DEFAULTS)):
                return False, f"unsafe-required-param:{bare}"
        # optional params fine: omitted
    body_src = ast.get_source_segment(src, target) or ""
    if BODY_FORBID.search(body_src):
        return False, "body-touches-io"
    return True, ""


def build_call_expr(fi: FuncInfo) -> str | None:
    parts = []
    for p in fi.params:
        bare = p["name"].lstrip("*")
        if bare in SELF_NAMES:
            continue
        if p["kind"] == "vararg":
            parts.append("*[]")
            continue
        if p["kind"] == "varkw":
            parts.append("**{}")
            continue
        if p["required"]:
            bases = ann_bases(p["ann"])
            base = sorted(bases & set(SAFE_DEFAULTS))
            if not base:
                return None
            val = SAFE_DEFAULTS[base[0]]
            parts.append(f"{bare}={val}" if p["kind"] == "kw" else val)
        # optional: omit
    return fi.name + "(" + ", ".join(parts) + ")"


def run_one(mod_name: str, func_name: str, inner_args: str,
            python_exe: str, repo_root: str, timeout: float = 60.0) -> dict:
    harness = (
        "import importlib, json, sys\n"
        "mod = importlib.import_module(sys.argv[1])\n"
        "fn = getattr(mod, sys.argv[2])\n"
        "r = eval('fn(' + sys.argv[3] + ')', {'fn': fn})\n"
        "def obs(v):\n"
        "    import collections.abc as abc, pathlib\n"
        "    if v is None: return {'kind':'none'}\n"
        "    if isinstance(v, bool): return {'kind':'bool'}\n"
        "    if isinstance(v, int): return {'kind':'int'}\n"
        "    if isinstance(v, float): return {'kind':'float'}\n"
        "    if isinstance(v, str): return {'kind':'str','len':len(v)}\n"
        "    if isinstance(v, bytes): return {'kind':'bytes','len':len(v)}\n"
        "    if isinstance(v, dict): return {'kind':'dict','len':len(v),'keys':sorted([k for k in v if isinstance(k,str)])[:12]}\n"
        "    if isinstance(v, (list, tuple)):\n"
        "        return {'kind':type(v).__name__,'len':len(v),'elem':(type(v[0]).__name__ if len(v) else '')}\n"
        "    if isinstance(v, (set, frozenset)): return {'kind':'set','len':len(v)}\n"
        "    if isinstance(v, (abc.Iterator, abc.Generator)): return {'kind':'iterator'}\n"
        "    if isinstance(v, pathlib.PurePath): return {'kind':'path'}\n"
        "    return {'kind':'object:'+type(v).__name__}\n"
        "print(json.dumps(obs(r)))\n"
    )
    with tempfile.TemporaryDirectory(prefix="drift_rt_") as td:
        env = dict(RUNTIME_ENV)
        env["HOME"] = td
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [python_exe, "-c", harness, mod_name, func_name, inner_args],
            capture_output=True, text=True, timeout=timeout,
            cwd=td, env=env,
        )
    return {
        "rc": proc.returncode,
        "stdout": proc.stdout.strip()[-400:],
        "stderr_tail": proc.stderr.strip()[-400:],
    }


def verdict_from_actual(actual: dict, ret_ann: str, ret_anchor: str,
                        doc_returns: str | None, doc_anchor: str) -> list[dict]:
    drifts: list[dict] = []
    kind = actual.get("kind", "unknown")
    if ret_ann:
        bases = ann_bases(ret_ann)
        if bases != {"unknown"} and not kind_matches(kind, bases):
            drifts.append({
                "kind": "runtime_return_vs_annotation",
                "severity": "high",
                "anchor": ret_anchor,
                "detail": f"annotation '-> {ret_ann}' but runtime returns {kind}",
            })
    if doc_returns:
        if not kind_matches(kind, {base_of(doc_returns)}):
            drifts.append({
                "kind": "runtime_return_vs_docstring",
                "severity": "high",
                "anchor": doc_anchor,
                "detail": f"docstring Returns '{doc_returns}' but runtime returns {kind}",
            })
    return drifts


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--fanin", required=True)
    ap.add_argument("--sample-cap", type=int, default=200)
    ap.add_argument("--runtime-cap", type=int, default=30)
    ap.add_argument("--runtime-target", type=int, default=12)
    ap.add_argument("--out-dir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--venv-python", default=sys.executable,
                    help="interpreter used for runtime sampling (repo venv python)")
    ap.add_argument("--run-runtime", choices=["yes", "no"], default="yes")
    args = ap.parse_args()

    root = os.path.abspath(args.repo_root)
    fanin_path = os.path.abspath(args.fanin)
    fanin = json.load(open(fanin_path, encoding="utf-8"))
    os.chdir(root)

    # resolve fanin entries -> existing modules in current main
    modules: dict[str, int] = {}
    missing: list[dict] = []
    for name, f in fanin:
        rel = name.replace(".", "/")
        hit = None
        for cand in (rel + ".py", rel + "/__init__.py"):
            if os.path.exists(os.path.join(root, cand)):
                hit = cand
                break
        if hit is None:
            parent = name.rsplit(".", 1)[0] if "." in name else name
            prel = parent.replace(".", "/")
            for cand in (prel + ".py", prel + "/__init__.py"):
                if os.path.exists(os.path.join(root, cand)):
                    hit = cand
                    break
            if hit is None:
                missing.append({"entry": name, "fanin": f})
                continue
        modules[hit] = max(modules.get(hit, 0), f)

    funcs: list[FuncInfo] = []
    all_classes: list[ClassInfo] = []
    for rel_path, fan in sorted(modules.items(), key=lambda kv: (-kv[1], kv[0])):
        fns, cls = analyze_module(rel_path, rel_path, fan)
        funcs.extend(fns)
        all_classes.extend(cls)
    funcs.sort(key=lambda x: (-x.fanin, x.path, x.lineno))
    sample = funcs[: args.sample_cap]
    ov_drifts: list[dict] = []
    for ci in all_classes:
        ov_drifts.extend(class_docstring_vs_init(ci))
    ov_drifts.extend(override_signature_drifts(all_classes))
    ov_drifts.sort(key=lambda r: (r["anchor"], r["kind"], r["detail"]))

    entries: list[dict] = []
    for fi in sample:
        claims = parse_docstring(fi.doc)
        drifts = static_checks(fi)
        entry = {
            "module": fi.module,
            "fanin": fi.fanin,
            "function": fi.qualname,
            "anchor": f"{fi.path}:{fi.lineno}",
            "ret_ann_line": fi.ret_ann_lineno if fi.ret_ann else None,
            "docstring_anchor": f"{fi.path}:{fi.doc_start}" if fi.doc.strip() else None,
            "signature": {
                "params": [f"{p['name']}" + (f": {p['ann']}" if p["ann"] else "") + ("" if p["required"] else "=…") for p in fi.params],
                "returns": fi.ret_ann or None,
            },
            "docstring": {
                "has": bool(fi.doc.strip()),
                "structured": claims.structured,
                "params": claims.params,
                "returns": claims.returns,
            },
            "static_drifts": drifts,
        }
        if args.run_runtime == "yes":
            ok, why = runtime_candidate(fi)
            entry["runtime"] = {"candidate": ok, "skip": why}
            if ok:
                call = build_call_expr(fi)
                entry["runtime"]["call_expr"] = call
        else:
            entry["runtime"] = {"candidate": False, "skip": "runtime-pass-disabled"}
        entries.append(entry)

    # runtime pass, deterministic order = entry order
    verified = 0
    if args.run_runtime == "yes":
        attempted = 0
        for entry in entries:
            if verified >= args.runtime_target or attempted >= args.runtime_cap:
                break
            rt = entry["runtime"]
            if not rt.get("candidate") or not rt.get("call_expr"):
                continue
            attempted += 1
            mod_name = entry["module"][:-3].replace("/", ".")
            if mod_name.endswith(".__init__"):
                mod_name = mod_name[: -len(".__init__")]
            func_name = entry["function"].split(".")[-1]
            inner = _inner_args(rt["call_expr"])
            anchor_path, anchor_line = entry["anchor"].rsplit(":", 1)
            try:
                res = run_one(mod_name, func_name, inner,
                              python_exe=os.path.abspath(args.venv_python),
                              repo_root=root)
            except subprocess.TimeoutExpired:
                entry["runtime"]["result"] = {"status": "timeout"}
                continue
            except Exception as exc:  # noqa: BLE001
                entry["runtime"]["result"] = {"status": "harness-error", "error": type(exc).__name__}
                continue
            if res["rc"] != 0:
                tail = res["stderr_tail"]
                entry["runtime"]["result"] = {
                    "status": "import-failed" if "Error" in tail or "error" in tail else "call-failed",
                    "error_tail": tail.splitlines()[-1] if tail else "",
                }
                continue
            try:
                actual = json.loads(res["stdout"].splitlines()[-1])
            except Exception:  # noqa: BLE001
                entry["runtime"]["result"] = {"status": "unparsable-output"}
                continue
            doc_anchor = entry.get("docstring_anchor") or anchor_path + ":" + anchor_line
            drifts = verdict_from_actual(
                actual,
                entry["signature"]["returns"] or "",
                f"{anchor_path}:{entry['ret_ann_line'] or anchor_line}",
                entry["docstring"]["returns"],
                doc_anchor,
            )
            entry["runtime"]["result"] = {"status": "verified", "observed": actual}
            entry["runtime"]["drifts"] = drifts
            entry["static_drifts"].extend(drifts)
            verified += 1

    for entry in entries:
        entry["drift"] = bool(entry["static_drifts"])
        entry["drift_kinds"] = sorted({d["kind"] for d in entry["static_drifts"]})

    all_rows = [dict(d, function=e["function"], fanin=e["fanin"])
                for e in entries for d in e["static_drifts"]]
    all_rows.extend(ov_drifts)
    all_rows.sort(key=lambda r: (r["anchor"], r["kind"], r["detail"]))

    report = {
        "tool": "scan_annotation_drift.py",
        "repo_root_commit_expected": "origin/main f07029cfcf2c8dfccdb671cdfc343db8334f5741",
        "fanin_source": "myfork/scan/coverage-gaps-det-20261006:evidence/coverage-gaps-20261005/summary.json#fanin_top50",
        "modules_resolved": len(modules),
        "modules_missing": missing,
        "functions_available": len(funcs),
        "functions_sampled": len(entries),
        "runtime_verified": verified,
        "drift_rows": len(all_rows),
        "drift_kind_counts": _kind_counts(all_rows),
        "override_drifts": ov_drifts,
        "entries": entries,
    }

    out_json = os.path.join(args.out_dir, "drift_report.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write("\n")

    write_markdown(report, os.path.join(args.out_dir, "report.md"))
    print(f"sampled={len(entries)} drift_rows={report['drift_rows']} runtime_verified={verified}")
    return 0


def _inner_args(call_expr: str) -> str:
    i = call_expr.index("(")
    return call_expr[i + 1: call_expr.rindex(")")]


def _kind_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for d in rows:
        counts[d["kind"]] = counts.get(d["kind"], 0) + 1
    return dict(sorted(counts.items()))


def write_markdown(report: dict, path: str) -> None:
    lines: list[str] = []
    lines.append("# Annotation drift scan — docstring vs annotation vs actual return\n")
    lines.append(f"- repo commit assumed: `{report['repo_root_commit_expected']}`")
    lines.append(f"- fanin source: `{report['fanin_source']}`")
    lines.append(f"- scan interpreter: Python {sys.version.split()[0]} (stdlib-only scan)")
    lines.append(f"- runtime sampling interpreter: passed via --venv-python")
    lines.append(f"- modules resolved: {report['modules_resolved']} (missing: {len(report['modules_missing'])})")
    lines.append(f"- functions available in universe: {report['functions_available']}")
    lines.append(f"- sampled (cap): {report['functions_sampled']}")
    lines.append(f"- runtime-verified: {report['runtime_verified']}")
    lines.append(f"- drift rows total: {report['drift_rows']}\n")
    lines.append("## Drift kind counts\n")
    lines.append("| kind | count |")
    lines.append("|---|---|")
    for k, v in report["drift_kind_counts"].items():
        lines.append(f"| `{k}` | {v} |")
    lines.append("")
    lines.append("## Drift rows (anchor = current main path:line)\n")
    lines.append("| function | anchor | kind | detail |")
    lines.append("|---|---|---|---|")
    for e in report["entries"]:
        if not e["drift"]:
            continue
        for d in e["static_drifts"]:
            detail = d["detail"].replace("|", "\\|")
            lines.append(f"| `{e['function']}` | `{d['anchor']}` | `{d['kind']}` ({d['severity']}) | {detail} |")
    for d in report["override_drifts"]:
        detail = d["detail"].replace("|", "\\|")
        lines.append(f"| (override) | `{d['anchor']}` | `{d['kind']}` ({d['severity']}) | {detail} |")
    lines.append("")
    lines.append("## Runtime-verified samples\n")
    lines.append("| function | anchor | call | observed | verdict |")
    lines.append("|---|---|---|---|---|")
    for e in report["entries"]:
        rt = e.get("runtime", {})
        if rt.get("result", {}).get("status") == "verified":
            obs = json.dumps(rt["result"]["observed"], sort_keys=True).replace("|", "\\|")
            verdict = "OK" if not rt.get("drifts") else "; ".join(d["kind"] for d in rt["drifts"])
            call = "`" + e["function"].split(".")[-1] + "(" + _inner_args(rt["call_expr"]) + ")`"
            lines.append(f"| `{e['function']}` | `{e['anchor']}` | {call} | `{obs}` | {verdict} |")
        elif "result" in rt:
            lines.append(f"| `{e['function']}` | `{e['anchor']}` | — | — | {rt['result'].get('status', '?')} |")
    lines.append("")
    lines.append("## Scope and dedup notes\n")
    lines.append("- Universe: public functions (module-level + public methods) inside fanin Top50 modules from "
                "`scan/coverage-gaps-det-20261006` crossed with current `main`; sample capped at 200 functions "
                "ordered by (module fanin desc, path, line).")
    lines.append("- Dedup vs `scan/mypy-adoption-20261006`: that scan measures annotation *adoption*; this scan "
                "reports *inconsistencies* between declared and actual behavior. Unannotated functions are not "
                "counted as drift here.")
    lines.append("- Dedup vs `test/settings-docstring-field-parity-20261006`: that card guards config Field "
                "defaults vs docstrings in the settings domain (dataclass field level); this scan is function "
                "signature/return level and does not inspect Field defaults.")
    lines.append("- Runtime pass is subprocess-isolated (temp HOME/cwd, 60s timeout, safe scalar args only); "
                "imports or calls that fail are recorded as skipped, never as drift.")
    lines.append("- Anchor lines are valid for the commit noted above; regenerate on the same commit to reproduce.")
    lines.append("- Re-run: `python3 scan_annotation_drift.py --repo-root <repo> --fanin fanin_top50.json "
                 "[--venv-python <repo venv python>]` "
                "(deterministic: fixed ordering, fixed args, sorted output).\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
