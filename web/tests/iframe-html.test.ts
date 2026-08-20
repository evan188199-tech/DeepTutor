import test from "node:test";
import assert from "node:assert/strict";

import {
  parseIframeLearningOutcome,
  prepareIframeHtml,
} from "../lib/iframe-html";

function bridgeSource(): string {
  const prepared = prepareIframeHtml(
    "<!doctype html><html><head></head><body><main>content</main></body></html>",
  );
  const match = prepared.match(/<script data-dt-bridge>([\s\S]*?)<\/script>/);
  assert.ok(match, "prepared iframe HTML should contain the host bridge");
  return match[1];
}

function runBridge(source: string) {
  const messages: unknown[] = [];
  const fakeWindow = {
    crypto: {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(7);
        return bytes;
      },
    },
    addEventListener: () => undefined,
  };
  const fakeDocument = {
    body: {},
    addEventListener: () => undefined,
  };
  const fakeParent = {
    postMessage: (message: unknown) => {
      messages.push(message);
    },
  };

  new Function("window", "parent", "document", source)(
    fakeWindow,
    fakeParent,
    fakeDocument,
  );
  return { window: fakeWindow, messages };
}

test("iframe bridge measures current body content instead of historical viewport height", () => {
  const source = bridgeSource();

  assert.match(source, /body\.scrollHeight > 0/);
  assert.doesNotMatch(
    source,
    /Math\.max\(document\.documentElement\.scrollHeight/,
  );
});

test("iframe bridge observes layout and tab-content changes with coalescing", () => {
  const source = bridgeSource();

  assert.match(source, /new ResizeObserver\(scheduleHeightReport\)/);
  assert.match(source, /new MutationObserver\(scheduleHeightReport\)/);
  assert.match(source, /characterData: true/);
  assert.match(source, /childList: true/);
  assert.match(source, /subtree: true/);
  assert.match(source, /requestAnimationFrame\(run\)/);
});

test("iframe bridge exposes the learning outcome contract", () => {
  const source = bridgeSource();

  assert.match(source, /window\.reportLearningOutcome/);
  assert.match(source, /dt:learning-outcome/);
  assert.match(source, /schemaVersion: 1/);
  assert.match(source, /eventId/);
});

test("reportLearningOutcome posts a versioned bridge message", () => {
  const { window, messages } = runBridge(bridgeSource());
  const accepted = (
    window as unknown as {
      reportLearningOutcome: (outcome: unknown) => boolean;
    }
  ).reportLearningOutcome({
    objectiveIds: ["obj_one"],
    activityType: "parameter_change",
    result: "completed",
    payload: { parameter: "slope" },
    eventId: "event_one",
    occurredAt: 1_760_000_000_000,
  });

  assert.equal(accepted, true);
  assert.deepEqual(messages, [
    {
      type: "dt:learning-outcome",
      schemaVersion: 1,
      eventId: "event_one",
      occurredAt: 1_760_000_000,
      objectiveIds: ["obj_one"],
      activityType: "parameter_change",
      result: "completed",
      payload: { parameter: "slope" },
    },
  ]);
});

test("reportLearningOutcome rejects payloads over 8 KiB in UTF-8", () => {
  const { window, messages } = runBridge(bridgeSource());
  const accepted = (
    window as unknown as {
      reportLearningOutcome: (outcome: unknown) => boolean;
    }
  ).reportLearningOutcome({
    objectiveIds: [],
    activityType: "parameter_change",
    result: "completed",
    payload: { value: "课".repeat(3000) },
  });

  assert.equal(accepted, false);
  assert.deepEqual(messages, []);
});

test("learning outcomes accept declared objective ids and de-duplicate them", () => {
  const parsed = parseIframeLearningOutcome(
    {
      type: "dt:learning-outcome",
      schemaVersion: 1,
      eventId: "event_one",
      occurredAt: 1,
      objectiveIds: ["obj_allowed", "obj_allowed"],
      activityType: "parameter_change",
      result: "completed",
      payload: { parameter: "slope" },
    },
    ["obj_allowed"],
  );

  assert.deepEqual(parsed?.objectiveIds, ["obj_allowed"]);
  assert.equal(parsed?.payload.parameter, "slope");
});

test("learning outcomes reject any objective id not declared by the block", () => {
  const parsed = parseIframeLearningOutcome(
    {
      type: "dt:learning-outcome",
      schemaVersion: 1,
      eventId: "event_one",
      occurredAt: 1,
      objectiveIds: ["obj_allowed", "obj_injected"],
      activityType: "parameter_change",
      result: "completed",
      payload: {},
    },
    ["obj_allowed"],
  );

  assert.equal(parsed, null);
});

test("learning outcome timestamps are normalized to Unix seconds", () => {
  const parsed = parseIframeLearningOutcome(
    {
      type: "dt:learning-outcome",
      schemaVersion: 1,
      eventId: "event_one",
      occurredAt: 1_760_000_000_000,
      objectiveIds: [],
      activityType: "parameter_change",
      result: "completed",
      payload: {},
    },
    [],
  );

  assert.equal(parsed?.occurredAt, 1_760_000_000);
});

test("learning outcome payload limits use UTF-8 bytes", () => {
  const message = {
    type: "dt:learning-outcome",
    schemaVersion: 1,
    eventId: "event_one",
    occurredAt: 1,
    objectiveIds: [],
    activityType: "parameter_change",
    result: "completed",
  };

  assert.equal(
    parseIframeLearningOutcome({ ...message, payload: { value: "课".repeat(3000) } }, []),
    null,
  );
});

test("invalid learning outcome messages are ignored", () => {
  const base = {
    type: "dt:learning-outcome",
    schemaVersion: 1,
    eventId: "event_one",
    occurredAt: 1,
    objectiveIds: [],
    activityType: "parameter_change",
    result: "completed",
    payload: {},
  };

  assert.equal(parseIframeLearningOutcome(base, [])?.schemaVersion, 1);
  assert.equal(parseIframeLearningOutcome({ ...base, schemaVersion: 2 }, []), null);
  assert.equal(parseIframeLearningOutcome({ ...base, result: "excellent" }, []), null);
  assert.equal(parseIframeLearningOutcome({ ...base, eventId: " " }, []), null);
  assert.equal(
    parseIframeLearningOutcome({ ...base, objectiveIds: ["x".repeat(129)] }, []),
    null,
  );
});
