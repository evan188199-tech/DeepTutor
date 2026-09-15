import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_WATCHING_LEARNING_PANEL_POSITION,
  DEFAULT_WATCHING_WORKSPACE_PANE,
  effectiveWatchingLearningPanelPosition,
  inspectorOpenForWatchingPane,
  isWatchingLearningPanelPosition,
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

test("learning panel starts below and only moves right in focus", () => {
  assert.equal(DEFAULT_WATCHING_LEARNING_PANEL_POSITION, "below");
  assert.equal(effectiveWatchingLearningPanelPosition("right", "focus"), "right");
  assert.equal(
    effectiveWatchingLearningPanelPosition("right", "conversation"),
    "below",
  );
  assert.equal(effectiveWatchingLearningPanelPosition("right", "activity"), "below");
});

test("only known persisted learning panel positions are accepted", () => {
  assert.equal(isWatchingLearningPanelPosition("below"), true);
  assert.equal(isWatchingLearningPanelPosition("right"), true);
  assert.equal(isWatchingLearningPanelPosition("sideways"), false);
  assert.equal(isWatchingLearningPanelPosition(null), false);
});
