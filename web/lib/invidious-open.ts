export function invidiousFallbackUrl(
  publicBaseUrl?: string | null,
  videoId?: string | null,
  positionSeconds?: number | null,
): string {
  const base = String(publicBaseUrl || "").trim().replace(/\/$/, "");
  if (!base) return "";
  const cleanVideoId = String(videoId || "").trim();
  if (cleanVideoId) {
    const pos =
      positionSeconds != null && Number.isFinite(positionSeconds)
        ? Math.max(0, Math.floor(positionSeconds))
        : 0;
    return `${base}/watch?v=${encodeURIComponent(cleanVideoId)}${pos > 1 ? `&t=${pos}` : ""}`;
  }
  return `${base}/feed/popular`;
}

export function shouldOpenInvidiousInCurrentTab(
  preferSameTab: boolean,
  popupAvailable: boolean,
): boolean {
  return preferSameTab || !popupAvailable;
}
