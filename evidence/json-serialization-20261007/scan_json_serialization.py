#!/usr/bin/env python3
"""Static scan: Python JSON serialization boundary.

Axes (issue AGEN-979):
  J1  default=str masking        (low)    json.dumps/json.dump with default=str silently stringifies
                                          non-serializable values (datetime -> "...", object -> "<...>")
                                          and can mask type drift.
  J2  non-finite float payload   (high)   float("nan")/float("inf")/math.nan/math.inf flows into
                                          json.dumps/json.dump without allow_nan=False -> payload
                                          contains NaN/Infinity tokens, invalid JSON per RFC 8259.
  J2b fail-fast NaN boundary     (medium) same flow but allow_nan=False present -> runtime ValueError.
  J3  non-serializable value     (high)   datetime/date/timedelta/Decimal/set/frozenset/bytes/
                                          bytearray/Path/struct_time/uuid value flows into
                                          json.dumps/json.dump without default= -> TypeError.
  J4  explicit allow_nan=True    (medium) documents intent to emit NaN/Infinity tokens.
  J5  reflective/python-mode     (medium) json.dumps(x.model_dump()) without mode="json", or
                                          json.dumps(asdict(...)/vars(...)/x.__dict__) without
                                          default= — field types (datetime/UUID/enum) not
                                          statically verifiable, TypeError when present.

Deterministic: findings sorted by (path, line, col, rule); no timestamps in JSON output.
Same input tree -> byte-identical findings.json.

Usage: python3 scan_json_serialization.py <repo-root> [more-roots...]
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

NONFINITE_CONSTS = {"nan", "inf", "-inf", "infinity", "-infinity"}

CLEARING_METHODS = {"isoformat", "strftime", "timestamp"}  # return str/float, serializable

DATETIME_FUNCS = {
    "now", "utcnow", "today", "fromtimestamp", "fromordinal", "strptime",
    "utcfromtimestamp", "combine", "fromisoformat",
}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".mypy_cache"}
TEST_MARKERS = ("/tests/", "/test_" , "conftest.py")


def is_test_path(rel: str) -> bool:
    parts = rel.replace("\\", "/")
    return "/tests/" in parts or "/test_" in parts or parts.endswith("conftest.py") or "/testing/" in parts


def python_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if is_test_path(rel):
            continue
        yield rel, p


# ---------------------------------------------------------------- value kinds

def classify_call(node: ast.Call) -> set[str]:
    """Kinds of values a Call expression produces."""
    f = node.func
    name = None
    base = None
    if isinstance(f, ast.Name):
        name = f.id
    elif isinstance(f, ast.Attribute):
        name = f.attr
        base = f.value
    if name is None:
        return set()

    # datetime family
    if isinstance(base, ast.Name) and base.id in {"datetime", "date", "time", "timedelta"}:
        return {"datetime"}
    if isinstance(base, ast.Attribute) and base.attr in {"datetime", "date", "timedelta", "time"}:
        if name in DATETIME_FUNCS or name in {"datetime", "date", "timedelta", "time"}:
            return {"datetime"}
    if name in {"datetime", "timedelta"} and isinstance(base, ast.Name) and base.id == "datetime":
        return {"datetime"}

    if name == "Decimal":
        return {"decimal"}
    if name in {"set", "frozenset"}:
        return {"set"}
    if name in {"bytes", "bytearray"}:
        return {"bytes"}
    if name in {"Path", "PurePath", "cwd", "home"} and (
        (isinstance(base, ast.Name) and base.id in {"Path", "PurePath", "os"})
        or (isinstance(base, ast.Attribute) and base.attr in {"Path", "PurePath"})
        or name in {"cwd", "home"} and isinstance(base, ast.Attribute)
    ):
        return {"path"}
    if name in {"gmtime", "localtime", "strptime"} and isinstance(base, ast.Attribute) \
            and isinstance(base.value, ast.Name) and base.value.id == "time":
        return {"structtime"}

    if name in {"uuid4", "uuid1", "uuid3", "uuid5"}:
        return {"uuid"}
    if name == "UUID" and isinstance(base, (ast.Name, ast.Attribute)):
        return {"uuid"}

    # non-finite floats
    if name == "float" and node.args and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str) \
            and node.args[0].value.strip().lower() in NONFINITE_CONSTS:
        return {"nonfinite"}
    if name in {"nan", "inf"} and isinstance(base, ast.Attribute) \
            and isinstance(base.value, ast.Name) and base.value.id in {"math", "np", "numpy"}:
        return {"nonfinite"}

    # method call on a risky variable: only listed methods clear the kind
    if isinstance(base, ast.Name):
        return set()  # scope-local inference handled by caller via var kinds
    return set()


def expr_kinds(node: ast.expr, varmap: dict[str, set[str]]) -> set[str]:
    """Kinds of non-serializable values an expression may carry."""
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.attr in CLEARING_METHODS:
            return set()  # dt.isoformat() etc -> str
        if isinstance(f, ast.Name) and f.id == "str":
            return set()
        kinds = classify_call(node)
        if kinds:
            return kinds
        # method/other call on risky name: propagate (conservative)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            return set(varmap.get(f.value.id, set()))
        return set()
    if isinstance(node, ast.Name):
        return set(varmap.get(node.id, set()))
    if isinstance(node, ast.Attribute):
        # bare module constants: math.nan / math.inf / np.nan / np.inf
        if node.attr in {"nan", "inf", "NAN", "INF", "Infinity"} \
                and isinstance(node.value, ast.Name) \
                and node.value.id in {"math", "np", "numpy"}:
            return {"nonfinite"}
        if node.attr in {"hex", "int"}:  # UUID.hex -> str, UUID.int -> int
            return set()
        return expr_kinds(node.value, varmap)
    if isinstance(node, ast.Subscript):
        return expr_kinds(node.value, varmap)
    if isinstance(node, ast.Dict):
        out: set[str] = set()
        for k in node.keys:
            if k is not None:
                out |= expr_kinds(k, varmap)
        for v in node.values:
            out |= expr_kinds(v, varmap)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        out = set()
        for e in node.elts:
            out |= expr_kinds(e, varmap)
        return out
    if isinstance(node, ast.Set):
        return {"set"} | set().union(*(expr_kinds(e, varmap) for e in node.elts)) if node.elts else {"set"}
    if isinstance(node, ast.BinOp):
        return expr_kinds(node.left, varmap) | expr_kinds(node.right, varmap)
    if isinstance(node, ast.IfExp):
        return expr_kinds(node.body, varmap) | expr_kinds(node.orelse, varmap)
    if isinstance(node, ast.JoinedStr):
        return set()  # f-string -> str
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bytes, bytearray)):
            return {"bytes"}
        return set()
    if isinstance(node, ast.Starred):
        return expr_kinds(node.value, varmap)
    if isinstance(node, ast.Await):
        return expr_kinds(node.value, varmap)
    return set()


# ------------------------------------------------------------------ scan core

DUMPS_NAMES = {"dumps", "dump"}


class Scope:
    def __init__(self, name: str):
        self.name = name
        self.varmap: dict[str, set[str]] = {}


def scan_file(rel: str, path: Path, root: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
    except SyntaxError:
        return []

    findings: list[dict] = []

    def dumps_kwargs(call: ast.Call):
        has_default = False
        default_is_str = False
        allow_nan = None  # None = not passed (stdlib default True)
        for kw in call.keywords:
            if kw.arg == "default":
                has_default = True
                default_is_str = isinstance(kw.value, ast.Name) and kw.value.id == "str"
            elif kw.arg == "allow_nan":
                allow_nan = isinstance(kw.value, ast.Constant) and kw.value.value is True
        return has_default, default_is_str, allow_nan

    def check_dumps(call: ast.Call, scope: Scope):
        if not call.args:
            return
        has_default, default_is_str, allow_nan = dumps_kwargs(call)
        kinds = expr_kinds(call.args[0], scope.varmap)

        # J5: reflective / pydantic python-mode payloads — field types not statically
        # provable; datetime/UUID/enum fields surface as TypeError here.
        arg0 = call.args[0]
        j5 = None
        if isinstance(arg0, ast.Call) and isinstance(arg0.func, ast.Attribute) \
                and arg0.func.attr == "model_dump":
            mode_kw = next((k for k in arg0.keywords if k.arg == "mode"), None)
            mode_json = mode_kw is not None and isinstance(mode_kw.value, ast.Constant) \
                and mode_kw.value.value == "json"
            if not mode_json:
                j5 = "model_dump() in python mode keeps datetime/UUID/Decimal/enum objects"
        elif isinstance(arg0, ast.Call) and isinstance(arg0.func, ast.Name) \
                and arg0.func.id in {"asdict", "vars"}:
            j5 = f"{arg0.func.id}() reflective dict — field types (enum/datetime) not statically verifiable"
        elif isinstance(arg0, ast.Attribute) and arg0.attr == "__dict__":
            j5 = "__dict__ reflective dict — field types (enum/datetime) not statically verifiable"
        if j5 and not has_default:
            findings.append(mk("J5", call, "medium", j5))

        if "nonfinite" in kinds:
            if allow_nan is False:
                findings.append(mk("J2b", call, "medium",
                                   "non-finite float flows into json serializer with allow_nan=False -> runtime ValueError"))
            else:
                findings.append(mk("J2", call, "high",
                                   "non-finite float flows into json serializer (allow_nan defaults True) -> NaN/Infinity tokens, invalid JSON"))
        else:
            if allow_nan is True:
                findings.append(mk("J4", call, "medium",
                                   "explicit allow_nan=True permits NaN/Infinity tokens in payload (invalid JSON per RFC 8259)"))

        serializable_kinds = kinds - {"nonfinite"}
        if serializable_kinds:
            if not has_default:
                findings.append(mk("J3", call, "high",
                                   f"value of kind {sorted(serializable_kinds)} flows into json serializer without default= -> TypeError"))
            elif default_is_str:
                findings.append(mk("J1", call, "low",
                                   f"default=str masks non-serializable kind {sorted(serializable_kinds)} (silent stringification)"))
        elif default_is_str:
            findings.append(mk("J1", call, "low",
                               "default=str masks any non-serializable value with silent stringification"))

    def mk(rule: str, call: ast.Call, grade: str, note: str) -> dict:
        arg = call.args[0]
        return {
            "rule": rule,
            "grade": grade,
            "file": rel,
            "line": call.lineno,
            "col": call.col_offset,
            "arg_line": arg.lineno,
            "note": note,
        }

    # scope walk: statements in source order; each statement is checked with the
    # varmap as of BEFORE that statement, then its assignments are applied.
    # Nested function/lambda/class scopes are skipped (they get their own pass).
    def iter_nonscoped(node: ast.AST):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            yield child
            yield from iter_nonscoped(child)

    def apply_assignment(node: ast.AST, scope: Scope):
        value = getattr(node, "value", None)
        if value is None:
            return
        kinds = expr_kinds(value, scope.varmap)
        targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                prev = scope.varmap.get(t.id, set())
                if isinstance(node, ast.AugAssign):
                    scope.varmap[t.id] = prev | kinds
                elif kinds or t.id not in scope.varmap:
                    scope.varmap[t.id] = kinds

    def walk_scope(body: list[ast.stmt], scope: Scope):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # separate scope pass in main walk
            # 1. check json.dumps/json.dump calls in this statement (pre-assignment state)
            for node in iter_nonscoped(stmt):
                if isinstance(node, ast.Call):
                    f = node.func
                    if isinstance(f, ast.Attribute) and f.attr in DUMPS_NAMES \
                            and isinstance(f.value, ast.Name) and f.value.id == "json":
                        check_dumps(node, scope)
            # 2. apply assignments: the statement itself, then nested ones
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                apply_assignment(stmt, scope)
            for node in iter_nonscoped(stmt):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node is not stmt:
                    apply_assignment(node, scope)

    module_scope = Scope("<module>")
    walk_scope(tree.body, module_scope)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fs = Scope(node.name)
            walk_scope(node.body, fs)
        elif isinstance(node, ast.ClassDef):
            cs = Scope(node.name)
            walk_scope(node.body, cs)  # class-level statements (class attrs) only;
            # methods are covered by the FunctionDef branch above

    return findings


def main() -> int:
    roots = [Path(p) for p in sys.argv[1:]]
    if not roots:
        print("usage: scan_json_serialization.py <repo-root> [more-roots...]", file=sys.stderr)
        return 2

    all_findings: list[dict] = []
    for root in roots:
        if not root.is_dir():
            print(f"skip: not a directory: {root}", file=sys.stderr)
            continue
        for rel, path in python_files(root):
            all_findings.extend(scan_file(rel, path, root))

    all_findings.sort(key=lambda f: (f["file"], f["line"], f["col"], f["rule"]))
    print(json.dumps(all_findings, indent=1, ensure_ascii=False, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
