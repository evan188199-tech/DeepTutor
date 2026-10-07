import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KeyboardEvent, PointerEvent } from "react";
import { useSidebarResize } from "@/hooks/useSidebarResize";

const WIDTH_KEY = "deeptutor.sidebar.width";

function pointerEvent(overrides?: {
  button?: number;
  pointerId?: number;
  clientX?: number;
}) {
  return {
    button: 0,
    pointerId: 7,
    clientX: 0,
    preventDefault: vi.fn(),
    currentTarget: {
      focus: vi.fn(),
      setPointerCapture: vi.fn(),
    },
    ...overrides,
  } as unknown as PointerEvent<HTMLDivElement>;
}

function keyEvent(key: string, shiftKey = false) {
  return {
    key,
    shiftKey,
    preventDefault: vi.fn(),
  } as unknown as KeyboardEvent<HTMLDivElement>;
}

function seedWidth(value: string) {
  window.localStorage.setItem(WIDTH_KEY, value);
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("useSidebarResize", () => {
  it("defaults to 220px with viewport-derived bounds", () => {
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(220);
    expect(result.current.min).toBe(220);
    expect(result.current.max).toBe(
      Math.min(480, Math.floor(window.innerWidth * 0.45)),
    );
    expect(result.current.resizing).toBe(false);
  });

  it("hydrates a stored width after mount", () => {
    seedWidth("300");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(300);
  });

  it("clamps an out-of-range stored width into bounds", () => {
    seedWidth("9999");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(result.current.max);
  });

  it("ignores a non-numeric stored width", () => {
    seedWidth("wide");
    const { result } = renderHook(() => useSidebarResize(false));
    expect(result.current.width).toBe(220);
  });

  it("shrinks the max bound when the viewport narrows", () => {
    const original = window.innerWidth;
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 800,
    });
    try {
      const { result } = renderHook(() => useSidebarResize(false));
      expect(result.current.max).toBe(360);

      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: 400,
      });
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      expect(result.current.max).toBe(220);
    } finally {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: original,
      });
    }
  });

  it("drags the width from the pointer delta and clamps to bounds", () => {
    seedWidth("300");
    const { result } = renderHook(() => useSidebarResize(false));
    const handle = result.current.handleProps;

    act(() => {
      handle.onPointerDown(pointerEvent({ pointerId: 7, clientX: 100 }));
    });
    expect(result.current.resizing).toBe(true);
    expect(document.body.style.cursor).toBe("col-resize");
    expect(document.body.style.userSelect).toBe("none");

    act(() => {
      handle.onPointerMove(
        pointerEvent({ pointerId: 7, clientX: 160 }),
      );
    });
    expect(result.current.width).toBe(360);

    act(() => {
      handle.onPointerMove(
        pointerEvent({ pointerId: 7, clientX: 1000 }),
      );
    });
    expect(result.current.width).toBe(result.current.max);

    act(() => {
      handle.onPointerUp(pointerEvent({ pointerId: 7 }));
    });
    expect(result.current.resizing).toBe(false);
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
    expect(window.localStorage.getItem(WIDTH_KEY)).toBe(
      String(result.current.width),
    );
  });

  it("ignores moves from another pointer or while not dragging", () => {
    const { result } = renderHook(() => useSidebarResize(false));
    const handle = result.current.handleProps;

    act(() => {
      handle.onPointerMove(pointerEvent({ pointerId: 7, clientX: 100 }));
    });
    expect(result.current.width).toBe(220);

    act(() => {
      handle.onPointerDown(pointerEvent({ pointerId: 7, clientX: 100 }));
    });
    act(() => {
      handle.onPointerMove(pointerEvent({ pointerId: 9, clientX: 200 }));
    });
    expect(result.current.width).toBe(220);

    act(() => {
      handle.onPointerMove(pointerEvent({ pointerId: 7, clientX: 130 }));
    });
    expect(result.current.width).toBe(250);
  });

  it("ignores pointer down while disabled or for non-primary buttons", () => {
    const { result, rerender } = renderHook(
      ({ disabled }) => useSidebarResize(disabled),
      { initialProps: { disabled: true } },
    );
    const handle = result.current.handleProps;
    const event = pointerEvent({ pointerId: 7, clientX: 100 });

    act(() => {
      handle.onPointerDown(event);
    });
    expect(result.current.resizing).toBe(false);

    rerender({ disabled: false });
    act(() => {
      handle.onPointerDown(pointerEvent({ button: 2, pointerId: 7 }));
    });
    expect(result.current.resizing).toBe(false);
  });

  it("ends the drag from pointer cancel and lost capture", () => {
    const { result } = renderHook(() => useSidebarResize(false));
    const handle = result.current.handleProps;

    act(() => {
      handle.onPointerDown(pointerEvent({ pointerId: 7 }));
    });
    act(() => {
      handle.onPointerCancel(pointerEvent({ pointerId: 7 }));
    });
    expect(result.current.resizing).toBe(false);

    act(() => {
      handle.onPointerDown(pointerEvent({ pointerId: 8 }));
    });
    act(() => {
      handle.onLostPointerCapture(pointerEvent({ pointerId: 99 }));
    });
    expect(result.current.resizing).toBe(true);
    act(() => {
      handle.onLostPointerCapture(pointerEvent({ pointerId: 8 }));
    });
    expect(result.current.resizing).toBe(false);
  });

  it("restores the body styles when unmounted mid-drag", () => {
    const { result, unmount } = renderHook(() => useSidebarResize(false));
    act(() => {
      result.current.handleProps.onPointerDown(pointerEvent({ pointerId: 7 }));
    });
    expect(document.body.style.cursor).toBe("col-resize");

    unmount();
    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("resets to the default width on double click", () => {
    seedWidth("400");
    const { result } = renderHook(() => useSidebarResize(false));
    act(() => {
      result.current.handleProps.onDoubleClick();
    });
    expect(result.current.width).toBe(220);
    expect(window.localStorage.getItem(WIDTH_KEY)).toBe("220");
  });

  it("moves by keyboard in 10px steps, 40px with shift, and jumps to bounds", () => {
    seedWidth("300");
    const { result } = renderHook(() => useSidebarResize(false));

    act(() => {
      result.current.handleProps.onKeyDown(keyEvent("ArrowRight"));
    });
    expect(result.current.width).toBe(310);

    act(() => {
      result.current.handleProps.onKeyDown(keyEvent("ArrowLeft", true));
    });
    expect(result.current.width).toBe(270);

    act(() => {
      result.current.handleProps.onKeyDown(keyEvent("ArrowRight", true));
    });
    expect(result.current.width).toBe(310);

    act(() => {
      result.current.handleProps.onKeyDown(keyEvent("Home"));
    });
    expect(result.current.width).toBe(220);

    act(() => {
      result.current.handleProps.onKeyDown(keyEvent("End"));
    });
    expect(result.current.width).toBe(result.current.max);

    const ignored = keyEvent("a");
    act(() => {
      result.current.handleProps.onKeyDown(ignored);
    });
    expect(ignored.preventDefault).not.toHaveBeenCalled();
  });

  it("ignores keyboard input while disabled", () => {
    const { result } = renderHook(() => useSidebarResize(true));
    const ignored = keyEvent("ArrowRight");
    act(() => {
      result.current.handleProps.onKeyDown(ignored);
    });
    expect(ignored.preventDefault).not.toHaveBeenCalled();
    expect(result.current.width).toBe(220);
  });
});
