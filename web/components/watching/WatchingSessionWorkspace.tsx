"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Loader2, MessageSquare, Youtube } from "lucide-react";

import { WatchingBrowser } from "@/components/watching/WatchingBrowser";
import { watchingRoute } from "@/lib/learning-routes";
import { sessionRoute } from "@/lib/mastery-session";
import { migrateWatchingSession } from "@/lib/session-api";
import type { TimedMediaMaterial } from "@/lib/video-learning-api";
import { resolveVideo } from "@/lib/video-learning-api";
import {
  bindWatchingMaterial,
  fetchWatchingBinding,
  startWatchingSession,
  type WatchingBinding,
} from "@/lib/watching-session-api";

function WatchingStage({ material }: { material: TimedMediaMaterial }) {
  const { t } = useTranslation();
  const playback = material.playback;
  const title = material.metadata?.title || material.source?.video_id || "";
  const start = Math.max(0, Math.floor(playback.start_seconds || 0));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {start > 0 && (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t("Resuming from your saved progress.")}
          </p>
        )}
      </div>
      {playback.provider === "youtube" ? (
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(playback.video_id)}?start=${start}&rel=0`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          className="aspect-video w-full rounded-xl border border-[var(--border)]"
        />
      ) : (
        <video
          controls
          preload="metadata"
          src={playback.stream_url}
          className="aspect-video w-full rounded-xl border border-[var(--border)] bg-black"
        />
      )}
    </div>
  );
}

export default function WatchingSessionWorkspace({ sessionId = "" }: { sessionId?: string }) {
  const router = useRouter();
  const { t } = useTranslation();
  const [binding, setBinding] = useState<WatchingBinding | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [error, setError] = useState("");
  const [showBrowser, setShowBrowser] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchWatchingBinding(sessionId)
      .then(async (value) => {
        if (cancelled) return;
        if (value.legacy_watching) {
          // Pre-workspace Watching sessions keep migrating to Reading (#1378).
          const migrated = await migrateWatchingSession(sessionId);
          if (!cancelled) {
            router.replace(
              sessionRoute({
                ...migrated,
                message_count: migrated.messages.length,
                last_message: migrated.messages.at(-1)?.content ?? "",
              }),
              { scroll: false },
            );
          }
          return;
        }
        setBinding(value);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, reload, router]);

  const startFromUrl = useCallback(
    async (url: string) => {
      setBusy(true);
      setError("");
      try {
        const material = await resolveVideo(url);
        const created = await startWatchingSession(
          material.material_id,
          material.metadata?.title || "",
        );
        router.push(watchingRoute(created.session_id));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : t("Could not load this section."));
        setBusy(false);
      }
    },
    [router, t],
  );

  const attachToSession = useCallback(
    async (url: string) => {
      if (!sessionId) return;
      setBusy(true);
      setError("");
      try {
        const material = await resolveVideo(url);
        const next = await bindWatchingMaterial(sessionId, material.material_id);
        setBinding(next);
        setShowBrowser(false);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : t("Could not load this section."));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, t],
  );

  const pickHandler = sessionId ? attachToSession : startFromUrl;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-6" data-watching-workspace="">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">{t("Immersive Watching")}</h1>
        <div className="flex items-center gap-2">
          {sessionId && (
            <a
              href={`/chat/${encodeURIComponent(sessionId)}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-xs font-medium"
            >
              <MessageSquare size={13} />
              {t("Open conversation")}
            </a>
          )}
          <button
            type="button"
            onClick={() => setShowBrowser((value) => !value)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-xs font-semibold text-[var(--primary-foreground)]"
          >
            <Youtube size={13} />
            {binding?.material ? t("Change video") : t("Attach a video")}
          </button>
        </div>
      </header>

      <p className="text-sm text-[var(--muted-foreground)]">
        {t(
          "Play a video with the tutor watching alongside you, and ask about whatever is on screen as it runs.",
        )}
      </p>

      {error && (
        <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 px-3 py-2 text-sm">
          {error}{" "}
          <button
            type="button"
            className="underline"
            onClick={() => {
              setError("");
              setReload((value) => value + 1);
            }}
          >
            {t("Retry")}
          </button>
        </div>
      )}

      {loading ? (
        <div role="status" className="flex items-center gap-2 p-6 text-sm">
          <Loader2 size={14} className="animate-spin" />
          {t("Loading…")}
        </div>
      ) : binding?.material ? (
        <WatchingStage material={binding.material} />
      ) : sessionId ? (
        <p className="rounded-xl border border-dashed border-[var(--border)] p-6 text-sm text-[var(--muted-foreground)]">
          {t("No video is attached to this conversation yet.")}
        </p>
      ) : null}

      {(showBrowser || (!sessionId && !binding)) && (
        <WatchingBrowser
          canDismiss={Boolean(sessionId)}
          onDismiss={() => setShowBrowser(false)}
          onSelectUrl={(url) => void pickHandler(url)}
        />
      )}

      {busy && (
        <div role="status" className="flex items-center gap-2 text-sm">
          <Loader2 size={14} className="animate-spin" />
          {t("Loading…")}
        </div>
      )}
    </div>
  );
}
