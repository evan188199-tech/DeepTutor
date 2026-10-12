# zero-mods batch 8 — candidate list evidence (2026-10-12)

Base: origin/main @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df` (release v1.6.14)
Source scan: `evidence/coverage-gaps-20261011/summary.json` `zero_top200`
(root_commit matches this base exactly, so the zero-coverage claim is current).

## Candidates (6 modules, 314 LOC total ≤ 600)

| Module | Path | LOC | fanin | New test file |
| --- | --- | --- | --- | --- |
| utils.error_utils | deeptutor/utils/error_utils.py | 81 | 3 | tests/utils/test_error_formatting.py |
| agents._shared.capability_result | deeptutor/agents/_shared/capability_result.py | 51 | 7 | tests/agents/test_capability_result_emission.py |
| services.session.workspace_preferences | deeptutor/services/session/workspace_preferences.py | 50 | 6 | tests/services/session/test_workspace_preferences_upgrade.py |
| services.embedding.request_options | deeptutor/services/embedding/request_options.py | 46 | 4 | tests/services/embedding/test_request_options.py |
| knowledge.progress_events | deeptutor/knowledge/progress_events.py | 45 | 2 | tests/knowledge/test_progress_events_ports.py |
| runtime.turn_engine | deeptutor/runtime/turn_engine.py | 41 | 5 | tests/runtime/test_turn_engine_forwarding.py |

All six appear in `zero_top200` with `covered = false`.

## Dedupe checks performed

1. Batch 6 (`test/zero-mods-batch6-20261011`, commit `d5699b2af`) covers
   `learning.question_card`, `learning.models`, `learning.visual_practice`,
   `tools.question.question_extractor` — none of the six candidates.
2. Batch 7 (`test/zero-mods-batch7-20261012`, commit `eda80b0ff`) covers
   `book.blocks.callout/flash_cards/timeline`,
   `services.learning_journal.models`, `services.mastery_hints` — none of the six.
3. Backlog / all-status test-* cards checked via Multica issue search
   (titles `test:*` / `*补测*`): excluded modules include
   `api.routers.capabilities_settings`, `tools.web_search`,
   `plugins.transactions`, `runtime.cache_reset`, `partners.channels.qq`,
   `book.agents.spine_agent`, `services.config.origins`,
   `services.config.image_description`, `services.rag.pipelines.llamaindex.errors`,
   `learning.visual_practice` (todo card), `__version__`, `book.errors`,
   `services.llm.provider_registry`. None of the six candidates has a card.
4. Grep over `tests/` at base: no test file imports or exercises the six
   modules (matches in other files are patch targets / local variable names).

## Verification

```
python -m pytest -q -p no:cacheprovider tests/utils/test_error_formatting.py \
  tests/agents/test_capability_result_emission.py \
  tests/services/session/test_workspace_preferences_upgrade.py \
  tests/services/embedding/test_request_options.py \
  tests/knowledge/test_progress_events_ports.py \
  tests/runtime/test_turn_engine_forwarding.py
→ 75 passed (0.85s), run under a 900s alarm

coverage of the six target modules from these tests only → 139 stmts, 0 miss, 100%
```

Neighbor suites (tests/utils, tests/agents, tests/services/embedding,
tests/knowledge, tests/runtime/test_orchestrator.py,
tests/services/session/*): with-batch8 failures are a strict subset of a
pristine-worktree baseline run at the same commit (16 vs 18; the 2 extra
baseline flakes are tests/agents/chat/test_context_budget.py). No new
failures introduced. Pre-existing failures live in agents LLM-binding tests
and are environment-related, untouched by this batch.

Product code untouched: commit contains only `tests/**` and this evidence dir.
