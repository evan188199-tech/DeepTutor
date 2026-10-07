import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FocusEvent } from "react";
import { useLingerExpand } from "@/hooks/use-linger-expand";

function focusEvent(matches: boolean) {
  return {
    currentTarget: { matches: vi.fn(() => matches) },
  } as unknown as FocusEvent<HTMLElement>;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useLingerExpand", () => {
  it("stays collapsed until an expand trigger fires", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    expect(result.current.expanded).toBe(false);
  });

  it("expands on hover and lingers after mouse leave before collapsing", () => {
    const { result } = renderHook(() =>
      useLingerExpand(false, 1200),
    );
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1199);
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("honours a custom linger window", () => {
    const { result } = renderHook(() => useLingerExpand(false, 300));
    act(() => {
      result.current.linger();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("re-arms the linger window on a second leave", () => {
    const { result } = renderHook(() => useLingerExpand(false, 500));
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("pins expansion and skips collapsing entirely", () => {
    const { result } = renderHook(() => useLingerExpand(false, 1200, true));
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(result.current.expanded).toBe(true);
  });

  it("expands while the menu is open even without hover", () => {
    const { result, rerender } = renderHook(
      ({ open }) => useLingerExpand(open),
      { initialProps: { open: false } },
    );
    expect(result.current.expanded).toBe(false);

    rerender({ open: true });
    expect(result.current.expanded).toBe(true);

    rerender({ open: false });
    expect(result.current.expanded).toBe(false);
  });

  it("tracks keyboard focus through :focus-visible", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    act(() => {
      result.current.triggerProps.onFocus(focusEvent(true));
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onBlur();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("ignores pointer-induced focus as keyboard focus", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    act(() => {
      result.current.triggerProps.onFocus(focusEvent(false));
    });
    expect(result.current.expanded).toBe(false);
  });

  it("clears the pending linger timer on unmount", () => {
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");
    const { result, unmount } = renderHook(() =>
      useLingerExpand(false, 1200),
    );
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(vi.getTimerCount()).toBe(1);

    unmount();
    expect(clearTimeoutSpy).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);

    expect(() => {
      act(() => {
        vi.advanceTimersByTime(5000);
      });
    }).not.toThrow();
    clearTimeoutSpy.mockRestore();
  });
});
