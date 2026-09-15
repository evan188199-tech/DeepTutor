/** Layout policy for Immersive Watching. Kept independent of React so every
 * caller agrees that only one companion pane may be visible at a time. */
export type WatchingWorkspacePane = "focus" | "conversation" | "activity";
export type WatchingLearningPanelPosition = "below" | "right";

export const DEFAULT_WATCHING_WORKSPACE_PANE: WatchingWorkspacePane = "focus";
export const DEFAULT_WATCHING_LEARNING_PANEL_POSITION: WatchingLearningPanelPosition =
  "below";

/** A right-side learning panel belongs to Focus only. Discuss and Activity
 * already own Watching's companion column, so retaining it there would turn
 * the workspace back into the three-column squeeze this layout prevents. */
export function effectiveWatchingLearningPanelPosition(
  preferred: WatchingLearningPanelPosition,
  pane: WatchingWorkspacePane,
): WatchingLearningPanelPosition {
  return pane === "focus" ? preferred : "below";
}

export function isWatchingLearningPanelPosition(
  value: string | null,
): value is WatchingLearningPanelPosition {
  return value === "below" || value === "right";
}

export function inspectorOpenForWatchingPane(
  pane: WatchingWorkspacePane,
): boolean {
  return pane === "activity";
}

export function toggleWatchingActivity(
  pane: WatchingWorkspacePane,
): WatchingWorkspacePane {
  return pane === "activity" ? "focus" : "activity";
}
