#!/usr/bin/env python3
"""OpenAPI schema quality scanner for deeptutor/api/routers (read-only).

Quality axes (complementary to scan-openapi-drift / scan-route-contracts):
  A. missing response models (untyped success schemas)
  B. undocumented 4xx/5xx errors (HTTPException raises not declared via responses=)
  C. pagination naming / structure inconsistency
  D. optionality annotation drift (Optional without default, None default w/o Optional,
     annotated model return vs dict literal, response_model bypassed by Response objects)

Usage: python3 scan_openapi_quality.py [REPO_ROOT] [OUT_DIR]
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

_FORM_DEFAULT_NONE = re.compile(r"^(Form|Query|Body|Header|Cookie)\(\s*(default=)?\s*None\s*\)$")

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
RESPONSE_CLASSES = {
    "JSONResponse", "StreamingResponse", "FileResponse", "PlainTextResponse",
    "HTMLResponse", "RedirectResponse", "Response", "ORJSONResponse", "EventSourceResponse",
}
PAGINATION_NAMES = {
    "page", "page_size", "pagesize", "per_page", "limit", "offset",
    "skip", "cursor", "before", "after", "page_token", "max_results",
}
ENVELOPE_LIST_KEYS = {"items", "data", "results", "records", "entries", "list"}
ENVELOPE_TOTAL_KEYS = {"total", "count", "total_count", "has_more", "next_cursor"}


def unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def ann_str(node):
    return unparse(node) if node is not None else None


def call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def is_none_annotation(ann):
    if ann is None:
        return False
    if isinstance(ann, ast.Constant) and ann.value is None:
        return True
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str) and ann.value.strip() in ("None",):
        return True
    return False


def is_optional_annotation(ann):
    """True for Optional[X] / X | None (incl. string form)."""
    if ann is None:
        return False
    src = unparse(ann)
    if "Optional" in src and "[" in src:
        return True
    if src.count("|") and "None" in src.replace(" ", ""):
        return True
    return False


def default_is_none(default):
    if default is None:
        return False
    if isinstance(default, ast.Constant) and default.value is None:
        return True
    return False


def dict_literal_keys(expr):
    """Top-level string keys of a dict literal, else None."""
    if isinstance(expr, ast.Dict):
        keys = []
        for k in expr.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.append(k.value)
            else:
                keys.append("<expr>")
        return keys
    return None


def classify_return(expr):
    """Classify a return expression."""
    if expr is None:
        return ("none", None)
    if isinstance(expr, ast.Constant) and expr.value is None:
        return ("none", None)
    if isinstance(expr, ast.Dict):
        return ("dict", dict_literal_keys(expr))
    if isinstance(expr, ast.List):
        return ("list", None)
    if isinstance(expr, (ast.Await,)):
        return classify_return(expr.value)
    if isinstance(expr, ast.Call):
        name = call_name(expr.func)
        if name in RESPONSE_CLASSES:
            return ("response_object", name)
        return ("call", name)
    if isinstance(expr, ast.IfExp):
        a = classify_return(expr.body)
        b = classify_return(expr.orelse)
        return ("mixed", [a[0], b[0]])
    if isinstance(expr, ast.Name):
        return ("var", expr.id)
    return ("other", type(expr).__name__)


def walk_raises_and_returns(func_node):
    raises = []          # (line, status_code, detail_kind)
    returns = []         # (line, kind, info)
    response_objects = []  # response class names returned

    def visit(node, in_handler):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if in_handler:
                    visit(child, True)  # nested helper still counts (closure in handler)
                    continue
                continue
            if isinstance(child, ast.Raise) and child.exc is not None:
                exc = child.exc
                if isinstance(exc, ast.Call):
                    nm = call_name(exc.func)
                    code = None
                    if nm in ("HTTPException",) or (nm or "").endswith("HTTPException"):
                        if exc.args and isinstance(exc.args[0], ast.Constant) and isinstance(exc.args[0].value, int):
                            code = exc.args[0].value
                        for kw in exc.keywords:
                            if kw.arg == "status_code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                                code = kw.value.value
                    if code is not None:
                        raises.append((child.lineno, code, nm))
            if isinstance(child, ast.Return):
                kind, info = classify_return(child.value)
                returns.append((child.lineno, kind, info))
                if kind == "response_object":
                    response_objects.append(info)
            visit(child, in_handler)

    visit(func_node, True)
    return raises, returns, response_objects


def scan_router_file(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    router_vars = {}
    routes = []
    ws_routes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            nm = call_name(node.value.func)
            if nm == "APIRouter":
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        router_vars[t.id] = node.lineno

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        deco_route = None
        is_ws = False
        deco_router_var = None
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            base = dec.func
            if not isinstance(base, ast.Attribute):
                continue
            if base.value.id not in router_vars:
                continue
            deco_router_var = base.value.id
            if base.attr in HTTP_METHODS:
                deco_route = (base.attr, dec)
            elif base.attr == "api_route":
                methods = None
                for kw in dec.keywords:
                    if kw.arg == "methods":
                        try:
                            methods = ast.literal_eval(kw.value)
                        except Exception:
                            methods = ["?"]
                deco_route = (",".join(methods or ["?"]).lower(), dec)
            elif base.attr == "websocket":
                p = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    p = dec.args[0].value
                ws_routes.append({"file": path.name, "line": dec.lineno, "func": node.name, "path": p})
                is_ws = True
        if deco_route is None or is_ws:
            continue

        method, dec = deco_route
        route_path = ""
        if dec.args and isinstance(dec.args[0], ast.Constant):
            route_path = dec.args[0].value
        elif dec.args:
            route_path = unparse(dec.args[0])

        kw = {}
        for k in dec.keywords:
            if k.arg in ("response_model", "status_code", "responses", "summary", "deprecated", "name", "response_class", "response_description"):
                try:
                    kw[k.arg] = ast.literal_eval(k.value)
                except Exception:
                    kw[k.arg] = unparse(k.value)

        # signature
        params = []
        pagination = []
        ps = node.args
        all_args = list(ps.posonlyargs) + list(ps.args)
        defaults = [None] * (len(all_args) - len(ps.defaults)) + list(ps.defaults)
        kwonly_args = list(ps.kwonlyargs)
        kw_defaults = list(ps.kw_defaults)
        for i, a in enumerate(all_args):
            d = defaults[i]
            params.append({
                "name": a.arg,
                "annotation": ann_str(a.annotation),
                "default": unparse(d) if d is not None else None,
                "lineno": a.lineno,
            })
        for a, d in zip(kwonly_args, kw_defaults):
            params.append({
                "name": a.arg,
                "annotation": ann_str(a.annotation),
                "default": unparse(d) if d is not None else None,
                "lineno": a.lineno,
            })
        for p in params:
            if p["name"] in PAGINATION_NAMES and p["name"] not in ("before", "after"):
                pagination.append(p)

        raises, returns, response_objects = walk_raises_and_returns(node)
        ret_ann = ann_str(node.returns)

        routes.append({
            "file": path.name,
            "file_line": dec.lineno,
            "func": node.name,
            "router_var": deco_router_var,
            "method": method.upper(),
            "path": route_path,
            "kwargs": {k: v for k, v in kw.items()},
            "has_response_model": "response_model" in kw,
            "has_responses_doc": "responses" in kw,
            "declared_status_code": kw.get("status_code"),
            "return_annotation": ret_ann,
            "params": params,
            "pagination_params": [p["name"] for p in pagination],
            "raises": [{"line": ln, "code": c, "exc": nm} for ln, c, nm in raises],
            "returns": [{"line": ln, "kind": k, "info": i} for ln, k, i in returns],
            "response_objects": response_objects,
        })
    return routes, ws_routes, router_vars


def scan_main_prefixes(main_path: Path):
    """Map (router module short-name, router var attr) -> include prefix."""
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("deeptutor.api.routers"):
            for a in node.names:
                aliases[a.asname or a.name] = a.name
    prefixes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node.func) == "include_router":
            if node.args:
                first = node.args[0]
                mod = var = None
                if isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name):
                    mod = aliases.get(first.value.id, first.value.id)
                    var = first.attr
                elif isinstance(first, ast.Attribute):
                    mod, var = first.value if isinstance(first.value, str) else "?", first.attr
                prefix = ""
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                if mod:
                    key = f"{mod}.{var}"
                    prev = prefixes.get(key)
                    prefixes[key] = prefix if prev is None else f"{prev}|{prefix}"
    return prefixes


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data")
    routers_dir = root / "deeptutor" / "api" / "routers"
    out_dir.mkdir(parents=True, exist_ok=True)

    prefixes = scan_main_prefixes(root / "deeptutor" / "api" / "main.py")

    all_routes = []
    all_ws = []
    files_scanned = []
    for f in sorted(routers_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        routes, ws, _vars = scan_router_file(f)
        mod = f.stem
        prefix = prefixes.get(f"{mod}.router", "")
        prefix_ws = prefixes.get(f"{mod}.ws_router", prefix)
        for r in routes:
            r["prefix"] = prefix_ws if r.get("router_var") == "ws_router" else prefix
            r["full_path"] = (r["prefix"] + r["path"]) if not r["path"].startswith(r["prefix"]) else r["path"]
        all_routes.extend(routes)
        all_ws.extend(ws)
        files_scanned.append({"file": f.name, "routes": len(routes), "ws": len(ws)})

    findings = []
    fid = 0

    def add(finding_type, severity, route, line, message, extra=None):
        nonlocal fid
        fid += 1
        findings.append({
            "id": f"OQ-{fid:03d}",
            "type": finding_type,
            "severity": severity,
            "file": route["file"],
            "line": line,
            "route": f"{route['method']} {route['full_path']}",
            "func": route["func"],
            "message": message,
            **(extra or {}),
        })

    for r in all_routes:
        # ---- A. response model coverage
        if not r["has_response_model"]:
            kinds = {ret["kind"] for ret in r["returns"]}
            ret_obj = set(r["response_objects"])
            if "response_object" in kinds and ret_obj <= {"StreamingResponse", "FileResponse", "EventSourceResponse"}:
                sev = "low"  # schema-free by nature
                style = f"streaming/file response ({','.join(sorted(ret_obj))})"
            elif ret_obj & RESPONSE_CLASSES:
                sev = "medium"
                style = f"returns {','.join(sorted(ret_obj))} (schema absent from OpenAPI)"
            elif "dict" in kinds:
                sev = "high"
                keys = sorted({k for ret in r["returns"] if ret["kind"] == "dict" and ret["info"] for k in ret["info"]})
                style = "returns raw dict" + (f" keys={keys[:8]}" if keys else "")
            elif r["return_annotation"]:
                sev = "medium"
                style = f"annotated -> {r['return_annotation']} but no response_model"
            else:
                sev = "low"
                style = "no response_model, returns via service call/variable"
            add("missing_response_model", sev, r, r["file_line"], f"No response_model; {style}.",
                {"return_style": style})
        else:
            # response_model declared but handler returns Response objects -> model bypassed
            if r["response_objects"]:
                add("response_model_bypassed", "high", r, r["file_line"],
                    f"response_model declared but handler returns {sorted(set(r['response_objects']))}; model not applied.")

        # ---- B. undocumented errors
        err_codes = sorted({x["code"] for x in r["raises"] if 400 <= x["code"] < 500})
        err5_codes = sorted({x["code"] for x in r["raises"] if x["code"] >= 500})
        if (err_codes or err5_codes) and not r["has_responses_doc"]:
            if err_codes:
                sev = "high" if len(err_codes) >= 3 else "medium"
                add("undocumented_4xx", sev, r, r["file_line"],
                    f"raises HTTPException {err_codes} but 'responses=' not declared; error schemas invisible in OpenAPI.",
                    {"codes": err_codes})
            if err5_codes:
                add("undocumented_5xx", "low", r, r["file_line"],
                    f"raises HTTPException {err5_codes} (server-side) not declared via 'responses='.",
                    {"codes": err5_codes})

        # ---- D. optionality drift
        for p in r["params"]:
            ann = p["annotation"] or ""
            if ann in ("Request", "Response", "WebSocket") or "Depends" in ann or "Security" in ann:
                continue  # framework-injected, not schema-visible
            if is_optional_annotation_str(ann) and p["default"] is None:
                add("optionality_drift", "high", r, p["lineno"],
                    f"param '{p['name']}: {ann}' has no default -> FastAPI treats it as REQUIRED despite Optional annotation.")
            elif _FORM_DEFAULT_NONE.match(p["default"] or "") and ann and not is_optional_annotation_str(ann):
                add("optionality_drift", "medium", r, p["lineno"],
                    f"param '{p['name']}: {ann} = {p['default']}' — None default via Form/Query with non-Optional annotation (schema shows required type, runtime allows None).")
            elif p["default"] == "None" and ann and not is_optional_annotation_str(ann):
                add("optionality_drift", "medium", r, p["lineno"],
                    f"param '{p['name']}: {ann} = None' — None default with non-Optional annotation.")
        # annotated model return vs dict literal
        if r["return_annotation"] and not r["return_annotation"].startswith(("None", "dict", "Dict", "list", "List", "Response", "StreamingResponse", "FileResponse")):
            dict_rets = [ret for ret in r["returns"] if ret["kind"] == "dict"]
            if dict_rets:
                add("optionality_drift", "medium", r, dict_rets[0]["line"],
                    f"declared -> {r['return_annotation']} but returns raw dict literal (annotation/return drift).")

        # ---- C. pagination
        if r["pagination_params"]:
            names = r["pagination_params"]
            style = ("page_style" if any(n.startswith("page") or n == "per_page" for n in names)
                     else "offset_style" if "offset" in names else
                     "cursor_style" if "cursor" in names else "limit_only")
            add("pagination_present", "info", r, r["file_line"],
                f"pagination params {names} (style={style}).", {"style": style, "params": names})
            # bare-list paginated route: no envelope -> client cannot read total/has_more
            kinds = {ret["kind"] for ret in r["returns"]}
            dict_keys_sets = [set(ret["info"]) for ret in r["returns"] if ret["kind"] == "dict" and ret["info"]]
            has_envelope = any(dict_keys_sets & (ENVELOPE_LIST_KEYS | ENVELOPE_TOTAL_KEYS) for dict_keys_sets in dict_keys_sets)
            if "list" in kinds or (dict_keys_sets and not has_envelope):
                add("pagination_structure", "medium", r, r["file_line"],
                    "paginated route returns a bare list (or dict without items/total envelope); client cannot learn total/has_more.")
            # unvalidated pagination params (raw defaults, no Query bounds)
            for p in r["params"]:
                if p["name"] in PAGINATION_NAMES and p["name"] not in ("before", "after"):
                    dft = p["default"] or ""
                    if not dft.startswith(("Query(", "Form(", "Body(")):
                        add("pagination_validation", "medium", r, p["lineno"],
                            f"pagination param '{p['name']}: {p['annotation']}' uses raw default ({dft or 'required'}) without Query(ge/le) bounds — inconsistent with Query-validated pagination elsewhere.")

        # ---- D2. envelope drift within one route (optionality of response fields)
        dict_rets = [ret for ret in r["returns"] if ret["kind"] == "dict" and ret["info"]]
        if len(dict_rets) >= 2:
            key_sets = [set(ret["info"]) for ret in dict_rets]
            base = key_sets[0]
            drift = any(ks != base for ks in key_sets[1:])
            if drift:
                variants = sorted({frozenset(ks) for ks in key_sets}, key=len)
                add("envelope_drift", "medium", r, dict_rets[0]["line"],
                    f"response dict envelope varies across branches ({len(variants)} shapes: {[sorted(v)[:8] for v in variants[:3]]}); "
                    "optional fields not declared anywhere in OpenAPI.",
                    {"shapes": [sorted(v) for v in variants]})

    data = {
        "meta": {
            "scanner": "scan_openapi_quality.py",
            "repo_root": str(root),
            "routers_dir": str(routers_dir),
            "files": files_scanned,
        },
        "routes": all_routes,
        "websocket_routes": all_ws,
        "findings": findings,
    }
    (out_dir / "openapi-quality-data.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    # quick aggregate for console
    from collections import Counter
    fc = Counter((f["type"], f["severity"]) for f in findings)
    print(f"routes={len(all_routes)} ws={len(all_ws)} findings={len(findings)}")
    for (t, s), n in sorted(fc.items()):
        print(f"  {t}/{s}: {n}")


def is_optional_annotation_str(ann: str) -> bool:
    return "Optional[" in ann or ("|" in ann and "None" in ann)


if __name__ == "__main__":
    main()
