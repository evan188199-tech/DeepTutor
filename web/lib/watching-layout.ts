/** Layout policy for Immersive Watching. Kept independent of React so every
 * caller agrees that only one companion pane may be visible at a time. */
export type WatchingWorkspacePane = "focus" | "conversation" | "activity";

export const DEFAULT_WATCHING_WORKSPACE_PANE: WatchingWorkspacePane = "focus";

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
