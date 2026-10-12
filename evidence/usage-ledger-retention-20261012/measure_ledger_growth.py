"""Offline growth/retention probe for the LLM usage ledger.

Reproduce: PYTHONPATH=<repo root> python evidence/usage-ledger-retention-20261012/measure_ledger_growth.py

Uses throwaway temp DBs and synthetic numeric records only. No service,
network or LLM access. Exercises the real write path (usage_ledger.record_call)
and the real read path (usage_ledger.usage_records).
"""

from __future__ import annotations

import json
import resource
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


def synth_record(i: int) -> dict:
    counts = {
        "prompt_tokens": 5231,
        "completion_tokens": 842,
        "total_tokens": 6073,
        "cache_read_input_tokens": 4096,
        "cache_creation_input_tokens": 512,
        "reasoning_tokens": 128,
    }
    return {
        "call_id": "%032x" % i,
        **counts,
        "model": "gpt-5.3-flash",
        "provider": "openai",
        "status": "completed",
        "estimated": False,
        "duration_seconds": 12.3456,
        "ttft_seconds": 0.4321,
        "generation_seconds": 11.2345,
        "tokens_per_second": 74.96,
        "cache_hit_rate": 0.783,
    }


def main(n: int = 5000, bulk_n: int = 100_000) -> None:
    from deeptutor.services.llm import usage_ledger

    tmp = Path(tempfile.mkdtemp())
    db = tmp / "usage.sqlite3"

    t0 = time.perf_counter()
    for i in range(n):
        usage_ledger.record_call(
            db,
            synth_record(i),
            started_at=1_700_000_000 + i,
            session_id="s-%04d" % (i % 40),
            turn_id="t%032x" % i,
            source="learning",
        )
    dt = time.perf_counter() - t0
    size = db.stat().st_size
    print(f"real-path writes: rows={n} total_s={dt:.2f} writes_per_s={n / dt:.0f}")
    print(f"db_bytes={size} bytes_per_row={size / n:.0f}")
    print(
        "usage_json_bytes_avg=",
        len(
            json.dumps(
                {k: v for k, v in synth_record(0).items() if k in usage_ledger._CALL_FIELDS},
                allow_nan=False,
            )
        ),
    )
    print(
        "wal_exists_after_close=",
        (tmp / "usage.sqlite3-wal").exists(),
        (tmp / "usage.sqlite3-shm").exists(),
    )

    usage_ledger.record_call(
        db, synth_record(0), started_at=1_700_000_000, session_id="s-0", turn_id="t", source="x"
    )
    with sqlite3.connect(db) as conn:
        print("rows_after_duplicate_replay=", conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0])

    usage_ledger.record_call(
        db, synth_record(n), started_at=1_700_000_000 + n, session_id="", turn_id="", source=""
    )
    with sqlite3.connect(db) as conn:
        print("rows_with_empty_session=", conn.execute("SELECT COUNT(*) FROM llm_calls WHERE session_id=''").fetchone()[0])

    t0 = time.perf_counter()
    out = usage_ledger.usage_records(1_700_000_000, 1_700_000_000 + n, path=db)
    print(f"read_rows={len(out)} read_s={time.perf_counter() - t0:.3f}")

    big = tmp / "bulk.sqlite3"
    payload = json.dumps(
        {k: v for k, v in synth_record(0).items() if k in usage_ledger._CALL_FIELDS},
        allow_nan=False,
    )
    with sqlite3.connect(big) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(usage_ledger_create_table_sql())
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_time ON llm_calls(started_at)"
        )
        rows = [
            (
                "%032x" % i,
                1_700_000_000 + i,
                "s-%04d" % (i % 40),
                "t%032x" % i,
                "learning",
                payload,
            )
            for i in range(bulk_n)
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO llm_calls VALUES (?, ?, ?, ?, ?, ?)", rows
        )
        conn.commit()
    print(f"bulk {bulk_n} rows: db_bytes={big.stat().st_size} bytes_per_row={big.stat().st_size / bulk_n:.0f}")

    t0 = time.perf_counter()
    out = usage_ledger.usage_records(1_700_000_000, 1_700_000_000 + bulk_n, path=big)
    print(
        f"read_bulk_rows={len(out)} read_s={time.perf_counter() - t0:.3f} "
        f"peak_rss_mb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}"
    )


def usage_ledger_create_table_sql() -> str:
    return """CREATE TABLE IF NOT EXISTS llm_calls (
        call_id TEXT PRIMARY KEY, started_at REAL NOT NULL,
        session_id TEXT NOT NULL, turn_id TEXT NOT NULL, source TEXT NOT NULL,
        usage_json TEXT NOT NULL)"""


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    bulk = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000
    main(n, bulk)
