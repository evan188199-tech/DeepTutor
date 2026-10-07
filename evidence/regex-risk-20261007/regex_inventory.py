#!/usr/bin/env python3
"""Static inventory of every regex call site in the repository.

Scope: Python (`re` module calls and calls on compiled `re.Pattern` objects)
and web TS/TSX/JS/MJS (regex literals and `new RegExp(...)` with literal args).

Output: JSON list of call sites, each with path, line, column, language, op,
pattern text (when statically recoverable), input argument source (when
recoverable), and flags. Read-only: never modifies repository files.
"""
from __future__ import annotations

import ast
import json
import os
import sys

PY_MATCH_OPS = {"match", "search", "findall", "finditer", "sub", "subn", "split", "fullmatch"}
PY_RE_ATTRS = PY_MATCH_OPS | {"compile", "escape", "purge", "template"}

PY_EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", "evidence"}
WEB_EXCLUDE_DIRS = PY_EXCLUDE_DIRS | {"next"}
WEB_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
PY_EXTS = {".py"}


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top in PY_EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in PY_EXCLUDE_DIRS]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


# --------------------------------------------------------------------------- #
# Python: AST-based extraction
# --------------------------------------------------------------------------- #

def _pattern_of(node: ast.expr):
    """Return (pattern_text, is_literal) for a pattern expression, or (None, False)."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value, True
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("ascii"), True
            except UnicodeDecodeError:
                return None, False
    return None, False


def _unparse(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


class PyRegexVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, src_lines: list[str]):
        self.rel = rel_path
        self.lines = src_lines
        self.sites: list[dict] = []
        # name -> pattern text of known compiled patterns (lexical, per block)
        self.scopes: list[dict[str, str]] = [{}]

    def _define(self, name: str, pattern: str) -> None:
        self.scopes[-1][name] = pattern

    def _lookup(self, name: str) -> str | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def _add(self, node: ast.Call, op: str, pattern: str | None, literal: bool,
             input_expr: ast.expr | None = None, extra: str | None = None,
             pattern_src: str | None = None):
        site = {
            "lang": "py",
            "path": self.rel,
            "line": node.lineno,
            "col": node.col_offset,
            "op": op,
            "pattern": pattern,
            "pattern_literal": literal,
            "pattern_src": pattern_src,
            "input_src": _unparse(input_expr) if input_expr is not None else None,
            "flags": extra,
        }
        self.sites.append(site)

    @staticmethod
    def _flag_names(keywords: list[ast.keyword], args: list[ast.expr]) -> str | None:
        names = [kw.arg for kw in keywords if kw.arg]
        for a in args:
            if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id == "re":
                names.append(a.attr)
            elif isinstance(a, ast.BinOp) and isinstance(a.op, ast.BitOr):
                for part in (a.left, a.right):
                    if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name) and part.value.id == "re":
                        names.append(part.attr)
        return "|".join(sorted(set(n for n in names if n and n not in ("string", "pattern", "repl", "count", "flags", "pos", "endpos")))) or None

    def _handle_call(self, node: ast.Call) -> None:
        f = node.func
        # re.<op>(...)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re":
            op = f.attr
            if op in PY_MATCH_OPS:
                if not node.args:
                    return
                pat, lit = _pattern_of(node.args[0])
                psrc = None if lit else _unparse(node.args[0])
                inp = node.args[1] if len(node.args) > 1 else None
                self._add(node, op, pat if lit else None, lit, input_expr=inp,
                          extra=self._flag_names(node.keywords, node.args[1:]), pattern_src=psrc)
            elif op == "compile":
                if node.args:
                    pat, lit = _pattern_of(node.args[0])
                    psrc = None if lit else _unparse(node.args[0])
                    self._add(node, "compile", pat if lit else None, lit,
                              extra=self._flag_names(node.keywords, node.args[1:]), pattern_src=psrc)
            else:
                if op in PY_RE_ATTRS:
                    self._add(node, op, None, False)
            return
        # <compiled>.<op>(...) or <compiled>.flags etc.
        if isinstance(f, ast.Attribute) and f.attr in PY_MATCH_OPS and isinstance(f.value, ast.Name):
            pat = self._lookup(f.value.id)
            if pat is not None or self._is_known_compiled(f.value.id):
                inp = node.args[0] if node.args else None
                self._add(node, f.attr, pat, pat is not None, input_expr=inp, pattern_src=None)

    def _is_known_compiled(self, name: str) -> bool:
        return self._lookup(name) is not None

    def visit_Assign(self, node: ast.Assign) -> None:
        # record compiled patterns before visiting the rest
        if isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re" and f.attr == "compile":
                pat, lit = _pattern_of(node.value.args[0]) if node.value.args else (None, False)
                if lit and pat is not None:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self._define(t.id, pat)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scopes.append(dict(self.scopes[-1]))
        self.generic_visit(node)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append(dict(self.scopes[-1]))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Call(self, node: ast.Call) -> None:
        self._handle_call(node)
        self.generic_visit(node)


def scan_python(root: str) -> list[dict]:
    sites: list[dict] = []
    for path in iter_files(root):
        if os.path.splitext(path)[1] not in PY_EXTS:
            continue
        rel = os.path.relpath(path, root)
        try:
            src = open(path, "r", encoding="utf-8", errors="replace").read()
            tree = ast.parse(src)
        except SyntaxError:
            continue
        v = PyRegexVisitor(rel, src.splitlines())
        v.visit(tree)
        sites.extend(v.sites)
    return sites


# --------------------------------------------------------------------------- #
# Web: lexer-based extraction of regex literals and new RegExp("...")
# --------------------------------------------------------------------------- #

def scan_web_file(path: str, rel: str) -> list[dict]:
    try:
        src = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    n = len(src)
    i = 0
    line = 1
    prev_sig = ""  # previous significant (non-space) char
    prev_word = ""  # previous identifier word
    sites: list[dict] = []
    pending_regexp_call: int | None = None
    regexp_parts: list[str] = []
    regexp_line = 0
    expect_method: int | None = None
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "\n":
            line += 1
            i += 1
            continue
        # comments
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = j if j != -1 else n
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            seg = src[i:j + 2] if j != -1 else src[i:]
            line += seg.count("\n")
            i = (j + 2) if j != -1 else n
            continue
        # strings
        if c in ("'", '"', "`"):
            quote = c
            j = i + 1
            depth_tpl = 0
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if quote == "`" and ch == "$" and j + 1 < n and src[j + 1] == "{":
                    depth_tpl += 1
                    j += 2
                    continue
                if quote == "`" and ch == "}" and depth_tpl > 0:
                    depth_tpl -= 1
                    j += 1
                    continue
                if ch == quote and depth_tpl == 0:
                    break
                if ch == "\n":
                    line += 1
                j += 1
            if quote != "`":
                # candidate for new RegExp("...") argument
                if pending_regexp_call is not None:
                    body = src[i + 1:j]
                    regexp_parts.append(body)
                i = j + 1
                prev_sig = quote
                continue
            i = j + 1
            prev_sig = quote
            continue
        # new RegExp( detection
        if c == "n" and src.startswith("new RegExp(", i) and not (prev_word and (prev_word[-1].isalnum() or prev_word[-1] in "_$")):
            pending_regexp_call = line
            regexp_parts = []
            regexp_line = line
            prev_sig = "("
            i += len("new RegExp(")
            continue
        # regex literal detection
        if c == "/" and prev_sig != "<" and _regex_can_start(prev_sig, prev_word):
            if line == 1 and src.startswith("#!/", i - 1):
                prev_sig = "/"
                i += 1
                continue
            body, flags, j, nl = _scan_regex_literal(src, i)
            if body is not None:
                sites.append({
                    "lang": "web",
                    "path": rel,
                    "line": line,
                    "col": i - src.rfind("\n", 0, i) - (1 if src.rfind("\n", 0, i) != -1 else 0),
                    "op": "literal",
                    "pattern": body,
                    "pattern_literal": True,
                    "input_src": None,
                    "flags": flags,
                })
                expect_method = len(sites) - 1
                line += nl
                i = j
                prev_sig = "/"
                prev_word = ""
                continue
        if c == "(":
            prev_sig = c
            prev_word = ""
            i += 1
            continue
        if c == ")" and pending_regexp_call is not None:
            if regexp_parts:
                flags = None
                parts = regexp_parts
                if len(parts) == 2 and parts[1] and all(ch in "dgimsuvy" for ch in parts[1]) and len(parts[1]) <= 5:
                    flags = parts[1]
                    parts = parts[:1]
                sites.append({
                    "lang": "web",
                    "path": rel,
                    "line": regexp_line,
                    "col": 0,
                    "op": "RegExp",
                    "pattern": "".join(parts),
                    "pattern_literal": True,
                    "input_src": None,
                    "flags": flags,
                })
                expect_method = len(sites) - 1
            else:
                sites.append({
                    "lang": "web",
                    "path": rel,
                    "line": regexp_line,
                    "col": 0,
                    "op": "RegExp",
                    "pattern": None,
                    "pattern_literal": False,
                    "input_src": None,
                    "flags": None,
                })
            pending_regexp_call = None
            regexp_parts = []
            prev_sig = c
            prev_word = ""
            i += 1
            continue
        if pending_regexp_call is not None and c in "{};=":
            pending_regexp_call = None
            regexp_parts = []
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            prev_word = src[i:j]
            prev_sig = src[j - 1]
            if expect_method is not None and i > 0 and src[i - 1] == ".":
                sites[expect_method]["op"] = prev_word
            expect_method = None
            if pending_regexp_call is not None and prev_word not in ("new", "RegExp") and src[i - 1] in " \t\n(+":
                # first argument is an identifier => dynamic pattern
                pending_regexp_call = None
                regexp_parts = []
            i = j
            continue
        prev_sig = c
        prev_word = ""
        i += 1
    return sites


def _regex_can_start(prev_sig: str, prev_word: str) -> bool:
    if prev_sig == "":
        return True
    if prev_sig in "(,=:[!&|?{};+-*%~^<>" or prev_sig == "\n":
        return True
    if prev_word in ("return", "typeof", "case", "in", "of", "instanceof", "new", "delete", "void", "do", "else"):
        return True
    return False


def _scan_regex_literal(src: str, i: int):
    """Scan a /.../flags regex literal starting at src[i] == '/'. Returns
    (body, flags, end_index_exclusive, newlines_consumed) or (None,)*4."""
    n = len(src)
    j = i + 1
    in_class = False
    body_start = j
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "\n":
            return None, None, None, 0
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            body = src[body_start:j]
            k = j + 1
            flags = []
            while k < n and (src[k].isalpha()):
                flags.append(src[k])
                k += 1
            if k < n and (src[k].isalnum() or src[k] in "_$"):
                return None, None, None, 0  # not flags => probably division
            return body, "".join(flags), k, src[i:k].count("\n")
        j += 1
    return None, None, None, 0


def scan_web(root: str) -> list[dict]:
    sites: list[dict] = []
    for path in iter_files(root):
        if os.path.splitext(path)[1] not in WEB_EXTS:
            continue
        rel = os.path.relpath(path, root)
        if rel.startswith("web/next") or "/.next/" in rel:
            continue
        sites.extend(scan_web_file(path, rel))
    return sites


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "regex_callsites.json"
    py_sites = scan_python(root)
    web_sites = scan_web(root)
    data = {
        "repo_head": None,
        "counts": {"python": len(py_sites), "web": len(web_sites), "total": len(py_sites) + len(web_sites)},
        "sites": py_sites + web_sites,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(json.dumps(data["counts"]))


if __name__ == "__main__":
    main()
