#!/usr/bin/env python3
"""Read-only SQLite query-plan inventory for the DeepTutor persistence surface.

Phases
  A  static AST extraction of SQL access points (execute/executemany/executescript)
     from the production ``deeptutor`` package.
  B  in-memory rebuild of every schema-owning module (real store constructors
     first, static DDL replay as fallback) and a union planning schema.
  C  EXPLAIN QUERY PLAN for every read/write access point against the union DB.
  D  deterministic flagging of full scans, missing indexes, temp B-tree sorts.
  E  JSON data + report.md + SHA256SUMS, byte-identical across reruns.

Usage
  python3 scan_sql_query_plans.py --repo /path/to/DeepTutor --out <evidence-dir> \
      --commit <sha> [--skip-imports]

No product code is modified; no real database file is opened. All rebuilds
happen in ``:memory:`` or a per-run temporary directory that is removed.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

SQL_METHODS = {"execute", "executemany", "executescript"}
EXCLUDE_SEGMENTS = {"tests", "test", "__pycache__", ".venv", "venv", "node_modules"}

READ_KEYWORDS = {"SELECT", "WITH"}
WRITE_KEYWORDS = {"INSERT", "REPLACE", "UPDATE", "DELETE"}

LARGE_TABLES = {
    "messages",
    "turns",
    "turn_events",
    "notebook_entries",
    "assessment_attempts",
    "practice_review_events",
    "reading_materials",
    "reading_turns",
    "llm_calls",
    "library_files",
    "handoff_records",
    "cron_jobs",
    "web_source_sync_jobs",
    "web_source_bilingual_pairings",
    "mastery_paths",
    "mastery_path_sessions",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

# Single-row / metadata lookup tables: a full scan is the whole point.
TINY_TABLES = {
    "reading_schema",
    "metadata",
    "cron_meta",
    "partner_runtime_status",
    "mastery_schema_migrations",
}


# ---------------------------------------------------------------------------
# Phase A: static extraction
# ---------------------------------------------------------------------------


def iter_targets(repo: Path) -> list[tuple[Path, str]]:
    targets = []
    for path in sorted(repo.rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        if not rel.startswith("deeptutor/"):
            continue
        segments = rel.split("/")
        if any(
            seg in EXCLUDE_SEGMENTS or (seg.startswith("test_") and seg.endswith(".py"))
            for seg in segments
        ):
            continue
        targets.append((path, rel))
    return targets


def collect_constant_assigns(tree: ast.Module) -> dict[str, str]:
    """Map simple ``NAME = "sql literal"`` assignments (module scope, first wins)."""
    assigns: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str) and target.id not in assigns:
                    assigns[target.id] = node.value.value
    return assigns


def split_script(script: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            text = buffer.strip()
            if text and not all(
                part.strip().startswith("--") or not part.strip()
                for part in [text]
            ):
                statements.append(text)
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    cleaned = []
    for stmt in statements:
        stripped = stmt.lstrip()
        if stripped.startswith("--"):
            # drop leading full-line comments but keep the statement body
            body = "\n".join(
                ln for ln in stmt.splitlines() if not ln.strip().startswith("--")
            ).strip()
            if body:
                cleaned.append(body)
        else:
            cleaned.append(stmt)
    return cleaned


def _flatten_str_expr(node: ast.AST, assigns: dict[str, str]) -> tuple[str, str, bool, str] | None:
    """Return (display, plannable, dynamic, note) for string-building expressions."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, node.value, False, "literal"
    if isinstance(node, ast.JoinedStr):
        display, plan, dynamic = [], [], False
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                display.append(value.value)
                plan.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                display.append("{?}")
                plan.append("?")
                dynamic = True
            else:
                display.append("{?}")
                plan.append("?")
                dynamic = True
        return "".join(display), "".join(plan), dynamic, "f-string"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_str_expr(node.left, assigns)
        right = _flatten_str_expr(node.right, assigns)
        if left and right:
            return (
                left[0] + right[0],
                left[1] + right[1],
                left[2] or right[2],
                "concat" if (left[2] or right[2]) else "literal",
            )
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, str)
        and node.args
        and isinstance(node.args[0], ast.List)
    ):
        sep = node.func.value.value
        display_parts, plan_parts, dynamic = [], [], False
        for element in node.args[0].elts:
            piece = _flatten_str_expr(element, assigns)
            if piece is None:
                return None
            display_parts.append(piece[0])
            plan_parts.append(piece[1])
            dynamic = dynamic or piece[2]
        return sep.join(display_parts), sep.join(plan_parts), dynamic, "join"
    if isinstance(node, ast.Name) and node.id in assigns:
        value = assigns[node.id]
        return value, value, False, f"const:{node.id}"
    return None


def statement_role(sql: str) -> str:
    stripped = sql.lstrip(" \t\r\n(;")
    match = re.match(
        r"(WITH|SELECT|INSERT|REPLACE|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|ATTACH|"
        r"DETACH|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|VACUUM|ANALYZE|REINDEX|EXPLAIN)\b",
        stripped,
        re.IGNORECASE,
    )
    keyword = match.group(1).upper() if match else "OTHER"
    if keyword in READ_KEYWORDS:
        return "read"
    if keyword in WRITE_KEYWORDS:
        return "write"
    return keyword.lower()


def collect_function_spans(tree: ast.Module) -> list[tuple[int, int, str]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name))
    return sorted(spans)


def enclosing_function(spans: list[tuple[int, int, str]], line: int) -> str:
    best = ""
    for start, end, name in spans:
        if start <= line <= end:
            best = name
    return best


def extract_access_points(repo: Path) -> tuple[list[dict], dict[str, int]]:
    access_points: list[dict] = []
    stats = {"files": 0, "call_sites": 0, "unextractable": 0, "statements": 0}
    for path, rel in iter_targets(repo):
        stats["files"] += 1
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        assigns = collect_constant_assigns(tree)
        spans = collect_function_spans(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in SQL_METHODS:
                continue
            if not node.args:
                continue
            stats["call_sites"] += 1
            flattened = _flatten_str_expr(node.args[0], assigns)
            if flattened is None:
                stats["unextractable"] += 1
                access_points.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "method": node.func.attr,
                        "role": "unknown",
                        "sql": "",
                        "sql_planned": None,
                        "dynamic": True,
                        "status": "unextractable",
                        "note": f"arg:{type(node.args[0]).__name__}",
                    }
                )
                continue
            display, plannable, dynamic, note = flattened
            method = node.func.attr
            pieces = split_script(plannable) if method == "executescript" else [plannable]
            display_pieces = split_script(display) if method == "executescript" else [display]
            for idx, piece in enumerate(pieces):
                stats["statements"] += 1
                display_piece = display_pieces[idx] if idx < len(display_pieces) else piece
                role = statement_role(piece)
                access_points.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "function": enclosing_function(spans, node.lineno),
                        "method": method,
                        "script_index": idx if method == "executescript" else None,
                        "role": role,
                        "sql": display_piece,
                        "sql_planned": piece if role in ("read", "write") else None,
                        "dynamic": dynamic,
                        "status": "extracted",
                        "note": note,
                    }
                )
    return access_points, stats


# ---------------------------------------------------------------------------
# Phase B: schema rebuild
# ---------------------------------------------------------------------------


def read_schema_objects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY rowid"
    ).fetchall()
    return [
        {"type": r[0], "name": r[1], "tbl_name": r[2], "sql": r[3]} for r in rows
    ]


def recipe_session_store(tmp: Path):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    SQLiteSessionStore(db_path=tmp / "chat_history.db")
    conn = sqlite3.connect(f"file:{tmp / 'chat_history.db'}?mode=ro", uri=True)
    return "import:SQLiteSessionStore(db_path=tmp)", conn


def recipe_learning_store(tmp: Path):
    from deeptutor.learning.storage import LearningStore

    store = LearningStore(root=tmp / "learning")
    del store
    conn = sqlite3.connect(f"file:{tmp / 'learning' / 'mastery.sqlite3'}?mode=ro", uri=True)
    return "import:LearningStore(root=tmp)", conn


def recipe_reading_catalog(tmp: Path):
    from deeptutor.reading.catalog_store import ReadingCatalogStore

    ReadingCatalogStore(root=tmp / "reading")
    conn = sqlite3.connect(f"file:{tmp / 'reading' / '_catalog.sqlite3'}?mode=ro", uri=True)
    return "import:ReadingCatalogStore(root=tmp)", conn


def recipe_marginnote_store(tmp: Path):
    from deeptutor.capabilities.marginnote4.store import MarginNoteStore

    MarginNoteStore(db_path=tmp / "marginnote.db")
    conn = sqlite3.connect(f"file:{tmp / 'marginnote.db'}?mode=ro", uri=True)
    return "import:MarginNoteStore(db_path=tmp)", conn


def recipe_cron_repository(tmp: Path):
    from deeptutor.services.cron.repository import SQLiteCronRepository

    SQLiteCronRepository(tmp / "cron.db")
    conn = sqlite3.connect(f"file:{tmp / 'cron.db'}?mode=ro", uri=True)
    return "import:SQLiteCronRepository(path=tmp)", conn


def recipe_web_source_repository(tmp: Path):
    from deeptutor.services.web_source.repository import SQLiteWebSourceSyncRepository

    SQLiteWebSourceSyncRepository(tmp / "web_source.db")
    conn = sqlite3.connect(f"file:{tmp / 'web_source.db'}?mode=ro", uri=True)
    return "import:SQLiteWebSourceSyncRepository(path=tmp)", conn


def recipe_file_library(tmp: Path):
    from deeptutor.services.storage.file_library import FileLibraryStore

    FileLibraryStore(db_path=tmp / "library.db", root=tmp / "library_files")
    conn = sqlite3.connect(f"file:{tmp / 'library.db'}?mode=ro", uri=True)
    return "import:FileLibraryStore(db_path=tmp, root=tmp)", conn


def recipe_task_board(tmp: Path):
    from deeptutor.services.task_board import TaskBoardStore

    store = TaskBoardStore(tmp / "task_board.db")
    connection = store._connect()  # schema is created lazily here in production
    connection.close()
    conn = sqlite3.connect(tmp / "task_board.db")
    return "import:TaskBoardStore._connect(path=tmp)", conn


def recipe_usage_ledger(tmp: Path):
    from deeptutor.services.llm.usage_ledger import record_call

    path = tmp / "usage.sqlite3"
    record_call(
        path,
        {
            "call_id": "scan-seed-0000",
            "provider": "scan",
            "model": "scan",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        started_at=0.0,
    )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return "import:usage_ledger.record_call(path=tmp)", conn


def recipe_partner_runtime_status(tmp: Path):
    from deeptutor.services.partners.runtime_status import PartnerRuntimeStatusRepository

    PartnerRuntimeStatusRepository(tmp / "partner_runtime.db")
    conn = sqlite3.connect(f"file:{tmp / 'partner_runtime.db'}?mode=ro", uri=True)
    return "import:PartnerRuntimeStatusRepository(path=tmp)", conn


def recipe_session_handoff(tmp: Path):
    from deeptutor.multi_user.session_handoff import SessionHandoffStore

    store = SessionHandoffStore(db_path=tmp / "session_handoff.db")
    connection = store._connect()  # schema is created lazily here in production
    store._initialize(connection)
    connection.close()
    conn = sqlite3.connect(tmp / "session_handoff.db")
    return "import:SessionHandoffStore._initialize(db_path=tmp)", conn


def recipe_workspace_catalog(tmp: Path, repo: Path):
    """WorkspaceCatalogMixin creates its tables inline; replay its two literals."""
    source = (repo / "deeptutor/services/workspace/catalog.py").read_text(encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    for match in re.finditer(
        r'CREATE TABLE IF NOT EXISTS \w+ \([^"]*?\)"', source, re.DOTALL
    ):
        ddl = match.group(0).rstrip('"')
        conn.execute(ddl)
    conn.commit()
    return "static:workspace/catalog.py inline DDL", conn


RECIPES = [
    ("services/session/sqlite_store.py", recipe_session_store),
    ("services/practice/storage.py", "covered-by:services/session/sqlite_store.py"),
    ("learning/storage.py", recipe_learning_store),
    ("reading/catalog_store.py", recipe_reading_catalog),
    ("capabilities/marginnote4/store.py", recipe_marginnote_store),
    ("services/cron/repository.py", recipe_cron_repository),
    ("services/web_source/repository.py", recipe_web_source_repository),
    ("services/storage/file_library.py", recipe_file_library),
    ("services/task_board.py", recipe_task_board),
    ("services/llm/usage_ledger.py", recipe_usage_ledger),
    ("services/partners/runtime_status.py", recipe_partner_runtime_status),
    ("multi_user/session_handoff.py", recipe_session_handoff),
    ("services/workspace/catalog.py", recipe_workspace_catalog),
]


def static_replay(repo: Path, rel: str) -> sqlite3.Connection:
    """Fallback: replay extracted DDL statements of one module in source order."""
    access_points, _ = extract_access_points(repo)
    conn = sqlite3.connect(":memory:")
    legacy_counter = 0
    target = f"deeptutor/{rel}"
    for point in access_points:
        if point["file"] != target:
            continue
        sql = point["sql_planned"] or point["sql"]
        role = point["role"]
        if role in ("read", "write", "pragma", "begin", "commit", "rollback", "unknown"):
            continue
        if role in ("create", "alter", "drop"):
            try:
                if role == "create" and re.search(r"CREATE TABLE (\w+_new)\b", sql, re.I):
                    new_name = re.search(r"CREATE TABLE (\w+_new)\b", sql, re.I).group(1)
                    base = re.sub(r"_new$", "", new_name)
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name=?", (base,)
                    ).fetchone()
                    if exists:
                        legacy_counter += 1
                        conn.execute(f"ALTER TABLE {base} RENAME TO {base}__legacy{legacy_counter}")
                        conn.execute(f"DROP TABLE {base}__legacy{legacy_counter}")
                    conn.execute(sql)
                    conn.execute(f"ALTER TABLE {new_name} RENAME TO {base}")
                else:
                    conn.execute(sql)
            except sqlite3.Error:
                continue
    conn.commit()
    return conn


def rebuild_schemas(repo: Path, skip_imports: bool) -> tuple[list[dict], list[dict]]:
    """Return (module_reports, schema_objects)."""
    module_reports: list[dict] = []
    schema_objects: list[dict] = []
    for rel, recipe in RECIPES:
        if isinstance(recipe, str):  # covered-by note
            module_reports.append({"module": rel, "method": recipe, "objects": 0})
            continue
        tmp = Path(tempfile.mkdtemp(prefix="dt-sqlplan-"))
        method = None
        conn = None
        error = None
        try:
            if skip_imports:
                raise RuntimeError("imports disabled via --skip-imports")
            if rel == "services/workspace/catalog.py":
                method, conn = recipe(tmp, repo)
            else:
                method, conn = recipe(tmp)
        except Exception as exc:  # noqa: BLE001 - record and fall back
            error = f"{type(exc).__name__}: {exc}"
            try:
                conn = static_replay(repo, rel)
                method = "static-replay"
            except Exception as exc2:  # noqa: BLE001
                module_reports.append(
                    {"module": rel, "method": "failed", "error": error, "error2": str(exc2)}
                )
                conn = None
        finally:
            pass
        if conn is None:
            tmp_cleanup(tmp)
            continue
        objects = read_schema_objects(conn)
        conn.close()
        module_reports.append(
            {
                "module": rel,
                "method": method,
                "error": error,
                "objects": len(objects),
                "tables": sorted(o["name"] for o in objects if o["type"] == "table"),
                "indexes": sorted(o["name"] for o in objects if o["type"] == "index"),
                "triggers": sorted(o["name"] for o in objects if o["type"] == "trigger"),
                "views": sorted(o["name"] for o in objects if o["type"] == "view"),
            }
        )
        for obj in objects:
            obj["source_module"] = rel
            schema_objects.append(obj)
        tmp_cleanup(tmp)
    return module_reports, schema_objects


def tmp_cleanup(tmp: Path) -> None:
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


def build_union_schema(
    schema_objects: list[dict], access_points: list[dict] | None = None
) -> tuple[sqlite3.Connection, list[dict]]:
    union = sqlite3.connect(":memory:")
    collisions: list[dict] = []
    seen: dict[str, str] = {}

    def norm(sql: str | None) -> str:
        return re.sub(r"\s+", " ", (sql or "").strip().lower())

    order = {"table": 0, "index": 1, "view": 2, "trigger": 3}
    for obj in sorted(schema_objects, key=lambda o: (order.get(o["type"], 9), o["name"])):
        name = obj["name"]
        if name in seen:
            if norm(seen[name]) != norm(obj["sql"]):
                collisions.append(
                    {
                        "name": name,
                        "kept_from": next(
                            o["source_module"]
                            for o in schema_objects
                            if o["name"] == name
                        ),
                        "rejected_from": obj["source_module"],
                    }
                )
            continue
        try:
            if obj["type"] == "table":
                union.execute(obj["sql"])
            else:
                union.executescript(f"{obj['sql']};")
        except sqlite3.Error as exc:
            collisions.append(
                {
                    "name": name,
                    "kept_from": obj["source_module"],
                    "error": str(exc),
                }
            )
            continue
        seen[name] = obj["sql"] or ""
    union.commit()

    # Runtime-created tables referenced by extracted DDL but absent from the
    # rebuilt stores: CREATE TEMP TABLE scratch tables and migration *_new
    # tables. Adding them raises plan coverage without inventing schema.
    runtime_created = []
    if access_points:
        for point in access_points:
            if point.get("role") != "create" or point.get("dynamic"):
                continue
            match = re.search(
                r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r"(?:main\.)?(\w+)",
                point.get("sql", ""),
                re.IGNORECASE,
            )
            if not match:
                continue
            name = match.group(1)
            if name in seen:
                continue
            if not (name.endswith("_new") or "temp" in point.get("sql", "").lower()):
                continue
            try:
                union.execute(point["sql"])
                seen[name] = point["sql"]
                runtime_created.append(name)
            except sqlite3.Error as exc:
                collisions.append({"name": name, "error": str(exc), "runtime": True})

    # session_transfer plans against an attached "target" database; mirror the
    # base tables there so those access points can be planned too.
    try:
        union.execute("ATTACH DATABASE ':memory:' AS target")
        for obj in schema_objects:
            if obj["type"] != "table":
                continue
            sql = re.sub(
                r"\bCREATE\s+TABLE\s+",
                "CREATE TABLE IF NOT EXISTS target.",
                obj["sql"],
                count=1,
                flags=re.IGNORECASE,
            )
            try:
                union.execute(sql)
            except sqlite3.Error:
                pass
        union.commit()
    except sqlite3.Error:
        pass
    return union, collisions


# ---------------------------------------------------------------------------
# Phase C+D: planning and flagging
# ---------------------------------------------------------------------------


def plan_statement(
    union: sqlite3.Connection, sql: str
) -> tuple[list[str] | None, str | None, str | None]:
    """Return (plan_rows, error, error_kind)."""
    nparams = 0
    for attempt in range(2):
        try:
            if attempt == 0:
                rows = union.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
            else:
                # programming error told us the exact placeholder count
                rows = union.execute(f"EXPLAIN QUERY PLAN {sql}", [None] * nparams).fetchall()
            return [row[3] for row in rows], None, None
        except sqlite3.ProgrammingError as exc:
            message = str(exc)
            match = re.search(r"uses (\d+)", message)
            if match and attempt == 0:
                nparams = int(match.group(1))
                continue
            return None, message, "bindings"
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if 'near "?"' in message:
                return None, message, "dynamic-identifier"
            return None, message, "operational"
        except sqlite3.Error as exc:
            return None, str(exc), "other"
    return None, "unreachable", "other"


def tables_in(sql: str, known_tables: list[str]) -> list[str]:
    found = []
    lowered = sql.lower()
    for table in sorted(known_tables, key=len, reverse=True):
        if re.search(rf"\b{re.escape(table.lower())}\b", lowered):
            found.append(table)
    return found


def has_where(sql: str) -> bool:
    return re.search(r"\bWHERE\b", sql, re.IGNORECASE) is not None


def flag_plan(role: str, sql: str, plan: list[str], tables: list[str]) -> list[dict]:
    flags = []
    big_hit = [t for t in tables if t in LARGE_TABLES]
    # sqlite_master probes are catalog lookups on a tiny virtual table —
    # scanning them is idiomatic, not a gap.
    catalog_probe = "sqlite_master" in sql.lower() or "sqlite_temp_master" in sql.lower()
    for detail in plan:
        if "USING TEMP B-TREE FOR ORDER BY" in detail:
            flags.append(
                {
                    "flag": "temp-btree-order-by",
                    "detail": detail,
                    "severity": "high" if big_hit else "medium",
                }
            )
        elif "USING TEMP B-TREE FOR GROUP BY" in detail:
            flags.append({"flag": "temp-btree-group-by", "detail": detail, "severity": "medium"})
        elif re.search(r"\bSCAN\b", detail) and "COVERING INDEX" not in detail:
            if re.match(r"SCAN \(", detail):
                # materialization of a CTE/subquery — inherent to window
                # functions, not an index gap
                flags.append({"flag": "scan-subquery-materialize", "detail": detail, "severity": "info"})
                continue
            if "SCAN CONSTANT ROW" in detail:
                flags.append({"flag": "constant-row", "detail": detail, "severity": "info"})
                continue
            if catalog_probe:
                flags.append({"flag": "catalog-probe", "detail": detail, "severity": "info"})
                continue
            scan_table = re.search(r"SCAN ([\w\"$]+)", detail)
            table = scan_table.group(1).strip('"') if scan_table else (tables[0] if tables else "?")
            using_index = "USING INDEX" in detail
            if using_index:
                # index-order walk (partial index or ORDER BY satisfied by
                # index); not an unindexed pile-of-pages scan.
                if has_where(sql):
                    severity = "low"
                    flag = "index-scan-filter-not-covered"
                else:
                    severity = "info"
                    flag = "index-scan"
            elif has_where(sql):
                if table in TINY_TABLES:
                    severity = "low"
                else:
                    severity = "high" if table in LARGE_TABLES else "medium"
                flag = "full-scan-with-filter"
            elif big_hit:
                severity = "medium"
                flag = "full-scan-large-table"
            else:
                severity = "info"
                flag = "full-scan"
            flags.append({"flag": flag, "detail": detail, "severity": severity})
        elif re.search(r"\bSCAN\b.*COVERING INDEX", detail):
            flags.append(
                {
                    "flag": "covering-index-scan",
                    "detail": detail,
                    "severity": "low" if has_where(sql) else "info",
                }
            )
        elif "MULTI-INDEX OR" in detail:
            flags.append({"flag": "multi-index-or", "detail": detail, "severity": "info"})
    return flags


def suggestion_for(
    flags: list[dict], tables: list[str], table_indexes: dict[str, list[str]], sql: str = ""
) -> str:
    primary = []
    kinds = {f["flag"] for f in flags}
    idx_note = ""
    scanned = [
        m.group(1).strip('"')
        for m in (re.search(r"SCAN ([\w\"$]+)", f["detail"]) for f in flags)
        if m and not m.group(1).startswith("(")
    ]
    cite_table = next((t for t in scanned if t in table_indexes or t in LARGE_TABLES), None)
    if cite_table is None and tables:
        cite_table = tables[0]
    if cite_table:
        existing = table_indexes.get(cite_table, [])
        idx_note = (
            f"；表 {cite_table} 现有索引: {', '.join(existing) if existing else '无'}"
        )
    if "full-scan-with-filter" in kinds:
        if re.search(r"\bLIKE\b", sql, re.IGNORECASE):
            primary.append(
                "含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；"
                "如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描"
            )
        else:
            primary.append("过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受" + idx_note)
    if "temp-btree-order-by" in kinds:
        primary.append("排序走临时 B-tree：考虑 (过滤列, 排序列) 复合索引让 ORDER BY 落索引，或收紧结果集/加 LIMIT")
    if "temp-btree-group-by" in kinds:
        primary.append("GROUP BY 走临时 B-tree：考虑按分组列建索引")
    if "full-scan-large-table" in kinds and not primary:
        primary.append("大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引")
    if "index-scan-filter-not-covered" in kinds and not primary:
        primary.append("沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引")
    if "covering-index-scan" in kinds and not primary:
        primary.append("全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影")
    return "；".join(primary) if primary else "信息项，无需处理"


# ---------------------------------------------------------------------------
# Phase E: outputs
# ---------------------------------------------------------------------------


def dump_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1, default=str) + "\n",
        encoding="utf-8",
    )


def excerpt(sql: str, limit: int = 160) -> str:
    one = " ".join(sql.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--skip-imports", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    out = args.out.resolve()
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Import provenance: the repo under scan must be the deeptutor we import.
    # A stale installed copy elsewhere would silently rebuild an old schema.
    repo_str = str(repo)
    while sys.path and sys.path[0] in ("", str(Path.cwd())):
        sys.path.pop(0)
    sys.path.insert(0, repo_str)
    import deeptutor  # noqa: PLC0415

    deeptutor_origin = Path(deeptutor.__file__).resolve()
    repo_origin = (repo / "deeptutor" / "__init__.py").resolve()
    if deeptutor_origin != repo_origin:
        print(
            f"FATAL: importing deeptutor from {deeptutor_origin}, not the repo under scan "
            f"({repo_origin}); refusing to produce misleading evidence",
            file=sys.stderr,
        )
        return 2

    # Phase A
    access_points, extraction_stats = extract_access_points(repo)

    # Phase B
    module_reports, schema_objects = rebuild_schemas(repo, args.skip_imports)
    union, collisions = build_union_schema(schema_objects, access_points)
    known_tables = [
        o["name"] for o in schema_objects if o["type"] == "table"
    ]
    table_indexes: dict[str, list[str]] = {}
    for obj in schema_objects:
        if obj["type"] == "index":
            table_indexes.setdefault(obj["tbl_name"], []).append(obj["name"])

    # Phase C+D
    planned = 0
    failed = 0
    skipped_non_sql = 0
    for point in access_points:
        if point["status"] != "extracted":
            continue
        if point["role"] not in ("read", "write"):
            skipped_non_sql += 1
            point["status"] = "not-planned"
            point["plan_status"] = "skipped"
            continue
        sql = point["sql_planned"]
        plan, error, error_kind = plan_statement(union, sql)
        if plan is None:
            failed += 1
            point["plan_status"] = "failed"
            point["plan_error"] = error
            point["plan_error_kind"] = error_kind
            point["plan"] = []
            point["flags"] = []
            continue
        planned += 1
        point["plan_status"] = "ok"
        point["plan_error"] = None
        point["plan"] = plan
        point["tables"] = tables_in(sql, known_tables)
        point["flags"] = flag_plan(point["role"], sql, plan, point["tables"])

    # Phase E
    findings = []
    for point in access_points:
        if point.get("plan_status") != "ok":
            continue
        gaps = [f for f in point["flags"] if f["severity"] in ("high", "medium", "low")]
        if not gaps:
            continue
        severity = min((g["severity"] for g in gaps), key=lambda s: SEVERITY_ORDER[s])
        findings.append(
            {
                "severity": severity,
                "file": point["file"],
                "line": point["line"],
                "function": point.get("function", ""),
                "role": point["role"],
                "tables": point.get("tables", []),
                "sql_excerpt": excerpt(point["sql"]),
                "plan_excerpts": [g["detail"] for g in gaps],
                "flags": sorted({g["flag"] for g in gaps}),
                "suggestion": suggestion_for(
                    gaps, point.get("tables", []), table_indexes, point["sql"]
                ),
            }
        )
    findings.sort(
        key=lambda f: (
            SEVERITY_ORDER[f["severity"]],
            f["file"],
            f["line"],
        )
    )

    summary = {
        "commit": args.commit,
        "sqlite_version": sqlite3.sqlite_version,
        "python": sys.version.split()[0],
        "deeptutor_imported_from": str(deeptutor_origin),
        "extraction": extraction_stats,
        "access_points_total": len(access_points),
        "planned_ok": planned,
        "planned_failed": failed,
        "not_planned_roles": skipped_non_sql,
        "unextractable": extraction_stats["unextractable"],
        "schema_modules": len(module_reports),
        "schema_tables": len(known_tables),
        "schema_indexes": sum(len(v) for v in table_indexes.values()),
        "schema_triggers": sum(
            1 for o in schema_objects if o["type"] == "trigger"
        ),
        "schema_views": sum(1 for o in schema_objects if o["type"] == "view"),
        "collisions": len(collisions),
        "findings": {
            sev: sum(1 for f in findings if f["severity"] == sev)
            for sev in ("high", "medium", "low")
        },
    }

    dump_json(data_dir / "access_points.json", access_points)
    dump_json(data_dir / "schema_modules.json", module_reports)
    dump_json(
        data_dir / "schema_objects.json",
        [
            {k: v for k, v in obj.items()}
            for obj in sorted(schema_objects, key=lambda o: (o["type"], o["name"]))
        ],
    )
    dump_json(data_dir / "collisions.json", collisions)
    dump_json(data_dir / "findings.json", findings)
    dump_json(data_dir / "summary.json", summary)

    write_report(out / "report.md", summary, module_reports, findings, access_points, args)

    # SHA256SUMS over everything except the sums file itself
    import hashlib as _h

    lines = []
    for path in sorted(out.rglob("*")):
        if (
            path.is_file()
            and path.name != "SHA256SUMS"
            and "__pycache__" not in path.parts
        ):
            digest = _h.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(out).as_posix()}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def write_report(
    out_path: Path,
    summary: dict,
    module_reports: list[dict],
    findings: list[dict],
    access_points: list[dict],
    args,
) -> None:
    lines = []
    lines.append("# SQLite 查询计划与索引缺口清点（EXPLAIN QUERY PLAN）")
    lines.append("")
    lines.append(f"- 源码版本: `{args.commit}`（origin/main，read-only 扫描）")
    lines.append(f"- SQLite 版本: {summary['sqlite_version']} / Python {summary['python']}")
    lines.append("- 轴线: 读路径与查询计划（与 scan-persistence 写入/原子性轴、fix-storage-write-fsync 写路径轴去重，不重复覆盖）")
    lines.append("")
    lines.append("## 口径（方法）")
    lines.append("")
    lines.append("1. **访问点提取**：AST 静态解析 `deeptutor/` 全部生产代码（排除 tests），")
    lines.append("   抓取 `execute` / `executemany` / `executescript` 调用中的 SQL 字面量、")
    lines.append("   f-string（插值规范化为 `?`）、字符串拼接与 join；`executescript` 按完整语句切分。")
    lines.append("2. **schema 重建**：优先用各模块真实 store 构造器在临时目录/内存库中初始化")
    lines.append("   （含全部 migration 与 trigger），失败时回退为源码 DDL 静态重放；")
    lines.append("   再合并为一张 union 规划库（同名同构去重，冲突记录在 collisions.json）。")
    lines.append("3. **计划采集**：对全部 read/write 访问点执行 `EXPLAIN QUERY PLAN`")
    lines.append("   （参数占位符不绑定，不影响结构化计划）；不连任何真实数据库。")
    lines.append("4. **缺口判定**：裸 `SCAN`（不带 USING INDEX/COVERING INDEX）= 全表扫描；")
    lines.append("   `SCAN … USING INDEX` = 索引序扫描（过滤列不在索引内，降级为 low）；")
    lines.append("   `USING TEMP B-TREE` = 大结果排序/分组；结合 WHERE 存在性与表规模分级（high/medium/low/info）。")
    lines.append("")
    lines.append("## 覆盖统计")
    lines.append("")
    lines.append(f"- 扫描文件数: {summary['extraction']['files']}；SQL 调用点: {summary['extraction']['call_sites']}；")
    lines.append(f"  SQL 语句: {summary['extraction']['statements']}；无法静态提取: {summary['unextractable']}")
    lines.append(f"- 访问点合计: {summary['access_points_total']} = 计划成功 {summary['planned_ok']}")
    lines.append(f"  + 计划失败 {summary['planned_failed']} + 非查询/DDL/PRAGMA 跳过 {summary['not_planned_roles']}")
    lines.append(f"- schema 模块: {summary['schema_modules']}；表: {summary['schema_tables']}；")
    lines.append(f"  索引: {summary['schema_indexes']}；触发器: {summary['schema_triggers']}；视图: {summary['schema_views']}")
    lines.append("")
    lines.append("### Schema 模块明细")
    lines.append("")
    lines.append("| 模块 | 重建方式 | 表 | 索引 | 触发器 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for mod in module_reports:
        lines.append(
            f"| `{mod['module']}` | {mod.get('method', '?')} | "
            f"{len(mod.get('tables', []))} | {len(mod.get('indexes', []))} | "
            f"{len(mod.get('triggers', []))} |"
        )
    lines.append("")
    lines.append("## 缺口清单")
    lines.append("")
    if not findings:
        lines.append("（无）")
    for idx, finding in enumerate(findings, 1):
        fn = f"，函数 `{finding['function']}`" if finding.get("function") else ""
        one_shot = "（迁移/一次性路径）" if finding.get("function", "").startswith("_migrate") else ""
        lines.append(
            f"{idx}. **[{finding['severity'].upper()}]** `{finding['file']}:{finding['line']}`"
            f"（{finding['role']}，表: {', '.join(finding['tables']) or '?'}{fn}）{one_shot}"
        )
        lines.append(f"   - SQL: `{finding['sql_excerpt']}`")
        for detail in finding["plan_excerpts"]:
            lines.append(f"   - 计划: {detail}")
        lines.append(f"   - 标记: {', '.join(finding['flags'])}")
        lines.append(f"   - 建议: {finding['suggestion']}")
    lines.append("")
    lines.append("## Top 缺口")
    lines.append("")
    top = [f for f in findings if f["severity"] == "high"][:8]
    if not top:
        top = findings[:8]
    for idx, finding in enumerate(top, 1):
        lines.append(
            f"{idx}. `{finding['file']}:{finding['line']}`"
            f"（`{finding.get('function', '')}`） — "
            f"{', '.join(finding['flags'])}（表: {', '.join(finding['tables']) or '?'}）"
        )
    lines.append("")
    lines.append("### 标记说明")
    lines.append("")
    lines.append("| 标记 | 含义 | 默认级别 |")
    lines.append("| --- | --- | --- |")
    lines.append("| full-scan-with-filter | 裸全表扫描且带 WHERE 过滤（缺索引） | 大表 high / 小表 medium |")
    lines.append("| full-scan-large-table | 大表无过滤全扫 | medium |")
    lines.append("| temp-btree-order-by | ORDER BY 走临时 B-tree（大结果排序） | 大表 high / 其余 medium |")
    lines.append("| temp-btree-group-by | GROUP BY 走临时 B-tree | medium |")
    lines.append("| index-scan-filter-not-covered | 沿索引序扫描后再过滤（非堆扫） | low |")
    lines.append("| covering-index-scan | 全量扫覆盖索引 | low/info |")
    lines.append("| scan-subquery-materialize / catalog-probe / index-scan / full-scan / multi-index-or | 信息项 | info |")
    lines.append("")
    lines.append("注：函数名以 `_migrate` 开头的访问点位于 schema 迁移路径，通常一次性执行，")
    lines.append("清点中仍列出但优先级可下调。")
    lines.append("")
    lines.append("## 去重边界")
    lines.append("")
    lines.append("- `scan-persistence`：写持久化/原子性轴（WAL、fsync、事务边界）— 本卡不覆盖。")
    lines.append("- `test-sqlite-store`：单模块行为测试 — 本卡为跨模块只读清点。")
    lines.append("- `fix-storage-write-fsync`：写路径修复 — 本卡不改代码。")
    lines.append("- 本卡输出仅为查询计划与索引缺口清单，不含任何 schema 变更。")
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "python3 evidence/scan-sql-query-plans-20261006/scripts/scan_sql_query_plans.py \\"
    )
    lines.append("  --repo . --commit <sha> \\")
    lines.append("  --out evidence/scan-sql-query-plans-20261006")
    lines.append("shasum -a 256 -c evidence/scan-sql-query-plans-20261006/SHA256SUMS")
    lines.append("```")
    lines.append("")
    lines.append(
        "重跑输出逐字节一致（同一 checkout、同一 SQLite 版本下哈希自证）；"
        "报告与数据不含时间戳。"
    )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
