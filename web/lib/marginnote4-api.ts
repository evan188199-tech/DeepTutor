import { apiFetch, apiUrl } from "@/lib/api";

export interface MarginNoteDevice {
  device_id: string;
  device_name: string;
  device_kind: "macos" | "ipados";
  protocol_version: number;
  paired_at: string;
  last_seen: string;
  active: boolean;
}

export interface MarginNotePairingCode {
  code: string;
  expires_at: string;
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // Non-JSON errors use the action-specific fallback.
  }
  return fallback;
}

function libraryPath(kbRef: string): string {
  return kbRef
    .split("/")
    .map(encodeURIComponent)
    .join("/");
}

export async function createMarginNotePairingCode(
  kbRef: string,
): Promise<MarginNotePairingCode> {
  const res = await apiFetch(apiUrl("/api/v1/marginnote4/pairing-codes"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kb_ref: kbRef }),
  });
  if (!res.ok) {
    throw new Error(await readError(res, "Unable to create pairing code"));
  }
  return (await res.json()) as MarginNotePairingCode;
}

export async function listMarginNoteDevices(
  kbRef: string,
): Promise<MarginNoteDevice[]> {
  const res = await apiFetch(
    apiUrl(`/api/v1/marginnote4/libraries/${libraryPath(kbRef)}/devices`),
  );
  if (!res.ok) {
    throw new Error(await readError(res, "Unable to load MarginNote devices"));
  }
  return (await res.json()) as MarginNoteDevice[];
}

export async function revokeMarginNoteDevice(deviceId: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/marginnote4/devices/${encodeURIComponent(deviceId)}`),
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(await readError(res, "Unable to revoke MarginNote device"));
  }
}
