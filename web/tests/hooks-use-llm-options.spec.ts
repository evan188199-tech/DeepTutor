import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLLMOptions } from "@/hooks/useLLMOptions";
import type { LLMOptionsResponse } from "@/lib/llm-options";

function response(
  overrides?: Partial<LLMOptionsResponse>,
): LLMOptionsResponse {
  return {
    active: null,
    options: [
      {
        profile_id: "p1",
        model_id: "m1",
        profile_name: "Profile 1",
        model_name: "Model 1",
        model: "model-1",
        provider: "openai",
        is_active_default: true,
      },
    ],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("useLLMOptions", () => {
  it("starts in a loading state with an empty catalog", () => {
    const loader = vi.fn(() => new Promise<LLMOptionsResponse>(() => {}));
    const { result } = renderHook(() => useLLMOptions(loader));
    expect(result.current.loading).toBe(true);
    expect(result.current.options).toEqual([]);
    expect(result.current.activeDefault).toBeNull();
    expect(result.current.error).toBe(false);
  });

  it("publishes the loaded catalog and leaves loading", async () => {
    const loader = vi.fn(async () =>
      response({ active: { profile_id: "p1", model_id: "m1" } }),
    );
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(false);
    expect(result.current.options).toHaveLength(1);
    expect(result.current.activeDefault).toEqual({
      profile_id: "p1",
      model_id: "m1",
    });
  });

  it("lands in the error state when the initial load fails", async () => {
    const loader = vi.fn(async () => {
      throw new Error("network down");
    });
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.loading).toBe(false);
    expect(result.current.options).toEqual([]);
  });

  it("coalesces concurrent refreshes into one in-flight load", async () => {
    let release: (value: LLMOptionsResponse) => void = () => {};
    const loader = vi.fn(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useLLMOptions(loader));

    await act(async () => {
      void result.current.refresh();
      void result.current.refresh();
      void result.current.refresh();
    });
    expect(loader).toHaveBeenCalledTimes(1);

    await act(async () => {
      release(response());
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.options).toHaveLength(1);
  });

  it("starts a fresh load once the in-flight one settles", async () => {
    const loader = vi.fn(async () => response());
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(loader).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.refresh();
    });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("keeps the last catalog visible during a background refresh", async () => {
    let release: (value: LLMOptionsResponse) => void = () => {};
    const loader = vi.fn(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useLLMOptions(loader));
    await act(async () => {
      release(response());
    });
    await waitFor(() => expect(result.current.options).toHaveLength(1));

    let second: (value: LLMOptionsResponse) => void = () => {};
    loader.mockImplementationOnce(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          second = resolve;
        }),
    );
    let refreshPromise: Promise<void> = Promise.resolve();
    await act(async () => {
      refreshPromise = result.current.refresh({ background: true });
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.options).toHaveLength(1);

    await act(async () => {
      second(
        response({
          options: [
            {
              profile_id: "p2",
              model_id: "m2",
              profile_name: "Profile 2",
              model_name: "Model 2",
              model: "model-2",
              provider: "anthropic",
              is_active_default: false,
            },
          ],
        }),
      );
      await refreshPromise;
    });
    await waitFor(() => expect(result.current.options).toHaveLength(1));
    expect(result.current.options[0]?.profile_id).toBe("p2");
  });

  it("falls back to ready on a failed refresh when a catalog exists", async () => {
    const loader = vi.fn(async () => response());
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.options).toHaveLength(1));

    loader.mockRejectedValueOnce(new Error("boom"));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.error).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.options).toHaveLength(1);
  });

  it("drops the result of an abandoned load after unmount", async () => {
    let release: (value: LLMOptionsResponse) => void = () => {};
    const loader = vi.fn(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          release = resolve;
        }),
    );
    const { result, unmount } = renderHook(() => useLLMOptions(loader));
    unmount();

    await act(async () => {
      release(response());
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.options).toEqual([]);
  });
});
