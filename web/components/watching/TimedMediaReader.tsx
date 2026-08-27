"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  BookmarkPlus,
  Compass,
  ExternalLink,
  FilePlus2,
  Flag,
  Globe,
  Loader2,
  MessageSquareText,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useWatching } from "@/context/WatchingContext";
import {
  addVideoNote,
  createBookFromVideo,
  createTranscriptJob,
  createVideoMark,
  deleteVideoMark,
  getInvidiousStatus,
  getVideoLearningMaterial,
  getTranscriptJob,
  patchVideoMark,
  publishVideoToKb,
  recordWatchProgress,
  suggestVideoMarks,
  timedMediaStreamUrl,
  timedMediaSubtitleUrl,
  type VideoLearningMark,
  type VideoMarkKind,
  type VideoMarkSuggestion,
  type VideoNote,
} from "@/lib/video-learning-api";
import {
  VIDEO_MARK_COLORS,
  cueIndexesFromSelection,
  formatWatchTime,
  learningEventsFromLearning,
  locatorsForRange,
  marksAtTime,
  rangeFromCues,
} from "@/lib/video-learning-marks";
import { WATCHING_ASK_EVENT } from "@/lib/watching-turn-state";
import { InvidiousHome } from "./InvidiousHome";
import {
  createRendererLaunch,
} from "@/lib/video-learning-remote-api";
import { invidiousFallbackUrl, shouldOpenInvidiousInCurrentTab } from "@/lib/invidious-open";
import { ReaderResizeHandle } from "@/components/reading/ReaderResizeHandle";
import { LearningRecordsPanel } from "./LearningRecordsPanel";
import { LearningTimeline } from "./LearningTimeline";

export function TimedMediaReader({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const {
    material,
    currentTime,
    pendingSeek,
    openUrl,
    replaceMaterial,
    close,
    setCurrentTime,
    seek,
    clearSeek,
  } = useWatching();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const actionBarRef = useRef<HTMLDivElement | null>(null);
  const insideMarksRef = useRef<Set<string>>(new Set());
  const [showInvidiousHome, setShowInvidiousHome] = useState(false);
  const [invidiousPublicUrl, setInvidiousPublicUrl] = useState<string>("");
  const [jobMessage, setJobMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [noteMessage, setNoteMessage] = useState("");
  const [playbackErrorMaterialId, setPlaybackErrorMaterialId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ start_seconds: number; end_seconds: number; quote: string; note?: string } | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const [rangeStart, setRangeStart] = useState<number | null>(null);
  const [markError, setMarkError] = useState("");
  const [suggestions, setSuggestions] = useState<VideoMarkSuggestion[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [endPrompt, setEndPrompt] = useState<VideoLearningMark | null>(null);
  const [kbBusy, setKbBusy] = useState(false);
  const [bookBusy, setBookBusy] = useState(false);
  const [publishMessage, setPublishMessage] = useState("");
  const [rendererMessage, setRendererMessage] = useState("");
  const [openingInvidious, setOpeningInvidious] = useState(false);

  const cumulativePlayedRef = useRef<number>(0);
  const lastPlaybackTimeRef = useRef<number>(-1);

  useEffect(() => {
    void getInvidiousStatus()
      .then((status) => {
        if (status.invidious_public_base_url) {
          setInvidiousPublicUrl(status.invidious_public_base_url);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (material?.learning?.cumulative_played_seconds) {
      cumulativePlayedRef.current = material.learning.cumulative_played_seconds;
    } else {
      cumulativePlayedRef.current = 0;
    }
    lastPlaybackTimeRef.current = -1;
    setDraft(null);
    setRangeStart(null);
    setSuggestions([]);
    setEndPrompt(null);
    insideMarksRef.current = new Set();
    // Reset only when switching videos; later watch-progress updates must not wipe local playback totals.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material?.material_id]);

  useEffect(() => {
    if (pendingSeek === null || !videoRef.current) return;
    videoRef.current.currentTime = pendingSeek;
    void videoRef.current.play().catch(() => {});
    clearSeek();
  }, [pendingSeek, clearSeek]);

  useEffect(() => {
    if (!material) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getVideoLearningMaterial(material.material_id);
        if (!cancelled) replaceMaterial(next);
      } catch {
        // The remote phone may be writing; the next interval will retry.
      }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [material, replaceMaterial]);

  useEffect(() => {
    if (!jobId || !material) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const job = await getTranscriptJob(jobId);
        if (cancelled) return;
        if (job.status === "completed") {
          setJobMessage(t("Subtitle generation completed."));
          setJobId(null);
          await openUrl(material.source.url);
        } else if (job.status === "failed" || job.status === "cancelled") {
          setJobMessage(job.error || t("Subtitle generation failed."));
          setJobId(null);
        } else {
          setJobMessage(`${t("Subtitle generation is running.")} ${job.progress ?? 0}%`);
        }
      } catch (caught) {
        if (!cancelled)
          setJobMessage(caught instanceof Error ? caught.message : t("Subtitle generation failed."));
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, material, openUrl, t]);

  const marks = useMemo(() => material?.learning.marks || [], [material?.learning.marks]);
  const notes = useMemo(() => material?.learning.notes || [], [material?.learning.notes]);
  const learningEvents = useMemo(() => learningEventsFromLearning(notes, marks), [notes, marks]);
  const activeCue = useMemo(
    () => material?.transcript.cues.find((cue) => currentTime >= cue.start && currentTime <= cue.end),
    [material, currentTime]
  );
  const activeCueIndex = useMemo(
    () => material?.transcript.cues.findIndex((cue) => cue === activeCue) ?? -1,
    [activeCue, material]
  );
  const selectedFormat = material ? Object.keys(material.playback.formats)[0] ?? "" : "";
  const format = material?.playback.formats[selectedFormat];
  const playbackError = playbackErrorMaterialId === material?.material_id;
  const duration = material?.source.duration_seconds || material?.metadata.duration_seconds || 0;

  useEffect(() => {
    if (!material) return;
    const nextInside = new Set<string>();
    for (const mark of marks) {
      if (mark.end_seconds <= mark.start_seconds) continue;
      const inside = currentTime >= mark.start_seconds && currentTime <= mark.end_seconds;
      if (inside) nextInside.add(mark.mark_id);
      else if (insideMarksRef.current.has(mark.mark_id) && currentTime > mark.end_seconds) {
        setEndPrompt(mark);
      }
    }
    insideMarksRef.current = nextInside;
  }, [currentTime, marks, material]);

  useEffect(() => {
    if (activeCueIndex < 0) return;
    transcriptRef.current
      ?.querySelector(`[data-cue-index="${activeCueIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeCueIndex]);

  const handleVideoSelect = async (videoUrl: string) => {
    setShowInvidiousHome(false);
    await openUrl(videoUrl);
  };

  const openInvidiousRenderer = async (
    videoId?: string,
    positionSeconds?: number,
    preferSameTab = false,
  ) => {
    setOpeningInvidious(true);
    setRendererMessage(t("Opening Invidious..."));
    const fallbackUrl = invidiousFallbackUrl(invidiousPublicUrl);
    let target: Window | null = null;
    // Hub / iPad: stay in the current tab so a blocked popup cannot look like
    // "no jump". Watch page: open a tab first, then replace it with the
    // bootstrap URL after the ticket is ready.
    if (!preferSameTab) {
      target = window.open(fallbackUrl || "about:blank", "_blank");
      try {
        if (target) target.opener = null;
      } catch {
        // Some browsers expose opener as read-only for a newly opened tab.
      }
    }
    try {
      const launch = await createRendererLaunch({
        videoId,
        positionSeconds,
        materialId: material?.material_id,
      });
      try {
        const origin = new URL(launch.launch_url).origin;
        if (origin) setInvidiousPublicUrl(origin);
      } catch {
        // Keep the last known public origin if the launch URL is unexpected.
      }
      if (shouldOpenInvidiousInCurrentTab(preferSameTab, Boolean(target))) {
        window.location.assign(launch.launch_url);
        return;
      }
      if (!target) throw new Error(t("Could not open Invidious."));
      target.location.assign(launch.launch_url);
      setRendererMessage(t("Opened Invidious. Use Phone remote & notes there when ready."));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : t("Could not open Invidious.");
      if (target && fallbackUrl) {
        try {
          target.location.assign(fallbackUrl);
        } catch {
          target.close();
        }
      } else if (target) {
        target.close();
      }
      setRendererMessage(
        fallbackUrl
          ? `${message} ${t("If the page did not jump, tap Continue to Invidious.")}`
          : message,
      );
    } finally {
      setOpeningInvidious(false);
    }
  };

  if (!material || showInvidiousHome) {
    return (
      <InvidiousHome
        onSelectVideo={handleVideoSelect}
        onOpenInvidious={() => void openInvidiousRenderer(undefined, undefined, true)}
        onClose={material ? () => setShowInvidiousHome(false) : onClose}
        openingInvidious={openingInvidious}
        openMessage={rendererMessage}
        fallbackOpenUrl={invidiousFallbackUrl(invidiousPublicUrl)}
      />
    );
  }

  const currentSegment = material.segments.find((row) => currentTime >= row.start && currentTime <= row.end);
  const askAboutCurrent = (intent: "explain" | "extract" = "explain") => {
    window.dispatchEvent(
      new CustomEvent(WATCHING_ASK_EVENT, {
        detail: { timeSeconds: currentTime, text: currentSegment?.text || "", intent },
      })
    );
  };

  const updateMarks = (update: (rows: VideoLearningMark[]) => VideoLearningMark[]) => {
    replaceMaterial((current) =>
      current
        ? { ...current, learning: { ...current.learning, marks: update(current.learning.marks || []) } }
        : current
    );
  };

  const updateNotes = (update: (rows: VideoNote[]) => VideoNote[]) => {
    replaceMaterial((current) =>
      current
        ? { ...current, learning: { ...current.learning, notes: update(current.learning.notes || []) } }
        : current
    );
  };

  const saveMark = async (payload: {
    kind: VideoMarkKind;
    start_seconds: number;
    end_seconds: number;
    quote?: string;
    note?: string;
    author?: "user" | "assistant";
  }) => {
    const locators = locatorsForRange(material.segments, payload.start_seconds, payload.end_seconds);
    try {
      const saved = await createVideoMark(material.material_id, { ...payload, ...locators });
      updateMarks((rows) => (rows.some((row) => row.mark_id === saved.mark_id) ? rows : [...rows, saved]));
      setDraft(null);
      setDraftNote("");
      setRangeStart(null);
      setMarkError("");
      window.getSelection()?.removeAllRanges();
    } catch (caught) {
      setMarkError(caught instanceof Error ? caught.message : t("Mark could not be saved."));
    }
  };

  const saveNote = async (text: string) => {
    try {
      const saved = await addVideoNote(material.material_id, text, currentTime);
      updateNotes((rows) => (rows.some((row) => row.note_id === saved.note_id) ? rows : [...rows, saved]));
      setNoteMessage(t("Note saved."));
    } catch (caught) {
      setNoteMessage(caught instanceof Error ? caught.message : t("Note could not be saved."));
    }
  };

  const handleTimeUpdate = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    const time = video.currentTime;
    const segment = material.segments.find((row) => time >= row.start && time <= row.end);
    setCurrentTime(time, segment?.locator);

    if (!video.paused && lastPlaybackTimeRef.current >= 0) {
      const delta = time - lastPlaybackTimeRef.current;
      if (delta > 0 && delta < 2.0) {
        cumulativePlayedRef.current += delta;
      }
    }
    lastPlaybackTimeRef.current = time;
  };

  const handlePauseOrSync = (event: React.SyntheticEvent<HTMLVideoElement>) => {
    const time = event.currentTarget.currentTime;
    lastPlaybackTimeRef.current = -1;
    void recordWatchProgress(material.material_id, time, cumulativePlayedRef.current).catch(() => {});
  };

  const captureSelection = () => {
    const indexes = cueIndexesFromSelection(transcriptRef.current, window.getSelection());
    const range = rangeFromCues(material.transcript.cues, indexes);
    if (range) {
      setDraft(range);
      setDraftNote("");
    }
  };

  const markCurrentTime = () => {
    const cue = material.transcript.cues.find((row) => currentTime >= row.start && currentTime <= row.end);
    setDraft({
      start_seconds: currentTime,
      end_seconds: currentTime,
      quote: cue?.text || "",
    });
  };

  const setRangeAnchor = (which: "start" | "end") => {
    if (which === "start") {
      setRangeStart(currentTime);
      return;
    }
    const start = rangeStart ?? currentTime;
    const end = currentTime;
    const from = Math.min(start, end);
    const to = Math.max(start, end);
    const quote = material.transcript.cues
      .filter((cue) => cue.end >= from && cue.start <= to)
      .map((cue) => cue.text)
      .join(" ");
    setDraft({ start_seconds: from, end_seconds: to, quote });
  };

  const extractKeyPoints = async () => {
    askAboutCurrent("extract");
    setExtracting(true);
    setMarkError("");
    try {
      const rows = await suggestVideoMarks(material.material_id, currentTime);
      setSuggestions(rows);
    } catch (caught) {
      setMarkError(caught instanceof Error ? caught.message : t("Key points could not be extracted."));
    } finally {
      setExtracting(false);
    }
  };

  const publishToKb = async () => {
    if (!material || kbBusy) return;
    setKbBusy(true);
    setPublishMessage("");
    setMarkError("");
    try {
      const result = await publishVideoToKb(material.material_id);
      replaceMaterial(result.material);
      setPublishMessage(
        result.updated
          ? t("Published to personal knowledge base.")
          : t("Knowledge base note is already up to date."),
      );
    } catch (caught) {
      setMarkError(
        caught instanceof Error
          ? caught.message
          : t("Could not publish this video to the knowledge base."),
      );
    } finally {
      setKbBusy(false);
    }
  };

  const createInteractiveBook = async () => {
    if (!material || bookBusy) return;
    setBookBusy(true);
    setPublishMessage("");
    setMarkError("");
    try {
      const result = await createBookFromVideo(material.material_id, {
        language: (typeof navigator !== "undefined" && navigator.language.startsWith("zh")) ? "zh" : "en",
      });
      replaceMaterial(result.material);
      const bookId = String(result.book?.id || "");
      if (bookId) {
        window.location.assign(`/book?book=${encodeURIComponent(bookId)}`);
        return;
      }
      setPublishMessage(t("Interactive book draft created."));
    } catch (caught) {
      setMarkError(
        caught instanceof Error
          ? caught.message
          : t("Could not create an interactive book from this video."),
      );
    } finally {
      setBookBusy(false);
    }
  };

  const invidiousVideoUrl = invidiousPublicUrl
    ? `${invidiousPublicUrl}/watch?v=${material.source.video_id}`
    : "";

  return (
    <section className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      <header className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <button
          type="button"
          onClick={() => {
            close();
            onClose();
          }}
          aria-label={t("Close")}
          className="rounded p-2 hover:bg-[var(--muted)]"
        >
          <X size={17} />
        </button>
        <button
          type="button"
          onClick={() => setShowInvidiousHome(true)}
          className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          title={t("Browse Invidious Videos")}
        >
          <Compass size={13} />
          <span>{t("Browse")}</span>
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{material.metadata.title}</h2>
          <p className="truncate text-xs text-[var(--muted-foreground)]">{material.metadata.author}</p>
        </div>
        <button
          type="button"
          onClick={() => void publishToKb()}
          disabled={kbBusy || bookBusy}
          title={t("Publish marks to personal knowledge base")}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {kbBusy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
          <span>{material.learning?.kb_publish ? t("Update KB") : t("Publish to KB")}</span>
        </button>
        <button
          type="button"
          onClick={() => void createInteractiveBook()}
          disabled={kbBusy || bookBusy}
          title={t("Create an interactive book from these marks")}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {bookBusy ? <Loader2 size={13} className="animate-spin" /> : <BookOpen size={13} />}
          <span>{t("Create Book")}</span>
        </button>
        <button
          type="button"
          onClick={() => void openInvidiousRenderer(material.source.video_id, currentTime)}
          disabled={openingInvidious}
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
          title={t("Open in Invidious")}
        >
          {openingInvidious ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
          <span>{t("Invidious")}</span>
        </button>
        <a
          href={material.playback.official_url}
          target="_blank"
          rel="noreferrer"
          title={t("Open in YouTube")}
          className="rounded p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ExternalLink size={16} />
        </a>
      </header>
      {publishMessage && (
        <div className="border-b border-[var(--border)] px-3 py-1.5 text-xs">
          <p className="text-[var(--foreground)]">{publishMessage}</p>
        </div>
      )}
      {rendererMessage && <div className="border-b border-[var(--border)] px-3 py-1.5 text-xs">{rendererMessage}</div>}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1.25fr)+minmax(300px,0.75fr)] lg:overflow-hidden">
        <div className="flex min-h-[240px] flex-col border-b border-[var(--border)] lg:min-h-0 lg:border-b-0 lg:border-r">
          <div className="min-h-0 flex-1 bg-black p-2">
          {format && !playbackError ? (
            <video
              ref={videoRef}
              className="h-full w-full object-contain"
              controls
              playsInline
              preload="metadata"
              src={timedMediaStreamUrl(material.material_id, selectedFormat)}
              onError={() => setPlaybackErrorMaterialId(material.material_id)}
              onPause={handlePauseOrSync}
              onEnded={handlePauseOrSync}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={(event) => {
                const start = material.source.entry_time_seconds || material.learning.last_position || 0;
                if (start > 0) event.currentTarget.currentTime = start;
              }}
            >
              {material.transcript.cues.length > 0 && (
                <track
                  kind="captions"
                  src={timedMediaSubtitleUrl(material.material_id)}
                  srcLang={material.transcript.language || "en"}
                  label={material.transcript.language || "Subtitles"}
                  default
                />
              )}
            </video>
          ) : playbackError ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-white">
              <p>{t("Playback failed. Open the video in YouTube or Invidious.")}</p>
              <div className="flex gap-2">
                {invidiousVideoUrl && (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded border border-white/40 px-3 py-1.5 text-xs"
                    onClick={() => void openInvidiousRenderer(material.source.video_id, currentTime)}
                    disabled={openingInvidious}
                  >
                    <Globe size={13} />
                    {t("Invidious")}
                  </button>
                )}
                <a
                  className="inline-flex items-center gap-1.5 rounded border border-white/40 px-3 py-1.5 text-xs"
                  href={material.playback.official_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={13} />
                  {t("YouTube")}
                </a>
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-white">
              {t("No compatible video stream was returned.")}
            </div>
          )}
        </div>

          <LearningTimeline
            events={learningEvents}
            duration={duration || 1}
            currentTime={currentTime}
            onSeek={seek}
          />
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <section aria-label={t("Transcript")} className="flex min-h-[220px] flex-[1.15] flex-col border-b border-[var(--border)]">
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-2.5 py-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              {t("Transcript")}
            </h3>
            <span className="tabular-nums text-[10px] text-[var(--muted-foreground)]">{formatWatchTime(currentTime)}</span>
          </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-2" ref={transcriptRef} onMouseUp={captureSelection} onTouchEnd={captureSelection}>
              {material.transcript.cues.length ? (
                <>
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => askAboutCurrent("explain")}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]"
                    >
                      <MessageSquareText size={15} />
                      {t("Explain here")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void extractKeyPoints()}
                      disabled={extracting}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs hover:bg-[var(--muted)] disabled:opacity-50"
                    >
                      {extracting ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                      {t("Extract key points")}
                    </button>
                    <button
                      type="button"
                      onClick={markCurrentTime}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]"
                    >
                      <BookmarkPlus size={15} />
                      {t("Mark here")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setRangeAnchor("start")}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]"
                    >
                      <Flag size={15} />
                      {rangeStart === null ? t("Set start") : `${t("Start")}: ${formatWatchTime(rangeStart)}`}
                    </button>
                    <button
                      type="button"
                      onClick={() => setRangeAnchor("end")}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]"
                    >
                      {t("Set end")}
                    </button>
                  </div>
                  {draft && (
                    <div ref={actionBarRef} className="sticky top-0 z-10 mb-2 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 shadow-sm">
                      <p className="mb-1.5 text-[11px] text-[var(--muted-foreground)]">
                        {formatWatchTime(draft.start_seconds)}
                        {draft.end_seconds !== draft.start_seconds ? ` – ${formatWatchTime(draft.end_seconds)}` : ""}
                      </p>
                      <div className="mb-2 flex flex-wrap gap-2">
                        {(["key_point", "question", "review"] as VideoMarkKind[]).map((kind) => (
                          <button
                            key={kind}
                            type="button"
                        className="rounded-lg px-2 py-1 text-[11px] text-white"
                            data-testid={`watching-mark-${kind}`}
                            style={{ backgroundColor: VIDEO_MARK_COLORS[kind] }}
                            onClick={() => void saveMark({ ...draft, kind, note: draftNote, author: "user" })}
                          >
                            {kind === "question" ? t("Question mark") : kind === "review" ? t("Review later") : t("Key point")}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="rounded-lg border border-[var(--border)] px-2 py-1 text-[11px]"
                          onClick={() => {
                            setDraft(null);
                            setDraftNote("");
                            window.getSelection()?.removeAllRanges();
                          }}
                        >
                          {t("Cancel")}
                        </button>
                      </div>
                      <input
                        value={draftNote}
                        onChange={(event) => setDraftNote(event.target.value)}
                        placeholder={t("Optional note for this mark")}
                        className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-[11px]"
                      />
                    </div>
                  )}
                  {material.transcript.cues.map((cue, index) => {
                    const cueActive = activeCue === cue;
                    const cueMarks = marksAtTime(marks, cue.start + (cue.end - cue.start) / 2);
                    return (
                      <div
                        key={`${cue.start}-${index}`}
                        data-cue-index={index}
                        data-active-cue={cueActive}
                        className={`relative mb-1 flex w-full gap-2 rounded-lg p-2 pl-3.5 text-xs ${cueActive ? "bg-[var(--muted)]" : "hover:bg-[var(--muted)]/60"}`}
                      >
                        {cueMarks.length > 0 && (
                          <span
                            aria-hidden
                            className="absolute bottom-2 left-1 top-2 flex w-2 gap-0.5 overflow-hidden rounded-full"
                          >
                            {cueMarks.slice(0, 3).map((mark) => (
                              <span
                                key={mark.mark_id}
                                className="flex-1"
                                style={{ backgroundColor: VIDEO_MARK_COLORS[mark.kind] }}
                              />
                            ))}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => seek(cue.start)}
                          className="shrink-0 font-mono text-[11px] tabular-nums text-[var(--muted-foreground)]"
                        >
                          {formatWatchTime(cue.start)}
                        </button>
                        <span data-testid="watching-cue-text" className="select-text leading-relaxed">{cue.text}</span>
                      </div>
                    );
                  })}
                </>
              ) : (
                <div className="space-y-3 p-2 text-xs text-[var(--muted-foreground)]">
                  <p>{t("No subtitles are available for this video.")}</p>
                  <button
                    type="button"
                    disabled={Boolean(jobId)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 disabled:opacity-50"
                    onClick={() => {
                      void createTranscriptJob(material.material_id)
                        .then((job) => {
                          setJobId(job.job_id);
                          setJobMessage(t("Subtitle generation submitted."));
                        })
                        .catch((caught) =>
                          setJobMessage(caught instanceof Error ? caught.message : t("Subtitle generation failed."))
                        );
                    }}
                  >
                    <FilePlus2 size={15} />
                    {t("Generate subtitles")}
                  </button>
                  {jobMessage && <p>{jobMessage}</p>}
                </div>
              )}
            </div>
          </section>

          <LearningRecordsPanel
            notes={notes}
            marks={marks}
            suggestions={suggestions}
            currentTime={currentTime}
            durationEndMark={endPrompt}
            error={markError}
            noteMessage={noteMessage}
            onSeek={seek}
            onDelete={(markId) => {
              void deleteVideoMark(material.material_id, markId)
                .then(() => updateMarks((rows) => rows.filter((row) => row.mark_id !== markId)))
                .catch((caught) => setMarkError(caught instanceof Error ? caught.message : t("Mark could not be deleted.")));
            }}
            onReviewed={(mark) => {
              void patchVideoMark(material.material_id, mark.mark_id, { reviewed: true })
                .then((saved) => updateMarks((rows) => rows.map((row) => (row.mark_id === saved.mark_id ? saved : row))))
                .then(() => setEndPrompt(null))
                .catch((caught) => setMarkError(caught instanceof Error ? caught.message : t("Mark could not be saved.")));
            }}
            onSaveSuggestion={(suggestion) => {
              void saveMark({ ...suggestion, author: "assistant" }).then(() => {
                setSuggestions((rows) => rows.filter((row) => row !== suggestion));
              });
            }}
            onDismissEnd={() => setEndPrompt(null)}
            onReplayEnd={(mark) => {
              setEndPrompt(null);
              seek(mark.start_seconds);
            }}
            onSaveNote={saveNote}
          />
        </div>
      </div>
      <ReaderResizeHandle />
    </section>
  );
}
