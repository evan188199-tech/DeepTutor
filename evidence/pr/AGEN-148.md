# PR: test(web): cover settings store persistence and normalization

`web/features/settings/store/SettingsStore.tsx` had no direct unit tests (coverage audit gap: 354 missing lines / 52.2% line coverage). This PR adds `web/tests/settings/settings-store.test.ts` with 27 `node:test` cases locking the settings persistence and normalization contracts. No product code is changed.

## Summary

- Add `web/tests/settings/settings-store.test.ts` (+655 lines): 27 `node:test` cases for `web/features/settings/store/SettingsStore.tsx`, the store backing global user preferences and their persistence.
- Covered contract groups:
  1. **`syncLoadedCodeBlockSettingsToAppShell`** — after applying a settings patch, the three code-block keys land in `localStorage`, the `CODE_BLOCK_SETTINGS_EVENT` announcement fires, and backend-provided values override stale local values.
  2. **`persistUiSettingsPatch` request shape** — verifies `PUT /api/settings/ui?dt_workspace=…`, `Content-Type: application/json`, and field-by-field JSON body equality via a recording fetch stub; fetch failures propagate.
  3. **Invalid-value normalization** — `null`/`undefined`/empty string/whitespace/garbage-type matrices normalize to defaults for themes (including case-insensitive boolean parsing such as `"True"`/`"TRUE"`) without throwing, keeping storage and store three-way consistent.
  4. **Constants and pure helpers** — `TOUR_STEPS` (7-step route order) and `RESPONSE_LANGUAGE_OPTIONS` (15 unique valid entries) integrity, plus `defaultCatalog`/`cloneCatalog`/`getActiveProfile`/`getActiveModel`/`serviceReadiness` contracts.
  - SSR guard: suite installs a `window` mock and asserts behavior is deterministic under the node:test runner (no DOM required).

## Root cause

No product defect. A coverage audit showed the settings store at 52.2% line coverage with 354 uncovered lines — the persistence and normalization contracts behind every user preference had no regression net, so a silent regression (wrong key written, lost announcement, throwing on malformed stored values) could pass the existing suite unnoticed. This PR closes that gap with tests only.

## Changes

- New file `web/tests/settings/settings-store.test.ts` (+655 lines).
- Zero product-code changes; runs under the existing `test:node` harness (`tsconfig.node-tests.json`), consistent with sibling suites such as `web/tests/settings-context-ui-sync.test.ts`.
- Fully isolated: in-memory `localStorage`/`sessionStorage`/event mocks and a recording fetch stub — no network calls, no persisted state.

## Tests

All commands run in `web/` on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/settings/settings-store.test.js` → **27 tests / 27 pass / 0 fail**
- `npm run test:node` → **1261 tests / 1261 pass / 0 fail** (1234 pre-existing + 27 new)
- `npm run check:fast` → all green (contracts OK; architecture 888 modules / 0 violations; typecheck 0 errors; vitest 113 files / 471 tests; eslint 0 errors; i18n parity + audit OK)
- `npx eslint tests/settings/settings-store.test.ts` → 0 errors / 0 warnings
- `npx prettier --check tests/settings/settings-store.test.ts` → clean

## Related issue

Related to the settings store coverage gap identified in an internal coverage audit. No upstream issue exists yet; this PR is standalone test hardening with no behavior change.
