"use client";

import { useMemo, useState } from "react";
import { Bookmark, HelpCircle, Play, RotateCcw, StickyNote, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  VIDEO_MARK_COLORS,
  filterLearningEvents,
  formatMarkRange,
  formatWatchTime,
  learningEventColor,
  learningEventCoversTime,
  learningEventsFromLearning,
  type LearningEvent,
  type LearningEventFilter,
} from "@/lib/video-learning-marks";
import type { VideoLearningMark, VideoMarkKind, VideoMarkSuggestion, VideoNote } from "@/lib/video-learning-api";

const FILTERS: LearningEventFilter[] = ["all", "note", "key_point", "question", "review"];

export function LearningRecordsPanel({
  notes,
  marks,
  suggestions,
  currentTime,
  durationEndMark,
  error,
  noteMessage,
  onSeek,
  onDelete,
  onReviewed,
  onSaveSuggestion,
  onDismissEnd,
  onReplayEnd,
  onSaveNote,
}: {
  notes: VideoNote[];
  marks: VideoLearningMark[];
  suggestions: VideoMarkSuggestion[];
  currentTime: number;
  durationEndMark: VideoLearningMark | null;
  error: string;
  noteMessage: string;
  onSeek: (seconds: number) => void;
  onDelete: (markId: string) => void;
  onReviewed: (mark: VideoLearningMark) => void;
  onSaveSuggestion: (suggestion: VideoMarkSuggestion) => void;
  onDismissEnd: () => void;
  onReplayEnd: (mark: VideoLearningMark) => void;
  onSaveNote: (text: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<LearningEventFilter>("all");
  const [noteText, setNoteText] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const events = useMemo(() => learningEventsFromLearning(notes, marks), [notes, marks]);
  const visible = useMemo(() => filterLearningEvents(events, filter), [events, filter]);

  const submitNote = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = noteText.trim();
    if (!text || savingNote) return;
    setSavingNote(true);
    try {
      await onSaveNote(text);
      setNoteText("");
    } finally {
      setSavingNote(false);
    }
  };

  return (
    <section
      aria-label={t("Learning records")}
      className="flex min-h-0 flex-1 flex-col border-t border-[var(--border)] lg:border-t-0"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-2.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Learning records")}
        </h3>
        <span className="tabular-nums text-[10px] text-[var(--muted-foreground)]">
          {formatWatchTime(currentTime)}
        </span>
      </div>
      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--border)] px-2 py-1.5">
        {FILTERS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={filter === kind}
            onClick={() => setFilter(kind)}
            className={`shrink-0 rounded px-2 py-1 text-[11px] ${
              filter === kind ? "bg-[var(--muted)] font-semibold" : "text-[var(--muted-foreground)]"
            }`}
          >
            {labelForKind(kind, t)}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {durationEndMark && (
          <div className="mb-2 rounded-lg border border-[var(--border)] bg-[var(--muted)] p-2">
            <p className="mb-1.5 text-[11px] text-[var(--muted-foreground)]">
              {t("Reached the end of this mark.")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                className="rounded border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--background)]"
                onClick={onDismissEnd}
              >
                {t("Continue watching")}
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--background)]"
                onClick={() => onReplayEnd(durationEndMark)}
              >
                <RotateCcw size={11} />
                {t("Replay mark")}
              </button>
              {durationEndMark.kind === "review" && (
                <button
                  type="button"
                  className="rounded border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--background)]"
                  onClick={() => onReviewed(durationEndMark)}
                >
                  {t("Mark as reviewed")}
                </button>
              )}
            </div>
          </div>
        )}

        {suggestions.length > 0 && (
          <div className="mb-3 space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              {t("Suggested marks")}
            </p>
            {suggestions.map((suggestion, index) => (
              <div
                key={`${suggestion.kind}-${suggestion.start_seconds}-${index}`}
                className="rounded-lg border border-dashed border-[var(--border)] p-2"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-[11px] font-medium" style={{ color: VIDEO_MARK_COLORS[suggestion.kind] }}>
                    {labelForKind(suggestion.kind, t)}
                  </span>
                  <button
                    type="button"
                    className="rounded bg-[var(--foreground)] px-2 py-1 text-[11px] text-[var(--background)]"
                    onClick={() => onSaveSuggestion(suggestion)}
                  >
                    {t("Save")}
                  </button>
                </div>
                <button
                  type="button"
                  className="font-mono text-[11px] text-[var(--muted-foreground)]"
                  onClick={() => onSeek(suggestion.start_seconds)}
                >
                  {formatMarkRange(suggestion)}
                </button>
                {suggestion.quote && <p className="mt-1 text-xs text-[var(--foreground)]">{suggestion.quote}</p>}
              </div>
            ))}
          </div>
        )}

        {error && <p className="mb-2 text-[11px] text-red-600">{error}</p>}

        {visible.length ? (
          <div className="space-y-2">
            {visible.map((event) => (
              <LearningRecordCard
                key={event.id}
                event={event}
                active={learningEventCoversTime(event, currentTime)}
                onSeek={onSeek}
                onDelete={onDelete}
              />
            ))}
          </div>
        ) : (
          <p className="px-1 text-xs text-[var(--muted-foreground)]">{t("No learning records yet.")}</p>
        )}
      </div>

      <form onSubmit={submitNote} className="shrink-0 space-y-1.5 border-t border-[var(--border)] p-2">
        <div className="flex gap-1.5">
          <input
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
            placeholder={t("Write a note about this timestamp...")}
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!noteText.trim() || savingNote}
            className="shrink-0 rounded-lg bg-[var(--foreground)] px-2.5 py-1.5 text-xs text-[var(--background)] disabled:opacity-50"
          >
            {savingNote ? t("Saving...") : t("Save note")}
          </button>
        </div>
        {noteMessage && <p className="text-[11px] text-[var(--muted-foreground)]">{noteMessage}</p>}
      </form>
    </section>
  );
}

function LearningRecordCard({
  event,
  active,
  onSeek,
  onDelete,
}: {
  event: LearningEvent;
  active: boolean;
  onSeek: (seconds: number) => void;
  onDelete: (markId: string) => void;
}) {
  const { t } = useTranslation();
  const isNote = event.kind === "note";

  return (
    <article
      data-testid={isNote ? "watching-note-card" : `watching-mark-card-${event.kind}`}
      className={`relative rounded-lg border p-2 pl-3 ${
        active ? "border-[var(--foreground)] bg-[var(--muted)]/70" : "border-[var(--border)]"
      }`}
    >
      <span
        aria-hidden
        className="absolute bottom-2 left-1 top-2 w-[3px] rounded-full"
        style={{ backgroundColor: learningEventColor(event) }}
      />
      <div className="mb-1 flex items-center gap-1.5">
        {isNote ? <StickyNote size={12} /> : event.kind === "question" ? <HelpCircle size={12} /> : <Bookmark size={12} />}
        <span className="text-[11px] font-medium" style={{ color: learningEventColor(event) }}>
          {labelForKind(event.kind, t)}
        </span>
        <button
          type="button"
          className="ml-auto inline-flex items-center gap-1 font-mono text-[11px] text-[var(--muted-foreground)]"
          onClick={() => onSeek(event.start_seconds)}
        >
          <Play size={10} />
          {formatMarkRange(event)}
        </button>
        {!isNote && (
          <button
            type="button"
            aria-label={t("Delete mark")}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            onClick={() => onDelete(event.id)}
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
      {event.quote && <p className="text-xs text-[var(--foreground)]">{event.quote}</p>}
      {event.note && (
        <p className={`text-[11px] text-[var(--muted-foreground)] ${event.quote ? "mt-1" : ""}`}>
          {event.note}
        </p>
      )}
      <div className="mt-1 flex items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
        {event.author === "assistant" && <span>{t("AI")}</span>}
        {event.reviewed_at && <span>{t("Reviewed")}</span>}
      </div>
    </article>
  );
}

function labelForKind(
  kind: LearningEventFilter,
  t: (key: string) => string
): string {
  if (kind === "all") return t("All");
  if (kind === "note") return t("Note");
  if (kind === "question") return t("Question mark");
  if (kind === "review") return t("Review later");
  return t("Key point");
}
