import { apiFetch, apiUrl } from "@/lib/api";
import type { TimedMediaMaterial } from "@/lib/video-learning-api";

export interface WatchingBinding {
  session_id: string;
  material_id: string;
  material: TimedMediaMaterial | null;
  legacy_watching?: boolean;
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as T;
}

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => ({}));
  const detail = (payload as { detail?: unknown })?.detail;
  const message =
    typeof detail === "string"
      ? detail
      : typeof (detail as { message?: unknown } | undefined)?.message === "string"
        ? (detail as { message: string }).message
        : null;
  return new Error(message || `Request failed (${response.status})`);
}

function bindingUrl(sessionId: string): string {
  return apiUrl(`/api/video-learning/watching/${encodeURIComponent(sessionId)}`);
}

export async function startWatchingSession(
  materialId: string,
  title = "",
): Promise<WatchingBinding> {
  return unwrap(
    await apiFetch(apiUrl("/api/video-learning/watching"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ material_id: materialId, title }),
    }),
  );
}

export async function fetchWatchingBinding(sessionId: string): Promise<WatchingBinding> {
  return unwrap(await apiFetch(bindingUrl(sessionId)));
}

export async function bindWatchingMaterial(
  sessionId: string,
  materialId: string,
): Promise<WatchingBinding> {
  return unwrap(
    await apiFetch(bindingUrl(sessionId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ material_id: materialId }),
    }),
  );
}
