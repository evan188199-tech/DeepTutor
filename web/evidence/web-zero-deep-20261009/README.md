# web-zero-deep-20261009 — reading library component tests

Baseline: `origin/main` @ `6cf793bd8` (release v1.6.14).

Source of the zero list: `web/evidence/web-test-gaps-20261007/summary.json`
(branch `scan/web-test-gaps-20261007`), entries
`components/reading/library/MaterialLibrary.tsx` (744 loc) and
`components/reading/library/ReadingLibrary.tsx` (621 loc), both
`actionable: true` ("no test file references this path or basename").

## What was added

`web/tests/reading/reading-library.smoke.spec.tsx` — 30 Vitest/jsdom cases
covering both library pages with the API layer mocked
(`@/lib/learning-library`, `@/lib/reading-workspace-api`,
`@/lib/courses-api`). No product code was changed.

ReadingLibraryPage (collections shelf):

- grouped shelves per workspace with per-folder facts (file counts,
  relative date, preparing spinner) and folder open-entry hrefs
- skeleton while loading; empty-library pitch vs search-miss state
- error state with retry, and error suppressing the empty pitch;
  unavailable-workspaces warning while content still lists
- recency vs name sort order
- per-workspace "New collection here" entries when workspaces are mixed
- folder menu: Start reading href, Rename/recolor (edit dialog),
  Delete collection dialog (copy, confirm, refresh)
- unsettled materials: failed row with failure detail + retry,
  processing row with progress
- create dialog: default-workspace target, save routes to the new folder
- course-scoped shelf (`?course=`): only referenced collections, course
  chip, workspace lock, attach-on-create hand-off

MaterialLibraryPage (material list):

- row facts: format tag, extent ("5 pages"), collection chips with
  folder hrefs, "+N" overflow, audio duration, quiz-star badge
- status filter chips (All / Not in a collection / Preparing / Failed)
  with derived counts and narrowing
- empty states: empty library, filtered-empty, search-miss
- search across title/filename with clear button
- open entry: assigned material routes to its first collection;
  unassigned opens the assign dialog limited to the row's workspace
- assign dialog: assign + refresh, failure keeps dialog with error,
  "New collection…" create-and-assign branch
- row menu: assign and delete branches; delete dialog copy for
  in-use vs unassigned materials, delete + refresh, failure error
- failed row retry (`retryReadingMaterial`)
- `?assign=` deep link opens the dialog and strips the parameter;
  cross-workspace rows route to that workspace's materials page
- `?create=1` opens the upload dialog and drops the flag; the header
  action routes through the destination chooser

## Command

```
cd web && npx vitest run tests/reading/reading-library.smoke.spec.tsx
```

Result: 30 passed / 30 (run twice to confirm stability).
`node ./scripts/typecheck.mjs` and `npx eslint` on the file pass.

## Notes

- The planned filename `reading-library.smoke.test.tsx` would never run
  in this repo: the Vitest include is `tests/**/*.spec.ts(x)` and node
  tests compile `tests/**/*.ts` only, so the spec uses the `.spec.tsx`
  suffix required by the Vitest runner.
- The backend `file_library` tests (dedup note in the scan) are out of
  scope here; this change is frontend-only.
