"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookmarkPlus,
  CheckCircle2,
  Clock,
  ExternalLink,
  Flame,
  Globe,
  History,
  ListVideo,
  Loader2,
  LogIn,
  LogOut,
  Play,
  RotateCcw,
  Search,
  Sparkles,
  StickyNote,
  Tv,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  InvidiousFeedItem,
  InvidiousHomeFeed,
  disconnectInvidious,
  disconnectYouTubeSession,
  connectYouTubeSession,
  getInvidiousAuthorizeUrl,
  getInvidiousHome,
  getYouTubeConnectOperation,
  getYouTubeSessionStatus,
  type YouTubeSessionStatus,
} from "@/lib/video-learning-api";

interface InvidiousHomeProps {
  onSelectVideo: (url: string) => Promise<boolean>;
  onOpenInvidious?: () => void;
  onClose?: () => void;
  initialUrl?: string;
  openingInvidious?: boolean;
  openMessage?: string;
  fallbackOpenUrl?: string;
  openingVideo?: boolean;
}

export function InvidiousHome({
  onSelectVideo,
  onOpenInvidious,
  onClose,
  initialUrl = "",
  openingInvidious = false,
  openMessage = "",
  fallbackOpenUrl = "",
  openingVideo = false,
}: InvidiousHomeProps) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(initialUrl);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feed, setFeed] = useState<InvidiousHomeFeed | null>(null);
  const [activeTab, setActiveTab] = useState<string>("");
  const [authorizing, setAuthorizing] = useState(false);
  const [youtube, setYoutube] = useState<YouTubeSessionStatus | null>(null);
  const [youtubeMessage, setYoutubeMessage] = useState("");
  const [youtubeOperationId, setYoutubeOperationId] = useState("");
  const [youtubeConnecting, setYoutubeConnecting] = useState(false);
  const prefetchedVideoIds = useRef(new Set<string>());

  const prefetchVideo = useCallback((videoId: string) => {
    if (!feed?.invidious_public_base_url || prefetchedVideoIds.current.size >= 3 || prefetchedVideoIds.current.has(videoId)) return;
    prefetchedVideoIds.current.add(videoId);
    try {
      const base = new URL(feed.invidious_public_base_url);
      void fetch(new URL(`/api/v1/videos/${encodeURIComponent(videoId)}`, base).toString(), { cache: "no-store" }).catch(() => {});
    } catch {
      // The learning flow remains available if the public Invidious URL is unavailable.
    }
  }, [feed?.invidious_public_base_url]);

  const fetchFeed = useCallback(async (tab?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getInvidiousHome(tab);
      setFeed(data);
      if (!activeTab || tab) {
        setActiveTab(data.current_tab);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to load Invidious feed."));
    } finally {
      setLoading(false);
    }
  }, [activeTab, t]);

  useEffect(() => {
    void fetchFeed();
    void getYouTubeSessionStatus().then(setYoutube).catch(() => {});
    const handleAuthMessage = (event: MessageEvent) => {
      if (event.data?.type === "INVIDIOUS_AUTH_SUCCESS") {
        void fetchFeed();
      }
    };
    window.addEventListener("message", handleAuthMessage);
    return () => window.removeEventListener("message", handleAuthMessage);
  }, [fetchFeed]);

  const handleYouTubeConnect = async () => {
    if (youtubeConnecting) return;
    setYoutubeConnecting(true);
    setYoutubeMessage(t("Using this Mac's existing Chrome session to retrieve YouTube subtitles."));
    try {
      const operation = await connectYouTubeSession();
      if (!operation.helper_available) {
        setYoutubeMessage(t("Chrome or Chromium is required on the Mac running DeepTutor."));
        setYoutubeConnecting(false);
        return;
      }
      setYoutube({ connection: operation.connection, helper_available: operation.helper_available });
      if (operation.mode === "host_chrome" || !operation.operation_id) {
        setYoutubeMessage(t("Make sure YouTube is signed in in Chrome on the Mac running DeepTutor."));
        setYoutubeConnecting(false);
        return;
      }
      setYoutubeOperationId(operation.operation_id || "");
    } catch (caught) {
      setYoutubeMessage(caught instanceof Error ? caught.message : t("Could not connect YouTube."));
      setYoutubeConnecting(false);
    }
  };

  useEffect(() => {
    if (!youtubeOperationId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const current = await getYouTubeConnectOperation(youtubeOperationId);
        if (cancelled) return;
        setYoutube({ connection: current.connection, helper_available: current.helper_available });
        if (current.connection === "connecting") {
          window.setTimeout(() => void poll(), 2_000);
          return;
        }
        await getYouTubeSessionStatus().then(setYoutube);
        setYoutubeMessage(current.connection === "connected" ? t("YouTube connected.") : t("YouTube connection expired. Please try again."));
        setYoutubeConnecting(false);
      } catch (caught) {
        if (!cancelled) {
          setYoutubeMessage(caught instanceof Error ? caught.message : t("Could not connect YouTube."));
          setYoutubeConnecting(false);
        }
      }
    };
    void poll();
    return () => { cancelled = true; };
  }, [t, youtubeOperationId]);

  const handleYouTubeDisconnect = async () => {
    try {
      await disconnectYouTubeSession();
      await getYouTubeSessionStatus().then(setYoutube);
      setYoutubeMessage(t("YouTube disconnected. Cached subtitles remain available."));
    } catch (caught) {
      setYoutubeMessage(caught instanceof Error ? caught.message : t("Could not disconnect YouTube."));
    }
  };

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    void fetchFeed(tab);
  };

  const handleConnect = async () => {
    setAuthorizing(true);
    try {
      const authUrl = await getInvidiousAuthorizeUrl();
      window.location.assign(authUrl);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to start authorization."));
      setAuthorizing(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnectInvidious();
      await fetchFeed();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Failed to disconnect."));
    }
  };

  const handleSubmitUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim()) {
      onSelectVideo(url.trim());
    }
  };

  const tabIcons: Record<string, any> = {
    Popular: Sparkles,
    Trending: Flame,
    Subscriptions: Tv,
    History: History,
    Playlists: ListVideo,
  };

  const currentTab = activeTab || feed?.current_tab || "Popular";

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      {/* Top Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <Globe className="text-[var(--primary)]" size={20} />
          <div>
            <h2 className="text-sm font-semibold tracking-tight">
              {t("Invidious Video Hub")}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)]">
              {feed?.connected
                ? t("Logged in • Watch history synced to Invidious")
                : t("Public Mode • Connect your account for subscriptions & history")}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {youtube?.connection === "connected" ? (
            <button
              type="button"
              onClick={() => void handleYouTubeDisconnect()}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              <LogOut size={13} />
              {t("Disconnect YouTube")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleYouTubeConnect()}
              disabled={youtubeConnecting}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {youtubeConnecting ? <Loader2 size={13} className="animate-spin" /> : <Globe size={13} />}
              {youtubeConnecting ? t("Waiting for YouTube login") : t("Connect YouTube")}
            </button>
          )}
          {feed?.connected ? (
            <button
              type="button"
              onClick={handleDisconnect}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <LogOut size={13} />
              {t("Disconnect Account")}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleConnect}
              disabled={authorizing}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-2.5 py-1 text-xs font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-50"
            >
              {authorizing ? <Loader2 size={13} className="animate-spin" /> : <LogIn size={13} />}
              {t("Connect Invidious")}
            </button>
          )}

          {onOpenInvidious && (
            <button
              type="button"
              onClick={onOpenInvidious}
              disabled={openingInvidious}
              className={`inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium disabled:opacity-50 ${
                feed?.connected
                  ? "bg-[var(--foreground)] text-[var(--background)] hover:opacity-90"
                  : "border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {openingInvidious ? <Loader2 size={13} className="animate-spin" /> : <ExternalLink size={13} />}
              {openingInvidious ? t("Opening Invidious...") : t("Open Invidious")}
            </button>
          )}

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label={t("Close")}
              className="rounded p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </header>
      {youtubeMessage && (
        <div className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm" role="status" aria-live="polite">
          <p className="font-medium text-[var(--foreground)]">{youtubeMessage}</p>
          {youtubeConnecting && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("If you are on an iPad or another computer, complete this step on the Mac running DeepTutor.")}</p>}
        </div>
      )}

      {(openingInvidious || openMessage) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--muted)]/30 px-4 py-2 text-xs">
          <p className="text-[var(--muted-foreground)]">
            {openMessage || (openingInvidious ? t("Opening Invidious...") : t("If the page did not jump, tap Continue to Invidious."))}
          </p>
          {fallbackOpenUrl && (
            <a
              href={fallbackOpenUrl}
              className="inline-flex items-center gap-1 font-medium text-[var(--foreground)] underline"
            >
              <ExternalLink size={12} />
              {t("Continue to Invidious")}
            </a>
          )}
        </div>
      )}

      {/* URL Input Bar */}
      <div className="border-b border-[var(--border)] bg-[var(--muted)]/20 p-3">
        <form onSubmit={handleSubmitUrl} className="flex gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("Paste a YouTube or Invidious video URL...")}
              className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] placeholder-[var(--muted-foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--foreground)]"
            />
          </div>
          <button
            type="submit"
            disabled={!url.trim()}
            className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] disabled:opacity-50"
          >
            <Play size={14} />
            {t("Start Learning")}
          </button>
        </form>
      </div>

      {/* Tab Navigation */}
      {feed?.tabs && feed.tabs.length > 0 && (
        <div className="flex overflow-x-auto border-b border-[var(--border)] px-4 py-2 gap-1 text-xs">
          {feed.tabs.map((tab) => {
            const Icon = tabIcons[tab] || Sparkles;
            const isActive = currentTab === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => handleTabChange(tab)}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 transition-colors ${
                  isActive
                    ? "bg-[var(--muted)] font-semibold text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={13} />
                {t(tab)}
              </button>
            );
          })}
        </div>
      )}

      {/* Content Area */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="animate-spin" size={20} />
            <p>{t("Loading videos from Invidious...")}</p>
          </div>
        ) : error ? (
          <div className="mx-auto max-w-md rounded-lg border border-red-300/40 bg-red-500/5 p-6 text-center text-sm text-red-600 dark:text-red-400">
            <p className="font-medium">{error}</p>
            <button
              type="button"
              onClick={() => fetchFeed(currentTab)}
              className="mt-3 inline-flex items-center gap-1.5 rounded border border-red-300/60 px-3 py-1.5 text-xs font-medium hover:bg-red-500/10"
            >
              <RotateCcw size={13} />
              {t("Retry")}
            </button>
          </div>
        ) : !feed?.items || feed.items.length === 0 ? (
          <EmptyFeedState
            tab={currentTab}
            connected={Boolean(feed?.connected)}
            onConnect={handleConnect}
            onOpenInvidious={onOpenInvidious}
            onSelectTab={handleTabChange}
            onRetry={() => fetchFeed(currentTab)}
            authorizing={authorizing}
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {feed.items.map((item) => (
              <VideoCard
                key={item.video_id}
                item={item}
                publicBaseUrl={feed.invidious_public_base_url}
                opening={openingVideo}
                onPrefetch={() => prefetchVideo(item.video_id)}
                onSelect={() => onSelectVideo(`https://youtu.be/${item.video_id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyFeedState({
  tab,
  connected,
  onConnect,
  onOpenInvidious,
  onSelectTab,
  onRetry,
  authorizing,
}: {
  tab: string;
  connected: boolean;
  onConnect: () => void;
  onOpenInvidious?: () => void;
  onSelectTab: (tab: string) => void;
  onRetry: () => void;
  authorizing: boolean;
}) {
  const { t } = useTranslation();

  if (tab === "Subscriptions") {
    if (!connected) {
      return (
        <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center shadow-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--primary)]">
            <Tv size={24} />
          </div>
          <h3 className="text-sm font-semibold text-[var(--foreground)]">
            {t("Connect Invidious to see your subscriptions")}
          </h3>
          <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("Connect your Invidious account to view updates from channels you follow. Watch progress and history will also sync across your devices.")}
          </p>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              onClick={onConnect}
              disabled={authorizing}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-50"
            >
              {authorizing ? <Loader2 size={13} className="animate-spin" /> : <LogIn size={13} />}
              {t("Connect Invidious")}
            </button>
            <button
              type="button"
              onClick={() => onSelectTab("Popular")}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Sparkles size={13} />
              {t("Explore Popular")}
            </button>
            <button
              type="button"
              onClick={() => onSelectTab("Trending")}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Flame size={13} />
              {t("Explore Trending")}
            </button>
          </div>
        </div>
      );
    }
    return (
      <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
          <Tv size={24} />
        </div>
        <h3 className="text-sm font-semibold text-[var(--foreground)]">
          {t("No subscription updates yet")}
        </h3>
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          {t("Your subscribed channels have no recent uploads, or you have not subscribed to channels on Invidious yet. Open Invidious to search and subscribe to channels, or explore trending content.")}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {onOpenInvidious && (
            <button
              type="button"
              onClick={onOpenInvidious}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] hover:opacity-90"
            >
              <ExternalLink size={13} />
              {t("Open Invidious")}
            </button>
          )}
          <button
            type="button"
            onClick={() => onSelectTab("Popular")}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <Sparkles size={13} />
            {t("Explore Popular")}
          </button>
          <button
            type="button"
            onClick={() => onSelectTab("Trending")}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <Flame size={13} />
            {t("Explore Trending")}
          </button>
        </div>
      </div>
    );
  }

  if (tab === "History") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
          <History size={24} />
        </div>
        <h3 className="text-sm font-semibold text-[var(--foreground)]">
          {t("No watch history yet")}
        </h3>
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          {t("Videos you watch or study in DeepTutor will automatically appear here, complete with your notes and key points.")}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => onSelectTab("Popular")}
            className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] hover:opacity-90"
          >
            <Sparkles size={13} />
            {t("Explore Popular Videos")}
          </button>
          {!connected && (
            <button
              type="button"
              onClick={onConnect}
              disabled={authorizing}
              className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <LogIn size={13} />
              {t("Connect Invidious")}
            </button>
          )}
        </div>
      </div>
    );
  }

  if (tab === "Playlists") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-8 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">
          <ListVideo size={24} />
        </div>
        <h3 className="text-sm font-semibold text-[var(--foreground)]">
          {t("No playlists found")}
        </h3>
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          {connected
            ? t("No playlists found in your Invidious account. Create playlists on Invidious to organize your learning videos.")
            : t("Connect your Invidious account to view and manage your playlists.")}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {!connected ? (
            <button
              type="button"
              onClick={onConnect}
              disabled={authorizing}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] hover:opacity-90"
            >
              <LogIn size={13} />
              {t("Connect Invidious")}
            </button>
          ) : onOpenInvidious ? (
            <button
              type="button"
              onClick={onOpenInvidious}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] hover:opacity-90"
            >
              <ExternalLink size={13} />
              {t("Open Invidious")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => onSelectTab("Popular")}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <Sparkles size={13} />
            {t("Explore Popular")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-48 flex-col items-center justify-center gap-2 text-center text-sm text-[var(--muted-foreground)]">
      <Search size={24} className="opacity-40" />
      <p>{t("No videos found in this feed.")}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-1 text-xs underline hover:text-[var(--foreground)]"
      >
        {t("Retry")}
      </button>
    </div>
  );
}

function VideoCard({
  item,
  publicBaseUrl,
  onSelect,
  onPrefetch,
  opening,
}: {
  item: InvidiousFeedItem;
  publicBaseUrl: string;
  onSelect: () => Promise<boolean>;
  onPrefetch: () => void;
  opening: boolean;
}) {
  const { t } = useTranslation();

  const progressPct =
    item.duration_seconds > 0 && item.last_position_seconds
      ? Math.min(100, Math.round((item.last_position_seconds / item.duration_seconds) * 100))
      : 0;

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] transition hover:border-[var(--foreground)]/30 hover:shadow-sm">
      {/* Thumbnail Container */}
      <div
        className="relative aspect-video w-full cursor-pointer bg-black/10 overflow-hidden"
        onPointerEnter={onPrefetch}
        onFocus={onPrefetch}
        onClick={() => void onSelect()}
      >
        <img
          src={item.thumbnail_url}
          alt={item.title}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          loading="lazy"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).src = `https://i.ytimg.com/vi/${item.video_id}/hqdefault.jpg`;
          }}
        />

        {/* Duration badge */}
        {item.duration_seconds > 0 && (
          <span className="absolute bottom-1.5 right-1.5 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[10px] font-medium text-white">
            {formatDuration(item.duration_seconds)}
          </span>
        )}

        {/* Watched badge */}
        {item.watched && (
          <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow">
            <CheckCircle2 size={10} />
            {t("Watched")}
          </span>
        )}

        {/* Notes / Marks badges */}
        {((item.notes_count ?? 0) > 0 || (item.marks_count ?? 0) > 0) && (
          <div className="absolute bottom-1.5 left-1.5 flex items-center gap-1">
            {(item.notes_count ?? 0) > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded bg-amber-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow" title={t("Notes")}>
                <StickyNote size={9} />
                {item.notes_count}
              </span>
            )}
            {(item.marks_count ?? 0) > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded bg-blue-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow" title={t("Key points")}>
                <BookmarkPlus size={9} />
                {item.marks_count}
              </span>
            )}
          </div>
        )}

        {/* Progress Bar */}
        {progressPct > 0 && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/40">
            <div
              className="h-full bg-red-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        )}

        {/* Hover play overlay */}
        <div className={`absolute inset-0 flex items-center justify-center bg-black/30 transition-opacity ${opening ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-black shadow">
            {opening ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} className="translate-x-0.5" />}
          </div>
        </div>
      </div>

      {/* Video Details */}
      <div className="flex flex-1 flex-col p-3">
        <h3
          onFocus={onPrefetch}
          onClick={() => void onSelect()}
          className="line-clamp-2 cursor-pointer text-xs font-semibold leading-snug text-[var(--foreground)] group-hover:text-[var(--primary)]"
          title={item.title}
        >
          {item.title}
        </h3>

        <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span className="truncate" title={item.author}>
            {item.author || t("Unknown Channel")}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between text-[10px] text-[var(--muted-foreground)]">
          <span>{item.published_text || (item.view_count ? `${item.view_count.toLocaleString()} views` : "")}</span>
          <div className="flex items-center gap-1.5">
            {publicBaseUrl && (
              <a
                href={`${publicBaseUrl}/watch?v=${item.video_id}`}
                target="_blank"
                rel="noreferrer"
                title={t("Open in Invidious")}
                className="hover:text-[var(--foreground)]"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink size={11} />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}
