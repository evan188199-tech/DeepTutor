import assert from "node:assert/strict";
import test from "node:test";

import {
  llmSelectionWithReasoningEffort,
  parseLLMSelection,
} from "../lib/llm-options";

test("parseLLMSelection keeps a stored reasoning-effort override (#641)", () => {
  assert.deepEqual(
    parseLLMSelection({
      profile_id: "p1",
      model_id: "m1",
      reasoning_effort: "high",
    }),
    { profile_id: "p1", model_id: "m1", reasoning_effort: "high" },
  );
  // `none` is a meaningful override, not an empty one.
  assert.deepEqual(
    parseLLMSelection({
      profile_id: "p1",
      model_id: "m1",
      reasoning_effort: "none",
    }),
    { profile_id: "p1", model_id: "m1", reasoning_effort: "none" },
  );
});

test("parseLLMSelection normalizes and drops an empty override", () => {
  assert.deepEqual(
    parseLLMSelection({
      profile_id: " p1 ",
      model_id: "m1",
      reasoning_effort: " High ",
    }),
    { profile_id: "p1", model_id: "m1", reasoning_effort: "high" },
  );
  // Auto: the field must stay absent so the profile default applies.
  assert.deepEqual(
    parseLLMSelection({
      profile_id: "p1",
      model_id: "m1",
      reasoning_effort: "",
    }),
    { profile_id: "p1", model_id: "m1" },
  );
  assert.deepEqual(parseLLMSelection({ profile_id: "p1", model_id: "m1" }), {
    profile_id: "p1",
    model_id: "m1",
  });
});

test("parseLLMSelection rejects malformed payloads", () => {
  assert.equal(parseLLMSelection(null), null);
  assert.equal(parseLLMSelection("p1:m1"), null);
  assert.equal(parseLLMSelection({ profile_id: "p1" }), null);
  assert.equal(parseLLMSelection({ reasoning_effort: "high" }), null);
  // A non-string effort is ignored rather than crashing the session restore.
  assert.deepEqual(
    parseLLMSelection({ profile_id: "p1", model_id: "m1", reasoning_effort: 7 }),
    { profile_id: "p1", model_id: "m1" },
  );
});

test("llmSelectionWithReasoningEffort attaches or clears the override", () => {
  const base = { profile_id: "p1", model_id: "m1" };
  assert.deepEqual(llmSelectionWithReasoningEffort(base, "high"), {
    profile_id: "p1",
    model_id: "m1",
    reasoning_effort: "high",
  });
  // Back to Auto: the override field is removed entirely.
  assert.deepEqual(llmSelectionWithReasoningEffort(
    { ...base, reasoning_effort: "high" },
    "",
  ), base);
  assert.deepEqual(llmSelectionWithReasoningEffort(base, "  "), base);
  assert.equal(llmSelectionWithReasoningEffort(null, "high"), null);
});
