import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useEmbeddingModels } from "@/hooks/useEmbeddingModels";
import type { ModelOption } from "@/features/knowledge/model/types";

const fixtures = vi.hoisted(() => ({
  models: vi.fn(),
}));
vi.mock("@/features/knowledge/api/engines", () => ({
  getEngineModelOptions: fixtures.models,
}));

const option = (modelId: string): ModelOption => ({
  profile_id: "provider",
  profile_name: "Provider",
  model_id: modelId,
  label: `Model ${modelId}`,
  model: modelId,
  detail: "2d",
});

const withEmbeddingOptions = (
  options: ModelOption[] | null,
  active: { profile_id: string; model_id: string } | null,
) => ({ embedding: { active, options } });

describe("useEmbeddingModels", () => {
  beforeEach(() => {
    fixtures.models
      .mockReset()
      .mockResolvedValue(
        withEmbeddingOptions([option("a"), option("b")], {
          profile_id: "provider",
          model_id: "b",
        }),
      );
  });

  it("selects the engine's active default when no preferred model is given", async () => {
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.options).toHaveLength(2);
    expect(result.current.selection).toEqual({
      profile_id: "provider",
      model_id: "b",
    });
    expect(result.current.error).toBeNull();
  });

  it("falls back to the first option when the engine reports no active default", async () => {
    fixtures.models.mockResolvedValue(
      withEmbeddingOptions([option("a"), option("b")], null),
    );
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.selection).toEqual({
      profile_id: "provider",
      model_id: "a",
    });
  });

  it("normalizes a payload without the embedding kind to an empty list", async () => {
    fixtures.models.mockResolvedValue({});
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.options).toEqual([]);
    expect(result.current.selection).toBeNull();
  });

  it("normalizes a non-array options payload to an empty list", async () => {
    fixtures.models.mockResolvedValue(
      withEmbeddingOptions(null, { profile_id: "provider", model_id: "a" }),
    );
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.options).toEqual([]);
    expect(result.current.selection).toBeNull();
  });

  it("keeps no selection when the configured embedding list is empty", async () => {
    fixtures.models.mockResolvedValue(
      withEmbeddingOptions([], { profile_id: "provider", model_id: "b" }),
    );
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.options).toEqual([]);
    expect(result.current.selection).toBeNull();
  });

  it("does not fetch when disabled and keeps the preferred selection", async () => {
    const preferred = { profile_id: "provider", model_id: "a" };
    const { result } = renderHook(() =>
      useEmbeddingModels(preferred, false),
    );
    await act(async () => {});
    expect(fixtures.models).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.selection).toEqual(preferred);
    expect(result.current.options).toEqual([]);
  });

  it("reports a failed load through its error state", async () => {
    fixtures.models.mockRejectedValue(new Error("engine offline"));
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("engine offline");
    expect(result.current.options).toEqual([]);
  });

  it("stringifies non-error rejections", async () => {
    fixtures.models.mockRejectedValue("engine offline");
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("engine offline");
  });

  it("accepts a manual selection update after loading", async () => {
    const { result } = renderHook(() => useEmbeddingModels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setSelection({ profile_id: "provider", model_id: "a" });
    });
    expect(result.current.selection).toEqual({
      profile_id: "provider",
      model_id: "a",
    });
  });
});
