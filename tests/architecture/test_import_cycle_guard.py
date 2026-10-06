"""Import-graph cycle guard for the Python sources.

A 2026-10-05 AST scan of ``deeptutor``/``deeptutor_cli``/``scripts`` found no
module-level import cycle, but several strongly connected components (SCCs)
whose cycle edges exist only as function-level (lazy) imports: the modules
are mutually reachable at runtime, yet importing either side first still
works. Every one of those edges is a tripwire — lift it to module level and
the import graph gains its first true cycle, raising ``ImportError`` at
import time.

Two invariants are pinned here:

1. ``test_no_module_level_import_cycles`` — the module-level import graph is
   acyclic. This is the guard that turns red the moment a masked lazy edge
   is lifted (or any new module-level cycle appears).
2. ``test_runtime_scc_set_unchanged`` — the set of runtime (lazy-masked)
   SCCs does not grow: five small SCCs are pinned by exact membership and
   the one large SCC by size plus its representative-cycle members. Any
   drift — a new cycle, a merge, an SCC absorbing another module — fails and
   must be reviewed before the baseline is updated on purpose.

The scan walks the same roots and resolves imports with the same rules as
the original evidence run (``evidence/import-cycles-20261005`` on the
``scan/import-cycles-20261005`` branch): only intra-repo edges, submodules
preferred over parent packages, ``TYPE_CHECKING`` blocks counted as lazy,
``if __name__ == "__main__"`` blocks ignored, "module level" wins over
"lazy" when a pair is imported both ways.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("deeptutor", "deeptutor_cli", "scripts")

# Baseline after decoupling learning.models ⇄ learning.pending (2026-10-06):
# the former two-module SCC is gone, the remaining five small SCCs are pinned
# by exact membership.
PINNED_SCCS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset(
            {
                "deeptutor.book.blocks.animation",
                "deeptutor.book.blocks.base",
                "deeptutor.book.blocks.callout",
                "deeptutor.book.blocks.code",
                "deeptutor.book.blocks.concept_graph",
                "deeptutor.book.blocks.deep_dive",
                "deeptutor.book.blocks.figure",
                "deeptutor.book.blocks.flash_cards",
                "deeptutor.book.blocks.interactive",
                "deeptutor.book.blocks.quiz",
                "deeptutor.book.blocks.section",
                "deeptutor.book.blocks.text",
                "deeptutor.book.blocks.timeline",
                "deeptutor.book.blocks.user_note",
            }
        ),
        frozenset(
            {
                "deeptutor.services.rag.eval.report",
                "deeptutor.services.rag.eval.runner",
            }
        ),
        frozenset(
            {
                "deeptutor.services.web_source.scheduler",
                "deeptutor.services.web_source.sync",
            }
        ),
        frozenset(
            {
                "deeptutor.agents.loop.agent_loop",
                "deeptutor.agents.loop.pipeline",
            }
        ),
        frozenset(
            {
                "deeptutor.textbook_struct.chapter_rebuild",
                "deeptutor.textbook_struct.page_headers",
            }
        ),
    }
)

# The one very large runtime SCC (services/session, partners, learning, …) is
# pinned by size and by the modules on its representative cycle, so neither a
# new member sneaking in nor a silent reshape can pass unnoticed.
LARGE_SCC_SIZE = 303
LARGE_SCC_CORE = frozenset(
    {
        "deeptutor.agents._shared.tool_composition",
        "deeptutor.services.session",
        "deeptutor.services.session.turn_runtime",
        "deeptutor.services.session._turn_runtime_shared",
        "deeptutor.learning.topic_materials",
        "deeptutor.services.session.source_inventory",
        "deeptutor.services.partners",
        "deeptutor.services.partners.runtime",
    }
)


def _collect_index() -> dict[str, str]:
    """Map every scanned module's dotted name to its repo-relative path."""
    index: dict[str, str] = {}
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            parts = path.relative_to(REPO_ROOT).parts
            if "__pycache__" in parts:
                continue
            name = parts[-1]
            if "tests" in parts or "testing" in parts:
                continue
            if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
                continue
            dotted = ".".join(parts[:-1] + (name[:-3],))
            if dotted.endswith(".__init__"):
                dotted = dotted[: -len(".__init__")]
            index[dotted] = "/".join(parts)
    return index


def _import_edges() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (module-level graph, any-level graph) over intra-repo imports."""
    index = _collect_index()

    edges: dict[str, dict[str, str]] = {}

    def add_edge(src: str, dst: str, lazy: bool) -> None:
        if dst == src:
            return
        current = edges.setdefault(src, {}).get(dst)
        # "module level" dominates "lazy": a pair imported both ways is a
        # module-level edge, matching the original scan.
        if current is None or (current == "lazy" and not lazy):
            edges[src][dst] = "top" if not lazy else "lazy"

    def resolve(dotted: str, node: ast.Import | ast.ImportFrom, is_package: bool) -> list[str]:
        base = dotted.split(".") if is_package else dotted.split(".")[:-1]
        targets: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in index:
                    targets.append(alias.name)
                    continue
                parts = alias.name.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    cand = ".".join(parts[:i])
                    if cand in index:
                        targets.append(cand)
                        break
            return targets
        level = node.level
        if level == 0:
            resolved = node.module or ""
        else:
            pkg = list(base)
            if level > len(pkg):
                return targets
            pkg = pkg[: len(pkg) - (level - 1)]
            resolved = ".".join(pkg + ([node.module] if node.module else []))
        if node.module == "" and level > 0:
            resolved = ".".join(base)
        elif resolved not in index:
            parts = resolved.split(".")
            resolved = ""
            for i in range(len(parts) - 1, 0, -1):
                cand = ".".join(parts[:i])
                if cand in index:
                    resolved = cand
                    break
        for alias in node.names:
            name = alias.name
            if name == "*":
                if resolved in index:
                    targets.append(resolved)
                continue
            sub = f"{resolved}.{name}" if resolved else name
            if sub in index:
                targets.append(sub)
            elif resolved in index:
                targets.append(resolved)
            else:
                parts = sub.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    cand = ".".join(parts[:i])
                    if cand in index:
                        targets.append(cand)
                        break
        return targets

    def visit(
        node: ast.AST,
        dotted: str,
        rel: str,
        func_depth: int,
        type_checking_depth: int,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, dotted, rel, func_depth + 1, type_checking_depth)
                continue
            if isinstance(child, ast.If):
                if _is_main_guard(child):
                    continue  # never executes at import time
                next_tc = type_checking_depth + (1 if _is_type_checking(child) else 0)
                visit(child, dotted, rel, func_depth, next_tc)
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                lazy = func_depth > 0 or type_checking_depth > 0
                for target in resolve(dotted, child, rel.endswith("__init__.py")):
                    if target in index:
                        add_edge(dotted, target, lazy)
                continue
            visit(child, dotted, rel, func_depth, type_checking_depth)

    for dotted, rel in sorted(index.items()):
        tree = ast.parse((REPO_ROOT / rel).read_bytes(), filename=rel)
        visit(tree, dotted, rel, 0, 0)

    top = {src: {dst for dst, kind in dsts.items() if kind == "top"} for src, dsts in edges.items()}
    every = {src: set(dsts) for src, dsts in edges.items()}
    return top, every


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    if isinstance(test, ast.BoolOp):
        return any(
            (isinstance(v, ast.Name) and v.id == "TYPE_CHECKING")
            or (isinstance(v, ast.Attribute) and v.attr == "TYPE_CHECKING")
            for v in test.values
        )
    return False


def _is_main_guard(node: ast.If) -> bool:
    return isinstance(node.test, ast.Compare) and "__name__" in ast.unparse(node.test)


def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    components: list[list[str]] = []
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(sorted(graph.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            for succ in successors:
                if succ not in index:
                    index[succ] = low[succ] = counter
                    counter += 1
                    stack.append(succ)
                    on_stack.add(succ)
                    work.append((succ, iter(sorted(graph.get(succ, ())))))
                    break
                if succ in on_stack:
                    low[node] = min(low[node], index[succ])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(component)
    return components


@lru_cache(maxsize=1)
def _graphs() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    return _import_edges()


def test_no_module_level_import_cycles() -> None:
    top, _ = _graphs()
    cycles = [c for c in _tarjan_scc(top) if len(c) > 1]
    assert not cycles, (
        "module-level import cycle(s) found: "
        f"{sorted(sorted(c) for c in cycles)}. A function-level import was "
        "likely lifted to module level (or a new module-level cycle added); "
        "importing these modules would now raise ImportError. Keep the edge "
        "lazy, invert the dependency, or share a leaf module instead."
    )


def test_runtime_scc_set_unchanged() -> None:
    _, every = _graphs()
    actual = {frozenset(c) for c in _tarjan_scc(every) if len(c) > 1}

    missing = PINNED_SCCS - actual
    assert not missing, (
        "pinned runtime cycle(s) changed: "
        f"{sorted(sorted(c) for c in missing)}. Review the diff for new or "
        "removed imports inside these modules, then update the baseline only "
        "with justification."
    )

    unknown = actual - PINNED_SCCS
    large = {c for c in unknown if len(c) == LARGE_SCC_SIZE and LARGE_SCC_CORE <= c}
    unexpected = unknown - large
    assert not unexpected, (
        "new runtime import cycle(s) found: "
        f"{sorted(sorted(c) for c in unexpected)}. A lazy edge was likely "
        "introduced or modules merged into a cycle; break the cycle (leaf "
        "module, dependency inversion, or TYPE_CHECKING) instead of "
        "extending the baseline."
    )
    assert len(large) == 1, (
        f"expected exactly one large runtime SCC of size {LARGE_SCC_SIZE} "
        f"containing its representative-cycle modules, got: "
        f"{sorted((sorted(c), len(c)) for c in large)}. The large SCC "
        "reshaped — review before updating LARGE_SCC_SIZE/LARGE_SCC_CORE."
    )
