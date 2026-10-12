# Evidence: LLM usage ledger growth & retention audit

Static audit of `deeptutor/services/llm/metrics.py` (279 lines) and
`deeptutor/services/llm/usage_ledger.py` (172 lines) at `origin/main`
(6cf793bd8, v1.6.14), plus fixture-level measurements of the real write path.
Evidence only — no source changes in this branch.

- Scope: ledger persistence (`usage_ledger.py`), metering fan-in
  (`metrics.py`, `provider_core/base.py`, `runtime/agentic/client.py`,
  `runtime/orchestrator.py`), read path
  (`api/routers/settings.py`, `services/session/usage_statistics.py`),
  lifecycle interplay (`multi_user/identity.py`, `services/path_service.py`).
- Dedup: `docs/guides/usage-ledger-20261011` is a user-facing guide (no
  growth/retention analysis); `test/usage-ledger-20261006` (merged in
  da856ad67, v1.6.9) covers functional tests of writes/merges;
  `test/usage-recovery-20261006` covers the *session*-store recovery path;
  `scan/session-sqlite-growth-20261011` covers `chat_history.db` growth.
  None of them audit usage-ledger growth, retention or orphans — that is the
  axis of this card.
- Measurement: `measure_ledger_growth.py` (offline, deterministic, no
  LLM/network/server, throwaway temp DBs only, synthetic numeric records).
- Reproduce:
  `PYTHONPATH=<repo root> python evidence/usage-ledger-retention-20261012/measure_ledger_growth.py`

## Measured headline numbers (measure_ledger_growth.py, Apple Silicon / APFS / py3.12 venv)

| probe | result |
|-------|--------|
| 5,000 rows via real `record_call` path | 3,248,128 bytes → **650 B/row**; 2.65 s → **~1,900 writes/s** (~0.53 ms/row incl. per-call connect + DDL + WAL pragma) |
| 100,000 rows bulk (same schema/indexes) | 64,790,528 bytes → **648 B/row** — growth is linear, no page-overhead curve |
| `usage_json` payload alone (16 fixed fields, representative values) | **440 B**; SQLite row + PK index + time index ≈ 210 B overhead |
| `-wal` / `-shm` after clean close | absent — `closing()` per write checkpoints and removes sidecars; no persistent WAL bloat |
| duplicate `call_id` replay (`INSERT OR IGNORE`) | row count unchanged (5,000 → 5,000) — replay-safe |
| row with `session_id=""`, `turn_id=""`, `source=""` | accepted — unattributed rows are storable |
| `usage_records` read, 5,000 rows (1 year window) | 0.041–0.052 s |
| `usage_records` read, 100,000 rows (1 year window) | 0.93–1.06 s, **peak RSS ~430–470 MB** (every row materialized as dicts with duplicated totals + `call_details`) |

Extrapolation at 1,000 calls/day (single account): ~0.65 MB/day ≈
**237 MB/year**, unbounded. Agentic turns issue multiple LLM calls per turn
and provider retries write one row per attempt (below), so real ratios are
higher; 10k calls/day ≈ 2.3 GB/year.

## Structure × growth × retention matrix

| id | aspect | current behavior | evidence (path:line) | growth | retention today |
|----|--------|------------------|----------------------|--------|-----------------|
| S1 | location | one SQLite DB per owner account: `<user_data_dir>/usage.sqlite3` | `usage_ledger.py:37-40`, `path_service.py:118-119` | scales × user count | deleted only by hand |
| S2 | schema | `llm_calls(call_id TEXT PK, started_at REAL, session_id, turn_id, source, usage_json)` + time index | `usage_ledger.py:58-62` | 6 columns + 2 indexes | no workspace/model columns outside `usage_json` |
| S3 | write trigger | one row per **provider attempt**, incl. `failed`/`interrupted`/`estimated` | `metrics.py:144-180` (`finish`), `provider_core/base.py:358-383` (retry loop wraps every attempt in `measure_provider_call`) | retry multiplier: N attempts = N rows | none |
| S4 | streaming paths | measured streams and instrumented clients record on close/`StopAsyncIteration`, incl. `status="interrupted"` | `metrics.py:183-249`, `258-279` | abandoned turns still add rows | none |
| S5 | write idempotency | `INSERT OR IGNORE` on `call_id` PK | `usage_ledger.py:58-64` | dedup exact replays | n/a |
| S6 | read path | year-window full materialization; each row → `TurnUsage` summary with totals + `call_details` | `usage_ledger.py:76-107`, consumer `settings.py:2415-2453`, aggregation `usage_statistics.py:160+` | O(rows in year) time and memory (measured 1.06 s / 432 MB @ 100k) | none (relies on caller-chosen year) |
| S7 | journal | WAL enabled on every write; per-call `close()` checkpoints | `usage_ledger.py:55-57` | sidecars transient (verified absent post-close) | n/a |

## Recovery paths (what already works)

| id | mechanism | evidence | verified |
|----|-----------|----------|----------|
| R-A | crash between insert and commit → SQLite WAL replay on next open | standard SQLite; WAL set at `usage_ledger.py:57` | sidecars cleaned on close; replay is automatic |
| R-B | duplicate insert (retry after crash) ignored via PK | `usage_ledger.py:64` | yes — count unchanged |
| R-C | ledger write lost → history snapshots compensate; `merge_records` keeps history-only calls, dedups by `call_id` in 500-ID batches | `metrics.py:179-180` (swallow+log), `usage_ledger.py:110-138`, `141-172` | code path only; functional coverage in `tests/services/llm/test_usage_ledger.py` |
| R-D | missing/corrupt table tolerated on read (`[]`, mode=ro) | `usage_ledger.py:80-86`, `159-161` | code path only |

## Orphan register (each with trigger)

| id | severity | orphan | evidence | trigger |
|----|----------|--------|----------|---------|
| O1 | medium | rows with empty `session_id`/`turn_id`/`source` — LLM calls outside an orchestrator turn binding (collector `None`) | `metrics.py:165-178` writes `""` when collector is `None`; schema has no NOT NULL beyond empty string (`usage_ledger.py:58-61`) | any provider call not running under `runtime/orchestrator.py:134-137` binding (background jobs, tools) |
| O2 | high | dangling `session_id` rows: sessions deleted from `chat_history.db` are never removed from `llm_calls` (no cascade, no FK; `usage_ledger` is referenced nowhere in `services/session/`) | grep: `usage.sqlite3` appears only at `usage_ledger.py:40` and tests | any session delete; rows accumulate forever |
| O3 | high | whole ledger DB orphaned after account deletion — `delete_user` pops the user record and revokes guardians but never removes `user_data_dir` | `multi_user/identity.py:367-390`; dir layout `path_service.py:107-119` | deleting any account leaves `usage.sqlite3` on disk indefinitely |
| O4 | low | coverage gap, not residue: `ledger_path()` failure at meter init or `record_call` failure drops the durable record (in-memory only, unrecoverable for unbound calls) | `metrics.py:81-87`, `179-180` | filesystem errors / lock timeout >5 s (`usage_ledger.py:55`) |
| O5 | low | no `workspace_id` dimension — owner-global rows cannot be pruned or attributed per workspace even though the read path iterates workspaces | `settings.py:2439-2452`, schema `usage_ledger.py:58-61` | structural |

## Retention recommendations (numbers-driven)

1. **R1 — time-window prune (highest value / lowest risk).** Stats are
   year-scoped (`settings.py:2417`, `usage_statistics.py:160-166`), so keeping
   2 rolling years suffices. Add `DELETE FROM llm_calls WHERE started_at < ?`
   on a daily timer per owner DB, then `PRAGMA incremental_vacuum` (with
   `auto_vacuum=INCREMENTAL`) so space returns to the OS — otherwise pages
   stay freelist-only (the sibling session-store scan measured the same
   file-never-shrinks behavior). At 1,000 calls/day this caps the DB at
   ~474 MB instead of unbounded growth.
2. **R2 — aggregate-then-prune.** Roll rows older than N days into a
   `llm_calls_daily(day, model, provider, totals…)` rollup, delete raw rows:
   100k rows/year collapse to ≤ ~2,200 day-rows/year (>45x) and the year read
   drops from 1.06 s / 432 MB RSS to milliseconds, because
   `aggregate_usage` only needs day/model totals (`usage_statistics.py:166+`).
3. **R3 — cascade cleanup.** Delete `llm_calls WHERE session_id = ?` on
   session hard-delete; remove (or at least archive) `user_data_dir` in
   `delete_user`. Closes O2/O3 without schema changes.
4. **R4 — bound the year read.** Even before pruning, paginate the ledger
   query by month (index `idx_llm_calls_time` already exists,
   `usage_ledger.py:62`) or stream rows into the aggregator instead of
   materializing all summaries, to remove the ~430–470 MB RSS spike at
   100k rows.
5. **R5 — attribute rows.** Persist `workspace_id` (or a stable scope key) at
   write time (`metrics.py:165-178` already has the collector context) to
   make O1/O2 rows prunable and per-workspace stats exact.

## Integrity

`SHA256SUMS` covers every file in this directory. All measurements ran
offline against throwaway temp DBs with synthetic numeric records; no
service, daemon, LLM call or network access was involved, and no source file
outside `evidence/` was modified.
