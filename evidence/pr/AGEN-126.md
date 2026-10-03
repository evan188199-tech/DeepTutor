# PR: test(knowledge): pin KB client request contract and cache invalidation

`web/features/knowledge/api/client.ts` — the shared frontend knowledge-base data layer (pure `fetch` + in-memory cache) — was the coverage audit's Top-15 gap #5 (304 missing statements, 13.9% line coverage suite-wide) with no tests pinning its request contract. This PR adds `web/tests/knowledge/client.test.ts` with 9 `node:test` cases covering request shape, cache scoping/invalidation, and 4xx error degradation. No product code is changed.

## Summary

- Add `web/tests/knowledge/client.test.ts` (+242 lines, 9 cases):
  1. **`listKnowledgeBases` request shape**: workspace mode issues `GET /api/knowledge-bases?dt_workspace=` with `cache: "no-store"`; the knowledge-page path and `{library: true}` both append `resource_library=true`; object payloads read the `knowledge_bases` field and odd shapes fall back to `[]`.
  2. **`getEmbeddingUsage`**: `GET /api/knowledge-bases/embedding-usage?dt_workspace=` with `cache: "no-store"`; never served from cache (two calls, two refetches).
  3. **4xx handling**: JSON `{detail}` bodies pass through as the error message; non-JSON bodies fall back to endpoint-specific copy ("Failed to list knowledge bases" / "Failed to load embedding model usage").
  4. **Cache contract**: a second call in the same scope hits the cache; `invalidateKnowledgeCaches()` forces refetch on both scopes; `{force: true}` bypasses the cache; library and workspace cache keys are isolated from each other.
  5. **File path builders**: `knowledgeBaseFilePath` / `knowledgeBaseFilePreviewTextPath` encode each path segment and append `resource_library` for library mode.

## Root cause

No product defect. A coverage audit identified `web/features/knowledge/api/client.ts` as Top-15 gap #5: the request shapes (endpoints, query parameters, `no-store` caching), multi-scope cache keys, `invalidateKnowledgeCaches()` semantics, and error-message degradation had no regression protection, so a refactor that broke any of these contracts would pass the existing suite unnoticed. This PR closes that gap with isolated tests only (assertions target fetch calls and returned values — no brittle class or DOM matching).

## Changes

- New file `web/tests/knowledge/client.test.ts` (+242 lines).
- Zero product-code changes (all `features/`, `app/`, and other product paths untouched).
- Test isolation: a custom `stubFetch` intercepts global `fetch` and is strictly `restore()`d in `finally`; the `window.location` simulation is likewise cleaned up in `finally`; every case runs independently with no state leakage.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12), from `web/`:

- `node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/knowledge/client.test.js` → **9/9 passed**
- `npm run test:node` (full node:test suite) → **1243/1243 passed**
- `npm run test:unit` (full Vitest suite) → **471/471 passed** (113 files)
- `npx eslint tests/knowledge/client.test.ts` → 0 errors / 0 warnings
- `npm run typecheck` → clean
- `npm run architecture:check` → no dependency violations (888 modules, 2753 dependencies cruised)
- `npm run i18n:check` → parity + audit OK
- `client.ts` coverage (c8 + V8, sourcemapped, node:test pipeline): **35.15% → 39.07% lines, 42.1% → 81.25% branches**

## Related issue

Related to the KB client coverage gap identified in an internal frontend coverage audit. No upstream issue exists; this PR is standalone test hardening with no behavior change.
