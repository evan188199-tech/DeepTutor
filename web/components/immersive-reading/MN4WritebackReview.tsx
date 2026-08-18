"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, CircleAlert, Loader2, RefreshCw, X } from "lucide-react";
import type { MN4WritebackItem } from "@/lib/immersive-reading-api";

interface MN4WritebackReviewProps {
  items: MN4WritebackItem[];
  loading: boolean;
  error: string | null;
  onApprove: (writebackIds: string[]) => Promise<void>;
  onReject: (writebackIds: string[]) => Promise<void>;
  onRetry: () => void;
}

export function MN4WritebackReview({
  items,
  loading,
  error,
  onApprove,
  onReject,
  onRetry,
}: MN4WritebackReviewProps) {
  const { t } = useTranslation();
  const [action, setAction] = useState<"approve" | "reject" | null>(null);
  const pendingItems = items.filter((item) => item.status === "pending_confirmation");

  const runAction = async (
    nextAction: "approve" | "reject",
    writebackIds: string[],
  ) => {
    setAction(nextAction);
    try {
      await (nextAction === "approve" ? onApprove(writebackIds) : onReject(writebackIds));
    } finally {
      setAction(null);
    }
  };

  if (loading) {
    return (
      <section className="flex min-h-[320px] items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        <span role="status">{t("Loading MarginNote 4 writebacks...")}</span>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("MarginNote 4 Sync Review")}</h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t("Review each generated item before it is written to MarginNote 4.")}
          </p>
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]"
        >
          <RefreshCw size={15} />
          {t("Refresh")}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-3 rounded-lg border border-red-500/25 bg-red-500/8 px-4 py-3 text-sm text-red-500"
        >
          <CircleAlert size={16} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">{error}</span>
        </div>
      )}

      {pendingItems.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-[var(--border)] px-6 py-12 text-center text-sm text-[var(--muted-foreground)]">
          {t("No pending MarginNote 4 writebacks.")}
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex justify-end">
            <button
              type="button"
              disabled={action !== null}
              onClick={() => void runAction("approve", pendingItems.map((item) => item.id))}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm font-medium text-[var(--primary-foreground)] transition disabled:opacity-50"
            >
              {action === "approve" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Check size={14} />
              )}
              {t("Approve all")}
            </button>
          </div>

          {pendingItems.map((item) => (
            <article
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium capitalize">{item.source_type}</p>
                <p className="mt-1 font-mono text-xs text-[var(--muted-foreground)]">
                  {item.id.slice(0, 12)} / {item.content_hash.slice(0, 12)}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  aria-label={t("Approve")}
                  disabled={action !== null}
                  onClick={() => void runAction("approve", [item.id])}
                  className="rounded-lg border border-[var(--border)] p-2 text-emerald-600 transition hover:bg-emerald-500/10 disabled:opacity-50"
                >
                  {action === "approve" ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Check size={14} />
                  )}
                </button>
                <button
                  type="button"
                  aria-label={t("Reject")}
                  disabled={action !== null}
                  onClick={() => void runAction("reject", [item.id])}
                  className="rounded-lg border border-[var(--border)] p-2 text-red-600 transition hover:bg-red-500/10 disabled:opacity-50"
                >
                  {action === "reject" ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <X size={14} />
                  )}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default MN4WritebackReview;
