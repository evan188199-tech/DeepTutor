# Evidence: learning journal storage growth & retention audit

Static audit of the learning journal storage surface at `origin/main`
(6cf793bd8, v1.6.14) plus a deterministic size-bound measurement.
Evidence only — no source changes in this branch.

- Scope: `deeptutor/services/learning_journal/store.py` (368 lines),
  `models.py`, write path `deeptutor/tools/learning_journal_tools.py`,
  per-turn reader `deeptutor/services/session/turns/executor.py`,
  read-only API `deeptutor/api/routers/learning_journal.py`,
  storage helpers `deeptutor/services/file_io.py`, path resolution
  `deeptutor/services/path_service.py` / `deeptutor/multi_user/paths.py`.
- Measurement: `measure_journal_bound.py` → `bounds.json` (offline,
  deterministic, no LLM/network/server).
- Reproduce:
  `PYTHONPATH=<repo root> /Users/Shared/DeepTutor/.venv/bin/python evidence/learning-journal-retention-20261011/measure_journal_bound.py`

## Headline correction to the card premise

The card says "未见 retention/prune/rotate 逻辑". A count-based prune
**does exist**: `MAX_RECORDS = 50` (`deeptutor/services/learning_journal/store.py:26`)
enforced as a FIFO ring buffer in `add_record`
(`store.py:280-281`); mission and last_session are single-slot
overwrites. Measured worst case: **one user's `journal.json` is bounded at
54,485 bytes (~53 KiB)** — 50 records × 1,041 B + 2,435 B mission/session,
serialized exactly as `atomic_write_json` does (`indent=2`,
`ensure_ascii=False`). Aggregate storage is `O(users) × 53 KiB`: linear in
user count, constant per user. So there is **no unbounded per-user growth**
of the journal file itself. The real retention gaps are: no
time-based/TTL retention, no archive-on-evict (silent data loss), no
rotation, no orphan-temp sweep, and write amplification on `note_session`.

## Growth path inventory (who writes what, where)

| id | path | what grows | bound |
|----|------|-----------|-------|
| W1 | `learning_update` tool → `LearningUpdateTool._update` `deeptutor/tools/learning_journal_tools.py:120-167` → `store.set_mission` (`store.py:185-216`) / `note_session` (`store.py:218-245`) / `add_record` (`store.py:247-289`) | journal.json content | ≤ 54,485 B/user (measured) |
| W2 | All writes funnel through `_mutate` (`store.py:299-310`) → `_atomic_write` (`store.py:320-321`) → `atomic_write_json` (`deeptutor/services/file_io.py:72-92`: temp file + fsync + `os.replace`) | write count, transient tmp file | file size constant; write count unbounded (see R6) |
| S1 | Sidecar `journal.json.lock`, created on first write (`store.py:327`), never deleted | 1 file/user, persists forever | constant, negligible (R4) |
| S2 | Crash-orphaned `tmp*` files in `learning_journal/` (`file_io.py:78-84` create, cleanup only in `finally` `file_io.py:90-92`) | 1 orphan per killed write | unbounded across crashes (R3) |
| R* | Readers (no storage growth): per-turn injection `deeptutor/services/session/turns/executor.py:569`, `learning_status` tool `learning_journal_tools.py:38`, GET overview `deeptutor/api/routers/learning_journal.py:13` → `overview()` `store.py:126-132` | CPU O(file) per call | bounded by 53 KiB (R8) |

Path resolution is per-user: `store.journal_path()` →
`get_path_service()` (`deeptutor/services/path_service.py:516-521`) →
`get_current_path_service()` → `<user workspace>/learning_journal/journal.json`
(`path_service.py:302-307`); no-user contexts fall back to the shared
default root (`deeptutor/multi_user/paths.py:158`).

## Risk register (each with path:line and trigger)

| id | severity | risk | path:line | trigger condition |
|----|----------|------|-----------|-------------------|
| R1 | info | Premise correction: FIFO count-cap already bounds the file; nothing unbounded per user | `store.py:26`, `store.py:280-281` | 51st distinct `add_record` truncates to last 50 |
| R2 | **medium** | Silent eviction without archive: oldest durable insight permanently discarded, no backup/log/metric | `store.py:280-281` | learner accumulates >50 distinct insights; the earliest lessons vanish with no trace |
| R3 | low | Orphaned temp files accumulate after crashes (SIGKILL between temp create and `os.replace`); no startup sweep | `file_io.py:78-84`, cleanup skipped on kill: `file_io.py:90-92`, replace at `file_io.py:89` | process killed mid-write; repeated crashes → one `tmp*` residue each, never cleaned |
| R4 | low | Lock file persists forever after first write | `store.py:327` (`path.with_suffix(".lock")` opened `"a+b"`, never unlinked) | any write; file remains after journal is abandoned/deleted with workspace? (removed only if parent tree is removed) |
| R5 | low | Per-path `threading.Lock` map never evicted in the module-level singleton store | `store.py:62` (`self._locks`), `store.py:312-318` (`_lock_for`), singleton `store.py:351-358` | multi-user server with N users → O(N) lock entries for process lifetime; bytes negligible, growth technically unbounded |
| R6 | low | Write amplification: `note_session` has no dedup — identical content still rewrites the whole file and bumps `updated_at` via `touch()` | `store.py:233-243` (always accepted, no content check), `store.py:304` (`journal.touch()` before mutator); contrast dedup+skip in `add_record`: `store.py:260-269`, `store.py:308-309` | model calls `note_session` each session with the same handoff → unbounded write count and mtime churn (size stays bounded); same for unchanged `set_mission` |
| R7 | edge | Retention invariant not enforced on read: `load()` accepts any record count (no clamp); cap applied only inside `add_record` | `store.py:82-87` (validation keeps all), clamp only `store.py:280-281` | externally edited / legacy file with >50 records → GET overview returns all of them (`store.py:130`, `learning_journal.py:10-13`) |
| R8 | info | Per-call read cost: every turn / tool call / GET fully parses and validates the file (all records) | `executor.py:569` → `injection_markdown` → `load()` `store.py:67-87`; `learning_journal_tools.py:38`; `learning_journal.py:13` | every turn and call; O(file) CPU, bounded by 53 KiB — no storage impact, caching optional |
| R9 | info | No-user contexts (CLI/background) share one default-root journal | `deeptutor/multi_user/paths.py:158` (`PathService.get_instance()` fallback) | store used outside a user request scope; expected desktop behavior, shared file on server deployments |

Injection slice is already growth-safe by design: `injection_markdown`
excludes records and returns `""` when empty (`store.py:134-159`), so
per-turn prompt overhead does not scale with journal history.

## Retention / cleanup policy recommendations

1. **P1 — TTL + archive-on-evict** (addresses R2): keep `MAX_RECORDS=50`
   as the hot-window cap; on eviction at `store.py:280-281`, append evicted
   records to `journal.archive.jsonl` in the same dir, capped (e.g. 2 MiB)
   with size-based rotation; optionally drop records older than a TTL
   (e.g. 180 d on `created_at`) into the archive at write time.
2. **P2 — no-op write short-circuit** (addresses R6): in `note_session`
   and `set_mission`, compare normalized content with the current value and
   return a `deduplicated` result without rewriting, mirroring
   `add_record`'s dedup (`store.py:260-269`) and `_mutate`'s skip
   (`store.py:308-309`).
3. **P3 — startup orphan sweep** (addresses R3): at app startup, remove
   `tmp*` files older than ~24 h under each `learning_journal/` dir.
   Do **not** sweep `.lock` files (deleting a flock-held file is racy;
   they are one constant-size file per workspace, R4 is acceptable).
4. **P4 — clamp on read** (addresses R7): enforce `MAX_RECORDS` in
   `load()` / `LearningJournal.from_dict` so the invariant holds regardless
   of how the file came to exceed it.

Cleanup hook locations:

- **H1** `store._mutate` (`store.py:299-310`) — eviction/archive hook
  (post-mutate, pre-write; already where the FIFO cap lives).
- **H2** API startup lifespan (`deeptutor/api/main.py`) — filesystem sweep
  hook (P3).
- **H3** `LearningJournal.from_dict` (`models.py:118-132`) — invariant
  clamp hook (P4).
- **H4** workspace/account deletion (`deeptutor/multi_user/paths.py`) —
  verify `learning_journal/` (journal + lock + archive) is removed with
  the workspace tree.

## Suggested split cards (≤3)

1. **Test card (TDD, backend)** — `add_record` archive-on-evict (P1).
   Assertions: (a) adding the 51st distinct record keeps `len(records)==50`
   and drops the oldest; (b) the evicted record's id/title/insight/
   created_at appear exactly once in the archive file; (c) a duplicate
   51st add hits the dedup path (`store.py:261-269`), evicts nothing and
   appends nothing to the archive; (d) existing store tests still pass.
   Files: `deeptutor/services/learning_journal/store.py`,
   `tests/services/learning_journal/test_store.py`.
2. **Fix card + tests** — no-op short-circuit for `note_session` /
   `set_mission` (P2). Assertions: (a) two identical `note_session` calls →
   second returns accepted with `deduplicated=True` and file bytes are
   byte-identical (no rewrite, no `updated_at` bump); (b) changed content
   still writes; (c) empty payloads still rejected without write;
   (d) `set_mission` behaves the same.
   Files: `store.py:185-245`, `tests/services/learning_journal/test_store.py`.
3. **Chore card + tests** — startup sweep of stale `tmp*` under
   `learning_journal/` dirs (P3). Assertions: (a) tmp file older than TTL
   removed, recent tmp file kept; (b) `journal.json` and `journal.json.lock`
   are never touched by the sweep; (c) idempotent and tolerant of a missing
   directory. Files: startup hook in `deeptutor/api/main.py`,
   new test under `tests/api/` (or `tests/services/`).

## Method notes

- Static reading of the audited files at 6cf793bd8; every `path:line`
  above was re-verified against the working tree.
- Size bound measured with the repo's own models/constants
  (`measure_journal_bound.py`), serialization identical to
  `atomic_write_json` (`file_io.py:85-86`): 54,485 B worst case
  (`bounds.json`).
- No servers, daemons, or background processes were started; no source
  files modified (`git diff origin/main` contains only `evidence/`).
