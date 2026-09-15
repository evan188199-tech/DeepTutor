"use client";

/**
 * The shared right-side workspace Inspector.
 *
 * The original implementation lives with the chat home components because
 * chat was its first consumer. Exporting the neutral name here gives each
 * workspace one stable entry point while the following adoption change moves
 * the remaining callers away from the chat-specific import path.
 */
export {
  default as WorkspaceInspector,
  default,
} from "@/components/chat/home/SessionViewerPanel";
export type {
  SessionViewerPanelHandle as WorkspaceInspectorHandle,
} from "@/components/chat/home/SessionViewerPanel";
