"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams, useParams } from "next/navigation";
import { invidiousAccountResultMessage } from "@/lib/invidious-account-result";
import { WatchingBrowser } from "./WatchingBrowser";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import type { SessionConfiguration } from "@/features/chat/ChatStateAdapter";
import { WatchingPane, WATCHING_ASK_EVENT } from "./WatchingPane";
import { browserStorage } from "@/shared/storage";
import {
  DEFAULT_WATCHING_LEARNING_PANEL_POSITION,
  DEFAULT_WATCHING_WORKSPACE_PANE,
  effectiveWatchingLearningPanelPosition,
  isWatchingLearningPanelPosition,
  type WatchingLearningPanelPosition,
  type WatchingWorkspacePane,
} from "@/lib/watching-layout";

/** The desktop panes are mutually exclusive: focus protects the learning
 * surface, while conversation and activity each own the companion column. */
export type {
  WatchingLearningPanelPosition,
  WatchingWorkspacePane,
} from "@/lib/watching-layout";

const LEARNING_PANEL_POSITION_KEY = "dt:watching:learning-panel-position";

/** Bind the existing player to the selected conversation, never browser-global history. */
export function WatchingSessionBridge({
  sessionKey,
  materialId,
  onMaterial,
  sourceUrl,
}: {
  sourceUrl?: string | null;
  sessionKey: string;
  materialId: string | null;
  onMaterial(configuration: SessionConfiguration): void;
}) {
  const { material, loading, error, restore, close, openUrl } = useWatching();
  const [restoredKey, setRestoredKey] = useState<string | null>(null);
  const binding = useRef(materialId);
  useEffect(() => {
    binding.current = materialId;
  }, [materialId]);
  useEffect(() => {
    let cancelled = false;
    void restore(sourceUrl ? null : binding.current).then(async () => {
      if (cancelled) return;
      if (sourceUrl) await openUrl(sourceUrl);
      if (!cancelled) setRestoredKey(sessionKey);
    });
    return () => {
      cancelled = true;
      close();
    };
  }, [sessionKey, sourceUrl, restore, close, openUrl]);
  useEffect(() => {
    if (
      restoredKey !== sessionKey ||
      loading ||
      error ||
      (material?.material_id ?? null) === materialId
    )
      return;
    onMaterial({ timedMediaId: material?.material_id ?? null });
  }, [
    restoredKey,
    sessionKey,
    material,
    materialId,
    loading,
    error,
    onMaterial,
  ]);
  return null;
}

/** Responsive presentation only; ChatWorkspace continues to own the single chat runtime. */
export function WatchingSurface({
  pane = DEFAULT_WATCHING_WORKSPACE_PANE,
  onPaneChange = () => {},
}: {
  pane?: WatchingWorkspacePane;
  onPaneChange?: (pane: WatchingWorkspacePane) => void;
}) {
  const { t } = useTranslation();
  const { material } = useWatching();
  const params = useSearchParams();
  const route = useParams();
  const [browsing, setBrowsing] = useState(
    !params.get("video") && !route.sessionId,
  );
  const [accountResult, setAccountResult] = useState(params.get("account"));
  const accountMessage = invidiousAccountResultMessage(accountResult);
  useEffect(() => {
    if (params.has("account"))
      window.history.replaceState(null, "", "/watching");
  }, [params]);
  const showBrowser = browsing && !params.get("video");
  // Start below on both server and first client paint, then restore the
  // learner's preference after mount so this never creates a hydration shift.
  const [learningPanelPosition, setLearningPanelPosition] =
    useState<WatchingLearningPanelPosition>(
      DEFAULT_WATCHING_LEARNING_PANEL_POSITION,
    );
  useEffect(() => {
    const stored = browserStorage.readRaw(
      "local",
      LEARNING_PANEL_POSITION_KEY,
    );
    if (!isWatchingLearningPanelPosition(stored)) return;
    // Yield first so the server/default-below markup hydrates unchanged.
    const frame = window.requestAnimationFrame(() =>
      setLearningPanelPosition(stored),
    );
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const selectLearningPanelPosition = (
    position: WatchingLearningPanelPosition,
  ) => {
    setLearningPanelPosition(position);
    browserStorage.writeRaw("local", LEARNING_PANEL_POSITION_KEY, position);
  };
  const effectiveLearningPanelPosition =
    effectiveWatchingLearningPanelPosition(learningPanelPosition, pane);
  useEffect(() => {
    const showChat = () => onPaneChange("conversation");
    window.addEventListener(WATCHING_ASK_EVENT, showChat);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, showChat);
  }, [onPaneChange]);
  return (
    <div
      className="watching-surface"
      data-watching-pane={pane}
      data-browsing={showBrowser || undefined}
    >
      {accountMessage && showBrowser && (
        <div
          role={accountResult === "connected" ? "status" : "alert"}
          className="watching-account-error flex items-center justify-between gap-3"
        >
          <span>{t(accountMessage)}</span>
          <button
            type="button"
            className="watching-browser-button shrink-0"
            onClick={() => setAccountResult(null)}
          >
            {t("Dismiss")}
          </button>
        </div>
      )}
      {showBrowser && (
        <WatchingBrowser
          canDismiss={!!material}
          onDismiss={() => setBrowsing(false)}
        />
      )}
      {!showBrowser && (
        <button
          className="watching-browse-toggle watching-browser-button"
          onClick={() => {
            window.history.replaceState(null, "", window.location.pathname);
            setBrowsing(true);
          }}
        >
          {t("Browse videos")}
        </button>
      )}
      <div
        className="watching-workspace-switcher"
        role="group"
        aria-label={t("Learning workspace")}
      >
        <button
          type="button"
          aria-pressed={pane === "focus"}
          onClick={() => onPaneChange("focus")}
        >
          {t("Focus")}
        </button>
        <button
          type="button"
          aria-pressed={pane === "conversation"}
          onClick={() => onPaneChange("conversation")}
        >
          {t("Discuss")}
        </button>
        <button
          type="button"
          aria-pressed={pane === "activity"}
          onClick={() => onPaneChange("activity")}
        >
          {t("Activity")}
        </button>
      </div>
      {pane === "focus" && !showBrowser && (
        <div
          className="watching-learning-position"
          role="radiogroup"
          aria-label={t("Learning panel position")}
        >
          <button
            type="button"
            role="radio"
            aria-checked={learningPanelPosition === "below"}
            onClick={() => selectLearningPanelPosition("below")}
          >
            {t("Below video")}
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={learningPanelPosition === "right"}
            onClick={() => selectLearningPanelPosition("right")}
          >
            {t("Right of video")}
          </button>
        </div>
      )}
      <div
        className="watching-mobile-tabs"
        role="group"
        aria-label={t("Immersive Watching")}
      >
        <button
          type="button"
          aria-pressed={pane === "focus"}
          onClick={() => onPaneChange("focus")}
        >
          {t("Video")}
        </button>
        <button
          type="button"
          aria-pressed={pane === "conversation"}
          onClick={() => onPaneChange("conversation")}
        >
          {t("Conversation")}
        </button>
        <button
          type="button"
          aria-pressed={pane === "activity"}
          onClick={() => onPaneChange("activity")}
        >
          {t("Activity")}
        </button>
      </div>
      <div className="dt-watching-shell" data-watching-open="true">
        <WatchingPane
          learningPanelPosition={effectiveLearningPanelPosition}
          onClose={() => onPaneChange("conversation")}
        />
      </div>
    </div>
  );
}
