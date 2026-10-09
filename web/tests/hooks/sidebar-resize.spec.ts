import { act, renderHook } from "@testing-library/react";
import type { KeyboardEvent, PointerEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSidebarResize } from "@/hooks/useSidebarResize";

const WIDTH_KEY = "deeptutor.sidebar.width";
const DEFAULT_WIDTH = 220;
const MIN_WIDTH = 220;

function pointerEvent(
  pointerId: number,
  clientX: number,
  button = 0,
): PointerEvent<HTMLDivElement> {
  return {
    pointerId,
    clientX,
    button,
    preventDefault: vi.fn(),
    currentTarget: {
      focus: vi.fn(),
      setPointerCapture: vi.fn(),
    },
  } as unknown as PointerEvent<HTMLDivElement>;
}

function keyboardEvent(
  key: string,
  shiftKey = false,
): KeyboardEvent<HTMLDivElement> {
  return {
    key,
    shiftKey,
    preventDefault: vi.fn(),
  } as unknown as KeyboardEvent<HTMLDivElement>;
}

function setViewport(px: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: px,
  });
}

function fireResize() {
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

describe("useSidebarResize", () => {
  beforeEach(() => {
    setViewport(1024);
  });

  afterEach(() => {
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });

  it("starts at the default width with viewport-derived bounds", () => {
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(DEFAULT_WIDTH);
    expect(result.current.min).toBe(MIN_WIDTH);
    expect(result.current.max).toBe(460); // floor(1024 * 0.45)
    expect(result.current.resizing).toBe(false);
  });

  it("hydrates a persisted width after mount", () => {
    localStorage.setItem(WIDTH_KEY, "340");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(340);
  });

  it("ignores persisted widths that are not positive finite numbers", () => {
    localStorage.setItem(WIDTH_KEY, "not-a-number");
    const first = renderHook(() => useSidebarResize(false));
    expect(first.result.current.width).toBe(DEFAULT_WIDTH);
    first.unmount();

    localStorage.setItem(WIDTH_KEY, "0");
    const second = renderHook(() => useSidebarResize(false));
    expect(second.result.current.width).toBe(DEFAULT_WIDTH);
  });

  it("clamps persisted widths above the absolute maximum", () => {
    localStorage.setItem(WIDTH_KEY, "9999");
    const { result } = renderHook(() => useSidebarResize(false));
    // preferred clamps to 480, then the viewport-derived max (460 at 1024px)
    // narrows the rendered width further.
    expect(result.current.width).toBe(460);
  });

  it("shrinks bounds on viewport resize and re-clamps an oversized width", () => {
    localStorage.setItem(WIDTH_KEY, "9999");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(460);

    setViewport(400);
    fireResize();
    expect(result.current.max).toBe(MIN_WIDTH);
    expect(result.current.width).toBe(MIN_WIDTH);

    // preferredWidth stays 480; the derived width follows the restored bounds.
    setViewport(1024);
    fireResize();
    expect(result.current.max).toBe(460);
    expect(result.current.width).toBe(460);
  });

  it("ignores non-primary buttons and disabled state on pointer down", () => {
    const { result, rerender } = renderHook(
      ({ disabled }) => useSidebarResize(disabled),
      { initialProps: { disabled: false } },
    );

    act(() => {
      result.current.handleProps.onPointerDown(pointerEvent(1, 100, 2));
    });
    expect(result.current.resizing).toBe(false);

    rerender({ disabled: true });
    act(() => {
      result.current.handleProps.onPointerDown(pointerEvent(1, 100));
    });
    expect(result.current.resizing).toBe(false);
  });

  it("tracks a drag, applies col-resize body styles, persists and restores", () => {
    const { result } = renderHook(() => useSidebarResize(false));

    const down = pointerEvent(7, 100);
    act(() => {
      result.current.handleProps.onPointerDown(down);
    });
    expect(result.current.resizing).toBe(true);
    expect(down.preventDefault).toHaveBeenCalled();
    expect(down.currentTarget.setPointerCapture).toHaveBeenCalledWith(7);
    expect(document.body.style.cursor).toBe("col-resize");
    expect(document.body.style.userSelect).toBe("none");

    act(() => {
      result.current.handleProps.onPointerMove(pointerEvent(7, 190));
    });
    expect(result.current.width).toBe(310);
    expect(localStorage.getItem(WIDTH_KEY)).toBe("310");

    act(() => {
      result.current.handleProps.onPointerUp(pointerEvent(7, 190));
    });
    expect(result.current.resizing).toBe(false);
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("ignores moves without an active drag or from another pointer id", () => {
    const { result } = renderHook(() => useSidebarResize(false));

    act(() => {
      result.current.handleProps.onPointerMove(pointerEvent(7, 500));
    });
    expect(result.current.width).toBe(DEFAULT_WIDTH);

    act(() => {
      result.current.handleProps.onPointerDown(pointerEvent(7, 100));
    });
    act(() => {
      result.current.handleProps.onPointerMove(pointerEvent(8, 500));
    });
    expect(result.current.width).toBe(DEFAULT_WIDTH);
    expect(localStorage.getItem(WIDTH_KEY)).toBeNull();

    act(() => {
      result.current.handleProps.onPointerUp(pointerEvent(7, 100));
    });
  });

  it("clamps extreme drags to the min and viewport-derived max", () => {
    const { result } = renderHook(() => useSidebarResize(false));

    const drag = (deltaX: number) => {
      act(() => {
        result.current.handleProps.onPointerDown(pointerEvent(7, 100));
      });
      act(() => {
        result.current.handleProps.onPointerMove(pointerEvent(7, 100 + deltaX));
      });
      act(() => {
        result.current.handleProps.onPointerUp(pointerEvent(7, 100 + deltaX));
      });
    };

    drag(-5000);
    expect(result.current.width).toBe(MIN_WIDTH);

    drag(5000);
    expect(result.current.width).toBe(460);
    expect(localStorage.getItem(WIDTH_KEY)).toBe("460");
  });

  it("ends the drag on pointer cancel and lost pointer capture", () => {
    const first = renderHook(() => useSidebarResize(false));
    act(() => {
      first.result.current.handleProps.onPointerDown(pointerEvent(7, 100));
    });
    act(() => {
      first.result.current.handleProps.onPointerCancel(pointerEvent(7, 100));
    });
    expect(first.result.current.resizing).toBe(false);
    first.unmount();

    const second = renderHook(() => useSidebarResize(false));
    act(() => {
      second.result.current.handleProps.onPointerDown(pointerEvent(7, 100));
    });
    act(() => {
      second.result.current.handleProps.onLostPointerCapture(
        pointerEvent(7, 100),
      );
    });
    expect(second.result.current.resizing).toBe(false);
    second.unmount();
  });

  it("keeps rapid drag cycles consistent and stops at the last value", () => {
    const { result } = renderHook(() => useSidebarResize(false));

    for (const delta of [30, -50, 80]) {
      act(() => {
        result.current.handleProps.onPointerDown(pointerEvent(7, 100));
      });
      act(() => {
        result.current.handleProps.onPointerMove(pointerEvent(7, 100 + delta));
      });
      act(() => {
        result.current.handleProps.onPointerUp(pointerEvent(7, 100 + delta));
      });
    }

    // 220 +30 -> 250; -50 clamps to the min 220; +80 -> 300
    expect(result.current.width).toBe(300);
    expect(result.current.resizing).toBe(false);
    expect(localStorage.getItem(WIDTH_KEY)).toBe("300");
  });

  it("restores body styles when unmounted mid-drag", () => {
    const { result, unmount } = renderHook(() => useSidebarResize(false));
    act(() => {
      result.current.handleProps.onPointerDown(pointerEvent(7, 100));
    });
    expect(document.body.style.cursor).toBe("col-resize");
    unmount();
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("double click resets to the default width", () => {
    localStorage.setItem(WIDTH_KEY, "400");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(400);

    act(() => {
      result.current.handleProps.onDoubleClick();
    });
    expect(result.current.width).toBe(DEFAULT_WIDTH);
    expect(localStorage.getItem(WIDTH_KEY)).toBe(String(DEFAULT_WIDTH));
  });

  it("supports keyboard steps and bound jumps", () => {
    const { result } = renderHook(() => useSidebarResize(false));
    const press = (key: string, shiftKey = false) => {
      const event = keyboardEvent(key, shiftKey);
      act(() => {
        result.current.handleProps.onKeyDown(event);
      });
      return event;
    };

    let event = press("ArrowRight");
    expect(event.preventDefault).toHaveBeenCalled();
    expect(result.current.width).toBe(230);

    press("ArrowLeft");
    expect(result.current.width).toBe(DEFAULT_WIDTH);

    event = press("ArrowRight", true);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(result.current.width).toBe(260);

    press("Home");
    expect(result.current.width).toBe(MIN_WIDTH);

    press("End");
    expect(result.current.width).toBe(460);

    event = press("a");
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(result.current.width).toBe(460);
    expect(localStorage.getItem(WIDTH_KEY)).toBe("460");
  });
});
