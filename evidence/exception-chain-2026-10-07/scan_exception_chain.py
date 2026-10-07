#!/usr/bin/env python3
"""AST-level scan for Python exception-chain hygiene issues.

Rules:
  E1 missing-explicit-cause     raise <new> inside except handler without `from` (implicit __context__ kept, __cause__ unset)
  E2 suppressed-cause-from-none raise ... from None inside handler (root-cause traceback deliberately dropped)
  E3 from-none-outside-handler  raise ... from None with no active handler (meaningless / hides earlier context)
  E4 bare-raise-outside-handler bare `raise` outside any except handler (runtime bug unless called from handler)
  E5 raise-non-exception        raise "<string>" or from "<string>" (TypeError at raise time)
  E6 return-in-finally          return/break/continue in finally (swallows in-flight exception)
  E7 wrong-cause-target         raise ... from <name> where <name> is not the caught exception nor locally bound

Dedup markers: findings raised inside broad handlers (`except Exception`, `except BaseException`,
bare except) are tagged dedup=scan-broad-excepts (overlap with the broad-capture scan axis).

Read-only: never writes to scanned sources.
"""
import ast
import hashlib
import json
import sys
from pathlib import Path

BROAD = {"Exception", "BaseException", None}  # None = bare except


def handler_type(handler):
    if handler.type is None:
        return "bare"
    return ast.unparse(handler.type)


def is_broad(handler):
    return handler_type(handler) in BROAD


def source_line(src_lines, lineno):
    if 1 <= lineno <= len(src_lines):
        return src_lines[lineno - 1].rstrip()[:200]
    return ""


def call_embeds_name(node, name):
    """True if `name` (caught exception var) appears inside raised expression."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name:
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "str":
            if sub.args and isinstance(sub.args[0], ast.Name) and sub.args[0].id == name:
                return True
    return False


class ScopeWalker:
    """Walks statements that execute *within* a handler's dynamic scope.

    Descends into control-flow bodies but NOT into nested handlers (each is
    its own scope) and NOT into nested function/class bodies (their raises
    run later, outside this handler).
    """

    def __init__(self, findings, rel, src_lines, collect_names=False):
        self.findings = findings
        self.rel = rel
        self.src_lines = src_lines
        self.collect_names = collect_names
        self.module_names = set()

    def emit(self, rule, severity, node, detail, dedup=None):
        f = {
            "rule": rule,
            "severity": severity,
            "path": self.rel,
            "line": node.lineno,
            "col": node.col_offset,
            "code": source_line(self.src_lines, node.lineno).strip(),
            "detail": detail,
        }
        if dedup:
            f["dedup"] = dedup
        self.findings.append(f)

    def bound_names(self, stmts):
        names = set()
        for st in stmts:
            for sub in ast.walk(st):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store,)):
                    names.add(sub.id)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    names.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for al in sub.names:
                        names.add((al.asname or al.name).split(".")[0])
                elif isinstance(sub, ast.arg):
                    names.add(sub.arg)
        return names

    @staticmethod
    def handler_catches(handler):
        """Set of exception type names caught by this handler."""
        t = handler.type
        if t is None:
            return {"BaseException"}
        if isinstance(t, ast.Name):
            return {t.id}
        if isinstance(t, (ast.Tuple, ast.List)):
            return {elt.id for elt in t.elts if isinstance(elt, ast.Name)}
        return set()

    @staticmethod
    def _is_log_call(stmt):
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Attribute) and fn.attr in {
                    "debug", "info", "warning", "warn", "error", "exception", "critical", "log",
                }:
                    return True
                if isinstance(fn, ast.Name) and fn.id.lstrip("_").startswith("log"):
                    return True
        return False

    def walk(self, stmts, ctx, handler, in_finally=False, finally_try=None, inherited=frozenset(),
             inherited_has_log=False, func_name=None):
        caught = ctx.get("name") if ctx else None
        broad = is_broad(handler) if handler else False
        dedup = "scan-broad-excepts" if (broad and ctx) else None
        htype = handler_type(handler) if handler else None
        local = (self.bound_names(stmts) | inherited) if self.collect_names else set()
        has_log = inherited_has_log or any(self._is_log_call(st) for st in stmts)

        for st in stmts:
            if isinstance(st, ast.Raise):
                self._classify_raise(st, ctx, handler, caught, dedup, htype, local, has_log, func_name)
            elif isinstance(st, ast.Return) and in_finally:
                self.emit("E6", "high", st,
                          "return in finally swallows any in-flight exception from try/except", dedup)
            elif isinstance(st, (ast.Break, ast.Continue)) and in_finally:
                self.emit("E6", "high", st,
                          f"{type(st).__name__} in finally swallows/discards any in-flight exception", dedup)
            # recursion
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue  # raises inside run later, outside this chain
            if isinstance(st, ast.If):
                self.walk(st.body, ctx, handler, in_finally, finally_try, local, has_log, func_name)
                self.walk(st.orelse, ctx, handler, in_finally, finally_try, local, has_log, func_name)
            elif isinstance(st, (ast.For, ast.AsyncFor)):
                self.walk(st.body, ctx, handler, in_finally, finally_try, local, has_log, func_name)
                self.walk(st.orelse, ctx, handler, in_finally, finally_try, local, has_log, func_name)
            elif isinstance(st, ast.While):
                self.walk(st.body, ctx, handler, in_finally, finally_try, local, has_log, func_name)
                self.walk(st.orelse, ctx, handler, in_finally, finally_try, local, has_log, func_name)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                self.walk(st.body, ctx, handler, in_finally, finally_try, local)
            elif isinstance(st, ast.Match):
                for case in st.cases:
                    self.walk(case.body, ctx, handler, in_finally, finally_try, local, has_log, func_name)
            elif isinstance(st, (ast.Try, ast.TryStar)):
                # nested try body/orelse still executes within this handler
                self.walk(st.body, ctx, handler, False, None, local, has_log, func_name)
                self.walk(st.orelse, ctx, handler, False, None, local, has_log, func_name)
                # nested handlers: separate scopes (processed at top level)
                # finally: still within handler chain when propagating
                self.walk(st.finalbody, ctx, handler, True, st, local, has_log, func_name)

    def _classify_raise(self, node, ctx, handler, caught, dedup, htype, local, has_log=False,
                            func_name=None):
        exc, cause = node.exc, node.cause
        in_handler = ctx is not None

        # E5: non-exception raise/from
        for part, label in ((exc, "raise target"), (cause, "from target")):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                self.emit("E5", "high", node,
                          f"{label} is a string literal; raising it raises TypeError instead", dedup)
                return

        if exc is None:  # bare re-raise
            if not in_handler:
                self.emit("E4", "medium", node,
                          "bare `raise` outside any except handler: RuntimeError at runtime unless invoked from a handler")
            return

        # cause target sanity (E7)
        if cause is not None and not isinstance(cause, ast.Constant):
            if isinstance(cause, ast.Name):
                if caught is not None and cause.id == caught:
                    pass
                elif cause.id not in local and cause.id not in self.module_names:
                    self.emit("E7", "medium", node,
                              f"`from {cause.id}` is neither the caught exception ({caught}) nor locally bound",
                              dedup)

        # E3: from None outside handler
        if isinstance(cause, ast.Constant) and cause.value is None and not in_handler:
            self.emit("E3", "low", node,
                      "`from None` with no active handler: suppresses __context__ from any earlier handled error")
            return

        # re-raise of the caught exception object: fine
        if in_handler and caught and isinstance(exc, ast.Name) and exc.id == caught:
            return

        # E2: from None inside handler
        if isinstance(cause, ast.Constant) and cause.value is None:
            embeds = bool(caught) and call_embeds_name(exc, caught)
            catches = self.handler_catches(handler) if handler else set()
            idiom = (
                isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                and exc.func.id == "SystemExit"
                and catches <= {"KeyboardInterrupt", "EOFError", "InterruptedError"}
            )
            pep562 = (
                isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                and exc.func.id == "AttributeError"
                and func_name in ("__getattr__", "__getattribute__")
            )
            if idiom or pep562:
                why = ("Ctrl-C/EOF converted to SystemExit" if idiom
                       else "PEP 562 module/attribute __getattr__ protocol")
                self.emit("E2", "low", node,
                          f"recognized idiom: {why}; `from None` is intentional here",
                          dedup)
                return
            sev = "medium" if embeds else "high"
            detail = ("`from None` inside handler drops the root-cause traceback; "
                      + ("message embeds the caught exception text, but chain/type is lost"
                         if embeds else
                         f"raised message does not reference caught exception `{caught}`; root cause fully lost"))
            if has_log:
                detail += " (handler logs before raising: likely intentional, verify root cause still reachable in logs)"
            self.emit("E2", sev, node, detail, dedup)
            return

        # E1: new raise in handler without cause
        if in_handler and cause is None:
            embeds = bool(caught) and call_embeds_name(exc, caught)
            detail = ("raise of a new exception inside handler without `from`: implicit __context__ survives, "
                      "but __cause__ unset (traceback prints 'During handling...' not 'direct cause')")
            if not embeds and htype in ("bare", "BaseException"):
                detail += "; handler is bare/BaseException and message omits the original error entirely"
            self.emit("E1", "medium", node, detail, dedup)


def scan_file(path, rel):
    findings = []
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [{"rule": "PARSE", "severity": "info", "path": rel, "line": e.lineno or 0,
                 "col": 0, "code": "", "detail": f"syntax error: {e.msg}"}]
    lines = src.splitlines()
    w = ScopeWalker(findings, rel, lines, collect_names=True)
    for node in tree.body:
        w.module_names |= w.bound_names([node])

    # top-level scopes: raises outside any handler (E3/E4)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef)):
            w.walk(_top_stmts(node), None, None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            w.walk(node.body, None, None, func_name=node.name)

    # each except handler is its own scope; remember enclosing function for idiom checks
    func_stack = []
    handler_func = {}

    class FuncTracker(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            func_stack.append(node.name)
            self.generic_visit(node)
            func_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ExceptHandler(self, node):
            handler_func[id(node)] = func_stack[-1] if func_stack else None
            self.generic_visit(node)

    FuncTracker().visit(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            ctx = {"name": node.name} if node.name else {}
            w.walk(node.body, ctx, node, func_name=handler_func.get(id(node)))
    return findings


def _top_stmts(node):
    if isinstance(node, ast.Module):
        return node.body
    return node.body


def main():
    root = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    pkg = root / "deeptutor"
    all_findings = []
    files = 0
    parse_fail = 0
    for py in sorted(pkg.rglob("*.py")):
        if not py.is_file():
            continue
        files += 1
        rel = str(py.relative_to(root))
        fs = scan_file(py, rel)
        if any(f["rule"] == "PARSE" for f in fs):
            parse_fail += 1
        all_findings.extend(fs)

    sev_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    all_findings.sort(key=lambda f: (sev_rank.get(f["severity"], 9), f["path"], f["line"]))

    # module clustering: package subdir under deeptutor/
    modules = {}
    for f in all_findings:
        parts = Path(f["path"]).parts
        mod = ".".join(parts[:2]) if len(parts) > 2 else "deeptutor(root)"
        modules.setdefault(mod, {"total": 0, "by_severity": {}})
        modules[mod]["total"] += 1
        modules[mod]["by_severity"][f["severity"]] = modules[mod]["by_severity"].get(f["severity"], 0) + 1

    rules = {}
    for f in all_findings:
        rules[f["rule"]] = rules.get(f["rule"], 0) + 1

    result = {
        "root": str(root),
        "files_scanned": files,
        "parse_failures": parse_fail,
        "total_findings": len(all_findings),
        "by_rule": dict(sorted(rules.items())),
        "by_severity": {},
        "modules": dict(sorted(modules.items(), key=lambda kv: -kv[1]["total"])),
        "findings": all_findings,
    }
    for f in all_findings:
        result["by_severity"][f["severity"]] = result["by_severity"].get(f["severity"], 0) + 1

    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("files_scanned", "parse_failures", "total_findings", "by_rule", "by_severity")},
                     indent=2))
    print("top modules:")
    for mod, info in list(result["modules"].items())[:10]:
        print(f"  {mod}: {info['total']} ({info['by_severity']})")


if __name__ == "__main__":
    main()
