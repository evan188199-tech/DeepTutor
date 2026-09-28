import { apiFetch, apiUrl } from "@/lib/api";
import type { VideoLearningMark, VideoMarkKind } from "@/lib/video-learning-api";

export type PlaybackState =
  | "playing"
  | "paused"
  | "buffering"
  | "ended"
  | "unknown";

export interface RendererDevice {
  device_id: string;
  device_name: string;
  device_kind: string;
  paired_at: string;
  last_seen: string;
  online: boolean;
  capabilities: string[];
}

export interface RendererLaunch {
  bootstrap_id: string;
  ticket: string;
  expires_at: string;
  launch_url: string;
  renderer_origin: string;
  material_id: string;
}

export interface RemoteSession {
  session_id: string;
  owner_id: string;
  device_id: string;
  instance_origin: string;
  video_id: string;
  material_id: string;
  title: string;
  position_ms: number;
  duration_ms: number;
  playback_state: PlaybackState;
  playback_rate: number;
  updated_at: string;
  last_heartbeat_at: string;
  online?: boolean;
}

export interface RemoteCommand {
  command_id: string;
  session_id: string;
  owner_id: string;
  device_id: string;
  command_type: string;
  payload: Record<string, unknown>;
  status: "pending" | "acked" | "failed" | "expired";
  created_at: string;
  acked_at: string | null;
  error: string | null;
}

export type RemoteAnnotation = VideoLearningMark;

export interface SessionCommandInput {
  type: "play" | "pause" | "seek" | "volume" | "mute" | "playback_rate" | "fullscreen";
  position_ms?: number;
  delta_ms?: number;
  volume?: number;
  muted?: boolean;
  playback_rate?: number;
  command_id?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(path), init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const detail = payload.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Request failed (${response.status})`,
    );
  }
  return (await response.json()) as T;
}

export async function createRendererLaunch(payload: {
  device_name?: string;
  device_kind?: string;
  renderer_origin?: string;
  video_id?: string;
  material_id?: string;
  position_seconds?: number;
}): Promise<RendererLaunch> {
  return request<RendererLaunch>("/api/video-learning/renderers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listRendererDevices(): Promise<RendererDevice[]> {
  return request<RendererDevice[]>("/api/video-learning/devices", {
    cache: "no-store",
  });
}

export async function revokeRendererDevice(deviceId: string): Promise<void> {
  await request<{ status: string }>(
    `/api/video-learning/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
  );
}

export async function listRemoteSessions(): Promise<RemoteSession[]> {
  const data = await request<{ sessions: RemoteSession[] }>(
    "/api/video-learning/sessions",
    { cache: "no-store" },
  );
  return data.sessions ?? [];
}

export async function sendRemoteSessionCommand(
  sessionId: string,
  payload: SessionCommandInput,
): Promise<RemoteCommand> {
  return request<RemoteCommand>(
    `/api/video-learning/sessions/${encodeURIComponent(sessionId)}/commands`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function listRemoteAnnotations(
  sessionId: string,
): Promise<RemoteAnnotation[]> {
  const data = await request<{ annotations: RemoteAnnotation[] }>(
    `/api/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations`,
    { cache: "no-store" },
  );
  return data.annotations ?? [];
}

export async function createRemoteAnnotation(
  sessionId: string,
  payload: { kind: VideoMarkKind; note?: string },
): Promise<RemoteAnnotation> {
  return request<RemoteAnnotation>(
    `/api/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function formatRemotePosition(ms: number): string {
  const total = Math.max(0, Math.floor(Number(ms) / 1000 || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}
