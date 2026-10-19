# Local development workflow

This repository uses a stable-mainline model. `main` is always deployable, and
product work happens in short-lived branches checked out in separate worktrees.
The primary checkout remains tied to the launchd-managed product so development
does not disturb the running local service.

## Starting work

1. Confirm the primary checkout is clean and either on `main` or on a release
   candidate pointing at the same commit:

   ```bash
   python3 scripts/check_primary_checkout.py
   git status --short --branch
   git rev-parse main
   ```

   The primary checkout is the launchd-owned control and deployment checkout,
   not a scratch workspace. If the governance check fails, first move the WIP
   to an isolated task worktree (or otherwise preserve it explicitly); do not
   start another feature on top of it.

2. Create an isolated worktree and branch from `main`:

   ```bash
   python3 scripts/workspace_governance.py create <type>/<slug>
   ```

   The branch must use `codex/{feat|fix|docs|chore|refactor|test|perf}/<slug>`.
   Keep it short-lived and push it to `myfork` before running long local
   verification or leaving significant work unattended.

3. Keep one product theme per branch. Classify work explicitly:

   - `feat`: new product capability or behavior.
   - `fix`: a defect in an already promised feature.
   - `test`: regression or real-device verification coverage.
   - `chore`: build, dependency, port, deployment, or release engineering.

Do not combine a feature, an unrelated bug fix, and broad cleanup in one branch.
Do not commit `.worktrees/`, build output, logs, local launchd configuration,
tokens, or cached credentials.
Keep rollback snapshots and deployment-recovery trees in ignored local paths
such as `backups/` or `web/.next-*/`; do not turn them into repository content.

## Workspace hygiene

Inspect the local fleet before and after significant work:

```bash
python3 scripts/workspace_governance.py audit --strict
```

The primary checkout must be clean, remain on `main`, and have no stash entries.
Prefer a commit on a topic branch over a stash whenever work must pause. If a
worktree contains experimental uncommitted work, snapshot it explicitly with
`workspace_governance.py archive`; do not treat stashes or dirty worktrees as
long-term storage.

Retire a worktree only after its branch is clean and present on `myfork`:

```bash
python3 scripts/workspace_governance.py retire /tmp/DeepTutor-<slug>
```

## Local feature commitments

`LOCAL_FEATURES.md` is the contract ledger for fork-local product promises; the
[DeepTutor · 学习体验](https://mac-mini.tail47dc0a.ts.net:14130/agents-plane/projects/042c9897-a9fc-491b-829a-748b258f210c)
Multica project is the workflow state. Keep those roles separate: a Multica
card may be in review after an upstream PR is submitted, but it is not locally
delivered until the accepted behavior is integrated into the local product line
and its regression gate passes.

Classify every promised feature before implementation:

- `upstream-covered`: verify the upstream behavior in an isolated worktree,
  record the release or merge commit and test evidence, and remove the matching
  local hotfix only after that stable upstream release reaches the local line.
- `upstream-candidate`: build general product behavior from the latest
  `origin/dev` and submit it upstream. Do not keep a parallel local patch when
  review is still possible.
- `local-only`: keep deployment, private-network, authentication, runtime-data,
  and family-specific behavior additive and local. Bind each item to the ledger
  and at least one regression test before it becomes a product promise.
- `parked`: preserve the design and reopen trigger, but do not count it as an
  active capability or migrate speculative implementation history.

Use two integration bases. Upstream candidates start from `origin/dev`. The
local product line consolidates against the current stable upstream release
(`origin/main`) unless an explicit release-cutover card says otherwise. When a
raw `dev` merge appears to cover a local feature, first replay its contract in
an isolated test worktree; do not move production or delete the local patch
merely because the merge event notification arrived.

For the legacy local integration delta, preserve the old `main` and tracked WIP,
then replay still-valid work onto the stable upstream baseline in small themed
batches such as governance/tests, auth handoff, video learning, reading and
knowledge, and partners/registration. Record each batch's omitted, superseded,
and intentionally local commits. After every batch, run the focused ledger gate,
update `LOCAL_FEATURES.md` and the Multica card with commit and test evidence,
and keep production cutover as a separate explicitly authorized task.

## Merging

Before merging a branch into `main`:

1. Rebase it on the latest `main`.
2. Keep the worktree clean.
3. Run the checks required for the touched subsystem.
4. Bind every new product behavior to at least one regression test.
5. Run `python3 scripts/check_primary_checkout.py` immediately before the
   fast-forward merge. It must pass; a dirty primary checkout means the WIP has
   not been protected or converged yet.

Merge only as a fast-forward from the primary checkout:

```bash
git switch main
git merge --ff-only codex/<slug>
git push myfork main
git worktree remove /tmp/DeepTutor-<slug>
git branch -d codex/<slug>
```

If the merge is not a fast-forward, return to the development worktree, rebase,
and rerun the focused checks. Do not hide divergence with an unplanned merge
commit, reset, or force push.

## Verification gates

Use the smallest relevant gate while developing, then the broader gate before
local product consolidation.

- Python changes: run focused `pytest` targets and Ruff on touched files.
- Web changes: run `cd web && npm run test:node` and `npm run lint`; require
  zero errors and no new warnings.
- Browser behavior: run the relevant Playwright suite.
- MarginNote 4: run its router, capability, and knowledge-base tests.
- Partner channels: run the Partner router, channel onboarding, and Feishu
  domain tests.

Before treating a revision as a local release candidate, also run the full
backend ledger from `LOCAL_FEATURES.md` and `npm run build`. Report every check
as pass, fail, or blocked; do not claim success for an unavailable check.

## Multica project tracking

DeepTutor development is tracked in the local Multica project
[DeepTutor 开发](https://mac-mini.tail47dc0a.ts.net:14130/agents-plane/projects/8836b042-58f4-46c0-a441-bd760ae2b4f0).
Use the existing local `pilot` profile; it maps to the synthetic identity
`pilot@local.test`. Keep its credential in the Multica profile and never copy,
print, or commit the token.

The `multica` binary is not on the default `PATH` in this checkout. Use:

```bash
MULTICA=/Users/xzh/services/ai-development/multica-pilot/bin/multica
```

The `pilot` profile defaults to the `xzh` workspace, while the DeepTutor project
lives in `agents-plane` (`8eee708c-66f8-4845-ac91-5fede2af789a`). A project
lookup without the workspace override can therefore return `404` even when the
credential is valid. Query it explicitly:

```bash
$MULTICA --profile pilot \
  --workspace-id 8eee708c-66f8-4845-ac91-5fede2af789a \
  project get 8836b042-58f4-46c0-a441-bd760ae2b4f0
```

If workspace IDs change, rederive them with `$MULTICA --profile pilot workspace
list` and use the `agents-plane` slug.

### Implemented PR watch ledger

Record submitted upstream work here so the Multica board and local workflow stay
aligned. Do not duplicate this tracking on the GitHub issue or PR.

| As of | Upstream issue and PR | Multica tracking | Merge watch |
| --- | --- | --- | --- |
| 2026-09-28 | [#1613](https://github.com/HKUDS/DeepTutor/issues/1613) -> [#1625](https://github.com/HKUDS/DeepTutor/pull/1625), branch `codex/fix/workspace-subagents`, base `dev`; open, mergeable, CI green. | Card `AGEN-33` (`01a0e8ab-b072-745a-9140-b1363a3ed468`) is in review. | Autopilot `4957dcce-7bd3-442d-96fc-925ee9ea5c82` runs at 04:00 `America/Los_Angeles`; it stays silent while the PR remains open and healthy, reports and pauses itself once after merge, closure, conflict, or CI failure. |
| 2026-09-28 | [#1262](https://github.com/HKUDS/DeepTutor/issues/1262) batch 1 -> [#1628](https://github.com/HKUDS/DeepTutor/pull/1628), branch `codex/docs/settings-screenshots-v1-6-12`, base `dev`; image-only, open, mergeable, CI green. | Card `AGEN-34` (`01a0e8ce-1cb1-75fe-83f1-b184a218341c`) is in review. | Autopilot `c9ae053a-18ae-4330-be60-fe0291b38d80` runs at 04:00 `America/Los_Angeles`; it stays silent while the PR remains open and healthy, reports and pauses itself once after merge, closure, conflict, or CI failure. |
| 2026-09-28 | Crawler sibling scope -> [#1632](https://github.com/HKUDS/DeepTutor/pull/1632), branch `fix/crawler-seed-scope`, base `dev`; open, mergeable, CI green. | Card `AGEN-24` (`01a0e898-aab1-7804-b38d-b89f750d5ebb`) is in review. | Autopilot `4005eea0-051a-4c26-a951-5262e324c670` runs at 04:00 `America/Los_Angeles`; it stays silent while the PR remains open and healthy, reports and pauses itself once after merge, closure, conflict, or CI failure. |
| 2026-09-29 | [#1429](https://github.com/HKUDS/DeepTutor/issues/1429) -> [#1430](https://github.com/HKUDS/DeepTutor/pull/1430), branch `codex/fix/crawler-robots`, base `dev`; closed without merge after review fix `afcd02318`. | Card `AGEN-38` (`01a0ea51-bc49-7edb-aca4-79dbfae7e0e3`) should be archived or marked closed. | Superseded by upstream `c547a5a31` (tag `v1.6.9`), which lands `web_source/robots.py` for the same issue. |
| 2026-10-01 | [#1676](https://github.com/HKUDS/DeepTutor/issues/1676) -> [#1682](https://github.com/HKUDS/DeepTutor/pull/1682), branch `codex/fix/tutor-latex-selection`, base `dev`; open, mergeable, CI green. | Card `AGEN-72` (`01a0f713-d937-7b12-8995-c21eb1f03715`) is in review. | Autopilot `7ef8784d-02ef-4702-9370-26d5e8c97480` runs at 04:00 `America/Los_Angeles`; it stays silent while the PR remains open and healthy, reports and pauses itself once after merge, closure, conflict, or CI failure. |

## Ports and product deployment

The product ports are fixed:

- Backend: `8001`
- Frontend: `3782`

The launchd services own those ports in the primary checkout. Development
worktrees must not write alternate ports into repository configuration or
`data/user/settings/system.json`. Pass temporary runtime ports explicitly with
environment variables, for example:

```bash
WEB_BASE_URL=http://127.0.0.1:4317
NEXT_PUBLIC_API_BASE=http://127.0.0.1:4318
```

After backend source changes reach the primary checkout, restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.deeptutor.api
```

After frontend source changes reach the primary checkout, rebuild the
production standalone bundle, restart `com.deeptutor.web.3782`, and verify the
changed route returns 200 and contains the new code.

## Upstream contributions

Create small upstream PRs from the latest `origin/dev`, not from the local
product integration history. `origin/main` is only an upstream release
snapshot and must not be used as the working base for PRs that target `dev`.
Keep these fork-local concerns out of upstream PRs unless a maintainer
explicitly asks for them:

- `LOCAL_FEATURES.md` and this workflow document.
- Partner QR onboarding.
- Local MarginNote 4 configuration or launchd setup.
- Temporary ports and local deployment details.

Before creating or updating upstream work, refresh and inspect the upstream
refs without merging them into the primary checkout:

```bash
git fetch origin
git status --short --branch
git rev-list --left-right --count main...origin/dev
```

A fetch only updates remote-tracking refs; it does not synchronize local
`main`. Never pull or merge `origin/dev` into a dirty or divergent primary
checkout. Start new upstream work directly from the fetched ref in an isolated
worktree:

```bash
git -c core.hooksPath=/dev/null worktree add \
  -b codex/<type>/<slug> /tmp/DeepTutor-upstream-<slug> origin/dev
```

The one-shot hook override is required because the primary checkout has a
local-only post-checkout hook; it must not be changed globally or used to skip
the upstream pre-commit checks.

To recover work that exists only on local product branches, create a separate
integration worktree from `origin/dev`, then cherry-pick or rebase only the
still-valid commits and run their focused checks before submitting a PR.

Before creating or updating upstream work, check the issue timeline, linked
and recent PRs, relevant branches, and new commits on `origin/dev`. If another
implementation is active or already landed, review, extend, or close the
existing work rather than building a parallel solution. For PRs that remain
open overnight, refresh `origin/dev` and repeat this audit before further
investment; when upstream fully covers the PR, close it as superseded and
record the covering commit or release.


## Recovery

When a long-lived branch diverges:

1. Preserve it with an explicitly named branch.
2. Recreate the development branch from current `main`.
3. Rebase or cherry-pick only still-valid work.
4. Rerun the focused regression gate.

When `main` fails after consolidation, stop deployment, isolate the failure with
the relevant tests, and fix it through a `fix/...` branch. Do not use history
rewrites to make a broken release disappear.
