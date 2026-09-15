"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listVideoNotes, type VideoNote } from "@/lib/video-learning-api";
import {
  seekWatchingVideo,
  WATCHING_NOTES_CHANGED_EVENT,
} from "@/lib/watching-notes-events";

function formatTime(value: number): string {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const hours = Math.floor(total / 3600);
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** Read-only companion for the editable notes panel in Watching. It refreshes
 * whenever that panel changes the same material, rather than maintaining a
 * second editable copy of the learner's notes. */
export default function WatchingNotesInspectorTab({
  materialId,
}: {
  materialId: string;
}) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState<VideoNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listVideoNotes(materialId);
      setNotes(rows);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Notes could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [materialId, t]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ materialId?: string }>).detail;
      if (detail?.materialId === materialId) void load();
    };
    window.addEventListener(WATCHING_NOTES_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WATCHING_NOTES_CHANGED_EVENT, onChanged);
  }, [load, materialId]);

  if (loading) {
    return <p className="flex items-center gap-2 p-4 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin" />{t("Loading notes.")}</p>;
  }
  if (error) {
    return <p role="alert" className="m-4 rounded-lg border border-[var(--border)] p-3 text-sm text-[var(--destructive)]">{error}</p>;
  }
  return (
    <section className="h-full overflow-y-auto p-4" aria-label={t("Video notes")}>
      <h2 className="mb-1 font-semibold">{t("Video notes")}</h2>
      <p className="mb-4 text-sm text-[var(--muted-foreground)]">{t("Jump to any note in the video.")}</p>
      {notes.length ? <div className="space-y-3">{notes.map(note => (
        <article key={`${note.notebook_id}:${note.note_id}`} className="rounded-lg border border-[var(--border)] p-3">
          <button type="button" onClick={() => seekWatchingVideo(note.time_seconds)} className="rounded px-1.5 py-0.5 font-mono text-xs tabular-nums text-blue-600 hover:bg-blue-500/10">{formatTime(note.time_seconds)}</button>
          <p className="mt-2 whitespace-pre-wrap text-sm">{note.body}</p>
          {note.quote && <blockquote className="mt-2 border-l-2 border-[var(--border)] pl-2 text-xs text-[var(--muted-foreground)]">{note.quote}</blockquote>}
        </article>
      ))}</div> : <p className="text-sm text-[var(--muted-foreground)]">{t("No notes yet.")}</p>}
    </section>
  );
}
