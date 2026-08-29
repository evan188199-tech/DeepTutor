"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { getVideoLearningMaterial, resolveVideoLearning, saveVideoPosition, type TimedMediaMaterial } from "@/lib/video-learning-api";
import {
  clearPersistedWatchingState,
  getWatchingModeActive,
  persistWatchingState,
  readPersistedWatchingState,
  setWatchingMaterial,
  setWatchingViewport,
  subscribeWatchingMode,
  watchingSessionStorageKey,
} from "@/lib/watching-turn-state";

interface WatchingContextValue {
  material: TimedMediaMaterial | null;
  active: boolean;
  loading: boolean;
  error: string | null;
  restoredFromSession: boolean;
  currentTime: number;
  pendingSeek: number | null;
  openUrl: (url: string) => Promise<boolean>;
  openMaterial: (materialId: string, options?: { seekSeconds?: number }) => Promise<void>;
  replaceMaterial: (next: TimedMediaMaterial) => void;
  close: () => void;
  setCurrentTime: (seconds: number, locator?: number) => void;
  seek: (seconds: number) => void;
  clearSeek: () => void;
}

const WatchingContext = createContext<WatchingContextValue>({ material: null, active: false, loading: false, error: null, restoredFromSession: false, currentTime: 0, pendingSeek: null, openUrl: async () => false, openMaterial: async () => {}, replaceMaterial: () => {}, close: () => {}, setCurrentTime: () => {}, seek: () => {}, clearSeek: () => {} });

function replaceWatchingUrl(materialId: string, timeSeconds: number): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("watching_material", materialId);
  if (timeSeconds > 0) url.searchParams.set("t", String(Math.floor(timeSeconds)));
  else url.searchParams.delete("t");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function clearWatchingUrl(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("watching_material");
  url.searchParams.delete("t");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

export function WatchingProvider({ children }: { children: ReactNode }) {
  const [material, setMaterial] = useState<TimedMediaMaterial | null>(null);
  const active = useSyncExternalStore(subscribeWatchingMode, getWatchingModeActive, () => false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoredFromSession, setRestoredFromSession] = useState(false);
  const [currentTime, setCurrentTimeState] = useState(0);
  const currentTimeRef = useRef(0);
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);
  const tokenRef = useRef(0);
  const lastSavedRef = useRef(0);

  useEffect(() => { setWatchingMaterial(material?.material_id ?? null); }, [material]);
  const sessionStorageKey = watchingSessionStorageKey();
  useEffect(() => {
    // The first video open can happen on `/home?watching_material=...`; that
    // route has no session-scoped storage key yet. Persist again when the
    // router replaces it with `/home/<sessionId>` so a later hard refresh can
    // restore the viewer instead of falling back to Reading.
    if (!material || !sessionStorageKey) return;
    persistWatchingState({ materialId: material.material_id, timeSeconds: currentTimeRef.current });
  }, [material, sessionStorageKey]);
  const accept = useCallback((next: TimedMediaMaterial, seekSeconds?: number, fromSession = false) => {
    const fallback = Number(next.source.entry_time_seconds || next.learning.last_position || 0);
    const start = Number.isFinite(seekSeconds) ? Math.max(0, Number(seekSeconds)) : fallback;
    setMaterial(next);
    setCurrentTimeState(start);
    currentTimeRef.current = start;
    setPendingSeek(start);
    setWatchingViewport({ timeSeconds: start });
    lastSavedRef.current = start;
    persistWatchingState({ materialId: next.material_id, timeSeconds: start });
    replaceWatchingUrl(next.material_id, start);
    setRestoredFromSession(fromSession);
  }, []);
  useEffect(() => {
    const persisted = readPersistedWatchingState();
    if (!persisted || !sessionStorageKey) return;
    let cancelled = false;
    const restoreToken = ++tokenRef.current;
    setLoading(true);
    void getVideoLearningMaterial(persisted.materialId)
      .then((next) => {
        if (!cancelled && restoreToken === tokenRef.current) accept(next, persisted.timeSeconds, true);
      })
      .catch(() => {
        if (!cancelled && restoreToken === tokenRef.current) setError("This video learning material could not be restored.");
      })
      .finally(() => {
        if (!cancelled && restoreToken === tokenRef.current) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accept, sessionStorageKey]);
  const openUrl = useCallback(async (url: string): Promise<boolean> => {
    const token = ++tokenRef.current; setLoading(true); setError(null); setRestoredFromSession(false);
    try {
      const next = await resolveVideoLearning(url);
      if (token !== tokenRef.current) return false;
      accept(next);
      return true;
    }
    catch (caught) {
      if (token === tokenRef.current) setError(caught instanceof Error ? caught.message : "This YouTube video could not be opened.");
      return false;
    }
    finally { if (token === tokenRef.current) setLoading(false); }
  }, [accept]);
  const openMaterial = useCallback(async (materialId: string, options?: { seekSeconds?: number }) => {
    const token = ++tokenRef.current; setLoading(true); setError(null); setRestoredFromSession(false);
    try {
      const next = await getVideoLearningMaterial(materialId);
      if (token === tokenRef.current) accept(next, options?.seekSeconds);
    }
    catch (caught) { if (token === tokenRef.current) setError(caught instanceof Error ? caught.message : "This video learning material could not be opened."); }
    finally { if (token === tokenRef.current) setLoading(false); }
  }, [accept]);
  const setCurrentTime = useCallback((seconds: number, locator?: number) => {
    const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0); currentTimeRef.current = safe; setCurrentTimeState(safe); setWatchingViewport({ timeSeconds: safe, locator });
    if (material && Math.abs(safe - lastSavedRef.current) >= 10) { lastSavedRef.current = safe; persistWatchingState({ materialId: material.material_id, timeSeconds: safe }); void saveVideoPosition(material.material_id, safe).catch(() => {}); }
  }, [material]);
  const replaceMaterial = useCallback((next: TimedMediaMaterial) => { setMaterial(next); }, []);
  const close = useCallback(() => { tokenRef.current += 1; clearPersistedWatchingState(); clearWatchingUrl(); setMaterial(null); setError(null); setRestoredFromSession(false); currentTimeRef.current = 0; setCurrentTimeState(0); setPendingSeek(null); setWatchingViewport({ timeSeconds: 0, locator: 0 }); }, []);
  const seek = useCallback((seconds: number) => { const safe = Math.max(0, seconds); currentTimeRef.current = safe; setPendingSeek(safe); setCurrentTimeState(safe); setWatchingViewport({ timeSeconds: safe }); }, []);
  const clearSeek = useCallback(() => setPendingSeek(null), []);
  useEffect(() => {
    const onClick = (event: MouseEvent) => { const target = event.target instanceof Element ? event.target.closest("a[href^=\"#dt-time-\"]") : null; if (!target) return; const value = Number((target as HTMLAnchorElement).hash.slice(9)); if (!Number.isFinite(value)) return; event.preventDefault(); seek(value); };
    window.addEventListener("click", onClick); return () => window.removeEventListener("click", onClick);
  }, [seek]);
  const value = useMemo(() => ({ material, active, loading, error, restoredFromSession, currentTime, pendingSeek, openUrl, openMaterial, replaceMaterial, close, setCurrentTime, seek, clearSeek }), [material, active, loading, error, restoredFromSession, currentTime, pendingSeek, openUrl, openMaterial, replaceMaterial, close, setCurrentTime, seek, clearSeek]);
  return <WatchingContext.Provider value={value}>{children}</WatchingContext.Provider>;
}

export function useWatching(): WatchingContextValue { return useContext(WatchingContext); }
