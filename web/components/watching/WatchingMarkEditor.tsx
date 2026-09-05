"use client";

import { useEffect, useRef } from "react";
import { BookmarkPlus, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { VideoMarkKind } from "@/lib/video-learning-api";

export function WatchingMarkEditor({ timestamp, busy, error, note, onChange, onSave, onNote, onClose }: {
  note: string;
  onChange(note: string): void;
  timestamp: string;
  busy: boolean;
  error: string | null;
  onSave(kind: VideoMarkKind, note: string): void;
  onNote(note: string): void;
  onClose(): void;
}) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(busy);
  const closeRef = useRef(onClose);
  useEffect(() => {
    busyRef.current = busy;
    closeRef.current = onClose;
  }, [busy, onClose]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLTextAreaElement>("textarea")?.focus({preventScroll:true});
    const reveal = () => {
      const panel = dialog?.closest<HTMLElement>(".watching-detail-panel");
      if (!dialog || !panel) return;
      const bounds = panel.getBoundingClientRect();
      const editor = dialog.getBoundingClientRect();
      const tools = panel.querySelector(".watching-transcript-tools")?.getBoundingClientRect().height ?? 0;
      const top = bounds.top + tools + 12;
      const bottom = bounds.top + panel.clientHeight - 12;
      const delta = editor.height > bottom - top || editor.top < top
        ? editor.top - top : Math.max(0, editor.bottom - bottom);
      if (Math.abs(delta) > 1) panel.scrollTo({top: panel.scrollTop + delta, behavior:"instant"});
    };
    const frame = requestAnimationFrame(reveal);
    const resize = new ResizeObserver(reveal);
    if (dialog) resize.observe(dialog);
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && dialog?.contains(document.activeElement)) {
        event.preventDefault();
        event.stopPropagation();
        if (!busyRef.current) closeRef.current();
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      document.removeEventListener("keydown", keydown, true);
      if (previous?.isConnected) previous.focus({preventScroll:true});
    };
  }, []);
  return (
      <div ref={dialogRef} role="region" aria-label={t("Save a learning mark")} aria-busy={busy} className="watching-mark-editor my-2 w-full rounded-xl border border-blue-500/25 bg-[var(--background)] p-3 text-[var(--foreground)]" onClick={event => event.stopPropagation()}>
        <div className="mb-3 flex items-center gap-2">
          <BookmarkPlus size={18}/><h2 className="flex-1 font-semibold">{t("Save a learning mark")}</h2>
          <button type="button" disabled={busy} aria-label={t("Close")} onClick={onClose} className="rounded p-2 hover:bg-[var(--muted)]"><X size={18}/></button>
        </div>
        <p className="mb-2 font-mono text-xs text-blue-600">{timestamp}</p>
        <label className="mt-2 block text-sm">
          {t("Optional annotation")}
          <textarea value={note} onChange={event=>onChange(event.target.value)} disabled={busy} className="mt-2 min-h-16 w-full rounded-lg border border-[var(--border)] bg-transparent p-2"/>
        </label>
        {error && <p role="alert" className="mt-2 text-sm text-[var(--destructive)]">{error}</p>}
        {busy && <p role="status" className="mt-2 flex items-center gap-2 text-sm"><Loader2 size={14} className="animate-spin"/>{t("Saving…")}</p>}
        <div className="mt-2 flex flex-wrap gap-2">
          {([['key_point','Key point'],['question','Question'],['review','Review later']] as const).map(([kind,label])=>(
            <button key={kind} type="button" disabled={busy} onClick={()=>onSave(kind,note)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)] disabled:opacity-50">{t(label)}</button>
          ))}
        </div>
        <button type="button" disabled={busy} onClick={() => onNote(note)} className="mt-3 text-sm text-blue-600 underline disabled:opacity-50">{t("Write a video note instead")}</button>
      </div>
  );
}
