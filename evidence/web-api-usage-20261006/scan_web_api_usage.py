#!/usr/bin/env python3
"""Scan frontend API call surface in web/ against the generated OpenAPI contract.

Scope (AGEN-857): HTTP call points in web/**/*.ts(x) — wrapper calls
(apiFetch/requestJson/requestVoid/requestBlob/asJsonOrThrow), raw fetch(),
and URL-builder nested calls (apiUrl/wsUrl/scopedUrl), plus a WebSocket
call-point inventory.

Checks:
  1. endpoint drift    — called path not present in contracts/schema/openapi.json
                         (segment match honoring {param} placeholders; slash
                         runs collapsed; trailing slash normalized and noted)
  2. method drift      — called method not declared for the matched path
  3. query-param drift — param names in URL literals or URLSearchParams-built
                         query strings (linked by variable name within the
                         same file) not declared in the contract for the
                         matched path+method
  4. bare-URL inventory — call sites pass raw URL strings; none is typed
                         against web/contracts/generated/api.ts. Reported as
                         usage stats + full call-point lists.

Out of scope (noted in report): request/response body field drift (needs
type-level analysis); WebSocket route contracts (not in OpenAPI).

Methodology: regex + a small balanced-paren/string-literal tokenizer
(AST-lite). Deterministic, stdlib only. Python >= 3.9.

Usage:
  python3 scan_web_api_usage.py --repo /path/to/repo/web --outdir <dir> [--ref X]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WRAPPER_RE = re.compile(
    r"\b(apiFetch|requestJson|requestVoid|requestBlob|asJsonOrThrow|fetch)\s*\("
)
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
IDENT = r"[A-Za-z_$][\w$]*"
BACKEND_PREFIXES = ("/api/", "/files/", "/health")
CONTRACT_METHODS = {"get", "post", "put", "delete", "patch", "head",
                    "options", "trace"}


# ---------------------------------------------------------------- tokenizer
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


def read_literal(text: str, i: int):
    """Read a JS string/template literal starting at text[i] (a quote).

    Returns (value, kind, next_index, interps). For templates, each ${...}
    expression is replaced by the marker "{}" and its source text is appended
    to the interps list (nested braces and backticks are tracked by counting).
    """
    quote = text[i]
    kind = "template" if quote == "`" else "string"
    out = []
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
    """Index just past the balanced-paren group whose '(' is text[i]."""
    depth = 0
    n = min(len(text), i + cap)
    j = i
    while j < n:
        c = text[j]
        if c in "'\"`" and depth > 0:
            _, _, j, _ = read_literal(text, j)
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
    """Span (start, end) of the first argument of a call at open_paren."""
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
            _, _, j, _ = read_literal(text, j)
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


def unwrap_url_builder(text: str, start: int, end: int):
    """If the arg span is apiUrl(...)/wsUrl(...)/scopedUrl(...), return the
    span of ITS first argument (up to 4 levels deep)."""
    span = (start, end)
    for _ in range(4):
        seg = text[span[0]: span[1]]
        m = re.match(rf"\s*(?:await\s+)?({IDENT})\s*\(", seg)
        if not m or m.group(1) not in {"apiUrl", "wsUrl", "scopedUrl"}:
            return span
        inner_open = span[0] + m.end() - 1
        inner = first_arg_span(text, inner_open)
        if inner is None:
            return span
        span = inner
    return span


# ---------------------------------------------------------------- contract
def load_contract(web_root: Path):
    schema_path = web_root / "contracts" / "schema" / "openapi.json"
    api_ts_path = web_root / "contracts" / "generated" / "api.ts"
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    paths = {}
    for p, item in schema.get("paths", {}).items():
        methods = {}
        for m, op in item.items():
            if m not in CONTRACT_METHODS or not isinstance(op, dict):
                continue
            qparams = [
                par.get("name")
                for par in op.get("parameters", [])
                if isinstance(par, dict) and par.get("in") == "query"
            ]
            methods[m.lower()] = qparams
        paths[p] = methods
    api_text = api_ts_path.read_text(encoding="utf-8")
    ts_keys = set(re.findall(r'readonly\s+"(/[^"]*)"\s*:\s*\{', api_text))
    return {
        "paths": paths,
        "schema_path": schema_path,
        "api_ts_path": api_ts_path,
        "ts_path_keys": ts_keys,
    }


def normalize_path(path: str):
    p = re.sub(r"/{2,}", "/", path)
    trailing = p.endswith("/") and len(p) > 1
    if trailing:
        p = p.rstrip("/") or "/"
    return p, trailing


def match_endpoint(norm: str, contract_paths):
    """Exact match, else best placeholder-aware segment match
    (fewest placeholders, then lexicographic — deterministic).

    Returns (path, shadow_positions) where shadow_positions lists segment
    indexes where a URL LITERAL matched a contract {param} (route-shadowing
    risk: the backend may resolve that literal to a dedicated static route
    that the OpenAPI export omits, e.g. include_in_schema=False aliases).
    """
    if norm in contract_paths:
        return norm, []
    parts = [s for s in norm.split("/") if s != ""]
    cands = []
    for cp in sorted(contract_paths):
        cparts = [s for s in cp.split("/") if s != ""]
        if len(cparts) != len(parts):
            continue
        shadow = []
        ok = True
        for i, (a, b) in enumerate(zip(parts, cparts)):
            if b.startswith("{") and b.endswith("}"):
                if a != "{}":
                    shadow.append(i)
                continue
            if a != b:
                ok = False
                break
        if ok:
            ph = sum(1 for b in cparts if b.startswith("{"))
            cands.append((ph, cp, shadow))
    if not cands:
        return None, []
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0][1], cands[0][2]


def path_variants(path_n: str):
    """(retained for documentation of historical variants; superseded by
    match_endpoint_variants)"""
    return [("as-is", path_n)]


def _prefix_match(url_segs, contract_segs) -> bool:
    """For bounded-union prefixes: literals must be equal; the URL '{}'
    marker accepts a contract literal or {param}; a contract {param} accepts
    only the URL '{}' marker (URL literals matching contract params is left
    to full-path as-is matching, not prefix guessing)."""
    for a, b in zip(url_segs, contract_segs):
        if a == "{}":
            continue
        if a == b:
            continue
        return False
    return True


def match_endpoint_variants(path_n: str, contract_paths):
    """Try, in order (deterministic; first hit wins):
      1. as-is — URL literal segments match contract literals, contract
         {param} accepts any single URL segment;
      2. dynamic-final-segment — URL's LAST segment is exactly '{}' (a
         runtime path value); the contract has a path with the same prefix
         and one extra final segment (literal or {param});
      3. suffix-stripped — URL's last segment ENDS with '{}' (conditional
         query-append idiom `...${qs ? '?x' : ''}`); strip trailing '{}'
         and re-match;
      4. final-dropped — last segment is exactly '{}' and the contract has
         the path without it.
    """
    cp, shadow = match_endpoint(path_n, contract_paths)
    if cp is not None:
        return cp, ("param-tolerant" if shadow else "as-is"), None, shadow
    segs = [s for s in path_n.split("/") if s != ""]
    if not segs:
        return None, None, None, None
    if segs[-1] == "{}":
        prefix = segs[:-1]
        finals = [cp2 for cp2 in sorted(contract_paths)
                  if len(cp2.split("/")) - 1 == len(prefix) + 1
                  and _prefix_match(prefix,
                                    [s for s in cp2.split("/") if s != ""][:-1])]
        if finals:
            return finals[0], "dynamic-final-segment", finals[:8], []
        return None, None, None, None
    if segs[-1].endswith("{}") and segs[-1] != "{}":
        stripped = segs[-1][: -2].rstrip("/")
        cand = "/".join(segs[:-1] + ([stripped] if stripped else []))
        cp2, sh2 = match_endpoint(cand, contract_paths)
        if cp2 is not None:
            return cp2, "suffix-stripped", None, sh2
    if segs[-1] == "{}" and len(segs) > 1:
        cp2, sh2 = match_endpoint("/".join(segs[:-1]), contract_paths)
        if cp2 is not None:
            return cp2, "final-dropped", None, sh2
    return None, None, None, None


def split_url(raw_url: str):
    """-> (path, query, is_absolute, abs_prefix)"""
    u = raw_url.strip()
    m = re.match(r"^(https?:|wss?:)?//[^/?#]*", u)
    if m:
        prefix = m.group(0)
        rest = u[len(prefix):] or "/"
        path, _, query = rest.partition("?")
        return (path or "/", query, True, prefix)
    path, _, query = u.partition("?")
    return path, query, False, ""


# ---------------------------------------------------------------- scanning
FUNC_HEAD_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function[\s*]\w+"
    r"|^\s*(?:export\s+)?const\s+\w+\s*=\s*(?:async\s+)?(?:function\b|\()",
    re.M,
)
WRAPPER_INJECTED_PARAMS = {"dt_workspace"}


CONST_LIT_RE = re.compile(
    r"""(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(["'])([^"'\n]{0,160}?)\2"""
)
IMPORT_RE = re.compile(r"""import\s*\{([^}]+)\}\s*from\s*["']([^"']+)["']""")
INTERP_TOKEN_RE = re.compile(r"[A-Za-z_$][\w$]*")


def resolve_module(specifier: str, cur_file: Path, web_root: Path):
    """Resolve an import specifier to a file (alias @/ → web root)."""
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


def literals_in_span(text: str, start: int, end: int):
    """All string/template literal start positions (with end) inside a span,
    at paren depth 0, whose value begins with '/'."""
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
            full = read_literal(text, j)
            if full[0].startswith("/"):
                out.append((j, full[2]))
            j = full[2]
            continue
        j += 1
    return out


def collect_file_context(text: str, cur_file: Path = None,
                         web_root: Path = None):
    """URLSearchParams vars (param names + lines), init lines and function
    header lines, used for call-site-scoped query linkage."""
    sp_vars, sp_inits = {}, {}
    for m in SP_INIT_RE.finditer(text):
        var = m.group(1)
        sp_vars.setdefault(var, [])
        sp_inits[var] = text.count("\n", 0, m.start()) + 1
    for m in SP_CALL_RE.finditer(text):
        var, name = m.group(1), m.group(2)
        if var in sp_vars:
            line = text.count("\n", 0, m.start()) + 1
            entry = (name, line)
            if entry not in sp_vars[var]:
                sp_vars[var].append(entry)
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
    func_lines = [text.count("\n", 0, m.start()) + 1
                  for m in FUNC_HEAD_RE.finditer(text)]
    const_env = {}
    for m in CONST_LIT_RE.finditer(text):
        const_env[m.group(1)] = m.group(3)
    if cur_file is not None and web_root is not None:
        for m in IMPORT_RE.finditer(text):
            names = [n.strip().split(" as ")[0].strip()
                     for n in m.group(1).split(",")]
            target = resolve_module(m.group(2), cur_file, web_root)
            if target is None or not str(target).startswith(str(web_root)):
                continue
            try:
                target_text = target.read_text(encoding="utf-8",
                                               errors="replace")
            except OSError:
                continue
            for cm in CONST_LIT_RE.finditer(target_text):
                if cm.group(1) in names:
                    const_env[cm.group(1)] = cm.group(3)
    return {"sp_vars": sp_vars, "sp_inits": sp_inits, "func_lines": func_lines,
            "const_env": const_env}


def scoped_sp_entries(ctx, var: str, call_line: int):
    """Param entries for var whose lines fall inside the enclosing function
    window of the call site (var names are reused across functions, so
    file-wide unions over-report). Falls back to no linkage."""
    entries = ctx["sp_vars"].get(var, [])
    func_lines = ctx["func_lines"]
    start = max([fl for fl in func_lines if fl <= call_line], default=1)
    end = min([fl for fl in func_lines if fl > call_line], default=10 ** 9)
    window = [(n, l) for n, l in entries if start <= l < end]
    return window, ("function-scoped" if window else "unlinked")


def scan_file(path: Path, rel: str, contract, web_root: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    ctx = collect_file_context(text, cur_file=path, web_root=web_root)
    sites = []
    for m in WRAPPER_RE.finditer(text):
        wrapper = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        open_paren = m.end() - 1
        call_end = match_balanced(text, open_paren)
        mmethod = METHOD_RE.search(text[m.start(): call_end])
        method = mmethod.group(1).upper() if mmethod else None
        arg = first_arg_span(text, open_paren)
        site = {
            "wrapper": wrapper,
            "line": line,
            "method": method,
            "file": rel,
        }
        if arg is None:
            site["url_kind"] = "no-args"
            sites.append(site)
            continue
        a0, a1 = unwrap_url_builder(text, arg[0], arg[1])
        arg_text = text[a0: a1]
        if arg_text.strip()[:1] in {"'", '"', "`"}:
            val, kind, _, interps = read_literal(text, a0)
            site["url_kind"] = kind
            site["url_raw"] = val
            if interps:
                site["interps"] = interps
        else:
            literals = literals_in_span(text, a0, a1)
            if len(literals) > 1:
                for li, (lit_start, _lit_end) in enumerate(literals):
                    val, kind, _, interps = read_literal(text, lit_start)
                    branch = dict(site)
                    branch["url_kind"] = kind
                    branch["url_raw"] = val
                    branch["ternary_branch"] = li
                    if interps:
                        branch["interps"] = interps
                    sites.append(branch)
                continue
            if len(literals) == 1:
                val, kind, _, interps = read_literal(text, literals[0][0])
                site["url_kind"] = kind
                site["url_raw"] = val
                site["single_literal_arg"] = True
                if interps:
                    site["interps"] = interps
            else:
                site["url_kind"] = "dynamic"
                site["arg_preview"] = re.sub(r"\s+", " ", arg_text.strip())[:80]
        sites.append(site)

    ws_sites = []
    for m in re.finditer(r"\bnew\s+(WebSocket|EventSource)\s*\(", text):
        kind = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        open_paren = m.end() - 1
        entry = {"wrapper": f"new {kind}", "line": line, "file": rel,
                 "method": None}
        arg = first_arg_span(text, open_paren)
        if arg:
            a0, a1 = unwrap_url_builder(text, arg[0], arg[1])
            if text[a0: a1].strip()[:1] in {"'", '"', "`"}:
                val, kind, _, interps = read_literal(text, a0)
                entry["url_kind"] = kind
                entry["url_raw"] = val
                if interps:
                    entry["interps"] = interps
            else:
                literals = literals_in_span(text, a0, a1)
                if literals:
                    val, kind, _, interps = read_literal(
                        text, literals[0][0])
                    entry["url_kind"] = kind
                    entry["url_raw"] = val
                    if interps:
                        entry["interps"] = interps
                else:
                    entry["url_kind"] = "dynamic"
                    entry["arg_preview"] = re.sub(
                        r"\s+", " ", text[a0: a1].strip())[:80]
        ws_sites.append(entry)

    typed_imports = bool(
        re.search(r"""from\s+["'][^"']*contracts/generated/api["']""", text)
    )
    return sites, ws_sites, typed_imports, ctx


def classify(site, contract, ctx):
    raw = site.get("url_raw")
    if raw is None:
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
                site["path_resolved"] = path_n
                trailing = trailing or t2
                break
    site["path_norm"] = path_n
    site["trailing_slash"] = trailing
    if not path_n.startswith(BACKEND_PREFIXES):
        site["url_class"] = ("backend-indeterminate" if "{}" in path_n
                             else "non-backend")
        return
    site["url_class"] = "backend"
    cp, variant, finals, shadow = match_endpoint_variants(
        path_n, contract["paths"])
    if cp is None:
        # remaining '{}' that is not a clean standalone segment means an
        # unresolved runtime interpolation (e.g. `${BASE}${path}`) — not
        # provable drift; park it for manual/caller-side resolution
        if any(seg != "{}" and "{}" in seg
               for seg in path_n.split("/") if seg):
            site["url_class"] = "backend-indeterminate"
            site["indeterminate_reason"] = "unresolved-interpolation"
            return
        site["verdict"] = "endpoint-not-in-contract"
        return
    site["contract_path"] = cp
    if shadow:
        site["param_shadow_segments"] = shadow
    if variant and variant != "as-is":
        site["match_variant"] = variant
    if finals:
        site["final_candidates"] = finals
    methods = contract["paths"][cp]
    if site["method"]:
        meth = site["method"].lower()
        site["method_declared"] = meth in methods
        if not site["method_declared"]:
            site["verdict"] = "method-not-declared"
            site["allowed_methods"] = sorted(methods)
    # --- query params: literal, interpolated literals, URLSearchParams ---
    qnames = []
    for qm in QUERY_NAME_RE.finditer("?" + query):
        qnames.append((qm.group(1), site["line"]))
    for expr in site.get("interps", []):
        for pm in re.finditer(r"""[?&]([A-Za-z0-9_.\-]+)=""", expr):
            qnames.append((pm.group(1), site["line"]))
    # query-position interps: markers after the first literal '?'
    query_interps = []
    if query:
        marker_idx, qpos = 0, raw.find("?")
        for i in range(0, len(raw) - 1):
            if raw[i:i + 2] == "{}":
                if qpos != -1 and i > qpos:
                    query_interps.append(marker_idx)
                marker_idx += 1
    interps = site.get("interps") or []
    for idx in query_interps:
        if idx >= len(interps):
            continue
        expr = interps[idx]
        tokens = INTERP_TOKEN_RE.findall(expr)
        linked = False
        for tok in tokens:
            if tok in ctx["sp_vars"]:
                entries, scope = scoped_sp_entries(ctx, tok, site["line"])
                qnames.extend(entries)
                site["query_via"] = f"URLSearchParams:{tok}({scope})"
                linked = True
                break
        if not linked and tokens:
            site.setdefault("interp_tokens", tokens[:4])
    declared = set()
    if site["method"] and site["method"].lower() in methods:
        declared = set(methods[site["method"].lower()])
    else:
        for ms in methods.values():
            declared.update(ms)
    unknown, seen = [], set()
    for name, ln in qnames:
        if name in seen:
            continue
        seen.add(name)
        if declared and name not in declared:
            if name in WRAPPER_INJECTED_PARAMS:
                site.setdefault("wrapper_injected_params", []).append(name)
                continue
            unknown.append({"name": name, "line": ln})
    if unknown:
        site["verdict"] = "query-param-not-in-contract"
        site["unknown_params"] = unknown
    if "verdict" not in site:
        site["verdict"] = "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path to web/ root")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--ref", default="", help="git ref recorded in report")
    args = ap.parse_args()
    web_root = Path(args.repo).resolve()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    contract = load_contract(web_root)

    exts = {".ts", ".tsx"}
    skip_dirs = {"node_modules", ".next", "contracts", "coverage", "dist"}
    all_sites, all_ws = [], []
    typed_files = []
    file_count = 0
    for p in sorted(web_root.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        rel = p.relative_to(web_root).as_posix()
        if any(part in skip_dirs for part in rel.split("/")):
            continue
        file_count += 1
        sites, ws_sites, typed, ctx = scan_file(p, rel, contract, web_root)
        if typed:
            typed_files.append(rel)
        for s in sites:
            classify(s, contract, ctx)
        all_sites.extend(sites)
        all_ws.extend(ws_sites)

    backend = [s for s in all_sites if s.get("url_class") == "backend"]
    drift_endpoints = [s for s in backend
                       if s.get("verdict") == "endpoint-not-in-contract"]
    drift_methods = [s for s in backend
                     if s.get("verdict") == "method-not-declared"]
    drift_params = [s for s in backend
                    if s.get("verdict") == "query-param-not-in-contract"]
    dyn = [s for s in all_sites if s.get("url_kind") == "dynamic"]
    indeterminate = [s for s in all_sites
                     if s.get("url_class") == "backend-indeterminate"]
    nonbackend = [s for s in all_sites if s.get("url_class") == "non-backend"]
    external = [s for s in all_sites if s.get("url_class") == "external"]

    def slim(sites):
        out = []
        for s in sites:
            keep = {k: v for k, v in s.items() if not k.startswith("_")}
            out.append(keep)
        return out

    result = {
        "ref": args.ref,
        "web_root": str(web_root),
        "files_scanned": file_count,
        "contract": {
            "schema": str(contract["schema_path"]),
            "generated_ts": str(contract["api_ts_path"]),
            "path_count": len(contract["paths"]),
            "api_ts_path_keys": len(contract["ts_path_keys"]),
            "schema_vs_ts_key_diff": sorted(
                set(contract["ts_path_keys"]) ^ set(contract["paths"])),
        },
        "summary": {
            "call_sites_total": len(all_sites),
            "backend_call_sites": len(backend),
            "backend_indeterminate_sites": len(indeterminate),
            "dynamic_url_sites": len(dyn),
            "non_backend_sites": len(nonbackend),
            "external_sites": len(external),
            "ws_sites": len(all_ws),
            "typed_contract_import_files": typed_files,
            "drift_endpoint": len(drift_endpoints),
            "drift_method": len(drift_methods),
            "drift_query_param": len(drift_params),
        },
        "drift": {
            "endpoint_not_in_contract": slim(drift_endpoints),
            "method_not_declared": slim(drift_methods),
            "query_param_not_in_contract": slim(drift_params),
        },
        "backend_call_sites": slim(
            sorted(backend, key=lambda s: (s["file"], s["line"]))),
        "backend_indeterminate_sites": slim(
            sorted(indeterminate, key=lambda s: (s["file"], s["line"]))),
        "dynamic_url_sites": slim(
            sorted(dyn, key=lambda s: (s["file"], s["line"]))),
        "non_backend_sites": slim(
            sorted(nonbackend, key=lambda s: (s["file"], s["line"]))),
        "external_sites": slim(
            sorted(external, key=lambda s: (s["file"], s["line"]))),
        "websocket_sites": slim(
            sorted(all_ws, key=lambda s: (s["file"], s["line"]))),
    }
    (outdir / "usage.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print("contract path-key diff (schema vs api.ts):",
          result["contract"]["schema_vs_ts_key_diff"] or "none")


if __name__ == "__main__":
    main()
