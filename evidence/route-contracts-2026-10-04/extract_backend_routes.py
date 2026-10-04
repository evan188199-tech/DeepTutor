#!/usr/bin/env python3
"""Statically extract the FastAPI route table for evidence reporting.

Reads deeptutor/api/main.py (mount prefixes) and deeptutor/api/routers/*.py
(APIRouter prefixes + route decorators). No app import, no side effects.
Outputs backend_routes.tsv: mount_prefix<TAB>router_prefix<TAB>method<TAB>path<TAB>file:line
"""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
ROUTERS = ROOT / "deeptutor" / "api" / "routers"
MAIN = ROOT / "deeptutor" / "api" / "main.py"

METHODS = "get|post|put|delete|patch|head|options|trace|api_route|websocket"
DECOR_RE = re.compile(rf"@([A-Za-z_][A-Za-z0-9_]*)\.({METHODS})\s*\(")
STR_RE = re.compile(r"""["']([^"']*)["']""")
APIROUTER_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*APIRouter\s*\(", re.MULTILINE
)
PREFIX_RE = re.compile(r"""prefix\s*=\s*["']([^"']*)["']""")
INCLUDE_RE = re.compile(r"\.include_router\(\s*([A-Za-z_][A-Za-z0-9_.]*)")
APPDECOR_RE = re.compile(rf"@app\.({METHODS})\s*\(")


def find_string_arg(text: str, start: int) -> str | None:
    """Return first quoted string inside the parens starting at `start` (position after '(')."""
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                break
        elif c in "\"'":
            m = STR_RE.match(text, i)
            if m:
                return m.group(1)
            i += 1
            continue
        i += 1
    return None


def parse_router_file(path: Path):
    """Return (router_name -> prefix, [ (router_name, method, path, lineno) ])."""
    text = path.read_text(encoding="utf-8")
    prefixes: dict[str, str] = {}
    routes = []
    # APIRouter instantiations (possibly multi-line) with prefix kwarg
    for m in APIROUTER_RE.finditer(text):
        name = m.group(1)
        # capture balanced parens
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        body = text[m.end():i]
        pm = PREFIX_RE.search(body)
        prefixes[name] = pm.group(1) if pm else ""
    # decorators
    for m in DECOR_RE.finditer(text):
        rname, meth = m.group(1), m.group(2)
        # find path: first quoted string after '('
        p = find_string_arg(text, m.end())
        if p is None:
            continue
        line = text.count("\n", 0, m.start()) + 1
        # api_route may declare methods=[...]
        if meth == "api_route":
            # look ahead within 400 chars for methods=
            seg = text[m.end():m.end() + 500]
            mm = re.search(r"methods\s*=\s*\[([^\]]*)\]", seg)
            if mm:
                for sm in re.findall(r"""["']([A-Z]+)["']""", mm.group(1)):
                    routes.append((rname, sm.lower(), p, line))
            else:
                routes.append((rname, "get", p, line))
        else:
            routes.append((rname, meth, p, line))
    # app-level decorators in this file (rare)
    for m in APPDECOR_RE.finditer(text):
        p = find_string_arg(text, m.end())
        if p is None:
            continue
        line = text.count("\n", 0, m.start()) + 1
        routes.append(("app", m.group(1), p, line))
    # nested include_router inside router files
    nested = []
    for m in INCLUDE_RE.finditer(text):
        ref = m.group(1)
        p = find_string_arg_prefix(text, m.end())
        line = text.count("\n", 0, m.start()) + 1
        nested.append((ref, p, line))
    return prefixes, routes, nested


def find_string_arg_prefix(text: str, start: int) -> str | None:
    """First prefix=\"...\" kwarg or positional string after include_router("""
    seg = text[start:start + 600]
    pm = PREFIX_RE.search(seg)
    if pm:
        return pm.group(1)
    return None


def parse_main():
    text = MAIN.read_text(encoding="utf-8")
    mounts = []  # (router_ref, prefix, line)
    for m in INCLUDE_RE.finditer(text):
        ref = m.group(1)
        prefix = find_string_arg_prefix(text, m.end()) or ""
        line = text.count("\n", 0, m.start()) + 1
        mounts.append((ref, prefix, line))
    app_routes = []
    for m in APPDECOR_RE.finditer(text):
        p = find_string_arg(text, m.end())
        if p is None:
            continue
        line = text.count("\n", 0, m.start()) + 1
        app_routes.append(("app", m.group(1), p, line))
    return mounts, app_routes


def parse_main_aliases():
    text = MAIN.read_text(encoding="utf-8")
    # alias -> module (e.g. `from deeptutor.api.routers import tools as tools_router`)
    aliases = {}
    # alias -> (module, imported_name) (e.g. `from deeptutor.api.routers.multi_user import router as multi_user_router`)
    attr_aliases = {}
    for m in re.finditer(
        r"from\s+deeptutor\.api\.routers\s+import\s*\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)",
        text,
    ):
        aliases[m.group(2)] = m.group(1)
    for m in re.finditer(
        r"from\s+deeptutor\.api\.routers\.([A-Za-z_][A-Za-z0-9_]*)\s+import\s+([A-Za-z_][A-Za-z0-9_]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)",
        text,
    ):
        attr_aliases[m.group(3)] = (m.group(1), m.group(2))
    return aliases, attr_aliases


def main():
    mounts, app_routes = parse_main()
    aliases, attr_aliases = parse_main_aliases()
    # gather router prefixes/routes per file
    file_info = {}
    nested_all = []
    for f in sorted(ROUTERS.glob("*.py")):
        prefixes, routes, nested = parse_router_file(f)
        rel = str(f.relative_to(ROOT))
        file_info[rel] = (prefixes, routes)
        for ref, pfx, line in nested:
            nested_all.append((rel, ref, pfx, line))

    # module name -> file rel
    mod2file = {Path(k).stem: k for k in file_info}

    rows = []
    # main.py app-level routes
    for _, meth, p, line in app_routes:
        rows.append(("", "", meth.upper(), p, f"deeptutor/api/main.py:{line}"))
    # mounted routers: ref like 'auth.router' or 'workspace.files_router'
    for ref, mount_prefix, mline in mounts:
        if ref in attr_aliases:
            mod, attr = attr_aliases[ref]
        else:
            parts = ref.split(".")
            if len(parts) < 2:
                rows.append((mount_prefix, "?", "?", f"UNRESOLVED:{ref}", f"deeptutor/api/main.py:{mline}"))
                continue
            mod, attr = parts[0], parts[1]
            mod = aliases.get(mod, mod)
        f = mod2file.get(mod)
        if not f:
            rows.append((mount_prefix, "?", "?", f"UNRESOLVED:{ref}", f"deeptutor/api/main.py:{mline}"))
            continue
        prefixes, routes = file_info[f]
        rprefix = prefixes.get(attr, "")
        # routes declared on that attr; if none declared on attr but attr is the
        # only/primary router, fall back to all routes in file
        attr_routes = [r for r in routes if r[0] == attr]
        used = attr_routes
        if not attr_routes:
            others = [r for r in routes if r[0] not in prefixes or r[0] == "app"]
            if others and len([k for k in prefixes]) <= 2:
                used = others
        for rname, meth, p, line in used:
            rows.append((mount_prefix, rprefix, meth.upper(), p, f"{f}:{line}"))

    seen = set()
    out = []
    for mount, rpre, meth, p, loc in rows:
        eff = (mount + rpre + p) if not p.startswith("UNRESOLVED") else p
        key = (eff, meth, loc)
        if key in seen:
            continue
        seen.add(key)
        out.append((mount, rpre, meth, p, loc, eff))
    for row in sorted(out, key=lambda r: (r[5], r[2], r[4])):
        print("\t".join(row))


if __name__ == "__main__":
    main()
