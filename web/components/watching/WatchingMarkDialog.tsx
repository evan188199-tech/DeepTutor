"use client";

import { useEffect, useRef, useState } from "react";
import { BookmarkPlus, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { VideoMarkKind } from "@/lib/video-learning-api";

export function WatchingMarkDialog({ quote, timestamp, busy, error, onSave, onNote, onClose }: {
  quote: string;
  timestamp: string;
  busy: boolean;
  error: string | null;
  onSave(kind: VideoMarkKind, note: string): void;
  onNote(note: string): void;
  onClose(): void;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
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
    dialog?.querySelector<HTMLTextAreaElement>("textarea")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (!busyRef.current) closeRef.current();
      }
      if (event.key !== "Tab" || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),textarea:not(:disabled)'));
      const first = controls[0], last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !controls.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      if (previous?.isConnected) previous.focus({preventScroll:true});
    };
  }, []);
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4" onClick={() => { if (!busy) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={t("Save a learning mark")} aria-busy={busy} className="max-h-[85dvh] w-full max-w-md overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--background)] p-5 text-[var(--foreground)] shadow-xl" onClick={event => event.stopPropagation()}>
        <div className="mb-3 flex items-center gap-2">
          <BookmarkPlus size={18}/><h2 className="flex-1 font-semibold">{t("Save a learning mark")}</h2>
          <button type="button" disabled={busy} aria-label={t("Close")} onClick={onClose} className="rounded p-2 hover:bg-[var(--muted)]"><X size={18}/></button>
        </div>
        <p className="mb-2 font-mono text-xs text-blue-600">{timestamp}</p>
        <blockquote className="max-h-36 overflow-y-auto border-l-2 border-blue-500/40 pl-3 text-sm leading-relaxed">{quote}</blockquote>
        <label className="mt-4 block text-sm">
          {t("Optional annotation")}
          <textarea value={note} onChange={event=>setNote(event.target.value)} disabled={busy} className="mt-2 min-h-20 w-full rounded-lg border border-[var(--border)] bg-transparent p-2"/>
        </label>
        {error && <p role="alert" className="mt-2 text-sm text-[var(--destructive)]">{error}</p>}
        {busy && <p role="status" className="mt-2 flex items-center gap-2 text-sm"><Loader2 size={14} className="animate-spin"/>{t("Saving…")}</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          {([['key_point','Key point'],['question','Question'],['review','Review later']] as const).map(([kind,label])=>(
            <button key={kind} type="button" disabled={busy} onClick={()=>onSave(kind,note)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)] disabled:opacity-50">{t(label)}</button>
          ))}
        </div>
        <button type="button" disabled={busy} onClick={() => onNote(note)} className="mt-3 text-sm text-blue-600 underline disabled:opacity-50">{t("Write a video note instead")}</button>
      </div>
    </div>
  );
}
