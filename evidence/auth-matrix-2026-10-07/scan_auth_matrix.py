#!/usr/bin/env python3
"""Static route x guard x surface matrix scanner for DeepTutor (AGEN-1125).

Read-only AST analysis:
  1. Parses deeptutor/api/main.py include_router calls (include-level guard
     groups such as _auth / _admin / [Depends(require_auth)]).
  2. Parses every module in deeptutor/api/routers for APIRouter objects,
     route decorators, decorator-level dependencies, signature-level
     Depends(...) guards, and in-handler auth markers (ws_require_auth,
     assert_learning_surface, device-token helpers).
  3. Extracts the learning-surface map from api/routers/auth.py
     (_learning_surface_for_path + _LEARNER_KB_READ_ROUTES +
     _LEARNER_SETTINGS_WRITE_ROUTES) and classifies every route.

Outputs auth_matrix.csv and a report fragment (counts/distribution) on stdout.
No product code is executed or modified.
"""

from __future__ import annotations

import ast
import csv
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "deeptutor" / "api" / "main.py"
ROUTERS_DIR = REPO / "deeptutor" / "api" / "routers"
AUTH = ROUTERS_DIR / "auth.py"

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
ALL_METHODS = HTTP_METHODS | {"websocket"}
GUARD_DEP_NAMES = {"require_auth", "require_admin", "require_learning_surface"}
PARTNER_GUARDS = {"usable_partner", "manageable_partner"}


# --------------------------------------------------------------------------
# Guard-flag extraction
# --------------------------------------------------------------------------
def dep_flags(node: ast.AST | None, groups: dict[str, set[str]]) -> set[str]:
    """Translate a dependency expression into guard flags.

    Flags: auth, admin, surface, partner-access.
    """
    flags: set[str] = set()
    if node is None:
        return flags
    if isinstance(node, ast.Name):
        if node.id == "require_admin":
            return {"auth", "admin"}
        if node.id == "require_auth":
            return {"auth"}
        if node.id == "require_learning_surface":
            return {"auth", "surface"}
        if node.id in PARTNER_GUARDS:
            return {"partner-access"}
        return set(groups.get(node.id, set()))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name == "Depends" and node.args:
            return dep_flags(node.args[0], groups)
        if name == "require_admin":
            return {"auth", "admin"}
        if name == "require_auth":
            return {"auth"}
        if name == "require_learning_surface":
            return {"auth", "surface"}
        if name in PARTNER_GUARDS:
            return {"partner-access"}
        return flags
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for el in node.elts:
            flags |= dep_flags(el, groups)
    return flags


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def expr_label(node: ast.AST | None) -> str:
    """Short source-ish label for a dependency expression (report only)."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        name = call_name(node)
        if name == "Depends" and node.args:
            return f"Depends({expr_label(node.args[0])})"
        return name or "?"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        inner = ", ".join(expr_label(e) for e in node.elts)
        return f"[{inner}]"
    return "?"


# --------------------------------------------------------------------------
# Phase 1: main.py — imports, guard groups, include_router calls, app routes
# --------------------------------------------------------------------------
@dataclass
class Include:
    module: str
    router_name: str
    prefix: str
    flags: set[str]
    include_label: str
    line: int


@dataclass
class AppRoute:
    methods: list[str]
    path: str
    line: int


def parse_main() -> tuple[list[Include], list[AppRoute], dict[str, str]]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    import_alias: dict[str, tuple[str, str | None]] = {}
    guard_groups: dict[str, set[str]] = {}
    includes: list[Include] = []
    app_routes: list[AppRoute] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "deeptutor.api.routers":
                for a in node.names:
                    import_alias[a.asname or a.name] = (a.name, None)
            elif node.module.startswith("deeptutor.api.routers."):
                mod = node.module.rsplit(".", 1)[-1]
                for a in node.names:
                    import_alias[a.asname or a.name] = (mod, a.name)

        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("_"):
                    flags = dep_flags(node.value, guard_groups)
                    if flags:
                        guard_groups[t.id] = flags

        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "include_router"
        ):
            call = node.value
            target = call.args[0] if call.args else None
            module = router_attr = None
            if isinstance(target, ast.Attribute):  # e.g. question.router
                base = target.value
                if isinstance(base, ast.Name) and base.id in import_alias:
                    module = import_alias[base.id][0]
                    router_attr = target.attr
            elif isinstance(target, ast.Name):  # e.g. multi_user_router
                mod, attr = import_alias.get(target.id, (None, None))
                module = mod
                router_attr = attr or "router"
            prefix = ""
            deps_node = None
            for kw in call.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = str(kw.value.value)
                elif kw.arg == "dependencies":
                    deps_node = kw.value
            if module and router_attr:
                includes.append(
                    Include(
                        module=module,
                        router_name=router_attr,
                        prefix=prefix,
                        flags=dep_flags(deps_node, guard_groups),
                        include_label=expr_label(deps_node) or "(none)",
                        line=node.lineno,
                    )
                )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods = []
            path = ""
            line = 0
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ALL_METHODS
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "app"
                ):
                    methods.append(dec.func.attr)
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        path = str(dec.args[0].value)
                    line = line or dec.lineno
            if methods:
                app_routes.append(AppRoute(methods=methods, path=path, line=line))

    guard_group_labels = {
        name: "+".join(sorted(flags)) for name, flags in guard_groups.items()
    }
    return includes, app_routes, guard_group_labels


# --------------------------------------------------------------------------
# Phase 2: router modules
# --------------------------------------------------------------------------
@dataclass
class Route:
    router_name: str
    method: str
    path: str
    line: int
    route_deps: set[str] = field(default_factory=set)
    route_dep_label: str = ""
    sig_deps: set[str] = field(default_factory=set)
    sig_dep_labels: list[str] = field(default_factory=list)
    body_markers: set[str] = field(default_factory=set)


@dataclass
class ModuleInfo:
    routers: dict[str, set[str]] = field(default_factory=dict)  # router name -> router-level flags
    router_dep_labels: dict[str, str] = field(default_factory=dict)
    routes: list[Route] = field(default_factory=list)
    guard_groups: dict[str, set[str]] = field(default_factory=dict)


BODY_MARKER_MAP = {
    "ws_require_auth": "ws-auth",
    "assert_learning_surface": "surface-assert",
    "_auth_device": "device-auth",
}


def parse_router_module(path: Path) -> ModuleInfo:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    info = ModuleInfo()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not (isinstance(node.value, ast.List) or isinstance(node.value, ast.Call)):
                continue
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                if isinstance(node.value, ast.Call) and (
                    call_name(node.value) == "APIRouter"
                ):
                    flags: set[str] = set()
                    label = ""
                    for kw in node.value.keywords:
                        if kw.arg == "dependencies":
                            flags = dep_flags(kw.value, info.guard_groups)
                            label = expr_label(kw.value)
                    info.routers[t.id] = flags
                    info.router_dep_labels[t.id] = label
                elif isinstance(node.value, ast.List):
                    flags = dep_flags(node.value, info.guard_groups)
                    if flags:
                        info.guard_groups[t.id] = flags

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method_path_pairs: list[tuple[str, str, int, ast.AST | None]] = []
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in ALL_METHODS
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id in info.routers
            ):
                route_path = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    route_path = str(dec.args[0].value)
                deps_node = None
                for kw in dec.keywords:
                    if kw.arg == "dependencies":
                        deps_node = kw.value
                method_path_pairs.append((dec.func.attr, route_path, dec.lineno, deps_node))
        if not method_path_pairs:
            continue
        sig_deps: set[str] = set()
        sig_labels: list[str] = []
        defaulted: list[tuple[ast.expr | None]] = []
        pos_args = node.args.args
        pos_defaults = node.args.defaults
        for arg, default in zip(pos_args[len(pos_args) - len(pos_defaults):], pos_defaults):
            defaulted.append(default)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            defaulted.append(default)
        for default in defaulted:
            if default is None or not isinstance(default, ast.Call):
                continue
            if call_name(default) == "Depends" and default.args:
                inner = default.args[0]
                if isinstance(inner, ast.Name) and (
                    inner.id in GUARD_DEP_NAMES
                    or inner.id in PARTNER_GUARDS
                    or inner.id in info.guard_groups
                ):
                    sig_deps |= dep_flags(default, info.guard_groups)
                    sig_labels.append(f"Depends({inner.id})")
        body_markers: set[str] = set()
        for sub in ast.walk(node):
            name = call_name(sub)
            if name and name in BODY_MARKER_MAP:
                body_markers.add(BODY_MARKER_MAP[name])

        for method, route_path, line, deps_node in method_path_pairs:
            info.routes.append(
                Route(
                    router_name=next(
                        d.func.value.id  # type: ignore[attr-defined]
                        for d in node.decorator_list
                        if isinstance(d, ast.Call)
                        and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ALL_METHODS
                        and isinstance(d.func.value, ast.Name)
                        and d.func.value.id in info.routers
                    ),
                    method=method,
                    path=route_path,
                    line=line,
                    route_deps=dep_flags(deps_node, info.guard_groups),
                    route_dep_label=expr_label(deps_node),
                    sig_deps=sig_deps,
                    sig_dep_labels=sig_labels,
                    body_markers=body_markers,
                )
            )
    return info


# --------------------------------------------------------------------------
# Phase 3: learning-surface map from auth.py
# --------------------------------------------------------------------------
@dataclass
class SurfaceMap:
    prefix_table: list[tuple[str, str]]
    kb_reads: set[str]
    settings_writes: set[tuple[str, str]]

    def surface_for(self, path: str, method: str) -> str:
        normalized = "/" + str(path or "").lstrip("/")
        for root, surface in self.prefix_table:
            if normalized == root or normalized.startswith(f"{root}/"):
                return surface
        if (
            method.upper() == "GET"
            and (
                normalized == "/api/knowledge-bases"
                or normalized.startswith("/api/knowledge-bases/")
            )
            and path in self.kb_reads
        ):
            return "reading"
        if path and (method.upper(), path) in self.settings_writes:
            return "chat"
        return ""


def parse_surface_map() -> SurfaceMap:
    tree = ast.parse(AUTH.read_text(encoding="utf-8"))
    kb_reads: set[str] = set()
    settings_writes: set[tuple[str, str]] = set()
    prefix_table: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.Set, ast.Call))
        ):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_LEARNER_KB_READ_ROUTES" in names:
                value = node.value
                if isinstance(value, ast.Call):
                    value = value.args[0] if value.args else None
                if isinstance(value, ast.Set):
                    for el in value.elts:
                        if isinstance(el, ast.Constant):
                            kb_reads.add(str(el.value))
            if "_LEARNER_SETTINGS_WRITE_ROUTES" in names:
                value = node.value
                if isinstance(value, ast.Call):
                    value = value.args[0] if value.args else None
                if isinstance(value, ast.Set):
                    for el in value.elts:
                        if (
                            isinstance(el, ast.Tuple)
                            and len(el.elts) == 2
                            and all(isinstance(e, ast.Constant) for e in el.elts)
                        ):
                            settings_writes.add(
                                (str(el.elts[0].value), str(el.elts[1].value))
                            )
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            # the prefix table loop inside _learning_surface_for_path
            pairs = [
                (e.elts[0].value, e.elts[1].value)
                for e in node.iter.elts
                if isinstance(e, ast.Tuple)
                and len(e.elts) == 2
                and all(isinstance(x, ast.Constant) for x in e.elts)
            ]
            if pairs and all(
                isinstance(r, str) and r.startswith("/api/") for r, _ in pairs
            ):
                prefix_table.extend(pairs)

    return SurfaceMap(
        prefix_table=prefix_table, kb_reads=kb_reads, settings_writes=settings_writes
    )


# --------------------------------------------------------------------------
# Phase 4: assemble matrix
# --------------------------------------------------------------------------
def scope_of(path: str) -> str:
    if path.startswith("/api"):
        return "api"
    if path.startswith("/files"):
        return "files"
    if path.startswith("/ws"):
        return "ws"
    return "app"


def main() -> int:
    includes, app_routes, guard_group_labels = parse_main()
    surface_map = parse_surface_map()

    module_infos: dict[str, ModuleInfo] = {}
    for mod_file in sorted(ROUTERS_DIR.glob("*.py")):
        if mod_file.name.startswith("_") or mod_file.name == "__init__.py":
            continue
        module_infos[mod_file.stem] = parse_router_module(mod_file)

    rows: list[dict] = []

    def add_row(**kw) -> None:
        rows.append(kw)

    for inc in includes:
        info = module_infos.get(inc.module)
        if info is None:
            add_row(
                scope=scope_of(inc.prefix), module=inc.module, router=inc.router_name,
                method="?", path=f"{inc.prefix}/*", src=f"deeptutor/api/main.py:{inc.line}",
                include_guard=inc.include_label, router_guard="", route_deps="",
                sig_deps="", body_auth="", effective_guard="ERROR-MODULE-NOT-FOUND",
                surface="", partner_access="", flags="INCLUDE_UNRESOLVED", public_context="",
            )
            continue
        router_flags = info.routers.get(inc.router_name, set())
        router_label = info.router_dep_labels.get(inc.router_name, "")
        for route in info.routes:
            if route.router_name != inc.router_name:
                continue
            full_path = inc.prefix + route.path
            flags = set(inc.flags) | router_flags | route.route_deps | route.sig_deps
            body = set(route.body_markers)
            if "ws-auth" in body:
                flags |= {"auth"}
            if "surface-assert" in body:
                flags |= {"surface"}
            partner = "yes" if "partner-access" in flags else ""
            flags.discard("partner-access")

            if "admin" in flags:
                guard = "admin"
            elif "surface" in flags:
                guard = "learning-surface"
            elif "auth" in flags:
                guard = "auth-only"
            elif "device-auth" in body:
                guard = "device-token"
            else:
                guard = "public"

            surface = surface_map.surface_for(full_path, route.method)

            out_flags: list[str] = []
            if guard == "public":
                if inc.module == "auth":
                    ctx = "auth-bootstrap (documented public)"
                elif inc.router_name == "public_router":
                    ctx = "public-ui-settings (documented public)"
                else:
                    ctx = "REVIEW"
                out_flags.append("NO_GUARD")
            else:
                ctx = ""
            if surface and "surface" not in flags and "admin" not in flags:
                out_flags.append("SURFACE_NO_SURFACE_GUARD")
            if "admin" in flags and surface:
                out_flags.append("ADMIN_OVER_DECLARED_SURFACE")
            if route.method == "websocket" and "surface" not in flags:
                out_flags.append("WS_NO_SURFACE_ENFORCEMENT")

            src = f"deeptutor/api/routers/{inc.module}.py:{route.line}"
            body_label = ",".join(sorted(body)) if body else ""
            add_row(
                scope=scope_of(full_path), module=inc.module, router=inc.router_name,
                method=route.method.upper(), path=full_path, src=src,
                include_guard=inc.include_label, router_guard=router_label,
                route_deps=route.route_dep_label,
                sig_deps=";".join(route.sig_dep_labels), body_auth=body_label,
                effective_guard=guard, surface=surface or "(none)",
                partner_access=partner, flags=";".join(out_flags), public_context=ctx,
            )

    for ar in app_routes:
        for m in ar.methods:
            full_path = ar.path
            add_row(
                scope=scope_of(full_path), module="(app)", router="app",
                method=m.upper(), path=full_path,
                src=f"deeptutor/api/main.py:{ar.line}",
                include_guard="(none)", router_guard="", route_deps="", sig_deps="",
                body_auth="", effective_guard="public", surface="(none)",
                partner_access="", flags="NO_GUARD", public_context="app-root-health",
            )

    # Coverage cross-checks -------------------------------------------------
    included_modules = {i.module for i in includes}
    modules_with_routers = {
        m for m, info in module_infos.items() if info.routers
    }
    never_included = sorted(modules_with_routers - included_modules)
    missing_routers = sorted(
        (i.module, i.router_name)
        for i in includes
        if i.module in module_infos
        and i.router_name not in module_infos[i.module].routers
    )
    routes_in_never_included = {
        m: len(module_infos[m].routes) for m in never_included
    }

    csv_path = Path(__file__).resolve().parent / "auth_matrix.csv"
    fieldnames = [
        "scope", "module", "router", "method", "path", "src", "include_guard",
        "router_guard", "route_deps", "sig_deps", "body_auth", "effective_guard",
        "surface", "partner_access", "flags", "public_context",
    ]
    rows.sort(key=lambda r: (r["scope"], r["module"], r["path"], r["method"]))
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary ---------------------------------------------------------------
    print(f"rows={len(rows)}")
    print("scope:", dict(Counter(r["scope"] for r in rows)))
    print("effective_guard:", dict(Counter(r["effective_guard"] for r in rows)))
    print("surface:", dict(Counter(r["surface"] for r in rows)))
    print(
        "guard_x_surface:",
        dict(Counter((r["effective_guard"], r["surface"]) for r in rows)),
    )
    flag_counts = Counter()
    for r in rows:
        for f in (r["flags"].split(";") if r["flags"] else []):
            flag_counts[f] += 1
    print("flags:", dict(flag_counts))
    print("modules_never_included:", never_included, routes_in_never_included)
    print("includes_missing_router:", missing_routers)
    print(f"csv={csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
