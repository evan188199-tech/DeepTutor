"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  ClipboardCopy,
  Laptop,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import {
  approveMarginNote4Writeback,
  createMarginNote4PairingCode,
  getMarginNote4BridgeStatus,
  listMarginNote4Devices,
  listMarginNote4Writebacks,
  markMarginNote4WritebackImported,
  rejectMarginNote4Writeback,
  type MarginNote4Device,
  type MarginNote4PairingCode,
  type MarginNote4BridgeStatus,
  type MarginNote4Writeback,
} from "@/lib/knowledge-api";
import { formatKnowledgeTimestamp } from "@/lib/knowledge-helpers";

interface MarginNote4BridgePanelProps {
  kbName: string;
}

const STATUS_TONES: Record<string, string> = {
  pending_confirmation:
    "bg-amber-100 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200",
  approved: "bg-sky-100 text-sky-800 dark:bg-sky-950/30 dark:text-sky-200",
  leased: "bg-sky-100 text-sky-800 dark:bg-sky-950/30 dark:text-sky-200",
  awaiting_import:
    "bg-purple-100 text-purple-800 dark:bg-purple-950/30 dark:text-purple-200",
  applied:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200",
  imported:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-950/30 dark:text-red-200",
  conflicted: "bg-red-100 text-red-800 dark:bg-red-950/30 dark:text-red-200",
};

export default function MarginNote4BridgePanel({
  kbName,
}: MarginNote4BridgePanelProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<MarginNote4BridgeStatus | null>(null);
  const [devices, setDevices] = useState<MarginNote4Device[]>([]);
  const [writebacks, setWritebacks] = useState<MarginNote4Writeback[]>([]);
  const [pairing, setPairing] = useState<MarginNote4PairingCode | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextStatus, nextDevices, nextWritebacks] = await Promise.all([
        getMarginNote4BridgeStatus({ kbName }),
        listMarginNote4Devices({ kbName }),
        listMarginNote4Writebacks({ kbName }),
      ]);
      setStatus(nextStatus);
      setDevices(nextDevices);
      setWritebacks(nextWritebacks.writebacks);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [kbName]);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(interval);
  }, [load]);

  const handlePair = async () => {
    const key = "pair";
    setWorking(key);
    setError(null);
    try {
      setPairing(await createMarginNote4PairingCode({ kbName }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorking(null);
    }
  };

  const handleAction = async (
    writeback: MarginNote4Writeback,
    action: "approve" | "reject" | "imported",
  ) => {
    setWorking(`${writeback.writeback_id}:${action}`);
    setError(null);
    try {
      if (action === "approve") {
        await approveMarginNote4Writeback({
          kbName,
          writebackId: writeback.writeback_id,
        });
      } else if (action === "reject") {
        await rejectMarginNote4Writeback({
          kbName,
          writebackId: writeback.writeback_id,
        });
      } else {
        await markMarginNote4WritebackImported({
          kbName,
          writebackId: writeback.writeback_id,
        });
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorking(null);
    }
  };

  const copyCommand = async () => {
    if (!pairing) return;
    try {
      await navigator.clipboard.writeText(pairing.command);
    } catch {
      window.prompt(t("Copy this pairing command"), pairing.command);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
            {t("MarginNote 4 Bridge")}
          </h2>
          <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
            {status
              ? t("{{count}} objects · {{pending}} pending review", {
                  count: status.object_count,
                  pending: status.pending_writebacks,
                })
              : t("Waiting for bridge status")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handlePair()}
            disabled={working === "pair"}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {working === "pair" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Laptop className="h-3.5 w-3.5" />
            )}
            {t("Pair Mac")}
          </button>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            title={t("Refresh")}
            className="inline-flex items-center rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[var(--foreground)] disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {pairing && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[12px] font-medium text-[var(--foreground)]">
              {t("One-time pairing command")}
            </span>
            <button
              type="button"
              onClick={() => void copyCommand()}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2 py-1 text-[11.5px]"
            >
              <ClipboardCopy className="h-3.5 w-3.5" />
              {t("Copy")}
            </button>
          </div>
          <pre className="mt-2 overflow-x-auto rounded-md bg-[var(--background)] p-2.5 font-mono text-[11px] leading-relaxed text-[var(--foreground)]">
            {pairing.command}
          </pre>
          <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
            {t("Expires {{time}}", {
              time: formatKnowledgeTimestamp(pairing.expires_at) ?? "",
            })}
          </p>
        </div>
      )}

      <section className="space-y-2">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Devices")}
        </h3>
        {devices.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No Mac connected")}
          </p>
        ) : (
          devices.map((device) => (
            <div
              key={device.device_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 py-2.5"
            >
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-[var(--foreground)]">
                  {device.device_name || device.device_id}
                </div>
                <div className="mt-0.5 font-mono text-[11px] text-[var(--muted-foreground)]">
                  {device.device_id}
                </div>
              </div>
              <span className="text-[11px] text-[var(--muted-foreground)]">
                {t("Last seen {{time}}", {
                  time: formatKnowledgeTimestamp(device.last_seen) ?? t("Unknown"),
                })}
              </span>
            </div>
          ))
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Writeback review")}
        </h3>
        {writebacks.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No writebacks")}
          </p>
        ) : (
          writebacks.map((writeback) => (
            <article
              key={writeback.writeback_id}
              className="rounded-lg border border-[var(--border)] p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h4 className="truncate text-[13px] font-medium text-[var(--foreground)]">
                    {writeback.title}
                  </h4>
                  <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {formatKnowledgeTimestamp(writeback.updated_at) ?? ""}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_TONES[writeback.status] ?? "bg-[var(--muted)] text-[var(--muted-foreground)]"}`}
                >
                  {writeback.status}
                </span>
              </div>
              <details className="mt-2">
                <summary className="cursor-pointer text-[12px] text-[var(--muted-foreground)]">
                  {t("Preview content")}
                </summary>
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-[var(--muted)]/50 p-2.5 font-mono text-[11px] leading-relaxed">
                  {writeback.markdown}
                </pre>
              </details>
              {writeback.last_error && (
                <p className="mt-2 text-[11.5px] text-red-700 dark:text-red-300">
                  {writeback.last_error}
                </p>
              )}
              {writeback.status !== "rejected" && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {writeback.status === "pending_confirmation" && (
                    <button
                      type="button"
                      onClick={() => void handleAction(writeback, "approve")}
                      disabled={working !== null}
                      className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-50"
                    >
                      <Check className="h-3.5 w-3.5" />
                      {t("Approve")}
                    </button>
                  )}
                  {writeback.status === "awaiting_import" && (
                    <button
                      type="button"
                      onClick={() => void handleAction(writeback, "imported")}
                      disabled={working !== null}
                      className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1 text-[11.5px] font-medium disabled:opacity-50"
                    >
                      <Check className="h-3.5 w-3.5" />
                      {t("Confirm import")}
                    </button>
                  )}
                  {["pending_confirmation", "approved", "failed", "conflicted"].includes(
                    writeback.status,
                  ) && (
                    <button
                      type="button"
                      onClick={() => void handleAction(writeback, "reject")}
                      disabled={working !== null}
                      className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-2.5 py-1 text-[11.5px] font-medium text-red-700 disabled:opacity-50 dark:border-red-900 dark:text-red-300"
                    >
                      <X className="h-3.5 w-3.5" />
                      {t("Reject")}
                    </button>
                  )}
                </div>
              )}
            </article>
          ))
        )}
      </section>
    </div>
  );
}
