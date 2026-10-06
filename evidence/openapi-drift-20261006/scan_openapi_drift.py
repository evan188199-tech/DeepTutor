#!/usr/bin/env python3
"""Contract drift scanner: live FastAPI OpenAPI vs web/contracts (api.ts snapshot).

Read-only: imports the app in-process (no server), renders app.openapi(),
and compares it against the checked-in web/contracts/schema/openapi.json
(the snapshot web/contracts/generated/api.ts was generated from).
Outputs machine-readable drift JSON. Does not write any contract file.

Usage:
    python scan_openapi_drift.py --repo-root /path/to/repo --out-dir ./out
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from collections import Counter
from pathlib import Path

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


# ────────────────────────────── live side (current routers) ──────────────────────────────


def render_live_openapi(repo_root: Path) -> dict:
    """Render through the repo's own exporter pipeline (merges + version stamp),
    so this matches exactly what `scripts/export_frontend_contracts.py --check` enforces."""
    sys.path.insert(0, str(repo_root))
    from deeptutor.api.contracts.export import render_contracts  # noqa: E402

    return json.loads(render_contracts()["openapi.json"])


def route_source_anchor(repo_root: Path) -> dict[tuple[str, str, str], tuple[str, int]]:
    """(METHOD, router-file-stem, route literal) -> (router file, decorator line).

    Scanned statically from deeptutor/api/routers/*.py so it does not depend on
    the app's custom router classes.
    """
    anchors: dict[tuple[str, str, str], tuple[str, int]] = {}
    dec = re.compile(
        r'@(?:\w+\.)?(\w+)\.(get|post|put|delete|patch|head|options|trace|websocket)'
        r'\(\s*[\'"]([^\'"]*)[\'"]', re.S)
    for py in sorted((repo_root / "deeptutor" / "api" / "routers").glob("*.py")):
        stem = py.stem
        text = py.read_text(encoding="utf-8")
        for m in dec.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            lit = re.sub(r"\{(\w+):[A-Za-z_]+\}", r"{\1}", m.group(3))
            anchors[(m.group(2).upper(), stem, lit)] = (str(py), lineno, m.group(1))
    # app-level routes in main.py (e.g. @app.get("/health/live"))
    main_py = repo_root / "deeptutor" / "api" / "main.py"
    if main_py.exists():
        text = main_py.read_text(encoding="utf-8")
        app_dec = re.compile(
            r'@app\.(get|post|put|delete|patch|head)\(\s*[\'"]([^\'"]*)[\'"]', re.S)
        for m in app_dec.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            lit = re.sub(r"\{(\w+):[A-Za-z_]+\}", r"{\1}", m.group(2))
            anchors[(m.group(1).upper(), "main", lit)] = (str(main_py), lineno, "app")
    return anchors


def include_prefixes(repo_root: Path) -> dict[tuple[str, str], str]:
    """(router-module stem, attr) -> mount prefix, parsed from api/main.py.

    Handles dotted args (`book.router`), bare aliases (`multi_user_router`)
    and aliased module imports (`from deeptutor.api.routers.tools import
    tools as tools_router`).
    """
    text = (repo_root / "deeptutor" / "api" / "main.py").read_text(encoding="utf-8")
    aliases: dict[str, str] = {}
    # module form: from deeptutor.api.routers.<mod> import router as <alias>
    for m in re.finditer(r'from deeptutor\.api\.routers\.(\w+) import ([^()\n]+)', text):
        mod = m.group(1)
        for part in m.group(2).split(","):
            part = part.strip()
            if not part or part.startswith("("):
                continue
            mm = re.match(r'(\w+) as (\w+)$', part)
            if mm:
                aliases[mm.group(2)] = mod
            else:
                aliases[part] = mod
    # package form (multiline): from deeptutor.api.routers import (x, y as z, ...)
    for m in re.finditer(r'from deeptutor\.api\.routers import \(([^)]*)\)', text, re.S):
        for part in m.group(1).split(","):
            part = part.strip()
            mm = re.match(r'(\w+)(?: as (\w+))?$', part)
            if mm:
                aliases[mm.group(2) or mm.group(1)] = mm.group(1)
    prefixes: dict[tuple[str, str], str] = {}
    for m in re.finditer(
            r'include_router\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*,\s*prefix="([^"]+)"',
            text, re.S):
        arg, prefix = m.group(1), m.group(2)
        if "." in arg:
            head, attr = arg.split(".", 1)
            mod = aliases.get(head, head)
        else:
            mod, attr = aliases.get(arg), "router"
        if mod:
            prefixes[(mod, attr)] = prefix
    return prefixes


def op_source_anchor(anchors, op_key: str, spec, prefixes: dict | None = None) -> tuple[str, int] | None:
    """Find the router file:line for "<METHOD> <full-path>".

    Resolution order: exact prefix-join (include_router prefix + decorator
    literal), then longest literal-suffix fallback.
    """
    method, full = op_key.split(" ", 1)
    if prefixes:
        for (m2, stem, lit), loc in anchors.items():
            if m2 != method:
                continue
            pre = prefixes.get((stem, loc[2]),
                               "" if (stem, loc[2]) == ("main", "app") else None)
            if pre is not None and (pre + lit).rstrip("/") == full.rstrip("/"):
                return (loc[0], loc[1])
    best = None
    for (m2, stem, lit), loc in anchors.items():
        if m2 != method or not lit:
            continue
        if full == lit or full.endswith(lit) or full.rstrip("/") == lit.rstrip("/"):
            if best is None or len(lit) > best[0]:
                best = (len(lit), (loc[0], loc[1]))
    return best[1] if best else None


# ────────────────────────────── contract side (checked-in snapshot) ─────────────────────


def load_contract_openapi(repo_root: Path) -> dict:
    p = repo_root / "web" / "contracts" / "schema" / "openapi.json"
    return json.loads(p.read_text(encoding="utf-8"))


def api_ts_path_anchors(repo_root: Path) -> dict[str, int]:
    """Map contract path key -> api.ts line of `readonly "<path>": {`."""
    text = (repo_root / "web" / "contracts" / "generated" / "api.ts").read_text(encoding="utf-8")
    anchors = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = re.match(r'^\s*readonly "((?:[^"\\]|\\.)*)": \{', line)
        if m and lineno < 10500:  # paths section precedes `export interface components`
            anchors[m.group(1)] = lineno
    return anchors


def api_ts_operation_lines(repo_root: Path) -> dict[str, int]:
    """Map operationId -> api.ts line of its declaration inside operations."""
    text = (repo_root / "web" / "contracts" / "generated" / "api.ts").read_text(encoding="utf-8")
    lines = text.splitlines()
    ops = {}
    for lineno, line in enumerate(lines, start=1):
        m = re.search(r'operations\["([A-Za-z0-9_]+)"\]', line)
        if m and m.group(1) not in ops:
            ops[m.group(1)] = lineno
    return ops


def api_ts_operation_blocks(repo_root: Path) -> dict[str, str]:
    """Extract each operation body block from api.ts `export interface operations`."""
    text = (repo_root / "web" / "contracts" / "generated" / "api.ts").read_text(encoding="utf-8")
    start = text.find("export interface operations {")
    blocks = {}
    if start < 0:
        return blocks
    lines = text[start:].splitlines()
    current = None
    depth = 0
    buf: list[str] = []
    for line in lines:
        m = re.match(r'^\s{2}readonly ([A-Za-z0-9_]+): \{', line)
        if m and depth == 0 and current is None:
            current, depth, buf = m.group(1), 1, [line]
            continue
        if current is not None:
            depth += line.count("{") - line.count("}")
            buf.append(line)
            if depth <= 0:
                blocks[current] = "\n".join(buf)
                current, depth, buf = None, 0, []
    return blocks


# ────────────────────────────── diff helpers ─────────────────────────────────────────────


def op_methods(side: dict) -> dict[str, dict[str, dict]]:
    """path -> method -> operation dict."""
    out: dict[str, dict[str, dict]] = {}
    for path, item in side.get("paths", {}).items():
        ops = {}
        for m, op in item.items():
            if isinstance(op, dict) and m in HTTP_METHODS:
                ops[m] = op
        out[path] = ops
    return out


def ref_name(node: dict) -> str | None:
    ref = node.get("$ref") if isinstance(node, dict) else None
    if ref:
        return ref.rsplit("/", 1)[-1]
    return None


def response_2xx(op: dict) -> tuple[str | None, dict]:
    responses = op.get("responses", {})
    for code in sorted(responses):
        try:
            ok = 200 <= int(code) < 300
        except ValueError:
            continue
        if ok:
            content = responses[code].get("content", {})
            for media in ("application/json",):
                if media in content:
                    return code, content[media].get("schema", {})
    return None, {}


def error_codes(op: dict) -> list[str]:
    out = []
    for code in op.get("responses", {}):
        if code == "default":
            out.append(code)
            continue
        try:
            c = int(code)
        except ValueError:
            out.append(code)
            continue
        if c >= 400:
            out.append(code)
    return sorted(out)


def schema_props(components: dict, name: str | None) -> dict | None:
    if not name:
        return None
    schema = components.get("schemas", {}).get(name)
    if schema is None:
        return None
    if schema.get("type") == "array":
        return {"__array_items__": ref_name(schema.get("items", {})) or
                (schema.get("items", {}).get("type"))}
    props = schema.get("properties")
    if props is None:
        return None
    return {k: (v.get("type") if isinstance(v, dict) and "type" in v
                else ref_name(v) or ("array:" + (ref_name(v.get("items", {})) or v.get("items", {}).get("type", "?"))
                                     if isinstance(v, dict) and "items" in v else "?"))
            for k, v in props.items()}


def inline_props(schema: dict, components: dict) -> dict | None:
    if not isinstance(schema, dict):
        return None
    name = ref_name(schema)
    if name:
        return schema_props(components, name)
    if schema.get("type") == "object":
        props = schema.get("properties")
        if props is None:
            return {}
        return {k: (v.get("type") if isinstance(v, dict) and "type" in v else ref_name(v) or "complex")
                for k, v in props.items()}
    if schema.get("type") == "array":
        return {"__array_items__": ref_name(schema.get("items", {})) or schema.get("items", {}).get("type")}
    return None


# ────────────────────────────── structured error scan ────────────────────────────────────


def _find_decorator(lines: list[str], i: int) -> tuple[int, str, str] | None:
    for j in range(i, max(0, i - 60) - 1, -1):
        m = re.match(
            r'\s*@(?:\w+_)?router\.(get|post|put|delete|patch|head|websocket)\(\s*["\']([^"\']+)',
            lines[j],
        )
        if m:
            return (j + 1, m.group(1).upper(), m.group(2))
    return None


def _enclosing_def(lines: list[str], i: int) -> tuple[str, int] | None:
    for j in range(i, max(0, i - 80) - 1, -1):
        m = re.match(r'^(?:async )?def (\w+)\(', lines[j])
        if m:
            return (m.group(1), j + 1)
    return None


def scan_structured_errors(routers_dir: Path) -> list[dict]:
    """Line-scan routers for code+message dict payloads; attribute to route(s).

    A site inside a route body maps to its own decorator. A site inside a
    helper maps to every route in the same file that calls the helper.
    """
    sites = []
    for py in sorted(routers_dir.rglob("*.py")):
        lines = py.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if '"code"' not in line and "'code'" not in line:
                continue
            window = lines[max(0, i - 6): i + 6]
            if not any('"message"' in w or "'message'" in w for w in window):
                continue
            decl = _find_decorator(lines, i)
            row = {
                "file": str(py),
                "line": i + 1,
                "decorator_line": decl[0] if decl else None,
                "method": decl[1] if decl else None,
                "route_literal": decl[2] if decl else None,
                "snippet": line.strip()[:160],
                "callers": [],
            }
            if decl is None:
                helper = _enclosing_def(lines, i)
                if helper:
                    row["helper"] = f"{helper[0]} (def at line {helper[1]})"
                    name = helper[0]
                    for k, cl in enumerate(lines):
                        if re.search(rf'\b{name}\(', cl) and "def " not in cl and k != i:
                            d2 = _find_decorator(lines, k)
                            if d2:
                                row["callers"].append({"line": k + 1, "decorator_line": d2[0],
                                                       "method": d2[1], "route_literal": d2[2]})
            sites.append(row)
    return sites


# ────────────────────────────── main ─────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    live = render_live_openapi(args.repo_root)
    contract = load_contract_openapi(args.repo_root)
    live_comp = live.get("components", {})
    contract_comp = contract.get("components", {})

    a = op_methods(live)
    b = op_methods(contract)
    ts_paths = api_ts_path_anchors(args.repo_root)
    ts_ops = api_ts_operation_lines(args.repo_root)
    ts_blocks = api_ts_operation_blocks(args.repo_root)
    anchors = route_source_anchor(args.repo_root)
    prefixes = include_prefixes(args.repo_root)

    report = {"meta": {}, "path_level": [], "method_level": [], "response_drift": [],
              "request_drift": [], "error_response_drift": [], "description_drift": [],
              "schema_level": [], "structured_errors": {}}

    report["meta"] = {
        "live_paths": len(a), "contract_paths": len(b),
        "live_operations": sum(len(v) for v in a.values()),
        "contract_operations": sum(len(v) for v in b.values()),
    }

    # 0. coverage: every rendered HTTP op resolved back to a routers/*.py decorator
    per_file: Counter = Counter()
    unresolved = []
    for p, ops in a.items():
        for m in ops:
            loc = op_source_anchor(anchors, f"{m.upper()} {p}", live, prefixes)
            if loc is None:
                unresolved.append(f"{m.upper()} {p}")
                continue
            per_file[Path(loc[0]).name] += 1
    report["coverage"] = {
        "http_operations": sum(len(v) for v in a.values()),
        "resolved_to_router_decorator": sum(per_file.values()),
        "unresolved": unresolved,
        "router_files_in_scope": sorted(
            q.name for q in (args.repo_root / "deeptutor" / "api" / "routers").glob("*.py")
            if not q.name.startswith("_")) + ["main.py (app-level routes)"],
        "operations_per_router_file": dict(sorted(per_file.items())),
    }

    # 1. path-level
    for p in sorted(set(a) - set(b)):
        methods = sorted(m.upper() for m in a[p])
        loc = op_source_anchor(anchors, f"{methods[0]} {p}", live, prefixes)
        report["path_level"].append({"kind": "missing_in_contract", "path": p,
                                     "methods": methods,
                                     "live_anchor": f"{loc[0]}:{loc[1]}" if loc else None})
    for p in sorted(set(b) - set(a)):
        report["path_level"].append({"kind": "stale_in_contract", "path": p,
                                     "methods": sorted(m.upper() for m in b[p]),
                                     "api_ts_line": ts_paths.get(p)})

    # 2. method-level
    for p in sorted(set(a) & set(b)):
        only_live = sorted(set(a[p]) - set(b[p]))
        only_b = sorted(set(b[p]) - set(a[p]))
        if only_live or only_b:
            probe = (only_live or only_b)[0] + " " + p
            loc = op_source_anchor(anchors, probe, live, prefixes)
            report["method_level"].append({
                "path": p, "missing_in_contract": [m.upper() for m in only_live],
                "stale_in_contract": [m.upper() for m in only_b],
                "api_ts_line": ts_paths.get(p),
                "live_anchor": f"{loc[0]}:{loc[1]}" if loc else None,
            })

    # 3. response drift per common path+method
    for p in sorted(set(a) & set(b)):
        for m in sorted(set(a[p]) & set(b[p])):
            la, cb = a[p][m], b[p][m]
            key = f"{m.upper()} {p}"
            entry = None
            # request body schema
            la_body = la.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            cb_body = cb.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            la_body_n, cb_body_n = ref_name(la_body), ref_name(cb_body)
            if la_body_n != cb_body_n:
                report["request_drift"].append({
                    "op": key, "kind": "request_schema_changed",
                    "live_schema": la_body_n or _inline_desc(la_body),
                    "contract_schema": cb_body_n or _inline_desc(cb_body),
                    "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                })
            elif la_body_n and la_body_n == cb_body_n:
                diff = _prop_diff(la_body_n, live_comp, contract_comp)
                if diff:
                    report["request_drift"].append({"op": key, "kind": "request_fields_changed",
                                                    "schema": la_body_n, **diff,
                                                    "api_ts_line": ts_ops.get(cb.get("operationId", ""))})

            # response status codes
            la_codes = _resp_codes(la)
            cb_codes = _resp_codes(cb)
            if set(la_codes) != set(cb_codes):
                loc = op_source_anchor(anchors, key, live, prefixes)
                entry = entry or {"op": key, "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                                  "live_anchor": f"{loc[0]}:{loc[1]}" if loc else None}
                entry["kind"] = "response_codes_changed"
                entry["live_codes"], entry["contract_codes"] = la_codes, cb_codes
                report["error_response_drift"].append(entry)

            code_s, sch_s = response_2xx(la)
            code_c, sch_c = response_2xx(cb)
            name_s, name_c = ref_name(sch_s), ref_name(sch_c)
            if name_s != name_c:
                report["response_drift"].append({
                    "op": key, "kind": "response_schema_changed",
                    "live_schema": name_s or _inline_desc(sch_s), "contract_schema": name_c or _inline_desc(sch_c),
                    "live_2xx": code_s, "contract_2xx": code_c,
                    "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                    "live_anchor": _loc(anchors, prefixes, key, live),
                })
            elif name_s:
                diff = _prop_diff(name_s, live_comp, contract_comp)
                if diff:
                    report["response_drift"].append({
                        "op": key, "kind": "response_fields_changed", "schema": name_s, **diff,
                        "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                        "live_anchor": _loc(anchors, prefixes, key, live),
                    })
            elif not name_s and not name_c:
                ps, pc = inline_props(sch_s, live_comp), inline_props(sch_c, contract_comp)
                if ps is not None and pc is not None and ps != pc:
                    added = sorted(set(ps) - set(pc))
                    removed = sorted(set(pc) - set(ps))
                    typed = {k: (pc.get(k), ps.get(k)) for k in set(ps) & set(pc) if ps[k] != pc[k]}
                    if added or removed or typed:
                        report["response_drift"].append({
                            "op": key, "kind": "inline_response_fields_changed",
                            "added_fields": added, "removed_fields": removed,
                            "changed_fields": {k: {"contract": v[0], "live": v[1]} for k, v in typed.items()},
                            "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                            "live_anchor": _loc(anchors, prefixes, key, live),
                        })

    # 3a-bis. description-only drift (docstring changes not synced)
    for p in sorted(set(a) & set(b)):
        for m in sorted(set(a[p]) & set(b[p])):
            la, cb = a[p][m], b[p][m]
            if la == cb:
                continue
            la_d, cb_d = dict(la), dict(cb)
            desc_live, desc_contract = la_d.pop("description", None), cb_d.pop("description", None)
            if la_d == cb_d and desc_live != desc_contract:
                loc = op_source_anchor(anchors, f"{m.upper()} {p}", live)
                report["description_drift"].append({
                    "op": f"{m.upper()} {p}", "kind": "description_only",
                    "contract_description": (desc_contract or "")[:200],
                    "live_description": (desc_live or "")[:200],
                    "api_ts_line": ts_ops.get(cb.get("operationId", "")),
                    "live_anchor": f"{loc[0]}:{loc[1]}" if loc else None,
                })

    # 3b. component schema-level diff (canonical JSON, whole schema)
    ls, cs = live_comp.get("schemas", {}), contract_comp.get("schemas", {})
    for n in sorted(set(ls) | set(cs)):
        a_s, c_s = ls.get(n), cs.get(n)
        if a_s == c_s:
            continue
        entry = {"schema": n}
        if a_s is None:
            entry["kind"] = "only_in_contract"
        elif c_s is None:
            entry["kind"] = "only_in_live"
        else:
            entry["kind"] = "content_changed"
            entry["added_fields"] = sorted(set(a_s.get("properties", {})) - set(c_s.get("properties", {})))
            entry["removed_fields"] = sorted(set(c_s.get("properties", {})) - set(a_s.get("properties", {})))
            entry["changed_fields"] = {
                k: {"contract": c_s["properties"][k], "live": a_s["properties"][k]}
                for k in set(a_s.get("properties", {})) & set(c_s.get("properties", {}))
                if json.dumps(a_s["properties"][k], sort_keys=True)
                != json.dumps(c_s["properties"][k], sort_keys=True)
            }
            entry["required_live"], entry["required_contract"] = (
                a_s.get("required", []), c_s.get("required", []))
        report["schema_level"].append(entry)

    # 4. structured errors
    sites = scan_structured_errors(args.repo_root / "deeptutor" / "api" / "routers")
    # map site -> live operations via decorator literal suffix match on path
    live_path_index: dict[str, list[str]] = {}
    for p, ops in a.items():
        for m in ops:
            live_path_index.setdefault(p.rstrip("/") or "/", []).append(f"{m.upper()} {p}")

    def _literal_to_op(method: str, lit: str, stem: str | None = None) -> str | None:
        if stem is not None:
            pre = prefixes.get((stem, "router"))
            if pre is not None:
                full = pre + lit
                for cand in live_path_index.get(full.rstrip("/") or "/", []):
                    if cand.startswith(method + " "):
                        return cand
        for full in live_path_index:
            if full == lit or full.endswith(lit) or full.endswith(lit.rstrip("/")):
                for cand in live_path_index[full]:
                    if cand.startswith(method + " "):
                        return cand
        return None

    coverage_rows = []
    for s in sites:
        base = {k: s[k] for k in ("file", "line", "method", "route_literal", "decorator_line")}
        if s.get("helper"):
            base["helper"] = s["helper"]
        stem = Path(s["file"]).stem
        op_keys: list[str] = []
        if s["route_literal"]:
            op = _literal_to_op(s["method"], s["route_literal"], stem)
            if op:
                op_keys.append(op)
        for c in s.get("callers", []):
            op = _literal_to_op(c["method"], c["route_literal"], stem)
            if op and op not in op_keys:
                op_keys.append(op)
        row = dict(base)
        row["operations"] = op_keys or None
        if not op_keys:
            row["note"] = "emit site not attributable to a route decorator in the same file"
        else:
            per_op = []
            for op_key in op_keys:
                meth, path = op_key.split(" ", 1)
                live_op = a.get(path, {}).get(meth.lower(), {})
                contract_op = b.get(path, {}).get(meth.lower(), {})
                ts_block = ts_blocks.get(contract_op.get("operationId", ""), "") if contract_op else ""
                per_op.append({
                    "operation": op_key,
                    "live_documented_error_codes": error_codes(live_op) if live_op else None,
                    "contract_documented_error_codes": error_codes(contract_op) if contract_op else None,
                    "contract_block_has_code_message": bool(
                        re.search(r'\bcode\b', ts_block) and re.search(r'\bmessage\b', ts_block)),
                    "contract_error_shape_documented": _error_shape_documented(contract_op, contract_comp),
                })
            row["per_operation"] = per_op
        coverage_rows.append(row)

    all_ops = {op for r in coverage_rows for op in (r.get("operations") or [])}
    documented = {op for r in coverage_rows for pr in (r.get("per_operation") or [])
                  if pr.get("contract_error_shape_documented") for op in [pr["operation"]]}
    report["structured_errors"] = {
        "emit_sites": len(coverage_rows),
        "distinct_operations": len(all_ops),
        "operations_with_shape_documented_in_contract": len(documented),
        "rows": coverage_rows,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "drift.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    cov = report["coverage"]
    print(f"coverage: {cov['resolved_to_router_decorator']}/{cov['http_operations']} ops resolved, "
          f"{len(cov['operations_per_router_file'])} router files, unresolved={len(cov['unresolved'])}")
    print(f"written: {out}")
    print(json.dumps(report["meta"]))
    print(f"path_level={len(report['path_level'])} method_level={len(report['method_level'])} "
          f"response_drift={len(report['response_drift'])} request_drift={len(report['request_drift'])} "
          f"error_response_drift={len(report['error_response_drift'])} "
          f"schema_level={len(report['schema_level'])}")
    return 0


def _loc(anchors, prefixes, key, live) -> str | None:
    loc = op_source_anchor(anchors, key, live, prefixes)
    return f"{loc[0]}:{loc[1]}" if loc else None


def _inline_desc(schema: dict) -> str:
    if not isinstance(schema, dict):
        return "?"
    t = schema.get("type")
    if t == "object":
        return "inline-object"
    if t == "array":
        return "inline-array"
    return f"inline({t or '?'})"


def _resp_codes(op: dict) -> list[str]:
    return sorted(op.get("responses", {}).keys())


def _prop_diff(name, live_comp, contract_comp):
    """Full property-level diff (fields + nullability + constraints), canonical JSON."""
    ps = schema_props_full(live_comp, name)
    pc = schema_props_full(contract_comp, name)
    if ps is None or pc is None:
        if ps is None and pc is None:
            return None
        return {"added_fields": sorted((ps or {}).keys() if ps else []),
                "removed_fields": sorted((pc or {}).keys() if pc else []),
                "changed_fields": {},
                "note": "schema missing on one side"}
    added = sorted(set(ps) - set(pc))
    removed = sorted(set(pc) - set(ps))
    changed = {k: {"contract": pc[k], "live": ps[k]} for k in set(ps) & set(pc)
               if json.dumps(ps[k], sort_keys=True) != json.dumps(pc[k], sort_keys=True)}
    if added or removed or changed:
        return {"added_fields": added, "removed_fields": removed, "changed_fields": changed}
    return None


def schema_props_full(components: dict, name: str | None) -> dict | None:
    if not name:
        return None
    schema = components.get("schemas", {}).get(name)
    if schema is None or not isinstance(schema, dict):
        return None
    return schema.get("properties")


def _error_shape_documented(op: dict, components: dict) -> bool:
    if not op:
        return False
    for code, resp in op.get("responses", {}).items():
        if code == "default":
            continue
        try:
            if int(code) < 400:
                continue
        except ValueError:
            continue
        content = resp.get("content", {})
        for media in content.values():
            node = media.get("schema", {})
            name = ref_name(node)
            props = None
            if name:
                props = (components.get("schemas", {}).get(name, {}) or {}).get("properties")
            else:
                props = node.get("properties") if isinstance(node, dict) else None
            if isinstance(props, dict):
                keys = set(props)
                if {"code", "message"} <= keys or {"detail"} <= keys:
                    detail = props.get("detail", {})
                    dn = ref_name(detail) if isinstance(detail, dict) else None
                    if dn:
                        dprops = (components.get("schemas", {}).get(dn, {}) or {}).get("properties") or {}
                        if {"code", "message"} <= set(dprops):
                            return True
                    if isinstance(detail, dict) and isinstance(detail.get("properties"), dict) \
                            and {"code", "message"} <= set(detail["properties"]):
                        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
