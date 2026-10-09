import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { useSetupSync } from "@/hooks/useSetupSync";
import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";
import { apiFetch } from "@/lib/api";
import { setTheme } from "@/lib/theme";
import type { StreamEvent } from "@/features/chat/model/protocol";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));
vi.mock("@/lib/theme", () => ({ setTheme: vi.fn() }));

function appliedMessage(toolCallId: string): { events: StreamEvent[] } {
  return {
    events: [
      {
        type: "tool_result",
        source: "test",
        stage: "loop",
        content: "",
        metadata: { tool_metadata: { setup_applied: { key: "theme" } } },
        tool_call_id: toolCallId,
        seq: 1,
        timestamp: 0,
      } as unknown as StreamEvent,
    ],
  };
}

function uiResponse(payload: Record<string, unknown>): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(apiFetch).mockReset();
  vi.mocked(setTheme).mockReset();
});

it("applies the server's language, response language and theme once per tool call", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    uiResponse({ language: "de", response_language: "ja", theme: "glass" }),
  );
  renderHook(() => useSetupSync([appliedMessage("call-1")]));

  await waitFor(() =>
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("de"),
  );
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBe("ja");
  expect(setTheme).toHaveBeenCalledWith("glass");
  expect(apiFetch).toHaveBeenCalledWith("/api/settings/ui");
});

it("does not refetch when the same history replays or the component re-renders", async () => {
  vi.mocked(apiFetch).mockResolvedValue(uiResponse({ theme: "glass" }));
  const messages = [appliedMessage("call-1")];
  const { rerender } = renderHook(
    ({ msgs }) => useSetupSync(msgs),
    { initialProps: { msgs: messages } },
  );
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));

  rerender({ msgs: messages });
  rerender({ msgs: [appliedMessage("call-1")] });
  await Promise.resolve();
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

it("honours a second, distinct tool call exactly once more", async () => {
  vi.mocked(apiFetch).mockResolvedValue(uiResponse({ theme: "snow" }));
  const { rerender } = renderHook(
    ({ msgs }) => useSetupSync(msgs),
    { initialProps: { msgs: [appliedMessage("call-1")] } },
  );
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));

  rerender({ msgs: [appliedMessage("call-1"), appliedMessage("call-2")] });
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2));
});

it("adopts nothing when the server answers with a non-ok response", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ ok: false } as Response);
  renderHook(() => useSetupSync([appliedMessage("call-1")]));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(setTheme).not.toHaveBeenCalled();
});

it("survives a rejected fetch without writing any preference", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new Error("network down"));
  renderHook(() => useSetupSync([appliedMessage("call-1")]));
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(setTheme).not.toHaveBeenCalled();
});

it("ignores a response that lands after unmount", async () => {
  let resolve!: (value: Response) => void;
  vi.mocked(apiFetch).mockReturnValue(
    new Promise<Response>((res) => {
      resolve = res;
    }),
  );
  const { unmount } = renderHook(() =>
    useSetupSync([appliedMessage("call-late")]),
  );
  unmount();

  resolve(uiResponse({ language: "de", theme: "dark" }));
  await new Promise((res) => setTimeout(res, 0));

  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(setTheme).not.toHaveBeenCalled();
});

it("keeps unrecognized languages and themes out of the browser", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    uiResponse({ language: "klingon", response_language: "xx", theme: "neon" }),
  );
  renderHook(() => useSetupSync([appliedMessage("call-1")]));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(setTheme).not.toHaveBeenCalled();
});

it("applies a valid theme even when the payload carries no language", async () => {
  vi.mocked(apiFetch).mockResolvedValue(uiResponse({ theme: "snow" }));
  renderHook(() => useSetupSync([appliedMessage("call-1")]));

  await waitFor(() => expect(setTheme).toHaveBeenCalledWith("snow"));
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
});

it("leaves the browser untouched without any setup_applied signal", () => {
  renderHook(() => useSetupSync([{ events: [] }]));
  expect(apiFetch).not.toHaveBeenCalled();
  expect(setTheme).not.toHaveBeenCalled();
});
