# Upstream sync audit: 2026-W38

Integration branch: `codex/chore/upstream-sync-2026-w38`
Merge commit: `92ee9efd7` (merges `origin/main` `897fce52f` into
`myfork/main` `69a556317`).

## Upstream delta

Upstream advanced by three mastery fixes; the fork carried 144 commits not
yet upstream.

| Commit | Subject | Classification |
| --- | --- | --- |
| `10f643daf` | Stop sending the tutor back to quiz a gate no quiz can clear | merge |
| `d49a41cd9` | Refresh the study map when a turn ends, not only when a socket says so | merge |
| `897fce52f` | Say which gate a number is being read against | merge |

Changed files: `deeptutor/capabilities/mastery/tools.py`,
`deeptutor/learning/policy.py`, `deeptutor/learning/tests/test_mastery_tools.py`,
`web/components/space/learning/ObjectiveDetail.tsx`,
`web/hooks/useMasteryStudySession.ts`, `web/locales/{en,zh}/app.json`, and
`web/tests/mastery-objective-gate-bar.spec.tsx`.

There are no database migrations, API router changes, authentication,
proxy, or deployment-surface changes in this delta.

## Local feature contract mapping

| Local capability | Overlap with delta | Risk | Evidence |
| --- | --- | --- | --- |
| `AUTH_ALLOW_REGISTRATION` and persisted setting | None; no auth files changed | None | contract + partner/auth ledger tests passed |
| Partner Feishu/Lark and WeCom onboarding | None | None | partner router, onboarding, and Feishu domain tests passed |
| Tailscale-to-Quick-Tunnel handoff and rotation | None; no proxy/auth/launcher files changed | None | covered by `tests/test_local_feature_contract.py` in the run below |
| YouTube Immersive Watching / timed media | None; no video-learning files changed | None | included in the local feature ledger run |
| External renderer bootstrap and phone remote control | None | None | included in the local feature ledger run |
| MarginNote 4 bridge and KB handling | None | None | router, capability, and knowledge-base suites passed |
| Plugin loading contract | None | None | `tests/plugins/test_loader.py` passed |
| Locale files (shared surface) | `web/locales/{en,zh}/app.json` both modified upstream | Low; union resolution | zh conflict resolved by keeping upstream's new gate key and updated `Topic name` translation; `en` auto-merged; both JSON files valid |

Upstream contribution extraction: none required this week; all three commits
are upstream-authored fixes with no fork-local candidate.

## Verification evidence

Run in the isolated worktree `/tmp/DeepTutor-upstream-sync-2026-w38` against
merge commit `92ee9efd7`:

- `git status --short` after merge: clean; no unresolved conflicts.
- Python contract and feature ledger:
  `tests/test_local_feature_contract.py`,
  `tests/reading/test_extensions.py`, `tests/plugins/test_loader.py`,
  `tests/api/test_partners_router.py`,
  `tests/services/partners/test_channel_onboarding.py`,
  `tests/services/partners/test_feishu_domain_initialization.py`,
  `tests/api/test_marginnote4_router.py`,
  `tests/capabilities/marginnote4`,
  `tests/knowledge/test_marginnote4_kb.py`, and
  `deeptutor/learning/tests/test_mastery_tools.py`:
  **196 passed**.
- `web npm run test:node`: **1162 passed**.
- `web npm run lint`: **0 errors**; none of the 70 pre-existing warnings are
  in files changed by this delta.
- `web npm run build`: **passed** (Google Fonts fetch required network).
- Playwright `release-ui-matrix.audit.ts` (includes `/mastery`) against the
  standalone build on `127.0.0.1:4317`: **32 passed** when run serially.
  An initial parallel run had 4 navigation timeouts against the
  single-process temporary server; each configuration passed on the serial
  rerun.

## Pilot metrics

- GLM consumption for this batch: 0 (budget adapter reported `single`
  availability; the one mechanical locale conflict was resolved by Codex
  because no GLM runtime is wired into dispatch yet).
- First-pass merge result: clean except one expected locale conflict.
- Codex escalations: 1 (locale conflict resolution and final review).
- Human intervention points: release directory creation, deployment switch,
  and post-switch health verification remain human-gated.

## Remaining human gates

Do not mark the Plane parent item `Done` until:

1. The integration branch merges to `myfork/main` via PR.
2. A new immutable release directory is built from the merged SHA.
3. API/web health checks and the key browser paths pass on the new release.
4. The old release rollback command is verified.
5. The launchd switch is explicitly approved and observed.
