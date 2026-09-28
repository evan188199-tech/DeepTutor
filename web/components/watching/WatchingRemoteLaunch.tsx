"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Loader2, MonitorSmartphone, RefreshCw } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useTranslation } from "react-i18next";

import {
  createRendererLaunch,
  type RendererLaunch,
} from "@/lib/video-learning-remote-api";

interface WatchingRemoteLaunchProps {
  materialId: string;
  videoId: string;
  positionSeconds: number;
}

export function WatchingRemoteLaunch({
  materialId,
  videoId,
  positionSeconds,
}: WatchingRemoteLaunchProps) {
  const { t } = useTranslation();
  const [launch, setLaunch] = useState<RendererLaunch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!launch) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [launch]);

  const secondsLeft = useMemo(() => {
    if (!launch) return 0;
    return Math.max(
      0,
      Math.ceil((Date.parse(launch.expires_at) - now) / 1000),
    );
  }, [launch, now]);

  const create = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const next = await createRendererLaunch({
        device_name: "External renderer",
        device_kind: "renderer",
        video_id: videoId,
        material_id: materialId,
        position_seconds: Math.max(0, Math.floor(positionSeconds)),
      });
      setLaunch(next);
      setNow(Date.now());
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("Renderer launch could not be created."),
      );
    } finally {
      setBusy(false);
    }
  };

  const copyLaunchUrl = async () => {
    if (!launch || !navigator.clipboard) return;
    await navigator.clipboard.writeText(launch.launch_url);
    setCopied(true);
  };

  return (
    <section
      className="mb-3 rounded-lg border border-[var(--border)] p-3"
      aria-label={t("External renderer")}
    >
      <div className="flex items-center gap-2">
        <MonitorSmartphone className="h-4 w-4 text-[var(--muted-foreground)]" />
        <span className="min-w-0 flex-1 text-sm font-medium">
          {t("External renderer")}
        </span>
        <button
          type="button"
          onClick={() => void create()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs font-medium disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : launch ? (
            <RefreshCw className="h-3.5 w-3.5" />
          ) : (
            <MonitorSmartphone className="h-3.5 w-3.5" />
          )}
          {launch ? t("New launch code") : t("Connect renderer")}
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-xs text-[var(--destructive)]">
          {error}
        </p>
      )}

      {launch && (
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="shrink-0 rounded-md border border-neutral-200 bg-white p-2 dark:border-neutral-700">
            <QRCodeSVG
              value={launch.launch_url}
              size={112}
              level="M"
              marginSize={1}
              fgColor="#000000"
              bgColor="#ffffff"
            />
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <p className="text-xs text-[var(--muted-foreground)]">
              {secondsLeft > 0
                ? t("Scan within {{seconds}} seconds", {
                    seconds: secondsLeft,
                  })
                : t("This launch code expired.")}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void copyLaunchUrl()}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? t("Copied") : t("Copy launch URL")}
              </button>
              <a
                href={launch.launch_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs"
              >
                {t("Open renderer")}
              </a>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
