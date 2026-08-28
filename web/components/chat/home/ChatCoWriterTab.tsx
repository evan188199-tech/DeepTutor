"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eye, Loader2, PenLine, Save, SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  createCoWriterDocument,
  updateCoWriterDocument,
} from "@/lib/co-writer-api";
import { notifyCoWriterChanged } from "@/lib/co-writer-events";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

const DRAFT_STORAGE_KEY = "deeptutor.chat_co_writer.draft";

type DraftMode = "write" | "preview";

export interface CoWriterDraftInput {
  title: string;
  content: string;
  fallbackTitle: string;
}

export interface CoWriterDraftState {
  documentId: string | null;
  title: string;
  content: string;
  savedTitle: string;
  savedContent: string;
}

export function buildCoWriterDraftPayload({
  title,
  content,
  fallbackTitle,
}: CoWriterDraftInput): { title: string; content: string } {
  return {
    title: (title.trim() || fallbackTitle).slice(0, 120),
    content,
  };
}

export function getCoWriterDraftStatus({
  documentId,
  title,
  content,
  savedTitle,
  savedContent,
}: CoWriterDraftState): "empty" | "unsaved" | "saved" {
  if (!content.trim()) return "empty";
  if (
    !documentId ||
    title.trim() !== savedTitle.trim() ||
    content !== savedContent
  ) {
    return "unsaved";
  }
  return "saved";
}

function readStoredDraft(): { title: string; content: string } | null {
  try {
    const raw = window.sessionStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { title?: unknown; content?: unknown };
    if (typeof parsed.title !== "string" || typeof parsed.content !== "string")
      return null;
    return { title: parsed.title, content: parsed.content };
  } catch {
    return null;
  }
}

export default function ChatCoWriterTab() {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [savedTitle, setSavedTitle] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [mode, setMode] = useState<DraftMode>("write");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const stored = readStoredDraft();
    if (!stored) return;
    setTitle(stored.title);
    setContent(stored.content);
  }, []);

  useEffect(() => {
    if (!title && !content) return;
    try {
      window.sessionStorage.setItem(
        DRAFT_STORAGE_KEY,
        JSON.stringify({ title, content }),
      );
    } catch {
      // A full session-storage quota should not block writing in the panel.
    }
  }, [title, content]);

  const status = useMemo(
    () =>
      getCoWriterDraftStatus({
        documentId,
        title,
        content,
        savedTitle,
        savedContent,
      }),
    [content, documentId, savedContent, savedTitle, title],
  );

  const handleSave = useCallback(async () => {
    if (status === "empty" || isSaving || status === "saved") return;
    setIsSaving(true);
    setError("");
    const payload = buildCoWriterDraftPayload({
      title,
      content,
      fallbackTitle: t("Chat note"),
    });
    try {
      const saved = documentId
        ? await updateCoWriterDocument(documentId, payload)
        : await createCoWriterDocument(payload);
      setDocumentId(saved.id);
      setSavedTitle(saved.title || payload.title);
      setSavedContent(saved.content ?? content);
      try {
        window.sessionStorage.removeItem(DRAFT_STORAGE_KEY);
      } catch {
        // Keeping the cleared-storage best effort is harmless.
      }
      notifyCoWriterChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  }, [content, documentId, isSaving, status, t, title]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s")
        return;
      event.preventDefault();
      void handleSave();
    },
    [handleSave],
  );

  const statusLabel = error
    ? t("Save failed")
    : isSaving
      ? t("Saving...")
      : status === "saved"
        ? t("Saved")
        : status === "unsaved"
          ? t("Unsaved")
          : t("New draft");

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--card)]">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--border)]/45 px-3 py-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/55">
          <PenLine
            size={14}
            strokeWidth={1.7}
            className="text-[var(--muted-foreground)]"
          />
        </div>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={120}
          spellCheck={false}
          placeholder={t("Chat note")}
          aria-label={t("Document title")}
          className="h-8 min-w-[140px] flex-1 rounded-lg border border-transparent bg-transparent px-2 text-[13px] font-medium text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/45 focus:bg-[var(--background)]"
        />
        <span
          className={`inline-flex shrink-0 items-center gap-1 text-[11px] ${
            error
              ? "text-[var(--destructive)]"
              : "text-[var(--muted-foreground)]"
          }`}
        >
          {isSaving && <Loader2 size={11} className="animate-spin" />}
          {statusLabel}
        </span>
      </div>

      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)]/35 px-3 py-2">
        <div
          role="tablist"
          aria-label={t("Chat note mode")}
          className="flex items-center rounded-lg bg-[var(--muted)]/45 p-0.5"
        >
          {(["write", "preview"] as DraftMode[]).map((item) => {
            const isActive = mode === item;
            const Icon = item === "write" ? SquarePen : Eye;
            return (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setMode(item)}
                className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11.5px] font-medium transition-colors ${
                  isActive
                    ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={12} strokeWidth={1.8} />
                {item === "write" ? t("Write") : t("Preview")}
              </button>
            );
          })}
        </div>
        <div className="flex min-w-0 items-center gap-1.5">
          {documentId && (
            <a
              href={`/co-writer/${encodeURIComponent(documentId)}`}
              className="hidden shrink-0 rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/45 hover:text-[var(--foreground)] sm:inline-flex"
            >
              {t("Open Co-Writer")}
            </a>
          )}
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={status === "empty" || isSaving || status === "saved"}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-[11.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {isSaving ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Save size={12} strokeWidth={1.9} />
            )}
            {t("Save draft")}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="shrink-0 border-b border-[var(--destructive)]/25 bg-[var(--destructive)]/8 px-3 py-2 text-[11.5px] leading-snug text-[var(--destructive)]"
        >
          {error}
        </div>
      )}

      {mode === "write" ? (
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          aria-label={t("Markdown draft")}
          placeholder={t("Write Markdown...")}
          className="min-h-0 flex-1 resize-none bg-[var(--card)] px-4 py-3 font-mono text-[12.5px] leading-6 text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/65"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {content.trim() ? (
            <MarkdownRenderer content={content} />
          ) : (
            <p className="text-[12.5px] text-[var(--muted-foreground)]">
              {t("Nothing to preview")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
