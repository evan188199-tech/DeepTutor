import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_WATCHING_WORKSPACE_PANE,
  inspectorOpenForWatchingPane,
  toggleWatchingActivity,
} from "../lib/watching-layout";

test("Watching starts in focus learning rather than a permanent split", () => {
  assert.equal(DEFAULT_WATCHING_WORKSPACE_PANE, "focus");
  assert.equal(inspectorOpenForWatchingPane("focus"), false);
  assert.equal(inspectorOpenForWatchingPane("conversation"), false);
});

test("Activity replaces the companion pane and toggles back to focus", () => {
  assert.equal(toggleWatchingActivity("focus"), "activity");
  assert.equal(toggleWatchingActivity("conversation"), "activity");
  assert.equal(toggleWatchingActivity("activity"), "focus");
  assert.equal(inspectorOpenForWatchingPane("activity"), true);
});
