import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";

const KEY = "spec-panel";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("useCollapsiblePanel", () => {
  it("starts at the default state when nothing is stored", () => {
    const { result } = renderHook(() => useCollapsiblePanel(KEY, false));
    expect(result.current.collapsed).toBe(false);
  });

  it("honours a stored default of collapsed", () => {
    const { result } = renderHook(() => useCollapsiblePanel(KEY, true));
    expect(result.current.collapsed).toBe(true);
  });

  it("hydrates from localStorage after mount", () => {
    window.localStorage.setItem(`panel:${KEY}:collapsed`, "1");
    const { result } = renderHook(() => useCollapsiblePanel(KEY, false));
    expect(result.current.collapsed).toBe(true);
  });

  it("treats a stored 0 as expanded", () => {
    window.localStorage.setItem(`panel:${KEY}:collapsed`, "0");
    const { result } = renderHook(() => useCollapsiblePanel(KEY, true));
    expect(result.current.collapsed).toBe(false);
  });

  it("keeps the default when storage access throws", () => {
    const original = window.localStorage;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem() {
          throw new Error("storage denied");
        },
      },
    });
    try {
      const { result } = renderHook(() => useCollapsiblePanel(KEY, true));
      expect(result.current.collapsed).toBe(true);
    } finally {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        value: original,
      });
    }
  });

  it("persists toggles back to localStorage", () => {
    const { result } = renderHook(() => useCollapsiblePanel(KEY, false));
    expect(window.localStorage.getItem(`panel:${KEY}:collapsed`)).toBeNull();

    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(true);
    expect(window.localStorage.getItem(`panel:${KEY}:collapsed`)).toBe("1");

    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(false);
    expect(window.localStorage.getItem(`panel:${KEY}:collapsed`)).toBe("0");
  });

  it("accepts direct set values", () => {
    const { result } = renderHook(() => useCollapsiblePanel(KEY, false));
    act(() => {
      result.current.setCollapsed(true);
    });
    expect(result.current.collapsed).toBe(true);
    expect(window.localStorage.getItem(`panel:${KEY}:collapsed`)).toBe("1");
  });

  it("rehydrates when the storage key changes", () => {
    window.localStorage.setItem("panel:other:collapsed", "1");
    const { result, rerender } = renderHook(
      ({ storageKey }) => useCollapsiblePanel(storageKey, false),
      { initialProps: { storageKey: KEY } },
    );
    expect(result.current.collapsed).toBe(false);

    rerender({ storageKey: "other" });
    expect(result.current.collapsed).toBe(true);
  });
});
