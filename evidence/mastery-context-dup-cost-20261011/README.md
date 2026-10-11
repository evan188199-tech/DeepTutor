# Evidence: Mastery Path replayed-history duplication cost

Measures how much of a Mastery Path conversation's assembled model context is
repeated historical state — the evidence side of upstream #1920 and #1926.
This directory contains measurement code and numbers only; no source changes.

- Method and raw numbers: `results.md` (machine-readable: `results.json`)
- Reproduce: `/Users/Shared/DeepTutor/.venv/bin/python evidence/mastery-context-dup-cost-20261011/measure_context_dup.py`
  (offline; no LLM call, no server, no network; deterministic fixture)

## Headline numbers (6 modules × 8 KPs fixture, M size)

- 94–99% of replayed-history bytes are `role=tool` messages (mastery state
  maps), not learner/tutor dialogue. Dialogue-only baseline: 12.4 KB / ~3.1k
  tokens at 20 turns; mastery M at 20 turns: 1.17 MB / ~358k tokens.
- ~48–56% of all replayed-history bytes are **exact duplicate JSON subtrees**
  — payload keys byte-identical to an earlier tool result in the same history.
  Whole messages are almost never byte-identical (<2%), because volatile
  counters (`path_revision`, one KP's `mastery`) fracture an otherwise
  unchanged result.
- One new turn with 3 main-loop rounds re-sends the same history ~3.1×
  (measured per-round estimates: e.g. 184k / 191k / 198k tokens).
- Two consecutive `mastery_status` calls that differ by one graded knowledge
  point: **89.7% of the `map` key's bytes are byte-identical per-KP entries**.
  The `map` key alone is 78% of the payload (16,238 of 20,733 B).

## Assembly path × duplication channel × size (static findings)

| # | assembly stage | what it duplicates | evidence |
|---|---|---|---|
| 1 | Verbatim replay of every prior turn, including all tool results | Full `mastery_status` / `mastery_build` / `mastery_revise` / quiz / grade results re-enter every later request; the replay code has no dedup or reference mechanism | `deeptutor/services/session/model_history.py:157-167` (`replay_history` concatenates groups), `deeptutor/services/session/model_history.py:124-142` (`replay_group` prefers the complete model exchange) |
| 2 | Per-round carriage inside one turn | The whole conversation (system + replayed history + earlier rounds) is re-sent by every main-loop round of the turn; measured ratio ≈ 3.1× at 3 rounds | `deeptutor/agents/loop/agent_loop.py:410-475` (round loop), `deeptutor/agents/loop/agent_loop.py:718-728` (round appended to the same list), `deeptutor/agents/loop/pipeline.py:490-495` (`messages.extend(deepcopy(history))`) |
| 3 | Turn persistence feeding channel 1 | The full turn — snapshots, tool call/result exchanges — is stored as one `model_turn` record and is exactly what channel 1 replays next turn | `deeptutor/agents/loop/agent_loop.py:355-366`, `deeptutor/services/session/turns/executor.py:928-931` |
| 4 | Runtime-snapshot accumulation | When a runtime block changes, a new `_context_snapshot` user row is appended; earlier copies stay in the replayed history at their original position. Small at fixture scale (0.35%) but grows linearly and is pure superseded text | `deeptutor/agents/loop/pipeline.py:515-527`, `deeptutor/agents/loop/prompt_blocks.py:27-40` (`RUNTIME_BLOCK_NAMES`), `deeptutor/agents/loop/prompt_blocks.py:99-117` (`split_for_replay`) |
| 5 | Oversized, mostly-static status payloads | `mastery_status` returns the full path map + per-KP `learning_stages` + `visual_requirements` + learner profile on every call ("Returned by mastery_status on every round"); 4 different tools each return the full `map_summary` | `deeptutor/capabilities/mastery/tools.py:764-823`, `deeptutor/capabilities/mastery/tools.py:507-511`, `deeptutor/learning/policy.py:365-419`, full-map results at `tools.py:775`, `tools.py:1752`, `tools.py:1913`, `tools.py:2337` |
| 6 | Budget policy admits large tool-JSON history | The history plan measures the serialized replay (tool JSON at full cost) against 0.35 × window capped at 131,072 tokens; under budget, the verbatim replay is returned as-is — no pressure toward dedup before compaction | `deeptutor/services/session/context_builder.py:37-39`, `deeptutor/services/session/context_builder.py:205-226`, `deeptutor/services/session/context_builder.py:309-311`, `deeptutor/services/session/context_builder.py:555-565` |
| 7 | Mastery uses the generic loop engine unchanged | `MasteryLoopPipeline` only swaps prompt blocks; every channel above applies to it unmodified | `deeptutor/capabilities/mastery/pipeline.py:57-70` |

Matrix numbers per scenario: `results.md` / `results.json`.

## Fix leads (for the #1926/#1920 fix cards; not implemented here)

1. **Reference stable subtrees at replay time** (channel 1): when assembling a
   request, replace byte-identical repeated subtrees in historical mastery
   results with a reference to the newest full copy in the same request — the
   measured ceiling is ~48–56% of history bytes; #1920 reports a conservative
   20–22% realized locally. Fragmentation point: volatile keys
   (`path_revision`, changed KP entries) must stay full so the fracture does
   not defeat the hash.
2. **Superseded-state collapse** (channels 1+3): historical `mastery_status` /
   `mastery_build` / `mastery_revise` results are authoritative-state reads,
   not learner evidence. Replay only the newest copy per tool (or per state
   epoch) and keep the full original in the persisted record/archive, which
   already exists independently of the prompt
   (`deeptutor/services/session/model_history.py:170-187` shows replay is a
   projection; persistence is separate).
3. **Shrink the payload itself** (channel 5): `visual_requirements` and
   `learning_stages` restate per-KP state already present in `map.modules`
   entries; `map` is 78% of the payload and 89.7% of its per-KP bytes are
   unchanged between consecutive calls. Emitting stable sections on demand or
   keying by `path_revision` would cut every future copy.
4. **Carriage cost is a multiplier** (channel 2): per-round re-send is
   protocol-shaped, so savings must come from shrinking the base history
   (leads 1–3); every 10% off the base saves ~30% of a 3-round turn's input.
5. **Budget weighting** (channel 6): counting tool JSON at full serialized
   cost in the history plan lets state maps crowd out dialogue before
   compaction; weighting or collapsing state reads inside the plan would
   align the budget with information content.

## Limitations

- Fixture payloads are synthetic but shape-faithful (built from the tool
  payload construction sites listed above); absolute sizes scale with real
  outline sizes and dialogue lengths.
- Token counts are planning estimates (`tiktoken/cl100k_base` over serialized
  JSON plus image allowances), matching the app's own estimator — not
  provider-reported billing.
- Compaction (summarize + recent tail) is not simulated; the measurements
  cover the pre-compaction replay path, which is the regime the 59–64k-token
  calls reported in #1926/#1920 were observed in.
- Runtime snapshots measure small here because the fixture profile text is
  short; real `sources` / `memory` manifests can be larger.
