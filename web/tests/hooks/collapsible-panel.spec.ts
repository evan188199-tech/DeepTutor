import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";

function storageKeyFor(key: string) {
  return `panel:${key}:collapsed`;
}

describe("useCollapsiblePanel", () => {
  it("starts expanded, persists toggles and returns to expanded", () => {
    const { result } = renderHook(() => useCollapsiblePanel("outline"));
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKeyFor("outline"))).toBeNull();

    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKeyFor("outline"))).toBe("1");

    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKeyFor("outline"))).toBe("0");
  });

  it("honors defaultCollapsed for the initial render", () => {
    const { result } = renderHook(() =>
      useCollapsiblePanel("resources", true),
    );
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKeyFor("resources"))).toBeNull();

    act(() => {
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKeyFor("resources"))).toBe("0");
  });

  it("hydrates a persisted collapsed state after mount", () => {
    localStorage.setItem(storageKeyFor("notes"), "1");
    const { result } = renderHook(() => useCollapsiblePanel("notes"));
    expect(result.current.collapsed).toBe(true);
  });

  it("hydrates an explicit expanded state and treats unknown values as expanded", () => {
    localStorage.setItem(storageKeyFor("chat"), "0");
    const first = renderHook(() => useCollapsiblePanel("chat", true));
    expect(first.result.current.collapsed).toBe(false);
    first.unmount();

    localStorage.setItem(storageKeyFor("chat"), "unexpected");
    const second = renderHook(() => useCollapsiblePanel("chat", true));
    expect(second.result.current.collapsed).toBe(false);
  });

  it("keeps the default when nothing is persisted", () => {
    const { result } = renderHook(() => useCollapsiblePanel("empty", true));
    expect(result.current.collapsed).toBe(true);
  });

  it("applies updater functions and persists the result", () => {
    localStorage.setItem(storageKeyFor("history"), "0");
    const { result } = renderHook(() => useCollapsiblePanel("history"));

    act(() => {
      result.current.setCollapsed((prev) => !prev);
    });
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKeyFor("history"))).toBe("1");

    act(() => {
      result.current.setCollapsed(false);
    });
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(storageKeyFor("history"))).toBe("0");
  });

  it("re-hydrates when the storage key changes", () => {
    localStorage.setItem(storageKeyFor("key-a"), "1");
    localStorage.setItem(storageKeyFor("key-b"), "0");
    const { result, rerender } = renderHook(
      ({ storageKey }) => useCollapsiblePanel(storageKey),
      { initialProps: { storageKey: "key-a" } },
    );
    expect(result.current.collapsed).toBe(true);

    rerender({ storageKey: "key-b" });
    expect(result.current.collapsed).toBe(false);
  });

  it("still updates state when persistence fails", () => {
    const setItem = vi
      .spyOn(localStorage, "setItem")
      .mockImplementation(() => {
        throw new Error("quota exceeded");
      });
    const { result } = renderHook(() => useCollapsiblePanel("quota"));

    expect(() => {
      act(() => {
        result.current.setCollapsed(true);
      });
    }).not.toThrow();
    expect(result.current.collapsed).toBe(true);
    expect(setItem).toHaveBeenCalled();
  });

  it("keeps rapid toggles consistent with the persisted value", () => {
    const { result } = renderHook(() => useCollapsiblePanel("rapid"));
    act(() => {
      result.current.toggle();
      result.current.toggle();
      result.current.toggle();
    });
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(storageKeyFor("rapid"))).toBe("1");
  });
});
