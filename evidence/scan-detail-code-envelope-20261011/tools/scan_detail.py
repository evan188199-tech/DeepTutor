"""Inventory all `detail` write points in the DeepTutor repo (read-only scan).

Classifies HTTPException / payload-dict `detail` values by whether they carry a
machine-readable code (`detail={"code": ..., ...}`) and emits CSV + JSON evidence.

Usage: python3 scan_detail.py [--repo ROOT] [--out DIR]
"""

from __future__ import annotations

import argparse
import ast
import collections
import csv
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

PLACEHOLDER = "<expr>"

HTTP_STATUS_MAP = {
    "HTTP_100_CONTINUE": 100, "HTTP_101_SWITCHING_PROTOCOLS": 101,
    "HTTP_200_OK": 200, "HTTP_201_CREATED": 201, "HTTP_202_ACCEPTED": 202,
    "HTTP_204_NO_CONTENT": 204, "HTTP_206_PARTIAL_CONTENT": 206,
    "HTTP_300_MULTIPLE_CHOICES": 300, "HTTP_301_MOVED_PERMANENTLY": 301,
    "HTTP_302_FOUND": 302, "HTTP_303_SEE_OTHER": 303, "HTTP_304_NOT_MODIFIED": 304,
    "HTTP_307_TEMPORARY_REDIRECT": 307, "HTTP_308_PERMANENT_REDIRECT": 308,
    "HTTP_400_BAD_REQUEST": 400, "HTTP_401_UNAUTHORIZED": 401,
    "HTTP_402_PAYMENT_REQUIRED": 402, "HTTP_403_FORBIDDEN": 403,
    "HTTP_404_NOT_FOUND": 404, "HTTP_405_METHOD_NOT_ALLOWED": 405,
    "HTTP_406_NOT_ACCEPTABLE": 406, "HTTP_407_PROXY_AUTHENTICATION_REQUIRED": 407,
    "HTTP_408_REQUEST_TIMEOUT": 408, "HTTP_409_CONFLICT": 409,
    "HTTP_410_GONE": 410, "HTTP_411_LENGTH_REQUIRED": 411,
    "HTTP_412_PRECONDITION_FAILED": 412, "HTTP_413_REQUEST_ENTITY_TOO_LARGE": 413,
    "HTTP_414_REQUEST_URI_TOO_LONG": 414, "HTTP_415_UNSUPPORTED_MEDIA_TYPE": 415,
    "HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE": 416,
    "HTTP_417_EXPECTATION_FAILED": 417, "HTTP_418_IM_A_TEAPOT": 418,
    "HTTP_422_UNPROCESSABLE_ENTITY": 422, "HTTP_423_LOCKED": 423,
    "HTTP_424_FAILED_DEPENDENCY": 424, "HTTP_425_TOO_EARLY": 425,
    "HTTP_426_UPGRADE_REQUIRED": 426, "HTTP_428_PRECONDITION_REQUIRED": 428,
    "HTTP_429_TOO_MANY_REQUESTS": 429, "HTTP_431_REQUEST_HEADER_FIELDS_TOO_LARGE": 431,
    "HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS": 451,
    "HTTP_500_INTERNAL_SERVER_ERROR": 500, "HTTP_501_NOT_IMPLEMENTED": 501,
    "HTTP_502_BAD_GATEWAY": 502, "HTTP_503_SERVICE_UNAVAILABLE": 503,
    "HTTP_504_GATEWAY_TIMEOUT": 504, "HTTP_505_HTTP_VERSION_NOT_SUPPORTED": 505,
}


@dataclass
class Site:
    id: int
    file: str
    line: int
    end_line: int
    module: str
    layer: str
    writer: str
    status_code: str
    detail_kind: str
    has_code: bool
    plaintext: bool
    detail_text: str
    normalized_text: str
    i18n_key: str
    func: str
    endpoint: str
    excluded_subset: str
    cluster_id: str = ""
    batch_hint: str = ""


def layer_of(rel: str) -> str:
    parts = Path(rel).parts
    if not parts:
        return "other"
    if parts[0] == "tests":
        return "test"
    if parts[0] == "deeptutor_cli":
        return "cli"
    if parts[:3] == ("deeptutor", "api", "routers"):
        return "api_router"
    if parts[:2] == ("deeptutor", "api"):
        return "api_internal"
    if parts[:2] == ("deeptutor", "services"):
        return "service"
    if len(parts) > 1 and parts[0] == "deeptutor":
        return f"pkg:{parts[1]}"
    return "other"


def module_of(rel: str) -> str:
    parts = Path(rel).parts
    if parts[:3] == ("deeptutor", "api", "routers"):
        return "api/routers/" + parts[3]
    if parts[:2] == ("deeptutor", "api"):
        return "api/" + "/".join(parts[2:])
    if parts[0] == "deeptutor_cli":
        return "cli/" + "/".join(parts[1:])
    if parts[0] == "tests":
        return "tests/" + "/".join(parts[1:])
    return "/".join(parts[:4]) if len(parts) > 4 else "/".join(parts)


def expr_snippet(node) -> str:
    try:
        text = ast.unparse(node)
    except Exception:
        text = PLACEHOLDER
    text = " ".join(text.split())
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def fstring_skeleton(node: ast.JoinedStr) -> str:
    out = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        else:
            out.append("{}")
    s = "".join(out)
    return s if len(s) <= 200 else s[:197] + "..."


def normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\{\}", " _x_ ", t)
    t = re.sub(r"%s|%d|\{[a-z_]+\}", " _x_ ", t)
    t = re.sub(r"[^a-z0-9_ ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(_x_ )+", "_x_ ", t)
    return t


def status_of(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "status_code":
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, int):
                return str(v.value)
            if isinstance(v, ast.Attribute):
                return str(HTTP_STATUS_MAP.get(v.attr, f"attr:{v.attr}"))
            if isinstance(v, ast.Name):
                return f"name:{v.id}"
            if isinstance(v, ast.Call):
                return "dynamic"
            return "expr"
    return "default(500?)"


class ParentMap(ast.NodeVisitor):
    def __init__(self):
        self.parents = {}

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents.setdefault(child, node)
        super().generic_visit(node)


def enclosing_info(parents: dict, node) -> tuple[str, str]:
    """Return (func_name, endpoint) walking up from node."""
    func = ""
    endpoint = ""
    cur = parents.get(node)
    while cur is not None:
        if not func and isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = cur.name
            for dec in cur.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in {
                    "get", "post", "put", "patch", "delete", "head", "options", "websocket",
                    "api_route", "route",
                }:
                    path = ""
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        path = str(dec.args[0].value)
                    endpoint = f"{dec.func.attr.upper() if dec.func.attr != 'api_route' else 'ANY'} {dec.func.value.id if isinstance(dec.func.value, ast.Name) else ''}{path}".strip()
                    break
        cur = parents.get(cur)
    return func, endpoint


def classify_detail(det) -> tuple[str, bool, bool, str, str]:
    """Return (kind, has_code, plaintext, text, i18n_key)."""
    if det is None:
        return ("none", False, False, "", "")
    if isinstance(det, ast.Constant) and isinstance(det.value, str):
        return ("plain_str", False, True, det.value, "")
    if isinstance(det, ast.Constant):
        return ("const_non_str", False, False, str(det.value), "")
    if isinstance(det, ast.JoinedStr):
        return ("fstring", False, True, fstring_skeleton(det), "")
    if isinstance(det, ast.Dict):
        keys = [k.value if isinstance(k, ast.Constant) else None for k in det.keys]
        if "code" in keys:
            code_v = next(
                (v for k, v in zip(det.keys, det.values)
                 if isinstance(k, ast.Constant) and k.value == "code"),
                None,
            )
            code_text = ""
            if isinstance(code_v, ast.Constant):
                code_text = str(code_v.value)
            elif code_v is not None:
                code_text = expr_snippet(code_v)
            return ("dict_code", True, False, code_text, "")
        return ("dict_no_code", False, True, expr_snippet(det), "")
    if isinstance(det, ast.Call):
        f = det.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "?")
        if name == "str":
            return ("str_call", False, True, expr_snippet(det), "")
        if name == "t":
            key = ""
            if det.args and isinstance(det.args[0], ast.Constant):
                key = str(det.args[0].value)
            return ("i18n_call", False, True, expr_snippet(det), key)
        return ("helper_call", False, True, expr_snippet(det), "")
    return ("dynamic", False, True, expr_snippet(det), "")


def scan(repo: Path) -> list[Site]:
    sites: list[Site] = []
    packages = [repo / "deeptutor", repo / "deeptutor_cli", repo / "tests"]
    py_files = sorted({p for base in packages if base.exists() for p in base.rglob("*.py")})
    for path in py_files:
        rel = str(path.relative_to(repo))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        pm = ParentMap()
        pm.visit(tree)
        parents = pm.parents
        lay = layer_of(rel)
        nodes = list(ast.walk(tree))
        # keep references to HTTPException detail nodes alive so their addresses
        # cannot be reused by unrelated Dict nodes (id() identity check below)
        exc_details: list = []
        for node in nodes:
            if isinstance(node, ast.Call):
                is_http_exc = (
                    isinstance(node.func, ast.Name) and node.func.id == "HTTPException"
                ) or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "HTTPException"
                )
                if is_http_exc:
                    det = next((kw.value for kw in node.keywords if kw.arg == "detail"), None)
                    kind, has_code, plaintext, text, i18n_key = classify_detail(det)
                    func, endpoint = enclosing_info(parents, node)
                    excl = "AGEN-1364" if rel == "deeptutor/api/routers/sessions.py" else ""
                    sites.append(Site(
                        id=0, file=rel, line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
                        module=module_of(rel), layer=lay, writer="http_exception",
                        status_code=status_of(node), detail_kind=kind, has_code=has_code,
                        plaintext=plaintext and not has_code, detail_text=text,
                        normalized_text=normalize(text) if plaintext and not has_code else "",
                        i18n_key=i18n_key, func=func, endpoint=endpoint,
                        excluded_subset=excl,
                    ))
                    if det is not None:
                        exc_details.append(det)
        handled_ids = {id(d) for d in exc_details}
        # payload dicts {"detail": ...} that are not an HTTPException(detail={...})
        for node in nodes:
            if isinstance(node, ast.Dict) and id(node) not in handled_ids:
                keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
                if "detail" in keys:
                    v = next((v for k, v in zip(node.keys, node.values)
                              if isinstance(k, ast.Constant) and k.value == "detail"), None)
                    kind, has_code, plaintext, text, i18n_key = classify_detail(v)
                    if has_code:
                        continue
                    func, endpoint = enclosing_info(parents, node)
                    writer = "payload_dict"
                    # detect JSONResponse(content={...}) context
                    cur = parents.get(node)
                    while cur is not None:
                        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) and cur.func.id == "JSONResponse":
                            writer = "json_response"
                            break
                        cur = parents.get(cur)
                    sites.append(Site(
                        id=0, file=rel, line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
                        module=module_of(rel), layer=lay, writer=writer,
                        status_code="", detail_kind=kind, has_code=has_code,
                        plaintext=plaintext, detail_text=text,
                        normalized_text=normalize(text) if plaintext else "",
                        i18n_key=i18n_key, func=func, endpoint=endpoint,
                        excluded_subset="",
                    ))
    for i, s in enumerate(sites, 1):
        s.id = i
    return sites


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sites = scan(repo)

    # cluster plaintext sites by normalized text
    clusters = collections.defaultdict(list)
    for s in sites:
        if s.plaintext and s.normalized_text:
            clusters[s.normalized_text].append(s)
    cluster_rows = []
    for cid, (text, members) in enumerate(
        sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0])), 1
    ):
        for m in members:
            m.cluster_id = f"C{cid:03d}"
        files = sorted({m.file for m in members})
        cluster_rows.append({
            "cluster_id": f"C{cid:03d}",
            "count": len(members),
            "normalized_text": text,
            "example_text": members[0].detail_text,
            "files": ";".join(files[:8]) + (";..." if len(files) > 8 else ""),
            "file_count": len(files),
        })

    with (out / "detail-inventory.json").open("w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in sites], f, ensure_ascii=False, indent=1)
    fields = list(asdict(sites[0]).keys()) if sites else []
    with (out / "detail-inventory.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in sites:
            w.writerow(asdict(s))
    with (out / "clusters.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cluster_rows[0].keys()) if cluster_rows else ["cluster_id"])
        w.writeheader()
        w.writerows(cluster_rows)
    print(f"sites={len(sites)} clusters={len(cluster_rows)}")
    kinds = collections.Counter(s.detail_kind for s in sites)
    print(dict(kinds))


if __name__ == "__main__":
    main()
