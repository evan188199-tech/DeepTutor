"use client";

import { scopedUrl } from "@/lib/workspace-scope";
import { WATCHING_HOME } from "@/lib/learning-routes";
import { browserStorage } from "@/shared/storage";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useSearchParams, useParams } from "next/navigation";
import { invidiousAccountResultMessage } from "@/lib/invidious-account-result";
import { WatchingBrowser } from "./WatchingBrowser";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import type { SessionConfiguration } from "@/features/chat/ChatStateAdapter";
import { WatchingPane, WATCHING_ASK_EVENT } from "./WatchingPane";

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

const LEARNING_LAYOUT_STORAGE_KEY = "dt:watching-learning-layout";
const LEARNING_SPLIT_MIN = 35;
const LEARNING_SPLIT_MAX = 75;
const LEARNING_SPLIT_DEFAULT = 60;

interface LearningLayoutState {
  learning: boolean;
  split: number;
}
const DEFAULT_LEARNING_LAYOUT: LearningLayoutState = {
  learning: false,
  split: LEARNING_SPLIT_DEFAULT,
};

type LearningFullscreen = "off" | "native" | "fallback";

function clampLearningSplit(value: number): number {
  if (!Number.isFinite(value)) return LEARNING_SPLIT_DEFAULT;
  return Math.min(LEARNING_SPLIT_MAX, Math.max(LEARNING_SPLIT_MIN, value));
}

/** Responsive presentation only; ChatWorkspace continues to own the single chat runtime. */
export function WatchingSurface() {
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
      window.history.replaceState(null, "", scopedUrl(WATCHING_HOME));
  }, [params]);
  const showBrowser = browsing && !params.get("video");
  const [view, setView] = useState<"video" | "chat">("video");
  useEffect(() => {
    const showChat = () => setView("chat");
    window.addEventListener(WATCHING_ASK_EVENT, showChat);
    return () => window.removeEventListener(WATCHING_ASK_EVENT, showChat);
  }, []);

  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const splitDragRef = useRef<{ left: number; width: number } | null>(null);
  const [layout, setLayout] = useState<LearningLayoutState>(
    DEFAULT_LEARNING_LAYOUT,
  );
  const { learning, split } = layout;
  const [fullscreen, setFullscreen] = useState<LearningFullscreen>("off");

  const workspaceElement = useCallback(
    () =>
      surfaceRef.current?.closest<HTMLElement>("[data-watching-workspace]") ??
      null,
    [],
  );

  // Restored after mount — not lazily — so the server-rendered markup and the
  // first client render agree; SidebarNav restores its persisted layout the
  // same way. Unreadable values fall back to the defaults.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = browserStorage.readRaw("local", LEARNING_LAYOUT_STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { learning?: unknown; split?: unknown };
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLayout({
        learning: saved.learning === true,
        split:
          typeof saved.split === "number"
            ? clampLearningSplit(saved.split)
            : LEARNING_SPLIT_DEFAULT,
      });
    } catch {
      // Ignore malformed layout preferences.
    }
  }, []);

  useEffect(() => {
    try {
      browserStorage.writeRaw(
        "local",
        LEARNING_LAYOUT_STORAGE_KEY,
        JSON.stringify(layout),
      );
    } catch {
      // Storage may be unavailable; the layout still works for this session.
    }
  }, [layout]);

  // The split variable lives on the shared workspace root so the video pane
  // and the conversation column read one source of truth. Attributes and CSS
  // only — neither runtime unmounts when the layout changes.
  useEffect(() => {
    const root = workspaceElement();
    if (!root) return;
    if (learning) {
      root.style.setProperty("--watching-split", `${clampLearningSplit(split)}%`);
      root.dataset.watchingLearning = "true";
    } else {
      root.style.removeProperty("--watching-split");
      delete root.dataset.watchingLearning;
    }
    return () => {
      root.style.removeProperty("--watching-split");
      delete root.dataset.watchingLearning;
    };
  }, [learning, split, workspaceElement]);

  useEffect(() => {
    const root = workspaceElement();
    if (!root) return;
    if (fullscreen === "fallback")
      root.dataset.watchingFullscreenFallback = "true";
    else delete root.dataset.watchingFullscreenFallback;
    return () => {
      delete root.dataset.watchingFullscreenFallback;
    };
  }, [fullscreen, workspaceElement]);

  useEffect(() => {
    const syncFullscreen = () => {
      const active = document.fullscreenElement != null;
      setFullscreen((current) =>
        active ? "native" : current === "native" ? "off" : current,
      );
    };
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const toggleFullscreen = async () => {
    const root = workspaceElement();
    if (!root) return;
    if (fullscreen === "native") {
      try {
        await document.exitFullscreen();
      } catch {
        // The fullscreenchange listener still syncs state on browser exit.
      }
      return;
    }
    if (fullscreen === "fallback") {
      setFullscreen("off");
      return;
    }
    if (
      typeof root.requestFullscreen !== "function" ||
      !document.fullscreenEnabled
    ) {
      setFullscreen("fallback");
      return;
    }
    try {
      await root.requestFullscreen();
    } catch {
      setFullscreen("fallback");
    }
  };

  const beginSplitDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const root = workspaceElement();
    if (!root) return;
    const rect = root.getBoundingClientRect();
    splitDragRef.current = { left: rect.left, width: rect.width || 1 };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const moveSplitDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = splitDragRef.current;
    if (!drag) return;
    const next = clampLearningSplit(
      ((event.clientX - drag.left) / drag.width) * 100,
    );
    setLayout((current) => ({ ...current, split: next }));
  };

  const endSplitDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!splitDragRef.current) return;
    splitDragRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const nudgeSplit = (direction: 1 | -1) =>
    setLayout((current) => ({
      ...current,
      split: clampLearningSplit(current.split + direction * 2),
    }));

  return (
    <div
      ref={surfaceRef}
      className="watching-surface"
      data-mobile-view={view}
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
        <div className="watching-surface-controls">
          <button
            type="button"
            className="watching-browser-button watching-learning-toggle"
            aria-pressed={learning}
            onClick={() =>
              setLayout((current) => ({ ...current, learning: !current.learning }))
            }
          >
            {t("Learning layout")}
          </button>
          <button
            type="button"
            className="watching-browser-button watching-fullscreen-toggle"
            aria-pressed={fullscreen !== "off"}
            onClick={() => void toggleFullscreen()}
          >
            {fullscreen === "off"
              ? t("Enter fullscreen")
              : t("Exit fullscreen")}
          </button>
          <button
            type="button"
            className="watching-browser-button watching-browse-toggle"
            onClick={() => {
              window.history.replaceState(null, "", scopedUrl(window.location.pathname));
              setBrowsing(true);
            }}
          >
            {t("Browse videos")}
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
          aria-pressed={view === "video"}
          onClick={() => setView("video")}
        >
          {t("Video")}
        </button>
        <button
          type="button"
          aria-pressed={view === "chat"}
          onClick={() => setView("chat")}
        >
          {t("Conversation")}
        </button>
      </div>
      <div className="dt-watching-shell" data-watching-open="true">
        <WatchingPane onClose={() => setView("chat")} />
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t("Video and conversation split")}
          aria-valuemin={LEARNING_SPLIT_MIN}
          aria-valuemax={LEARNING_SPLIT_MAX}
          aria-valuenow={Math.round(split)}
          tabIndex={0}
          className="watching-split-handle"
          onPointerDown={beginSplitDrag}
          onPointerMove={moveSplitDrag}
          onPointerUp={endSplitDrag}
          onPointerCancel={endSplitDrag}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              nudgeSplit(-1);
            } else if (event.key === "ArrowRight") {
              event.preventDefault();
              nudgeSplit(1);
            }
          }}
        />
      </div>
    </div>
  );
}
