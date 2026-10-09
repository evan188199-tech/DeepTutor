import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";

function storageKey(name: string) {
  return `panel:${name}:collapsed`;
}

beforeEach(() => {
  localStorage.clear();
});

describe("useCollapsiblePanel", () => {
  it("starts expanded by default", () => {
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    expect(result.current.collapsed).toBe(false);
  });

  it("keeps defaultCollapsed when nothing is stored", () => {
    const { result } = renderHook(() =>
      useCollapsiblePanel("sidebar", true),
    );
    expect(result.current.collapsed).toBe(true);
  });

  it("hydrates stored collapsed=1 after mount", () => {
    localStorage.setItem(storageKey("sidebar"), "1");
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    expect(result.current.collapsed).toBe(true);
  });

  it("hydrates stored collapsed=0 over a collapsed default", () => {
    localStorage.setItem(storageKey("sidebar"), "0");
    const { result } = renderHook(() => useCollapsiblePanel("sidebar", true));
    expect(result.current.collapsed).toBe(false);
  });

  it("persists setCollapsed(true) as 1", () => {
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    act(() => {
      result.current.setCollapsed(true);
    });
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKey("sidebar"))).toBe("1");
  });

  it("persists setCollapsed(false) as 0", () => {
    localStorage.setItem(storageKey("sidebar"), "1");
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    act(() => {
      result.current.setCollapsed(false);
    });
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKey("sidebar"))).toBe("0");
  });

  it("toggle flips the state and persists each direction", () => {
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKey("sidebar"))).toBe("1");
    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKey("sidebar"))).toBe("0");
  });

  it("supports functional updates", () => {
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    act(() => {
      result.current.setCollapsed((prev) => !prev);
    });
    expect(result.current.collapsed).toBe(true);
    act(() => {
      result.current.setCollapsed((prev) => !prev);
    });
    expect(result.current.collapsed).toBe(false);
  });

  it("keeps the state usable when storage writes fail", () => {
    const { result } = renderHook(() => useCollapsiblePanel("sidebar"));
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });
    act(() => {
      result.current.setCollapsed(true);
    });
    expect(result.current.collapsed).toBe(true);
  });

  it("re-hydrates when the storage key changes", () => {
    localStorage.setItem(storageKey("alpha"), "1");
    localStorage.setItem(storageKey("beta"), "0");
    const { result, rerender } = renderHook(
      ({ panelKey }) => useCollapsiblePanel(panelKey),
      { initialProps: { panelKey: "alpha" } },
    );
    expect(result.current.collapsed).toBe(true);
    rerender({ panelKey: "beta" });
    expect(result.current.collapsed).toBe(false);
  });
});
