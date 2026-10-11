# scan: backend `detail.code` error-code parity inventory

Scope: static inventory of every HTTP error envelope the backend emits as
`detail={"code": ...}`, the routes that can emit it, and the web/lib
consumption layer that parses/matches it. Baseline: `origin/main` @ `6cf793bd8`
(release v1.6.14). Read-only scan — no code changed.

## Method

- Emission sites: regex sweep for `detail\s*=\s*{` across `deeptutor/**.py`
  (non-test), then resolution of dynamic `code=` sources
  (`UserMcpError`, `CodexAuthError`, cli `InstallOutcome`).
- Route attribution: enclosing helper → its call sites → nearest
  `@router.<method>("path")` decorator (helper-based emitters:
  `_book_paused_http`, `_claim_content_mutation`, `_unreadable`,
  `_note_error`, `_refuse`, `_codex_http_exception`).
- Web consumption: every `web/lib` parser that reads `detail.code`
  (book-api, cli-apps-api, mcp-api, codex-oauth) plus every code→copy
  mapping table (book-errors CODE_MESSAGES, mcp-store REFUSAL_KEYS,
  codex-oauth codexErrorMessageKey) and the declared readiness contract
  (backend `DETAIL_CODES` vs web `EXPLAINED_DETAIL_CODES`).
- Adjacent surface kept separate: `book_paused` also travels a WebSocket
  error frame (deeptutor/api/routers/book.py:1786, parsed at web/lib/book-ws-operation.ts:117);
  readiness `detail_code` rides a 200 response body, not an error envelope.

## Family registry status (drift class 1 — undeclared)

| family | codes | backend-side declared registry | web-side mapping |
|---|---|---|---|
| book (`book_*`) | 3 | none (single-site literals) | book-errors.ts CODE_MESSAGES, all 3 |
| notebook | 1 | none (helper literal) | none |
| mcp (`mcp.*`) | 11 | none (`UserMcpError` literals) | mcp-store.ts REFUSAL_KEYS, 6 of 11 |
| cli (`cli.*`) | 4 | none (`InstallOutcome` literals) | parsed (cli-apps-api.ts) but never matched |
| codex oauth | 37 | none (`CodexAuthError` literals) | codex-oauth.ts codexErrorMessageKey, 11 of 37 |
| settings readiness (`detail_code`) | 47 + 1 client-only | `DETAIL_CODES` deeptutor/services/config/readiness.py:64 | EXPLAINED_DETAIL_CODES web/lib/settings-readiness.ts:135, 41 of 47 (7 "running" codes intentionally unexplained, per comment at :128) |

Declared-contract integrity: web `EXPLAINED_DETAIL_CODES` (41) ⊆ backend
`DETAIL_CODES` (47) with exactly the 7 documented running codes left out —
no violation. `connection_test_failed` is client-derived only
(web/components/settings/SettingsReadinessPanel.tsx:101, pinned as CLIENT_ONLY
in web/tests/settings-readiness-i18n.test.ts:113) and absent from backend
`DETAIL_CODES` — a web-side-only declaration, documented in the test.
Parser engine readiness reasons stay inside `PARSER_REPORT_REASONS`
(deeptutor/services/config/readiness.py:125, engines emit only not_configured / update_required /
models_missing / cli_missing + "ready").

**52 of 56** distinct HTTP `detail.code` values (codex 37 + mcp 11 + cli 4)
have no backend-side declared registry at all — they exist only as scattered
literals; unlike readiness, nothing on either side enumerates them.

## Drift class 2 — same meaning, different names

| meaning | name A | name B |
|---|---|---|
| a required credential is absent | `required_credential_missing` deeptutor/services/config/readiness.py:81 | `mcp.missing_credential` deeptutor/api/routers/space_mcp.py:337 |
| upstream returned an unusable payload | `catalog_invalid_response` deeptutor/services/codex_auth/catalog.py:233 | `invalid_response` web/lib/codex-oauth.ts:152 (web-local only; backend never sends it, yet web maps it as an arrival code at :243) |
| "the selected component is unavailable" | `selected_parser_unavailable` / `selected_parser_unreachable` / `selected_parser_unknown` deeptutor/services/config/readiness.py:83-85 | `selected_video_provider_not_configured` / `selected_video_provider_unknown` deeptutor/services/config/readiness.py:112-113 (two construction patterns for one family) |

Style split (observation, not counted): flat snake_case `book_*` /
`notebook_unreadable` vs dotted namespaces `mcp.*` / `cli.*` vs bare codex
oauth tokens — three conventions, no written rule.

## Drift class 3 — web-unmapped codes: 36

Backend emits them through `detail.code`; web either parses the code and
never matches it, or does not parse the object form at all. Full list with
evidence in `codes-routes-consumption.tsv` (column 3 = `UNMAPPED`).

Breakdown: codex 26 (of 37), mcp 5 (of 11), cli 4 (of 4), notebook 1 (of 1).

Top 10 unmapped by static emission sites (ties by route breadth):

| # | code | emission sites | routes that can emit |
|---|---|---|---|
| 1 | `notebook_unreadable` | deeptutor/api/routers/notebook.py:36 + deeptutor/api/routers/video_learning.py:119 | 13 routes (deeptutor/api/routers/notebook.py:204,221,246,270,301,325,360,395; deeptutor/api/routers/video_learning.py:265,281,294,306,315) |
| 2 | `authentication_required` | deeptutor/services/codex_auth/service.py:715,725,820,828 | all 7 codex routes via deeptutor/api/routers/settings.py:597 |
| 3 | `login_not_active` | deeptutor/services/codex_auth/oauth.py:221; deeptutor/services/codex_auth/service.py:551,578,1328 | codex status/complete/cancel routes |
| 4 | `catalog_invalid` | deeptutor/services/codex_auth/catalog.py:36,51,61,288 | models/refresh, reasoning-effort via deeptutor/services/codex_auth/service.py:139/905 |
| 5 | `state_mismatch` | deeptutor/services/codex_auth/service.py:557,661,1323 | oauth/complete |
| 6 | `codex_catalog_unavailable` | deeptutor/services/codex_auth/service.py:139,905,918 | models/refresh, reasoning-effort |
| 7 | `catalog_too_large` | deeptutor/services/codex_auth/catalog.py:42,274 | models/refresh, reasoning-effort |
| 8 | `catalog_invalid_response` | deeptutor/services/codex_auth/catalog.py:233,282 | models/refresh, reasoning-effort |
| 9 | `token_response_invalid` | deeptutor/services/codex_auth/service.py:1125,1147 | oauth/complete |
| 10 | `cli.install_failed` | deeptutor/services/cli_apps/installer.py:156 + fallback deeptutor/api/routers/space_cli_apps.py:149 | POST /catalog/{app_id}/install (deeptutor/api/routers/space_cli_apps.py:135) |

## Counts

- distinct backend-emitted `detail.code` values: **56**
  (book 3, notebook 1, mcp 11, cli 4, codex 37)
- web-mapped: **20** (book 3, mcp 6, codex 11)
- web-unmapped (class 3): **36**
- families with no backend-side declared registry (class 1): **52** codes
  in 3 families (codex, mcp, cli); the two existing declared contracts
  (readiness, parser reasons) show no violations
- synonym pairs/families (class 2): **3**
- code value emitted but web-side-only declarations: **2**
  (`invalid_response` web/lib/codex-oauth.ts:152+243;
  `connection_test_failed` web/lib/settings-readiness.ts:143, client-derived)

## Files

- `codes-routes-consumption.tsv` — one row per code: value × route coverage ×
  web consumption, every cell with path:line evidence.
- `drift-findings.md` — this file.
- `SHA256SUMS` — checksums of both.
