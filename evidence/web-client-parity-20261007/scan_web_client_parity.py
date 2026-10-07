#!/usr/bin/env python3
"""Web client <-> backend route parity scanner (AGEN-1107).

Read-only. Compares every HTTP call site in web/**/*.{ts,tsx} against the
LIVE backend route table (FastAPI app walked in-process, no server started),
including routes hidden with include_in_schema=False that the generated
contract never shows.

Drift classes:
  A1 endpoint-not-in-backend   — client calls a path the backend does not serve
  A2 method-not-allowed        — client HTTP method not declared on any matched route
  B1 query-param-not-read      — client sends a query param no matched route declares
  B2 body-key-not-in-model     — literal JSON body key absent from the backend body model
  B3 param-shadow-enumeration  — URL literal lands on a backend {param} whose values
                                 are enumerated as separate literal routes
  C1 backend-route-uncalled    — backend REST route with zero matching client call sites

Frontend extraction methodology reuses the AST-lite tokenizer proven in
evidence/web-api-usage-20261006/scan_web_api_usage.py (balanced parens, JS
string/template literals, URLSearchParams function-scoped linkage, module-level
string constants resolved across imports).

Backend side: app.routes walk (fastapi _IncludedRouter.original_router +
include_context.prefix) — yields every real route with its dependant
(query/path params), body model fields and endpoint file:line.

Usage (run with the repo .venv python so the app imports):
  .venv/bin/python scan_web_client_parity.py \
      --repo-root /path/to/repo --outdir <dir> [--ref X]
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import typing
from pathlib import Path

WRAPPER_RE = re.compile(
    r"\b(apiFetch|requestJson|requestVoid|requestBlob|asJsonOrThrow|asJson|fetch)\s*\("
)
# unwrap order: longest names first so asJson never stops asJsonOrThrow peeling
UNWRAP_NAMES = {"asJsonOrThrow", "requestJson", "requestVoid", "requestBlob",
                "apiFetch", "asJson", "fetch", "apiUrl", "wsUrl", "scopedUrl"}
METHOD_RE = re.compile(
    r"""\bmethod\s*:\s*["'](GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)["']""",
    re.IGNORECASE,
)
QUERY_NAME_RE = re.compile(r"[?&]([A-Za-z0-9_.\-]+)=")
SP_INIT_RE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*new\s+URLSearchParams\s*\(")
SP_CALL_RE = re.compile(
    r"""\b(\w+)\s*\.\s*(?:set|get|has|append|getAll)\s*\(\s*["']([^"']*)["']"""
)
SP_INIT_OBJ_KEY_RE = re.compile(r"""(?:[{,]\s*)(\w+)\s*:""")
INTERP_TOKEN_RE = re.compile(r"[A-Za-z_$][\w$]*")
FUNC_HEAD_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function[\s*](\w+)"
    r"|^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?(?:function\b|\()",
    re.M,
)
CONST_LIT_RE = re.compile(
    r"""(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(["'])([^"'\n]{0,160}?)\2"""
)
IMPORT_RE = re.compile(r"""import\s*\{([^}]+)\}\s*from\s*["']([^"']+)["']""")
WRAPPER_INJECTED_PARAMS = {"dt_workspace"}
SKIP_DIRS = {"node_modules", ".next", "contracts", "coverage", "dist",
             "tests", "e2e"}


# ------------------------------------------------------------- tokenizer
def skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def read_lit(text: str, i: int):
    quote = text[i]
    kind = "template" if quote == "`" else "string"
    out: list[str] = []
    interps: list[str] = []
    j = i + 1
    depth_tpl = 0
    expr_start = -1
    while j < len(text):
        c = text[j]
        if depth_tpl > 0:
            if c == "{":
                depth_tpl += 1
            elif c == "}":
                depth_tpl -= 1
                if depth_tpl == 0:
                    interps.append(text[expr_start:j])
                    expr_start = -1
            j += 1
            continue
        if c == "\\":
            out.append(text[j: j + 2])
            j += 2
            continue
        if kind == "template":
            if c == "$" and j + 1 < len(text) and text[j + 1] == "{":
                out.append("{}")
                depth_tpl = 1
                expr_start = j + 2
                j += 2
                continue
            if c == "`":
                return "".join(out), kind, j + 1, interps
        elif c == quote:
            return "".join(out), kind, j + 1, interps
        out.append(c)
        j += 1
    return "".join(out), kind, len(text), interps


def match_balanced(text: str, i: int, cap: int = 4000) -> int:
    depth = 0
    n = min(len(text), i + cap)
    j = i
    while j < n:
        c = text[j]
        if c in "'\"`" and depth > 0:
            _, _, j, _ = read_lit(text, j)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return min(len(text), i + cap)


def first_arg_span(text: str, open_paren: int):
    i = skip_ws(text, open_paren + 1)
    if i >= len(text) or text[i] == ")":
        return None
    start = i
    depth = 0
    j = i
    n = len(text)
    while j < n:
        c = text[j]
        if c in "'\"`":
            _, _, j, _ = read_lit(text, j)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return (start, j)
            depth -= 1
        elif c == "," and depth == 0:
            return (start, j)
        j += 1
    return (start, n)


def unwrap_arg(text: str, start: int, end: int):
    """Peel apiUrl/wsUrl/scopedUrl and nested wrapper calls (asJson(fetch(x)))
    down to the innermost first argument."""
    span = (start, end)
    for _ in range(6):
        seg = text[span[0]: span[1]]
        m = re.match(r"\s*(?:await\s+)?([A-Za-z_$][\w$]*)\s*\(", seg)
        if not m or m.group(1) not in UNWRAP_NAMES:
            return span
        inner_open = span[0] + m.end() - 1
        inner = first_arg_span(text, inner_open)
        if inner is None:
            return span
        span = inner
    return span


def literals_in_span(text: str, start: int, end: int):
    out = []
    depth = 0
    j = start
    while j < end:
        c = text[j]
        if c in "([{":
            depth += 1
            j += 1
            continue
        if c in ")]}":
            depth -= 1
            j += 1
            continue
        if c in "'\"`" and depth == 0:
            val, _kind, j2, _ip = read_lit(text, j)
            if val.startswith("/"):
                out.append((j, j2))
            j = j2
            continue
        j += 1
    return out


def resolve_module(specifier: str, cur_file: Path, web_root: Path):
    if specifier.startswith("@/"):
        base = web_root / specifier[2:]
    elif specifier.startswith("."):
        base = (cur_file.parent / specifier).resolve()
    else:
        return None
    for cand in (base.with_suffix(".ts"), base.with_suffix(".tsx"),
                 base / "index.ts", base / "index.tsx",
                 base.with_suffix(".mts"), base.with_suffix(".cts"),
                 base.with_suffix(".cjs")):
        if cand.is_file():
            return cand
    return None


def collect_file_context(text: str, cur_file: Path, web_root: Path):
    sp_vars: dict[str, list[tuple[str, int]]] = {}
    for m in SP_INIT_RE.finditer(text):
        sp_vars.setdefault(m.group(1), [])
    for m in SP_CALL_RE.finditer(text):
        var, name = m.group(1), m.group(2)
        if var in sp_vars:
            line = text.count("\n", 0, m.start()) + 1
            if (name, line) not in sp_vars[var]:
                sp_vars[var].append((name, line))
    for m in SP_INIT_RE.finditer(text):
        open_paren = m.end() - 1
        arg = first_arg_span(text, open_paren)
        if arg and text[arg[0]: arg[1]].strip().startswith("{"):
            body = text[arg[0]: arg[1]]
            line0 = text.count("\n", 0, arg[0]) + 1
            for km in SP_INIT_OBJ_KEY_RE.finditer(body):
                entry = (km.group(1), line0)
                if entry not in sp_vars[m.group(1)]:
                    sp_vars[m.group(1)].append(entry)
    func_heads = []
    for m in FUNC_HEAD_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        name = m.group(1) or m.group(2)
        func_heads.append((line, name))
    const_env = {}
    for m in CONST_LIT_RE.finditer(text):
        const_env[m.group(1)] = m.group(3)
    for m in IMPORT_RE.finditer(text):
        names = [n.strip().split(" as ")[0].strip()
                 for n in m.group(1).split(",")]
        target = resolve_module(m.group(2), cur_file, web_root)
        if target is None or not str(target).startswith(str(web_root)):
            continue
        try:
            target_text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for cm in CONST_LIT_RE.finditer(target_text):
            if cm.group(1) in names:
                const_env[cm.group(1)] = cm.group(3)
    return {"sp_vars": sp_vars, "func_heads": func_heads,
            "const_env": const_env}


def enclosing_function(ctx, line: int):
    heads = ctx["func_heads"]
    best = None
    for ln, name in heads:
        if ln <= line:
            best = name
        else:
            break
    return best


def scoped_sp_entries(ctx, var: str, call_line: int):
    entries = ctx["sp_vars"].get(var, [])
    heads = [h[0] for h in ctx["func_heads"]]
    start = max([fl for fl in heads if fl <= call_line], default=1)
    end = min([fl for fl in heads if fl > call_line], default=10 ** 9)
    window = [(n, l) for n, l in entries if start <= l < end]
    return window, ("function-scoped" if window else "unlinked")


def split_url(raw_url: str):
    u = raw_url.strip()
    m = re.match(r"^(https?:|wss?:)?//[^/?#]*", u)
    if m:
        prefix = m.group(0)
        rest = u[len(prefix):] or "/"
        path, _, query = rest.partition("?")
        return (path or "/", query, True, prefix)
    path, _, query = u.partition("?")
    return path, query, False, ""


def normalize_path(path: str):
    p = re.sub(r"/{2,}", "/", path)
    trailing = p.endswith("/") and len(p) > 1
    if trailing:
        p = p.rstrip("/") or "/"
    return p, trailing


# --------------------------------------------------- url <-> route matching
def match_endpoint(norm: str, backend_paths):
    if norm in backend_paths:
        return norm, []
    parts = [s for s in norm.split("/") if s != ""]
    cands = []
    for bp in backend_paths:
        bparts = [s for s in bp.split("/") if s != ""]
        if len(bparts) != len(parts):
            continue
        shadow: list[int] = []
        lit_exact = 0
        ok = True
        for i, (a, b) in enumerate(zip(parts, bparts)):
            if b.startswith("{") and b.endswith("}"):
                if a != "{}":
                    shadow.append(i)
                continue
            if a == b:
                lit_exact += 1
                continue
            ok = False
            break
        if ok:
            ph = sum(1 for b in bparts if b.startswith("{"))
            cands.append((lit_exact, ph, bp, shadow))
    if not cands:
        return None, []
    cands.sort(key=lambda t: (-t[0], t[1], t[2]))
    return cands[0][2], cands[0][3]


def _prefix_match(url_segs, back_segs) -> bool:
    for a, b in zip(url_segs, back_segs):
        if a == "{}" or a == b:
            continue
        return False
    return True


def match_endpoint_variants(path_n: str, backend_paths):
    cp, shadow = match_endpoint(path_n, backend_paths)
    if cp is not None:
        return cp, ("param-shadow" if shadow else "as-is"), None, shadow
    segs = [s for s in path_n.split("/") if s != ""]
    if not segs:
        return None, None, None, None
    # dynamic-segment-enumeration: exactly one non-final {} marker; backend
    # has literal routes at that position (frontend parameterized an
    # enumerated literal route set — rag-pipelines style coupling).
    # Every other segment must match literally (params belong to as-is).
    dyn = [i for i, s in enumerate(segs) if s == "{}"]
    if len(dyn) == 1 and dyn[0] < len(segs) - 1:
        k = dyn[0]
        cands = []
        for bp in sorted(backend_paths):
            bparts = [s for s in bp.split("/") if s != ""]
            if len(bparts) != len(segs) or bparts[k].startswith("{"):
                continue
            if all(a == b for i2, (a, b) in enumerate(zip(segs, bparts))
                   if i2 != k):
                cands.append(bp)
        if cands:
            return cands[0], "dynamic-segment-enumeration", cands, []
    if segs[-1] == "{}":
        prefix = segs[:-1]
        finals = [bp for bp in sorted(backend_paths)
                  if len(bp.split("/")) - 1 == len(prefix) + 1
                  and _prefix_match(prefix,
                                    [s for s in bp.split("/") if s != ""][:-1])]
        if finals:
            return finals[0], "dynamic-final-segment", finals[:8], []
        return None, None, None, None
    if segs[-1].endswith("{}") and segs[-1] != "{}":
        stripped = segs[-1][: -2].rstrip("/")
        cand = "/".join(segs[:-1] + ([stripped] if stripped else []))
        cp2, sh2 = match_endpoint(cand, backend_paths)
        if cp2 is not None:
            return cp2, "suffix-stripped", None, sh2
    if segs[-1] == "{}" and len(segs) > 1:
        cp2, sh2 = match_endpoint("/".join(segs[:-1]), backend_paths)
        if cp2 is not None:
            return cp2, "final-dropped", None, sh2
    return None, None, None, None


# ------------------------------------------------------ body literal keys
def object_literal_keys(text: str, start: int, end: int):
    """Depth-1 keys of the object literal spanning [start,end).

    Only identifiers in KEY position count: right after '{' or ',' at
    depth 1. Value identifiers (server_url: serverUrl) are never keys.
    """
    keys: list[str] = []
    depth = 0
    j = start
    expect_key = False
    while j < end:
        c = text[j]
        if c in "'\"`":
            _, _, j, _ = read_lit(text, j)
            continue
        if c in "([{":
            depth += 1
            expect_key = depth == 1
            j += 1
            continue
        if c in ")]}":
            depth -= 1
            if depth == 0:
                break
            expect_key = depth == 1 and False
            j += 1
            continue
        if depth == 1 and c == ",":
            expect_key = True
            j += 1
            continue
        if depth == 1 and expect_key:
            if text.startswith("...", j):
                j += 3
                expect_key = False
                continue
            m = re.match(r"\s*(?:\.\.\.\s*)?([A-Za-z_$][\w$]*)\s*:",
                         text[j: end])
            if m:
                if m.group(1) not in keys:
                    keys.append(m.group(1))
                j += m.end()
                expect_key = False
                continue
            m2 = re.match(r"\s*([A-Za-z_$][\w$]*)\s*[,}]", text[j: end])
            if m2:
                if m2.group(1) not in keys:
                    keys.append(m2.group(1))
                j = j + m2.end()
                expect_key = text[j - 1] == ","
                continue
            j += 1
            continue
        j += 1
    return keys


def extract_body_keys(text: str, call_start: int, call_end: int):
    span_text = text[call_start: call_end]
    for bm in re.finditer(r"\bbody\s*:\s*", span_text):
        i = skip_ws(text, call_start + bm.end())
        if text.startswith("JSON.stringify", i):
            i = skip_ws(text, i + len("JSON.stringify"))
            if i < len(text) and text[i] == "(":
                i = skip_ws(text, i + 1)
        if i < len(text) and text[i] == "{":
            keys = object_literal_keys(text, i, min(len(text), i + 6000))
            if keys:
                return keys, text.count("\n", 0, i) + 1
    return None, None


# -------------------------------------------------------------- file scan
def scan_file(path: Path, rel: str, web_root: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    ctx = collect_file_context(text, path, web_root)
    sites = []
    for m in WRAPPER_RE.finditer(text):
        wrapper = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        open_paren = m.end() - 1
        call_end = match_balanced(text, open_paren)
        mmethod = METHOD_RE.search(text[m.start(): call_end])
        method = mmethod.group(1).upper() if mmethod else None
        arg = first_arg_span(text, open_paren)
        site = {"wrapper": wrapper, "line": line, "method": method,
                "file": rel, "func": enclosing_function(ctx, line)}
        if arg is not None:
            a0, a1 = unwrap_arg(text, arg[0], arg[1])
            body_keys, body_line = extract_body_keys(text, m.start(), call_end)
            if body_keys:
                site["body_keys"] = body_keys
                site["body_line"] = body_line
            if text[a0: a1].strip()[:1] in {"'", '"', "`"}:
                val, kind, _, interps = read_lit(text, a0)
                site["url_kind"] = kind
                site["url_raw"] = val
                if interps:
                    site["interps"] = interps
            else:
                literals = literals_in_span(text, a0, a1)
                if len(literals) > 1:
                    for li, (ls, _le) in enumerate(literals):
                        val, kind, _, interps = read_lit(text, ls)
                        branch = dict(site)
                        branch["url_kind"] = kind
                        branch["url_raw"] = val
                        branch["ternary_branch"] = li
                        if interps:
                            branch["interps"] = interps
                        sites.append(branch)
                    continue
                if len(literals) == 1:
                    val, kind, _, interps = read_lit(text, literals[0][0])
                    site["url_kind"] = kind
                    site["url_raw"] = val
                    site["single_literal_arg"] = True
                    if interps:
                        site["interps"] = interps
                else:
                    site["url_kind"] = "dynamic"
                    site["arg_preview"] = re.sub(
                        r"\s+", " ", text[a0: a1].strip())[:80]
        else:
            site["url_kind"] = "no-args"
        sites.append(site)

    ws_sites = []
    for m in re.finditer(r"\bnew\s+(WebSocket|EventSource)\s*\(", text):
        kind = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        open_paren = m.end() - 1
        entry = {"wrapper": f"new {kind}", "line": line, "file": rel,
                 "method": None, "func": enclosing_function(ctx, line)}
        arg = first_arg_span(text, open_paren)
        if arg:
            a0, a1 = unwrap_arg(text, arg[0], arg[1])
            if text[a0: a1].strip()[:1] in {"'", '"', "`"}:
                val, kind, _, interps = read_lit(text, a0)
                entry["url_kind"] = kind
                entry["url_raw"] = val
                if interps:
                    entry["interps"] = interps
            else:
                literals = literals_in_span(text, a0, a1)
                if literals:
                    val, kind, _, interps = read_lit(text, literals[0][0])
                    entry["url_kind"] = kind
                    entry["url_raw"] = val
                    if interps:
                        entry["interps"] = interps
                else:
                    entry["url_kind"] = "dynamic"
                    entry["arg_preview"] = re.sub(
                        r"\s+", " ", text[a0: a1].strip())[:80]
        ws_sites.append(entry)
    return sites, ws_sites, text, ctx


def classify(site, backend_paths, ctx):
    raw = site.get("url_raw")
    if raw is None:
        site["url_class"] = "no-url"
        return
    path, query, is_abs, prefix = split_url(raw)
    if is_abs:
        site["url_class"] = "external"
        site["abs_prefix"] = prefix
        return
    path_n, trailing = normalize_path(path)
    if path_n.startswith("{}"):
        interps = site.get("interps") or []
        first_tokens = INTERP_TOKEN_RE.findall(interps[0]) if interps else []
        for tok in first_tokens:
            val = ctx["const_env"].get(tok)
            if val and val.startswith("/"):
                path_n, t2 = normalize_path(val + path_n[2:])
                site["base_const"] = tok
                trailing = trailing or t2
                break
    site["path_norm"] = path_n
    site["trailing_slash"] = trailing
    if not (path_n.startswith("/api/") or path_n.startswith("/files/")
            or path_n.startswith("/health") or path_n.startswith("/ws/")):
        site["url_class"] = ("backend-indeterminate" if "{}" in path_n
                             else "non-backend")
        return
    site["url_class"] = "backend"
    cp, variant, finals, shadow = match_endpoint_variants(path_n, backend_paths)
    if cp is None:
        if any(seg != "{}" and "{}" in seg
               for seg in path_n.split("/") if seg):
            site["url_class"] = "backend-indeterminate"
            site["indeterminate_reason"] = "unresolved-interpolation"
            return
        site["verdict"] = "A1-endpoint-not-in-backend"
        return
    site["matched_path"] = cp
    if shadow:
        site["param_shadow_segments"] = shadow
    if variant != "as-is":
        site["match_variant"] = variant
    if finals:
        site["final_candidates"] = finals
    if variant == "dynamic-segment-enumeration":
        site["verdict"] = "B3a-enum-route-coupling"
        return
    routes = backend_paths[cp]
    methods: set[str] = set()
    declared_q: set[str] = set()
    body_models: list[dict] = []
    for r in routes:
        methods.update(r["methods"])
        for q in r["query_params"]:
            declared_q.add(q["name"])
        if r.get("body") and r["body"].get("kind") == "model":
            body_models.append(r["body"])
    if site["method"]:
        meth = site["method"].upper()
        site["method_declared"] = meth in methods
        if not site["method_declared"]:
            site["verdict"] = "A2-method-not-allowed"
            site["allowed_methods"] = sorted(methods)
    # ---- query params
    qnames: list[tuple[str, int]] = []
    for qm in QUERY_NAME_RE.finditer("?" + query):
        qnames.append((qm.group(1), site["line"]))
    for expr in site.get("interps", []):
        for pm in re.finditer(r"""[?&]([A-Za-z0-9_.\-]+)=""", expr):
            qnames.append((pm.group(1), site["line"]))
    query_interps: list[int] = []
    if query:
        marker_idx = 0
        qpos = raw.find("?")
        for i in range(0, len(raw) - 1):
            if raw[i:i + 2] == "{}":
                if qpos != -1 and i > qpos:
                    query_interps.append(marker_idx)
                marker_idx += 1
    interps = site.get("interps") or []
    for idx in query_interps:
        if idx >= len(interps):
            continue
        for tok in INTERP_TOKEN_RE.findall(interps[idx]):
            if tok in ctx["sp_vars"]:
                entries, scope = scoped_sp_entries(ctx, tok, site["line"])
                qnames.extend(entries)
                site["query_via"] = f"URLSearchParams:{tok}({scope})"
                break
    unknown: list[dict] = []
    seen: set[str] = set()
    for name, ln in qnames:
        if name in seen:
            continue
        seen.add(name)
        if declared_q and name not in declared_q:
            if name in WRAPPER_INJECTED_PARAMS:
                site.setdefault("wrapper_injected_params", []).append(name)
                continue
            unknown.append({"name": name, "line": ln})
    if unknown and "verdict" not in site:
        site["verdict"] = "B1-query-param-not-read"
        site["unknown_params"] = unknown
    if "verdict" not in site and qnames and not declared_q:
        dead = [{"name": n, "line": l} for n, l in qnames
                if n not in WRAPPER_INJECTED_PARAMS]
        if dead:
            site["verdict"] = "B4-query-param-dead"
            site["dead_params"] = dead
    # ---- body keys
    if site.get("body_keys") and body_models:
        site["body_model"] = sorted({b["model"] for b in body_models})
    if site.get("body_keys") and "verdict" not in site:
        if body_models:
            fields: set[str] = set()
            for b in body_models:
                fields.update(b["fields"].keys())
            extra = [k for k in site["body_keys"]
                     if k not in fields and k != "signal"]
            if extra:
                site["verdict"] = "B2-body-key-not-in-model"
                site["extra_body_keys"] = extra
                site["body_model"] = sorted({b["model"] for b in body_models})
    if "verdict" not in site:
        if site.get("param_shadow_segments"):
            site["verdict"] = "B3b-param-shadow-info"
        else:
            site["verdict"] = "ok"


# ------------------------------------------------------------ backend side
def short_type(ann):
    if ann is None:
        return "?"
    name = getattr(ann, "__name__", None)
    if name and not typing.get_origin(ann):
        return name
    origin = typing.get_origin(ann)
    if origin is typing.Union:
        args = typing.get_args(ann)
        parts = [short_type(a) for a in args if a is not type(None)]
        txt = "|".join(parts)
        return f"({txt}|None)" if type(None) in args else txt
    if origin is not None:
        args = [short_type(a) for a in typing.get_args(ann)]
        return f"{getattr(origin, '__name__', str(origin))}[{','.join(args)}]"
    return str(ann)


def describe_body(body_field):
    if body_field is None:
        return None
    t = getattr(body_field, "annotation", None)
    if t is None:
        fi = getattr(body_field, "field_info", None)
        t = getattr(fi, "annotation", None)
    if t is None:
        t = getattr(body_field, "type_", None)
    if t is None:
        return None
    for _ in range(3):
        origin = typing.get_origin(t)
        if origin is typing.Union:
            args = [a for a in typing.get_args(t) if a is not type(None)]
            if len(args) == 1:
                t = args[0]
                continue
        break
    if isinstance(t, type) and hasattr(t, "model_fields"):
        fields = {}
        for fname, finfo in getattr(t, "model_fields", {}).items():
            fields[getattr(finfo, "alias", None) or fname] = short_type(
                finfo.annotation)
        return {"kind": "model", "model": getattr(t, "__name__", str(t)),
                "fields": fields}
    origin = typing.get_origin(t)
    if origin in (list, dict):
        return {"kind": "list" if origin is list else "dict",
                "model": short_type(t), "fields": {}}
    return {"kind": "scalar", "model": short_type(t), "fields": {}}


def load_backend_routes(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from fastapi.routing import APIRoute  # noqa: E402

    import deeptutor.api.main as api_main  # noqa: E402

    app = api_main.app
    routes: list[dict] = []
    ws_routes: list[dict] = []

    def norm(p: str) -> str:
        return re.sub(r"\{(\w+):[A-Za-z_]+\}", r"{\1}", p)

    def loc_of(endpoint):
        try:
            f = inspect.getsourcefile(endpoint)
            ln = inspect.getsourcelines(endpoint)[1]
            if f:
                try:
                    f = str(Path(f).resolve().relative_to(repo_root))
                except ValueError:
                    pass
            return (f, ln)
        except (OSError, TypeError):
            return (None, None)

    def walk(route_list, prefix=""):
        for r in route_list:
            cls = type(r).__name__
            if cls == "_IncludedRouter":
                ctx = r.include_context
                walk(r.original_router.routes, prefix + (ctx.prefix or ""))
                continue
            if isinstance(r, APIRoute):
                full = norm(prefix + r.path) or "/"
                file_, line_ = loc_of(r.endpoint)
                qps = []
                for f in r.dependant.query_params:
                    qps.append({
                        "name": getattr(f.field_info, "alias", None) or f.name,
                        "type": short_type(f.field_info.annotation),
                    })
                pps = [f.name for f in r.dependant.path_params]
                routes.append({
                    "path": full,
                    "methods": sorted(m.upper() for m in r.methods),
                    "include_in_schema": bool(r.include_in_schema),
                    "handler": getattr(r.endpoint, "__name__", "?"),
                    "file": file_,
                    "line": line_,
                    "query_params": qps,
                    "path_params": pps,
                    "body": describe_body(r.body_field),
                })
            elif cls == "APIWebSocketRoute":
                full = norm(prefix + r.path) or "/"
                file_, line_ = loc_of(r.endpoint)
                ws_routes.append({
                    "path": full,
                    "handler": getattr(r.endpoint, "__name__", "?"),
                    "file": file_,
                    "line": line_,
                })
    walk(app.routes)
    return routes, ws_routes


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True,
                    help="repo root that contains deeptutor/ and web/")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--ref", default="", help="git ref recorded in report")
    args = ap.parse_args()
    repo_root = Path(args.repo_root).resolve()
    web_root = repo_root / "web"
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    backend_routes, backend_ws = load_backend_routes(repo_root)
    backend_paths: dict[str, list[dict]] = {}
    for r in backend_routes:
        backend_paths.setdefault(r["path"], []).append(r)

    exts = {".ts", ".tsx"}
    all_sites, all_ws = [], []
    umbrella_consts: set[str] = set()
    file_count = 0
    for p in sorted(web_root.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        rel = p.relative_to(web_root).as_posix()
        if any(part in SKIP_DIRS for part in rel.split("/")):
            continue
        file_count += 1
        sites, ws_sites, text, ctx = scan_file(p, rel, web_root)
        for v in ctx["const_env"].values():
            v = v.rstrip("/")
            if (v.startswith("/api/") or v.startswith("/files/")
                    or v.startswith("/ws/")):
                if len([s for s in v.split("/") if s]) >= 2:
                    umbrella_consts.add(v)
        for s in sites:
            classify(s, backend_paths, ctx)
        all_sites.extend(sites)
        all_ws.extend(ws_sites)

    backend = [s for s in all_sites if s.get("url_class") == "backend"]
    indeterminate = [s for s in all_sites
                     if s.get("url_class") == "backend-indeterminate"]
    nonbackend = [s for s in all_sites if s.get("url_class") == "non-backend"]
    external = [s for s in all_sites if s.get("url_class") == "external"]
    dynamic = [s for s in all_sites if s.get("url_kind") == "dynamic"]

    drift_a1 = [s for s in backend
                if s.get("verdict") == "A1-endpoint-not-in-backend"]
    drift_a2 = [s for s in backend
                if s.get("verdict") == "A2-method-not-allowed"]
    drift_b1 = [s for s in backend
                if s.get("verdict") == "B1-query-param-not-read"]
    drift_b2 = [s for s in backend
                if s.get("verdict") == "B2-body-key-not-in-model"]
    drift_b3a = [s for s in backend
                 if s.get("verdict") == "B3a-enum-route-coupling"]
    drift_b3b = [s for s in backend
                 if s.get("verdict") == "B3b-param-shadow-info"]
    drift_b4 = [s for s in backend
                if s.get("verdict") == "B4-query-param-dead"]

    # C1: backend REST routes never matched by any client call site
    def norm_path_for_match(p: str) -> str:
        return p.rstrip("/") or "/"

    matched_keys: set[tuple[str, str]] = set()
    matched_paths: set[str] = set()
    for s in backend:
        cp = s.get("matched_path")
        if not cp:
            continue
        matched_paths.add(norm_path_for_match(cp))
        if s.get("method"):
            matched_keys.add((norm_path_for_match(cp), s["method"].upper()))
    uncalled_routes = []
    for r in backend_routes:
        p = norm_path_for_match(r["path"])
        called_methods = sorted(m for (mp, m) in matched_keys if mp == p)
        route_called = bool(called_methods) or p in matched_paths
        uncalled_routes.append({
            "path": r["path"],
            "methods": r["methods"],
            "include_in_schema": r["include_in_schema"],
            "handler": r["handler"],
            "file": r["file"],
            "line": r["line"],
            "called_methods": called_methods,
            "verdict": "C1-uncalled" if not route_called else "covered",
        })
    c1 = []
    for r in uncalled_routes:
        if r["verdict"] != "C1-uncalled":
            continue
        p = r["path"]
        r["umbrella"] = None
        for u in sorted(umbrella_consts):
            if p == u or p.startswith(u if u.endswith("/") else u + "/"):
                r["umbrella"] = u
                r["verdict"] = "C1a-uncalled-dynamic-prefix"
                break
        c1.append(r)
    c1a = [r for r in c1 if r["verdict"] == "C1a-uncalled-dynamic-prefix"]
    c1b = [r for r in c1 if r["verdict"] == "C1-uncalled"]

    def slim(rows):
        out = []
        for s in rows:
            keep = {}
            for k, v in s.items():
                if k == "file" and v:
                    keep["file"] = v
                else:
                    keep[k] = v
            out.append(keep)
        return out

    result = {
        "ref": args.ref,
        "repo_root": str(repo_root),
        "files_scanned": file_count,
        "backend": {
            "rest_routes": len(backend_routes),
            "hidden_rest_routes": sum(
                1 for r in backend_routes if not r["include_in_schema"]),
            "ws_routes": len(backend_ws),
            "unique_paths": len(backend_paths),
        },
        "summary": {
            "call_sites_total": len(all_sites),
            "backend_call_sites": len(backend),
            "backend_indeterminate": len(indeterminate),
            "dynamic_url_sites": len(dynamic),
            "non_backend_sites": len(nonbackend),
            "external_sites": len(external),
            "ws_call_sites": len(all_ws),
            "drift_A1_endpoint": len(drift_a1),
            "drift_A2_method": len(drift_a2),
            "drift_B1_query_param": len(drift_b1),
            "drift_B2_body_key": len(drift_b2),
            "drift_B3a_enum_route_coupling": len(drift_b3a),
            "drift_B3b_param_shadow_info": len(drift_b3b),
            "drift_B4_query_param_dead": len(drift_b4),
            "C1_backend_routes_uncalled": len(c1),
            "C1a_uncalled_dynamic_prefix": len(c1a),
            "C1b_uncalled_no_static_caller": len(c1b),
        },
        "drift": {
            "A1_endpoint_not_in_backend": slim(drift_a1),
            "A2_method_not_allowed": slim(drift_a2),
            "B1_query_param_not_read": slim(drift_b1),
            "B2_body_key_not_in_model": slim(drift_b2),
            "B3a_enum_route_coupling": slim(drift_b3a),
            "B3b_param_shadow_info": slim(drift_b3b),
            "B4_query_param_dead": slim(drift_b4),
            "C1_backend_routes_uncalled": slim(c1),
        },
        "umbrella_consts": sorted(umbrella_consts),
        "backend_routes": slim(backend_routes),
        "backend_ws_routes": slim(backend_ws),
        "backend_call_sites": slim(
            sorted(backend, key=lambda s: (s["file"], s["line"]))),
        "backend_indeterminate_sites": slim(
            sorted(indeterminate, key=lambda s: (s["file"], s["line"]))),
        "dynamic_url_sites": slim(
            sorted(dynamic, key=lambda s: (s["file"], s["line"]))),
        "ws_call_sites": slim(
            sorted(all_ws, key=lambda s: (s["file"], s["line"]))),
    }
    (outdir / "parity.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print("backend rest routes:", len(backend_routes),
          "unique paths:", len(backend_paths))


if __name__ == "__main__":
    main()
