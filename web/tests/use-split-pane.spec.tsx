import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import { useSplitPane } from "@/features/co-writer/hooks/useSplitPane";

const SPLIT_RATIO_KEY = "deeptutor.co_writer.split_ratio.v2";

type SplitPaneState = ReturnType<typeof useSplitPane>;

function containerRef(left = 100, width = 1000): RefObject<HTMLElement | null> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  container.getBoundingClientRect = () =>
    ({
      left,
      top: 0,
      right: left + width,
      bottom: 400,
      width,
      height: 400,
      x: left,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
  return { current: container };
}

function pointerDown(
  result: { current: SplitPaneState },
): ReactPointerEvent<HTMLDivElement> {
  const event = {
    pointerId: 7,
    preventDefault: vi.fn(),
    currentTarget: { setPointerCapture: vi.fn() },
  } as unknown as ReactPointerEvent<HTMLDivElement>;
  act(() => {
    result.current.handleSplitterPointerDown(event);
  });
  return event;
}

function pointerMove(clientX: number) {
  act(() => {
    window.dispatchEvent(new MouseEvent("pointermove", { clientX }));
  });
}

function pointerEnd(type: "pointerup" | "pointercancel" = "pointerup") {
  act(() => {
    window.dispatchEvent(new MouseEvent(type));
  });
}

let rafCallback: FrameRequestCallback | null = null;

function flushPreferences() {
  expect(rafCallback).toBeTypeOf("function");
  act(() => {
    rafCallback?.(0);
  });
}

beforeEach(() => {
  rafCallback = null;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    rafCallback = callback;
    return 1;
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

it("starts at the default ratio and adopts the persisted ratio once preferences load", () => {
  localStorage.setItem(SPLIT_RATIO_KEY, "0.7");
  const { result } = renderHook(() => useSplitPane(containerRef()));
  expect(result.current.editorRatio).toBe(0.5);
  flushPreferences();
  expect(result.current.editorRatio).toBe(0.7);
});

it("falls back to the default ratio when the persisted value is not numeric", () => {
  localStorage.setItem(SPLIT_RATIO_KEY, "not-a-number");
  const { result } = renderHook(() => useSplitPane(containerRef()));
  flushPreferences();
  expect(result.current.editorRatio).toBe(0.5);
});

it.each([
  ["0.99", 0.82],
  ["0.01", 0.18],
  ["-3", 0.18],
])("clamps the persisted ratio %s into the editable band (%s)", (stored, expected) => {
  localStorage.setItem(SPLIT_RATIO_KEY, stored);
  const { result } = renderHook(() => useSplitPane(containerRef()));
  flushPreferences();
  expect(result.current.editorRatio).toBe(expected);
});

it("persists ratio changes to storage after preferences have loaded", () => {
  const { result } = renderHook(() => useSplitPane(containerRef()));
  flushPreferences();
  expect(localStorage.getItem(SPLIT_RATIO_KEY)).toBeNull();
  act(() => {
    result.current.setEditorRatio(0.62);
  });
  expect(localStorage.getItem(SPLIT_RATIO_KEY)).toBe("0.62");
});

it("does not persist ratio changes before preferences have loaded", () => {
  const { result } = renderHook(() => useSplitPane(containerRef()));
  act(() => {
    result.current.setEditorRatio(0.62);
  });
  expect(localStorage.getItem(SPLIT_RATIO_KEY)).toBeNull();
});

it("starts resizing on splitter pointer down when both panes are visible", () => {
  const { result } = renderHook(() => useSplitPane(containerRef()));
  flushPreferences();
  const event = pointerDown(result);
  expect(result.current.isResizingSplit).toBe(true);
  expect(event.preventDefault).toHaveBeenCalled();
});

it("ignores splitter pointer down when a pane is collapsed", () => {
  const { result } = renderHook(() => useSplitPane(containerRef()));
  flushPreferences();
  act(() => {
    result.current.setEditorCollapsed(true);
  });
  const editorEvent = pointerDown(result);
  expect(result.current.isResizingSplit).toBe(false);
  expect(editorEvent.preventDefault).not.toHaveBeenCalled();
  act(() => {
    result.current.setEditorCollapsed(false);
    result.current.setPreviewCollapsed(true);
  });
  const previewEvent = pointerDown(result);
  expect(result.current.isResizingSplit).toBe(false);
  expect(previewEvent.preventDefault).not.toHaveBeenCalled();
});

it("maps pointer position to the editor ratio from the container rect", () => {
  const { result } = renderHook(() => useSplitPane(containerRef(100, 1000)));
  flushPreferences();
  pointerDown(result);
  pointerMove(600);
  expect(result.current.editorRatio).toBe(0.5);
  pointerMove(300);
  expect(result.current.editorRatio).toBe(0.2);
});

it.each([
  [50, 0.18],
  [2000, 0.82],
])("clamps drag position %spx to ratio %s", (clientX, expected) => {
  const { result } = renderHook(() => useSplitPane(containerRef(100, 1000)));
  flushPreferences();
  pointerDown(result);
  pointerMove(clientX);
  expect(result.current.editorRatio).toBe(expected);
  expect(localStorage.getItem(SPLIT_RATIO_KEY)).toBe(String(expected));
});

it("ignores pointer moves while the container has no measurable width", () => {
  const ref = containerRef(100, 1000);
  const { result } = renderHook(() => useSplitPane(ref));
  flushPreferences();
  pointerDown(result);
  ref.current!.getBoundingClientRect = () =>
    ({
      left: 100,
      top: 0,
      right: 100,
      bottom: 400,
      width: 0,
      height: 400,
      x: 100,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;
  pointerMove(500);
  expect(result.current.editorRatio).toBe(0.5);
});

it.each(["pointerup", "pointercancel"] as const)(
  "ends the drag on %s and ignores later moves",
  (type) => {
    const { result } = renderHook(() => useSplitPane(containerRef(100, 1000)));
    flushPreferences();
    pointerDown(result);
    expect(result.current.isResizingSplit).toBe(true);
    pointerEnd(type);
    expect(result.current.isResizingSplit).toBe(false);
    pointerMove(900);
    expect(result.current.editorRatio).toBe(0.5);
  },
);

it("ignores pointer moves when the container is not attached yet", () => {
  const ref: RefObject<HTMLElement | null> = { current: null };
  const { result } = renderHook(() => useSplitPane(ref));
  flushPreferences();
  pointerDown(result);
  pointerMove(600);
  expect(result.current.editorRatio).toBe(0.5);
});
