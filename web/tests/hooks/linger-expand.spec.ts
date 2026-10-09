import { act, renderHook } from "@testing-library/react";
import type { FocusEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLingerExpand } from "@/hooks/use-linger-expand";

function focusEvent(focusVisible: boolean): FocusEvent<HTMLElement> {
  return {
    currentTarget: {
      matches: vi.fn(() => focusVisible),
    },
  } as unknown as FocusEvent<HTMLElement>;
}

describe("useLingerExpand", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts collapsed, expands on hover and collapses after the linger", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    expect(result.current.expanded).toBe(false);

    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("cancels the pending collapse when the pointer re-enters during linger", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(vi.getTimerCount()).toBe(1);

    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    expect(vi.getTimerCount()).toBe(0);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.expanded).toBe(true);
  });

  it("honors a custom linger window", () => {
    const { result } = renderHook(() => useLingerExpand(false, 300));
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("expands for keyboard focus and lingers after blur", () => {
    const { result } = renderHook(() => useLingerExpand(false));

    act(() => {
      result.current.triggerProps.onFocus(focusEvent(true));
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onBlur();
    });
    expect(result.current.expanded).toBe(true);
    expect(vi.getTimerCount()).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(result.current.expanded).toBe(false);
  });

  it("does not expand on focus without the focus-visible style", () => {
    const { result } = renderHook(() => useLingerExpand(false));
    act(() => {
      result.current.triggerProps.onFocus(focusEvent(false));
    });
    expect(result.current.expanded).toBe(false);
  });

  it("stays expanded while the owned menu is open", () => {
    const { result, rerender } = renderHook(({ open }) => useLingerExpand(open), {
      initialProps: { open: false },
    });

    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(result.current.expanded).toBe(false);

    rerender({ open: true });
    expect(result.current.expanded).toBe(true);
    rerender({ open: false });
    expect(result.current.expanded).toBe(false);
  });

  it("never collapses while pinned", () => {
    const { result } = renderHook(() => useLingerExpand(false, 1200, true));
    expect(result.current.expanded).toBe(true);

    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.expanded).toBe(true);
  });

  it("keeps rapid hover cycles consistent with a single pending timer", () => {
    const { result } = renderHook(() => useLingerExpand(false, 1200));

    for (let cycle = 0; cycle < 5; cycle += 1) {
      act(() => {
        result.current.triggerProps.onMouseEnter();
      });
      act(() => {
        result.current.triggerProps.onMouseLeave();
      });
    }
    expect(vi.getTimerCount()).toBe(1);

    act(() => {
      vi.advanceTimersByTime(600);
    });
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    act(() => {
      vi.advanceTimersByTime(1199);
    });
    expect(result.current.expanded).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.expanded).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the pending linger timer on unmount", () => {
    const { result, unmount } = renderHook(() => useLingerExpand(false));
    act(() => {
      result.current.triggerProps.onMouseEnter();
    });
    act(() => {
      result.current.triggerProps.onMouseLeave();
    });
    expect(vi.getTimerCount()).toBe(1);

    unmount();
    expect(vi.getTimerCount()).toBe(0);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(vi.getTimerCount()).toBe(0);
  });
});
