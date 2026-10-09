import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { useLLMOptions } from "@/hooks/useLLMOptions";
import type { LLMOptionsResponse } from "@/lib/llm-options";

type OptionsLoader = (options?: { force?: boolean }) => Promise<LLMOptionsResponse>;

const catalog = (modelId: string): LLMOptionsResponse => ({
  active: { profile_id: "profile-1", model_id: modelId },
  options: [
    {
      profile_id: "profile-1",
      model_id: modelId,
      profile_name: "Primary",
      model_name: `Model ${modelId}`,
      model: modelId,
      provider: "openai",
      is_active_default: true,
    },
  ],
});

describe("useLLMOptions", () => {
  let loader: Mock<OptionsLoader>;

  beforeEach(() => {
    loader = vi.fn();
  });

  it("loads the catalog on mount and exposes the active default", async () => {
    loader.mockResolvedValue(catalog("model-1"));
    const { result } = renderHook(() => useLLMOptions(loader));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(false);
    expect(result.current.options).toEqual(catalog("model-1").options);
    expect(result.current.activeDefault).toEqual(catalog("model-1").active);
  });

  it("surfaces an error and an empty catalog when the initial load fails", async () => {
    loader.mockRejectedValue(new Error("unavailable"));
    const { result } = renderHook(() => useLLMOptions(loader));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(true);
    expect(result.current.options).toEqual([]);
    expect(result.current.activeDefault).toBeNull();
  });

  it("keeps the last usable catalog ready when a later refresh fails", async () => {
    loader.mockResolvedValueOnce(catalog("model-1"));
    loader.mockRejectedValueOnce(new Error("refresh failed"));
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.options).toHaveLength(1));

    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.error).toBe(false);
    expect(result.current.loading).toBe(false);
    expect(result.current.options).toEqual(catalog("model-1").options);
    expect(result.current.activeDefault).toEqual(catalog("model-1").active);
  });

  it("reloads the catalog from the loader on an explicit refresh", async () => {
    loader
      .mockResolvedValueOnce(catalog("model-1"))
      .mockResolvedValueOnce(catalog("model-2"));
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.activeDefault).toEqual(catalog("model-1").active);

    await act(async () => {
      await result.current.refresh();
    });
    expect(loader).toHaveBeenCalledTimes(2);
    expect(result.current.loading).toBe(false);
    expect(result.current.options).toEqual(catalog("model-2").options);
    expect(result.current.activeDefault).toEqual(catalog("model-2").active);
  });

  it("passes the force flag through to the loader", async () => {
    loader.mockResolvedValue(catalog("model-1"));
    const { result } = renderHook(() => useLLMOptions(loader));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(loader).toHaveBeenLastCalledWith({ force: undefined });

    await act(async () => {
      await result.current.refresh({ force: true });
    });
    expect(loader).toHaveBeenLastCalledWith({ force: true });
  });

  it("coalesces concurrent refreshes into one in-flight loader call", async () => {
    let resolveFirst: (payload: LLMOptionsResponse) => void = () => {};
    loader.mockImplementation(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          resolveFirst = resolve;
        }),
    );
    const { result } = renderHook(() => useLLMOptions(loader));
    const refresh = result.current.refresh;

    await act(async () => {
      const second = refresh();
      const third = refresh();
      resolveFirst(catalog("model-1"));
      await Promise.all([second, third]);
    });

    expect(loader).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.options).toEqual(catalog("model-1").options);
  });

  it("does not update state after unmount", async () => {
    let resolveFirst: (payload: LLMOptionsResponse) => void = () => {};
    loader.mockImplementation(
      () =>
        new Promise<LLMOptionsResponse>((resolve) => {
          resolveFirst = resolve;
        }),
    );
    const { result, unmount } = renderHook(() => useLLMOptions(loader));
    const optionsBeforeUnmount = result.current.options;
    unmount();

    expect(() => resolveFirst(catalog("model-1"))).not.toThrow();
    expect(optionsBeforeUnmount).toEqual([]);
  });
});
