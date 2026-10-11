# Evidence: session SQLite store growth & orphan-row audit

Static audit of `deeptutor/services/session/sqlite_store.py` at `origin/main`
(6cf793bd8, v1.6.14) plus fixture-level measurements of the real store paths.
Evidence only — no source changes in this branch.

- Scope: `deeptutor/services/session/sqlite_store.py` (4,612 lines), write
  paths in `deeptutor/services/session/turns/executor.py`,
  `turns/lifecycle.py`, `turns/request_preparer.py`, recycle-bin API
  `deeptutor/api/routers/sessions.py`, workspace maintenance
  `deeptutor/services/workspace/data_migration.py`.
- #1793 relation: the lost-ack resend fix (d15e35a37, in this base) makes
  resends **reuse the original conversation and re-point the submission row**
  (`sqlite_store.py:1179-1223`, `1380-1397`, `1432-1436`). That binding is
  correct; this audit maps the storage residue the same write path leaves
  behind.
- Dedup: selection axis (SQLite vs PocketBase) and query-plan axis belong to
  scan-persistence / scan-sql-query-plans; not covered here. This card covers
  growth, orphan rows and retention gaps.
- Measurement: `measure_store_growth.py` → `bounds.json` (offline,
  deterministic, no LLM/network/server, throwaway temp DBs only).
- Reproduce:
  `PYTHONPATH=<repo root> python evidence/session-sqlite-growth-20261011/measure_store_growth.py`

## Measured headline numbers (bounds.json)

| probe | result |
|-------|--------|
| PRAGMA journal_mode / auto_vacuum / wal_autocheckpoint | `wal` / `0` / `1000` (all defaults; no vacuum policy) |
| 5 failed resends of one submission | 5 `turns` rows + 5 `turn_events` rows (1 submission row) |
| regenerate once | superseded turn row + its events retained; 1 dangling `turns.assistant_message_id` |
| `delete_message` mid-chain | child's `parent_message_id` dangles; `get_message_path` returned 2 rows instead of 4 |
| delete a regenerated exchange via its user row | 3 turns → 2 (only 1 resolved turn deleted) |
| hard-delete session with notebook entry | notebook row survives (`session_id=NULL`, dead `turn_id`); turn_submissions cascade away |
| soft-delete (recycle bin) | all rows retained, listed in bin; no TTL |
| 10 sessions bulk-inserted then hard-deleted | `page_count` 109 → 109, `freelist_count` 0 → 58 (file never shrinks) |
| 200 streamed deltas, one turn | 200 `turn_events` rows, 102,800 payload bytes, retained after completion |
| `ensure_notebook_session` ×3 | 3 zero-message sessions listed as regular conversations |
| turn deleted, then resend | submission row survives with `turn_id=NULL`, resend re-binds a new turn |

## Growth path inventory (who writes what, where)

| id | path | what grows | bound |
|----|------|-----------|-------|
| W1 | messages: `add_message` (`sqlite_store.py:1997-2064`) from `executor.py:868/1107-1152` | full `content`, `events_json`, `attachments_json`, `metadata_json` per row | O(messages), unbounded |
| W2 | turns: `begin_turn` (`sqlite_store.py:1359-1458`) — one row per admission, **including every failed resend** | `turns` rows | O(admissions+resends), unbounded |
| W3 | turn_events: `_append_turn_events_sync` (`sqlite_store.py:1677-1755`); every non-DONE stream event buffered (`lifecycle.py:655-691`) and flushed (`lifecycle.py:693-765`) from `executor.py:1017-1049` | content/thinking/tool deltas, per-row `content`+`metadata_json` | O(deltas) per turn, **never trimmed post-completion** |
| W4 | turn_submissions: `_reserve_submission_sync` (`sqlite_store.py:1179-1223`) | 1 row per distinct submission, **no timestamp column** (`sqlite_store.py:350-356`) | dies only with its session (CASCADE) |
| W5 | notebook/assessment/quiz: `_upsert_notebook_entries_in_conn` (`3185+`), `_append_assessment_attempt_sync` (`3342+`), `put_reading_quiz_pending` (`3607+`) | rows keyed by origin/turn/question; regenerate mints new `turn_id` → new UNIQUE slots | O(saved questions × attempts) |
| W6 | placeholder sessions: `ensure_notebook_session` (`sqlite_store.py:1241-1266`) | zero-message `sessions` rows | unbounded, no cleanup |
| W7 | sidecars: WAL mode (`sqlite_store.py:287`), migration lock file (`sqlite_store.py:63`) | `-wal`, `-shm`, `.migrate.lock` files per DB | bounded by autocheckpoint; sidecars persist |

Per-user amplification: each account gets its own `chat_history.db`
(`sqlite_store.py:257-265`, legacy move `267-281`), so every path above
scales × user count.

## Risk register (each with path:line and trigger)

| id | severity | risk | path:line | trigger condition |
|----|----------|------|-----------|-------------------|
| R1 | **medium** | Resend/failed-turn debris: every resend of a failed turn inserts a NEW `turns` row and re-points the submission; superseded failed turns (and their `turn_events`) are never deleted — `SUBMISSION_PREVIOUS_TURN_FIELD` is carried as metadata only | `sqlite_store.py:1380-1397`, `1414-1436`; `request_preparer.py:769-779`, `861-863`; `protocol.py:14-17` | user retries a failing send N times (e.g. provider outage loops, #1793/#1421 scenario) → +1 turn row + its events per retry, per submission |
| R2 | **medium** | Regenerate residue: only the assistant **message** is deleted; the superseded turn row survives with `assistant_message_id` pointing at the deleted row (column has no FK, `sqlite_store.py:341`) and its `turn_events` stay forever | `request_preparer.py:877-884`; `sqlite_store.py:2236-2240`; unique partial index `618-621` | every regenerate / resend-with-replace; also leaves dangling turn→message links that `_get_messages_sync`'s LEFT JOIN (`2603`) silently drops |
| R3 | **medium** | `delete_message` is a bare row delete: children keep `parent_message_id` → deleted id (no FK on the column, `sqlite_store.py:314`); the LLM context walk stops silently at the hole, so post-delete turns run with truncated history (measured: 4-row chain returned 2) | `sqlite_store.py:2236-2240`, walk `2630-2660` (break at `2653-2654`) | regenerate replace path (`request_preparer.py:883`) or feishu channel deletion (`partners/channels/feishu.py:1359`) removing any row that has children; contrast the #912 splice in `_delete_turn_by_message_sync` (`2384-2397`) which `delete_message` does not reuse |
| R4 | low | Paired branch delete resolves exactly ONE turn (user-row metadata stamp, then legacy `created_at <=` fallback, both `LIMIT 1`); regenerated sibling turns of the same user row survive after the whole exchange is deleted (measured 3 → 2) | `sqlite_store.py:2290-2336`, delete at `2376-2378` | deleting the user message of an exchange that was regenerated ≥1 time |
| R5 | **medium** | `turn_submissions` has no `created_at` (columns: id, workspace, digest, session, turn) → no aging is even expressible; rows live until the session is hard-deleted; after turn deletion rows persist with `turn_id=NULL` (dead for replay, still reserve the binding per #1793 design) | `sqlite_store.py:350-356`, `2378` (turn delete → SET NULL), `1179-1223` | any long-lived conversation: 1 permanent row per distinct submission, plus NULL-turn rows after message deletion |
| R6 | low | Notebook/assessment rows survive hard delete by design (`ON DELETE SET NULL`) but keep `turn_id` strings referencing cascade-deleted turns (TEXT column, no FK) — dead refs that can never re-link; growth is permanent per saved question | `sqlite_store.py:377-378`, `421-424`, `380` | hard delete (`api/routers/sessions.py:647`) of a session that saved notebook entries/assessments (measured: 1 row, dead turn ref) |
| R7 | low | Zero-message placeholder sessions from `ensure_notebook_session` are indistinguishable from real conversations in listings (`_WHERE_NATIVE` only excludes `imported_*` and recycled) and have no cleanup path | `sqlite_store.py:1241-1266`, filter at `2848-2851` | notebook-only / partner sources filing entries without chat rows |
| R8 | low | Recycle-bin retention is forever: soft delete only sets `deleted_at`; no TTL sweep exists anywhere; `hard_delete` is reachable only via an explicit API call | `sqlite_store.py:1945-1952`, `1970-1977`; `api/routers/sessions.py:637-647` | users delete conversations and never empty the bin; rows (and their turns/messages) accumulate |
| R9 | **medium** | No space reclamation: `auto_vacuum=0`, no VACUUM anywhere in the store; the only VACUUM in the codebase runs inside workspace migration snapshot pruning (`data_migration.py:875-886`), not scheduled maintenance. Measured: after deleting 100% of rows, `page_count` unchanged, 58 pages on the freelist | `sqlite_store.py:283-292` (init PRAGMAs) | sustained churn (delete + recreate) → monotonic disk footprint per account DB |
| R10 | info | WAL growth is bounded in practice: every op opens/closes its own connection (`1119-1134`), so the default `wal_autocheckpoint=1000` drains; a long-lived external read transaction would stall checkpointing and grow `-wal` up to writer volume | `sqlite_store.py:287`, `1119-1134` | only if tooling opens long reads against the same DB (backups, analytics) |
| R11 | info | Answer text is stored twice: assembled copy in `messages.content` (`executor.py:1096-1152`) plus every raw delta in `turn_events.content` (measured 102.8 KB for one 200-delta turn); read-side caps (`event_preview.py:14-15`: 200 events / 128 KiB) bound reads, not storage | `executor.py:1017-1049`, `lifecycle.py:679-691`, `sqlite_store.py:1677-1755` | every streaming turn; largest with thinking-heavy or tool-heavy turns |
| R12 | edge | Non-terminal turns after a crash are reaped to `failed` (`app/service.py:460-494`), which is correct, but those rows then join the R1 debris pool — nothing distinguishes "reapable" from "keep" after reaping | `app/service.py:471-488`; `sqlite_store.py:1545-1560` | worker crash mid-turn, then recovery pass; residue persists unless the user deletes the message pair |

## Retention / cleanup recommendations (no code changed on this branch)

1. **Recycle-bin TTL** (R8): scheduled sweep `DELETE FROM sessions WHERE
   deleted_at < now - 30d` reuses the existing cascade fan-out
   (`hard_delete_session`, `sqlite_store.py:1970-1977`); notebook/assessment
   rows survive by SET NULL, so learner data is preserved.
2. **Resend debris cap** (R1, R12): when a resend completes successfully, delete
   superseded failed turns of the same submission (turn row + events), or add a
   startup sweep for `status='failed' AND assistant_message_id IS NULL AND
   finished_at < now - 7d`.
3. **`delete_message` hygiene** (R2, R3): reuse the #912 parent splice
   (`2384-2397`) and null dangling `turns.assistant_message_id` after the
   delete; alternatively deprecate the bare path in favor of
   `delete_turn_by_message`.
4. **Branch delete completeness** (R4): resolve ALL turns tied to the user row
   (metadata stamp + turns created between the user row and each sibling
   answer) instead of `LIMIT 1`.
5. **Submission aging** (R5): add `created_at` to `turn_submissions` (small
   migration like `478-479`) and expire rows whose `turn_id` is NULL or whose
   turn is terminal and older than a bound window; keep the reservation
   semantics within that window (that is the #1793 guarantee).
6. **Bound `turn_events`** (R11): either stop persisting pure CONTENT deltas
   (the answer already lands in `messages.content`) or trim per-turn events to
   the trace-preview cap after the terminal transition, keeping
   `result`/`done`/usage events that `usage_records` (`2665-2714`) needs.
7. **Space reclamation** (R9): enable `auto_vacuum=INCREMENTAL` (one-time full
   VACUUM required, feasible before DBs grow) plus periodic
   `PRAGMA incremental_vacuum`; or schedule an offline `VACUUM` reusing the
   migration-window precedent (`data_migration.py:886`).
8. **Dead notebook refs** (R6, optional): one-time backfill setting
   `turn_id=''` where the turn no longer exists (keeps the UNIQUE slot
   semantics) — or accept and document as intended.
