# web zero-coverage deep pass — Space import surfaces (2026-10-09)

Card: AGEN-1199 — `test: web 空间导入向导补测（ImportWizard/EduHubImportModal）`

## Scope

Zero-coverage files from `myfork/scan/web-test-gaps-20261007` →
`web/evidence/web-test-gaps-20261007/summary.json` (`zero` list, `actionable: true`):

- `web/components/space/ImportWizard.tsx` (574 LOC)
- `web/components/space/EduHubImportModal.tsx` (587 LOC)

Dedup note: `test-space-cli-apps` / `test-space-mcp-router` cover backend
routes; this card covers only the two web import components above.

## Deliverable

- `web/tests/space/space-import.smoke.spec.tsx` — new spec, both components.
- Naming deviation from the card text (`…smoke.test.tsx`): the repo's vitest
  config (`web/vitest.config.mts`) collects only `tests/**/*.spec.ts(x)`
  (`test:unit`), while `test:node` compiles `tests/**/*.ts` only — a
  `.test.tsx` file would never run in any pipeline. The file uses the repo
  convention `.spec.tsx` so it is actually executed; test-file-only change,
  no product code touched (`git diff origin/main` is empty).

## Coverage points

ImportWizard (chat-history import):

1. Intro step renders; folder picker disabled + fallback warning when File
   System Access is unsupported; supported-hint branch when supported.
2. Wizard stepping: folder scan → select phase; groups listed with counts,
   summary line, all units pre-selected, default agent name from
   `SOURCE_LABEL`, import button reflects selected session count.
3. Selection toggling: unit toggle / Clear / Select all keep the import
   button count and disabled state in sync.
4. Empty scan (`projects: []`) → "No conversations found" empty state;
   no name input; footer Import stays disabled.
5. Scan failure `not_recognized` → error view with source-specific message;
   "Try again" returns to intro (error cleared).
6. Scan aborted (`ImportScanError("aborted")`) → back to intro, no error view.
7. Submission success: parse → `importChatHistory` called with source,
   normalized sessions and `{ id, name }` (custom agent name honored);
   `saveAgent` registers agent with source/folder/scope
   (`{ kind: "projects", cwds: [...] }`); Done view shows imported/skipped
   counts; "Done" fires `onImported`.
8. Registry write failure stays best-effort: import still completes.
9. In-flight import locks the modal: no close button, backdrop mousedown and
   Escape do not close, footer shows "Working…"; recovery to Done after the
   promise resolves.
10. Submission failure (`importChatHistory` rejects) → generic error view;
    dialog stays open.
11. ChatGPT export path: footer button triggers the hidden file input;
    successful parse → `importChatHistoryInBatches("chatgpt", …)` with
    `onProgress`; Done view with zero-skip subtitle; input value reset after
    change (same-file re-select fix).
12. ChatGPT parse failure `invalid_export` → specific error message;
    "Try again" returns to intro.

EduHubImportModal (skill import):

1. Catalog load renders listings (name/summary/downloads/stars) and hub link
   from the authoritative `webUrl`.
2. Catalog failure → error panel with the error message and working "Retry"
   (second call succeeds).
3. Search filter by name/summary; no-match state; clearing restores the list.
4. Pre-installed skills (via `installedNames`) show the "Installed" badge and
   "Re-download" button label.
5. Detail view: `fetchHubSkillDetail(slug)` called; version badge; tags;
   YAML frontmatter stripped from the markdown body; "View on EduHub" link;
   "Back" returns to the list.
6. Detail load failure renders the error message alongside listing metadata.
7. Install success: `installSkillFromHub("eduhub:<slug>", { force: false })`;
   session-local installed set flips the badge/button; `onInstalled` fired.
8. Install failure: error message on the card, button becomes "Retry",
   `onInstalled` not fired.
9. Modal open/close: inner clicks don't close; overlay click, X button and
   Escape each close.
10. Escape layering with detail open: first Escape returns to the list, second
    closes the modal.

## Verification (local, 2026-10-09)

Commands run in `web/` on branch `test/web-space-import-20261009`
(worktree from `origin/main` @ `6cf793bd8`):

- `npx vitest run tests/space/space-import.smoke.spec.tsx`
  → Test Files 1 passed, Tests 22 passed (22/22).
- `npm run test:unit` (full suite incl. the new spec)
  → Test Files 147 passed, Tests 675 passed.
- `npx eslint tests/space/space-import.smoke.spec.tsx` → clean.
- `npm run typecheck` → clean.
- `git diff origin/main --stat` → empty (no product code modified); commit
  adds only the spec and this evidence note.

## Observations (no fix card filed, listed for triage)

1. Empty-scan select phase keeps the footer's "Import" button visible
   (disabled) — arguably fine, listed in case the empty state should hide it.
2. Done title uses the single key `Imported {{count}} conversations`
   (`Imported 1 conversations` in English) — no plural handling for en; zh
   copy reads naturally. Low-priority i18n polish.
