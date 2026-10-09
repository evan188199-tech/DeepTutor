# web zero-coverage deep test supplement: memory graph + run panel

Date: 2026-10-08 · Base: origin/main @ `6cf793bd8` (release: v1.6.14) · Branch: `agent/agen1189-memory-graph-panel-tests`

## Scope

Zero-coverage components from the `web-test-gaps-20261007` scan
(`web/evidence/web-test-gaps-20261007/summary.json`, `zero` list):

- `web/components/memory/MemoryGraph.tsx` (992 loc) — no test file referenced it
- `web/components/memory/MemoryRunPanel.tsx` (952 loc) — no test file referenced it

Dedup: `web/lib/memory-graph.ts` pure functions (parseDoc / buildGraph /
splitRef) are already covered by `web/tests/lib/memory-graph.test.ts`
(node:test). This supplement only adds the component layer and reuses the
real `buildGraph` with a mocked `fetchMemorySnapshot` transport.

## Deliverable

`web/tests/memory/memory-graph-panel.smoke.spec.tsx` — 15 vitest + Testing
Library component tests (jsdom), no product code changed.

Naming note: the task card suggested `memory-graph-panel.smoke.test.tsx`.
The repo's vitest config (`web/vitest.config.mts`) only picks up
`tests/**/*.spec.ts(x)`; a `.test.tsx` file would never execute, failing the
"Vitest 通过" acceptance criterion. The file is therefore named
`*.spec.tsx`, matching the repo-wide convention for component tests
(`.test.ts` files are compiled separately for the DOM-less node runner).

## Coverage points

MemoryGraph (7 tests):

1. Loading state ("Composing memory graph…"), disabled Refresh, header back
   link `/memory`, then after fetch: 6 visible nodes (L1/L2/L3, `r=0`
   anchors hidden), 4 edges (3 strong L2→L1 + 1 soft L3→surface), legend.
2. Hover opens the preview card (layer label, cluster label, section,
   preview text); pointer-out closes it; both L1 and L2 nodes checked.
3. Node click locks selection: active halo circle rendered, 2-hop highlight
   focuses 3 edges (`stroke-opacity 0.85`) and dims the rest (`0.04`);
   second click releases the selection.
4. Pointer-down on the canvas background clears the selection.
5. Layer toggles: switching L1 off removes its 3 nodes and the 2 incident
   edges, leaving 1 soft edge; toggling back restores 6 nodes / 4 edges.
6. Zoom in / out move the scale readout (0% → 35% → 44% → 35%) with the
   0.35–4× clamp respected; Fit resets it.
7. Refresh re-fetches the snapshot.

MemoryRunPanel (8 tests, mocked `apiFetch` routing + a controllable SSE
`ReadableStream` for run events, mocked `listLLMOptions`):

1. Full update run: idle empty-trace → composer defaults (budget from
   `/api/memory/settings`, active model from options) → POST
   `/api/memory/runs/start` with exact body (layer/key/mode/budget/
   llm_selection/language) → running state (Cancel button, disabled mode
   buttons and budget input, "Working…" row) → streamed events render
   ("Run started", llm turn card with streamed response, prompt
   Disclosure expand) → doc_updated ("Markdown updated", undo depth badge,
   undo locked while running, `onDocUpdated` fired) → done ("Done") →
   run_ended (Run button restored, `onRunComplete` fired once).
2. LLM turn failure: `llm_io_end` with error renders the inline error box
   (replacing "Streaming…"); a run-level `error` event renders the error
   row with its message.
3. Start failure: non-2xx `/api/memory/runs/start` shows the failure text
   inline in the trace and the composer returns to the ready state.
4. Cancel: clicking Cancel POSTs `/api/memory/runs/run-1/cancel`; a
   `cancelled` + `run_ended status=cancelled` pair renders the "Cancelled"
   row and restores the Run button (`onRunComplete` fired).
5. Undo: after `doc_updated` (undo_depth 1) and run completion, Undo is
   enabled with the depth badge; clicking POSTs
   `/api/memory/runs/run-1/undo`; the returned `undo_applied` event renders
   "Undo applied" and clears the badge/affordance; `onDocUpdated` fired
   twice (doc_updated + undo_applied).
6. Reset: requires `window.confirm`; declining POSTs nothing; accepting
   POSTs `/api/memory/doc/L2/chat/reset`, clears the local trace back to
   the empty state and fires `onDocUpdated`.
7. Mode switching: dedup shows the Iter input (settings default), audit
   shows its own budget default (8), typed budget overrides are clamped to
   max 200 and survive mode round-trips (per-mode override state).
8. Model options failure: the model pill shows "Models unavailable" and is
   disabled while Run stays available.

## Defect candidates found

None. All behaviours matched the source expectations; no product code was
changed. (Two test-side adjustments were needed, not defects: the graph
`<svg>` must be scoped by `aria-label` because the header back-link icon is
also an `<svg>`, and layer-toggle buttons have no space in their accessible
name due to adjacent spans.)

## Verification

```
npx vitest run tests/memory/memory-graph-panel.smoke.spec.tsx
  → Test Files 1 passed · Tests 15 passed (15)
npx vitest run                      (whole web suite)
  → Test Files 147 passed (147) · Tests 668 passed (668)
npm run typecheck                   → clean
npx eslint tests/memory/memory-graph-panel.smoke.spec.tsx → clean
```

Upstream PR gate: not applicable — this branch carries the task-mandated
`evidence/` directory, which upstream PR branches must not contain, so no
upstream PR is opened from this branch.
