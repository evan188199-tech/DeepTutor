# web zero-coverage deep fill: `components/partners/group/useGroupSession.ts`

Date: 2026-10-09
Source scan: `web/evidence/web-test-gaps-20261007/summary.json` — entry
`components/partners/group/useGroupSession.ts` (574 loc, status `zero`).
Baseline: origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df` (release v1.6.14).

## What was added

- `web/tests/partners/use-group-session.spec.tsx` — 36 tests, no product code changed.

Naming note: the task text suggested `use-group-session.test.tsx`, but the web
vitest config only includes `tests/**/*.spec.ts(x)` (`.test.ts` files run under
the node runner, which cannot execute JSX). A `.tsx` renderHook test therefore
follows the repo's `.spec.tsx` convention (same as `tests/hooks/useDragSort.spec.tsx`),
otherwise the file would never run in `npm run test:unit`.

## Test approach

- The browser `WebSocket` global is replaced with a controllable fake; the real
  `ReconnectingWebSocket` class drives it, so reconnect backoff is exercised
  with fake timers. Frames are injected via callbacks — no network access.
- `getPartnerGroupHistory` is mocked with manually resolved promises.
- `lib/stream` stays real: optimistic body growth and retraction recompute are
  part of the behavior under test.

## Coverage points

1. History load: initial `loading`, attach waits for history readiness,
   history failure still finishes loading with an empty transcript.
2. Thread switch: live turn retired declaratively, fresh socket per session,
   attach re-sent with the new session key.
3. Group switch: socket rebuilt for the new group URL.
4. Roster edits: socket survives, new rounds pick up the updated member list
   (no-mention rounds target the whole roster).
5. Panel round lifecycle: user message opens a member-ordered live round;
   traces grow the optimistic body (non-content events do not); a retraction
   marker recomputes the body; partner messages dedupe by event id and retire
   the live seat; `done` clears the round; `error` reports a dismissable
   error; `cancelled` ends quietly; a malformed frame does not tear down the
   session; a late joiner extends targets and sorts last.
6. Follow-up rounds: `partner_started` with an invocation opens a follow-up
   round without a user message and adopts the turn id from the first trace;
   persisted `invocation_question`/`invocation_reply` pairs stay chronological;
   legacy messages without follow-up kinds remain panel rounds.
7. Seat ordering and passes: first-pass messages, `debate_rebuttal` pass 1,
   live second-pass seat placement stays stable while other answers land;
   progress `clash` flags the second pass.
8. Invocations: approve parks in `pendingActions` exactly once and clears on
   `invocation_updated`; a failed send reverts the pending marker; `askPeer`
   auto-approves exactly its own pending invocation once; a disconnected
   `askPeer` arms nothing; updates rewrite the matching persisted message.
9. Cancel/stop: cancel records the live round as stopped before the server
   confirms; failed cancel sends record nothing; persisted `round_stopped`
   markers survive a reload and are not speakers.
10. Errors and retries: a drop disables sending until the backoff reconnect
    lands, then re-attaches; backoff grows across attempts (250ms → 500ms);
    an error event marks disconnect without tearing the socket down; unmount
    stops the socket and a late open cannot resurrect it or schedule retries.
11. Outbound helpers: `send`, `summarizeRound`, `reportConsultationActivity`
    payloads; all helpers are no-ops while disconnected.

## Result

```
npm run test:unit -- tests/partners/use-group-session.spec.tsx
Test Files  1 passed (1)
     Tests  36 passed (36)
```

eslint (scoped to the new file): clean. No product code modified.

## Defect candidates

None found. Behaviors that looked suspicious but are correct by design:

- After `partner_message`, the live seat is retired but a persisted `done`
  seat for the same author appears in the merged round — intended, the
  authoritative message replaces the optimistic one.
- A landed answer can appear after a still-streaming live seat when member
  order wins the pass-rank tie — the live seat itself keeps its slot, which is
  the DOM-stability property the hook documents.
