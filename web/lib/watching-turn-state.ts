export const WATCHING_CAPABILITY = "immersive_watching";
export const WATCHING_ASK_EVENT = "dt:watching-ask";

const state = { materialId: null as string | null, timeSeconds: 0, locator: 0 };
let modeActive = false;
const modeListeners = new Set<() => void>();

export interface PersistedWatchingState {
  materialId: string;
  timeSeconds: number;
}

export function watchingSessionStorageKey(pathname?: string): string | null {
  const currentPath = pathname ?? (typeof window === "undefined" ? "" : window.location.pathname);
  const match = currentPath.match(/^\/home\/([^/]+)/);
  if (!match?.[1]) return null;
  return `dt:watching-session:${decodeURIComponent(match[1])}`;
}

export function readPersistedWatchingState(pathname?: string): PersistedWatchingState | null {
  const key = watchingSessionStorageKey(pathname);
  if (!key || typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedWatchingState>;
    if (typeof parsed.materialId !== "string" || !parsed.materialId) return null;
    const timeSeconds = Number(parsed.timeSeconds);
    return { materialId: parsed.materialId, timeSeconds: Number.isFinite(timeSeconds) ? Math.max(0, timeSeconds) : 0 };
  } catch {
    return null;
  }
}

export function persistWatchingState(state: PersistedWatchingState, pathname?: string): void {
  const key = watchingSessionStorageKey(pathname);
  if (!key || typeof window === "undefined") return;
  try { window.sessionStorage.setItem(key, JSON.stringify(state)); } catch { /* storage can be unavailable */ }
}

export function clearPersistedWatchingState(pathname?: string): void {
  const key = watchingSessionStorageKey(pathname);
  if (!key || typeof window === "undefined") return;
  try { window.sessionStorage.removeItem(key); } catch { /* storage can be unavailable */ }
}

export function setWatchingModeActive(active: boolean): void {
  if (modeActive === active) return;
  modeActive = active;
  modeListeners.forEach((listener) => listener());
}

export function getWatchingModeActive(): boolean { return modeActive; }
export function subscribeWatchingMode(listener: () => void): () => void {
  modeListeners.add(listener);
  return () => modeListeners.delete(listener);
}

export function setWatchingMaterial(materialId: string | null): void {
  state.materialId = materialId;
  if (!materialId) { state.timeSeconds = 0; state.locator = 0; }
}

export function setWatchingViewport(next: { timeSeconds?: number; locator?: number }): void {
  if (typeof next.timeSeconds === "number" && Number.isFinite(next.timeSeconds)) state.timeSeconds = Math.max(0, next.timeSeconds);
  if (typeof next.locator === "number" && Number.isFinite(next.locator)) state.locator = Math.max(0, Math.floor(next.locator));
}

export function watchingTurnFields(capability: string | null | undefined): { timed_media_id?: string; timed_media_viewport?: { time_seconds: number; locator?: number } } {
  if (capability !== WATCHING_CAPABILITY || !state.materialId) return {};
  return { timed_media_id: state.materialId, timed_media_viewport: { time_seconds: state.timeSeconds, ...(state.locator > 0 ? { locator: state.locator } : {}) } };
}

export function resetWatchingTurnState(): void { state.materialId = null; state.timeSeconds = 0; state.locator = 0; }
