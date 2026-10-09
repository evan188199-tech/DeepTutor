import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

vi.mock("@/lib/api", () => api);

/**
 * The hook keeps a module-level preference cache and in-flight request slot;
 * resetting the module registry per test gives each case a fresh cache.
 */
async function loadPreferenceHook() {
  const mod = await import("@/hooks/useVoiceMathSpeak");
  return mod.useVoiceMathSpeakPreference;
}

function settingsResponse(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload };
}

beforeEach(() => {
  vi.resetModules();
  api.apiFetch.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("starts optimistic-on and loading before settings resolve", async () => {
  api.apiFetch.mockReturnValue(new Promise(() => {}));
  const usePreference = await loadPreferenceHook();
  const { result } = renderHook(() => usePreference());
  expect(result.current.value).toBe(true);
  expect(result.current.loading).toBe(true);
});

it("hydrates the saved preference from /api/settings", async () => {
  api.apiFetch.mockResolvedValue(
    settingsResponse({ ui: { voice_math_speak: true } }),
  );
  const usePreference = await loadPreferenceHook();
  const { result } = renderHook(() => usePreference());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.value).toBe(true);
  expect(api.apiFetch).toHaveBeenCalledWith("/api/settings");
});

it("honors a server-side off preference", async () => {
  api.apiFetch.mockResolvedValue(
    settingsResponse({ ui: { voice_math_speak: false } }),
  );
  const usePreference = await loadPreferenceHook();
  const { result } = renderHook(() => usePreference());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.value).toBe(false);
  expect(result.current.error).toBeUndefined();
});

it("falls back to enabled when the settings request fails", async () => {
  api.apiFetch.mockRejectedValue(new Error("offline"));
  const usePreference = await loadPreferenceHook();
  const { result } = renderHook(() => usePreference());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.value).toBe(true);
});

it("saves toggles with an optimistic update and a PUT", async () => {
  api.apiFetch.mockResolvedValue(settingsResponse({ ui: {} }));
  const usePreference = await loadPreferenceHook();
  const { result } = renderHook(() => usePreference());
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => {
    await result.current.setValue(false);
  });
  expect(result.current.value).toBe(false);
  const [url, init] = api.apiFetch.mock.calls.at(-1) as [
    string,
    RequestInit & { body: string; headers: Record<string, string> },
  ];
  expect(url).toBe("/api/settings/voice-math-speak");
  expect(init.method).toBe("PUT");
  expect(init.headers["Content-Type"]).toBe("application/json");
  expect(init.body).toBe(JSON.stringify({ voice_math_speak: false }));
});

it("broadcasts toggles to concurrently mounted instances", async () => {
  api.apiFetch.mockResolvedValue(settingsResponse({ ui: {} }));
  const usePreference = await loadPreferenceHook();
  const first = renderHook(() => usePreference());
  const second = renderHook(() => usePreference());
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  await waitFor(() => expect(second.result.current.loading).toBe(false));
  await act(async () => {
    await first.result.current.setValue(false);
  });
  expect(first.result.current.value).toBe(false);
  expect(second.result.current.value).toBe(false);
});

it("reuses the cached preference for later mounts", async () => {
  api.apiFetch.mockResolvedValue(
    settingsResponse({ ui: { voice_math_speak: true } }),
  );
  const usePreference = await loadPreferenceHook();
  const first = renderHook(() => usePreference());
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  first.unmount();
  const second = renderHook(() => usePreference());
  expect(second.result.current.loading).toBe(false);
  expect(second.result.current.value).toBe(true);
  expect(api.apiFetch).toHaveBeenCalledTimes(1);
});

it("shares a single in-flight settings request across mounts", async () => {
  let resolveSettings: (value: unknown) => void = () => {};
  api.apiFetch.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveSettings = resolve;
      }),
  );
  const usePreference = await loadPreferenceHook();
  const first = renderHook(() => usePreference());
  const second = renderHook(() => usePreference());
  expect(api.apiFetch).toHaveBeenCalledTimes(1);
  resolveSettings(settingsResponse({ ui: { voice_math_speak: false } }));
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  await waitFor(() => expect(second.result.current.loading).toBe(false));
  expect(first.result.current.value).toBe(false);
  expect(second.result.current.value).toBe(false);
});

it("ignores settings responses that land after unmount", async () => {
  let resolveSettings: (value: unknown) => void = () => {};
  api.apiFetch.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveSettings = resolve;
      }),
  );
  const usePreference = await loadPreferenceHook();
  const { unmount } = renderHook(() => usePreference());
  unmount();
  resolveSettings(settingsResponse({ ui: { voice_math_speak: false } }));
  await Promise.resolve();
  await Promise.resolve();
  expect(api.apiFetch).toHaveBeenCalledTimes(1);
});
