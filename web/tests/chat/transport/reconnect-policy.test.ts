import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  reconnectDelay,
  shouldReconnect,
} from "../../../features/chat/transport/reconnect-policy";

const webRoot = process.cwd();

const BASE_DELAY_MS = 250;
const MAX_DELAY_MS = 8_000;
const JITTER_LOW = 0.8;
const JITTER_HIGH = 1.2;
const WORST_CASE_RUNG_MS = Math.round(MAX_DELAY_MS * JITTER_HIGH);

const GATE_SITES = [
  {
    label: "QuizFollowupContext",
    file: "context/QuizFollowupContext.tsx",
  },
  {
    label: "ChatStateAdapter",
    file: "features/chat/ChatStateAdapter.tsx",
  },
  {
    label: "BookChatPanel",
    file: "app/(workspace)/learning/books/components/BookChatPanel.tsx",
  },
  {
    label: "whisper page",
    file: "app/(workspace)/whisper/page.tsx",
  },
] as const;

function readSource(relativePath: string): string {
  return fs.readFileSync(path.join(webRoot, relativePath), "utf8");
}

function resolveNamedConstant(name: string): number {
  const searchRoots = ["lib", path.join("features", "chat", "transport"), "shared"];
  const pattern = new RegExp(`(?:export\\s+)?const\\s+${name}\\s*=\\s*(\\d+)`);
  for (const root of searchRoots) {
    const absoluteRoot = path.join(webRoot, root);
    if (!fs.existsSync(absoluteRoot)) continue;
    const stack = [absoluteRoot];
    while (stack.length > 0) {
      const directory = stack.pop()!;
      for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const target = path.join(directory, entry.name);
        if (entry.isDirectory()) {
          stack.push(target);
          continue;
        }
        if (!/\.tsx?$/.test(entry.name)) continue;
        const match = pattern.exec(fs.readFileSync(target, "utf8"));
        if (match) return Number(match[1]);
      }
    }
  }
  throw new Error(
    `submit gate references constant ${name} but no numeric definition was found under ${searchRoots.join(", ")}`,
  );
}

type GateBudget = { limit: number; intervalMs: number };

function parseGateBudget(source: string, file: string): GateBudget {
  const limitMatch = /if\s*\(\s*attempt\s*>=\s*(\d+|[A-Z_][A-Z0-9_]*)\s*\)/.exec(
    source,
  );
  assert.ok(
    limitMatch,
    `${file}: submit gate shape changed — no "if (attempt >= N)" branch found; update this contract test`,
  );
  const limitToken = limitMatch[1];
  const setTimeoutIndex = source.indexOf("setTimeout", limitMatch.index);
  assert.ok(
    setTimeoutIndex !== -1,
    `${file}: submit gate shape changed — no setTimeout retry after the gate`,
  );
  const tail = source.slice(setTimeoutIndex, setTimeoutIndex + 400);
  const intervalMatch = /,\s*(\d+|[A-Z_][A-Z0-9_]*)\s*,?\s*\)/.exec(tail);
  assert.ok(
    intervalMatch,
    `${file}: submit gate shape changed — could not read the retry interval`,
  );
  const resolve = (token: string): number =>
    /^\d+$/.test(token) ? Number(token) : resolveNamedConstant(token);
  return {
    limit: resolve(limitToken),
    intervalMs: resolve(intervalMatch[1]),
  };
}

function gateBudgets(): Array<{ label: string; file: string } & GateBudget> {
  return GATE_SITES.map(({ label, file }) => ({
    label,
    file,
    ...parseGateBudget(readSource(file), file),
  }));
}

function jitterNeutralRung(attempt: number): number {
  return reconnectDelay(attempt, () => 0.5);
}

function cumulativeReconnectMs(rungs: number): number {
  let total = 0;
  for (let attempt = 0; attempt < rungs; attempt += 1) {
    total += jitterNeutralRung(attempt);
  }
  return total;
}

test("reconnect ladder grows exponentially from 250ms and caps at 8s", () => {
  const expected = [250, 500, 1_000, 2_000, 4_000, 8_000];
  expected.forEach((value, attempt) => {
    assert.equal(
      jitterNeutralRung(attempt),
      value,
      `reconnectDelay(attempt=${attempt}) drifted`,
    );
  });
  for (let attempt = 6; attempt <= 10; attempt += 1) {
    assert.equal(
      jitterNeutralRung(attempt),
      MAX_DELAY_MS,
      `reconnectDelay(attempt=${attempt}) must stay pinned at the cap`,
    );
  }
});

test("reconnect jitter stays within 0.8x..1.2x of each exponential rung", () => {
  for (let attempt = 0; attempt <= 8; attempt += 1) {
    const exponential = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
    const low = Math.round(exponential * JITTER_LOW);
    const high = Math.round(exponential * JITTER_HIGH);
    assert.equal(reconnectDelay(attempt, () => 0), low);
    assert.equal(reconnectDelay(attempt, () => 1), high);
    for (const draw of [0.25, 0.5, 0.75]) {
      const delay = reconnectDelay(attempt, () => draw);
      assert.ok(
        delay >= low && delay <= high,
        `reconnectDelay(attempt=${attempt}, random=${draw}) = ${delay} left [${low}, ${high}]`,
      );
    }
  }
  assert.equal(
    reconnectDelay(8, () => 1),
    WORST_CASE_RUNG_MS,
    "worst-case rung (cap x 1.2 jitter) is the budget floor this suite pins",
  );
});

test("shouldReconnect keeps the ladder alive for active turns and bounded idle retries", () => {
  assert.equal(
    shouldReconnect({ attempt: 0, activeTurnId: "turn-1", pageVisible: false }),
    true,
    "an active turn must reconnect regardless of visibility",
  );
  assert.equal(
    shouldReconnect({ attempt: 0, activeTurnId: null, pageVisible: false }),
    false,
    "idle + hidden must not reconnect",
  );
  assert.equal(
    shouldReconnect({ attempt: 4, activeTurnId: null, pageVisible: true }),
    true,
    "idle but visible keeps retrying below the idle attempt limit",
  );
  assert.equal(
    shouldReconnect({ attempt: 5, activeTurnId: null, pageVisible: true }),
    false,
    "idle retries stop at the idle attempt limit",
  );
});

test("all four submit gates share one retry budget", () => {
  const budgets = gateBudgets();
  const first = budgets[0];
  for (const gate of budgets) {
    assert.equal(
      gate.limit,
      first.limit,
      `${gate.label} retry limit drifted from ${first.label}`,
    );
    assert.equal(
      gate.intervalMs,
      first.intervalMs,
      `${gate.label} retry interval drifted from ${first.label}`,
    );
  }
});

test("submit gate give-up is bounded and reports a user-facing failure", () => {
  for (const gate of gateBudgets()) {
    assert.ok(gate.limit > 0, `${gate.label}: retry limit must be positive`);
    assert.ok(
      gate.intervalMs > 0,
      `${gate.label}: retry interval must be positive`,
    );
    const budgetMs = gate.limit * gate.intervalMs;
    assert.ok(
      budgetMs <= 60_000,
      `${gate.label}: give-up budget ${budgetMs}ms must stay bounded`,
    );
    const source = readSource(gate.file);
    const limitMatch = /if\s*\(\s*attempt\s*>=/.exec(source);
    assert.ok(limitMatch, `${gate.file}: gate branch disappeared`);
    const giveUpBlock = source.slice(limitMatch.index, limitMatch.index + 600);
    assert.match(
      giveUpBlock,
      /error|Connection failed|notify\(/i,
      `${gate.label}: exhausting the wait must surface a user-facing failure`,
    );
  }
});

test("submit retry budget covers the worst-case reconnect rung", () => {
  const budgets = gateBudgets();
  for (const gate of budgets) {
    const budgetMs = gate.limit * gate.intervalMs;
    assert.ok(
      budgetMs >= WORST_CASE_RUNG_MS,
      `${gate.label} submit budget is ${budgetMs}ms (${gate.limit} x ${gate.intervalMs}ms) but one reconnect rung can take up to ${WORST_CASE_RUNG_MS}ms — a submit issued mid-reconnect gives up before the socket returns. Raise the submit budget above the reconnect ladder (see upstream #1648).`,
    );
  }
});

test("a submit issued mid-reconnect is delivered anywhere on the reconnect ladder", () => {
  const { limit, intervalMs } = gateBudgets()[0];
  const reachablePollsMs = (limit - 1) * intervalMs;
  const table: string[] = [];
  for (let rungs = 0; rungs <= 4; rungs += 1) {
    const reconnectAt = cumulativeReconnectMs(rungs);
    table.push(`rungs 0..${rungs}: reconnect lands at ${reconnectAt}ms`);
    assert.ok(
      reachablePollsMs >= reconnectAt,
      `submit wait window is ${reachablePollsMs}ms (last poll of ${limit} x ${intervalMs}ms) but the socket reconnects only after ${reconnectAt}ms when the ladder reaches rung ${rungs}.\n${table.join("\n")}\nThe submit gives up first and reports a false expiry (upstream #1648).`,
    );
  }
});
