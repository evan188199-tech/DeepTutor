import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";
import { apiFetch } from "@/lib/api";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import type { StreamEvent } from "@/features/chat/model/protocol";

import { useSetupSync } from "@/hooks/useSetupSync";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

/** A chat message carrying one `setup_applied` tool result, as the wire does. */
function appliedMessage(id: string, key = "theme") {
  return {
    events: [
      {
        type: "tool_result",
        seq: 1,
        tool_call_id: id,
        content: "",
        source: "capability",
        stage: "responding",
        metadata: { tool_metadata: { setup_applied: { key } } },
      } as unknown as StreamEvent,
    ],
  };
}

function uiResponse(payload: Record<string, unknown>): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockResolvedValue(uiResponse({}));
});

afterEach(() => cleanup());

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("useSetupSync", () => {
  it("does not consult the server when no applied setting signal exists", () => {
    renderHook(() => useSetupSync([{ events: [] }]));

    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("re-reads server preferences once for a fresh applied id and writes both languages", async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      uiResponse({ language: "zh", response_language: "fr" }),
    );
    const { rerender } = renderHook(
      ({ messages }) => useSetupSync(messages),
      { initialProps: { messages: [appliedMessage("call-1")] } },
    );

    await waitFor(() => {
      expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh");
    });
    expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBe("fr");
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith("/api/settings/ui");

    // Replayed history is a new array with the same ids: no second sync.
    rerender({ messages: [appliedMessage("call-1")] });
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("syncs again exactly once per newly applied id", async () => {
    const { rerender } = renderHook(
      ({ messages }) => useSetupSync(messages),
      { initialProps: { messages: [appliedMessage("call-1")] } },
    );
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(1);

    rerender({ messages: [appliedMessage("call-1"), appliedMessage("call-2")] });
    await flush();
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });

  it("falls back to the interface language when the server sends no response language", async () => {
    vi.mocked(apiFetch).mockResolvedValue(uiResponse({ language: "de" }));

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await waitFor(() => {
      expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("de");
    });
    expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBe("de");
  });

  it("leaves stored languages untouched when the server language is not selectable", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    vi.mocked(apiFetch).mockResolvedValue(
      uiResponse({ language: "klingon" }),
    );

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await flush();
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("fr");
    expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  });

  it("applies a valid theme to the document and persists it", async () => {
    vi.mocked(apiFetch).mockResolvedValue(uiResponse({ theme: "dark" }));

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await waitFor(() => {
      expect(
        document.documentElement.classList.contains("dark"),
      ).toBe(true);
    });
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("ignores an unknown theme string and keeps the current one", async () => {
    localStorage.setItem(THEME_STORAGE_KEY, "snow");
    vi.mocked(apiFetch).mockResolvedValue(uiResponse({ theme: "neon" }));

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await flush();
    expect(document.documentElement.classList.contains("theme-snow")).toBe(
      false,
    );
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("snow");
  });

  it("ignores a non-ok response without touching stored preferences", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    vi.mocked(apiFetch).mockResolvedValue({
      ok: false,
      json: async () => ({ language: "zh" }),
    } as unknown as Response);

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await flush();
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  });

  it("falls back silently when the sync fails and keeps the stored preferences", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "pl");
    vi.mocked(apiFetch).mockRejectedValue(new TypeError("network down"));

    renderHook(() => useSetupSync([appliedMessage("call-1")]));

    await flush();
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("pl");
    expect(apiFetch).toHaveBeenCalledTimes(1);

    // The hook stays usable: a later signal still syncs normally.
    vi.mocked(apiFetch).mockResolvedValue(uiResponse({ language: "pl" }));
    renderHook(() => useSetupSync([appliedMessage("call-2")]));
    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledTimes(2);
    });
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("pl");
  });

  it("cancels an in-flight sync on unmount so nothing is written afterwards", async () => {
    let release: (response: Response) => void = () => {};
    vi.mocked(apiFetch).mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

    const { unmount } = renderHook(() =>
      useSetupSync([appliedMessage("call-1")]),
    );
    unmount();

    await act(async () => {
      release(uiResponse({ language: "zh", theme: "dark" }));
      await Promise.resolve();
    });

    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
