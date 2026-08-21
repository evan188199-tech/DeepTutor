"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Cable,
  Check,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldOff,
} from "lucide-react";
import {
  createMarginNotePairingCode,
  listMarginNoteDevices,
  revokeMarginNoteDevice,
  type MarginNoteDevice,
  type MarginNotePairingCode,
} from "@/lib/marginnote4-api";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

interface MarginNoteDevicePanelProps {
  kb: KnowledgeBase;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function secondsUntil(value: string): number {
  const date = new Date(value).getTime();
  return Number.isNaN(date) ? 0 : Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

export default function MarginNoteDevicePanel({
  kb,
}: MarginNoteDevicePanelProps) {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<MarginNoteDevice[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<MarginNotePairingCode | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDevices(await listMarginNoteDevices(kb.name));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDevices([]);
    } finally {
      setLoading(false);
    }
  }, [kb.name]);

  useEffect(() => {
    if (kb.metadata?.type !== "marginnote4") return;
    void load();
  }, [kb.metadata?.type, load]);

  useEffect(() => {
    if (!pairingCode) return;
    const timer = window.setInterval(() => {
      const next = secondsUntil(pairingCode.expires_at);
      setRemaining(next);
      if (next === 0) setPairingCode(null);
    }, 1000);
    setRemaining(secondsUntil(pairingCode.expires_at));
    return () => window.clearInterval(timer);
  }, [pairingCode]);

  if (kb.metadata?.type !== "marginnote4") return null;

  const generateCode = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setPairingCode(await createMarginNotePairingCode(kb.name));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (deviceId: string) => {
    if (busy || !window.confirm(t("Revoke this MarginNote device?"))) return;
    setBusy(true);
    setError(null);
    try {
      await revokeMarginNoteDevice(deviceId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--foreground)]">
            <Cable className="h-3.5 w-3.5" />
            {t("MarginNote 4 device")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t(
              "Pair one MarginNote 4 installation. Its notes, cards and mind maps stay read-only.",
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading || busy}
            title={t("Refresh devices")}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={() => void generateCode()}
            disabled={loading || busy}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <KeyRound className="h-3 w-3" />
            )}
            {t("Generate pairing code")}
          </button>
        </div>
      </div>

      {pairingCode && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                {t("One-time pairing code")}
              </div>
              <div className="mt-1 font-mono text-[18px] font-semibold tracking-[0.18em] text-emerald-900 dark:text-emerald-100">
                {pairingCode.code}
              </div>
            </div>
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-300">
              {t("Expires in {{seconds}}s", { seconds: remaining })}
            </span>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 px-1 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("Loading devices…")}
        </div>
      ) : devices?.length ? (
        <div className="divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
          {devices.map((device) => (
            <div
              key={device.device_id}
              className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {device.device_name ||
                      (device.device_kind === "ipados" ? "iPad" : "Mac")}
                  </span>
                  {device.active ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                      <Check className="h-3 w-3" />
                      {t("Active")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                      {t("Revoked")}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  {t("Protocol {{version}}", { version: device.protocol_version })}
                  {" · "}
                  {t("Last sync")} {formatTime(device.last_seen)}
                </div>
              </div>
              {device.active && (
                <button
                  type="button"
                  onClick={() => void revoke(device.device_id)}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-2.5 py-1 text-[12px] font-medium text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-300 dark:hover:bg-red-950/40"
                >
                  <ShieldOff className="h-3 w-3" />
                  {t("Revoke")}
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        !error && (
          <div className="rounded-md border border-dashed border-[var(--border)] px-3 py-5 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No MarginNote device paired yet.")}
          </div>
        )
      )}
    </section>
  );
}
