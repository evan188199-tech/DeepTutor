import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];

  callback: ResizeObserverCallback;
  observed: Element[] = [];
  disconnect = vi.fn();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe = vi.fn((element: Element) => {
    this.observed.push(element);
  });

  trigger() {
    this.callback([], this as unknown as ResizeObserver);
  }
}

let observerInstances: FakeResizeObserver[];

function measureTarget(initialHeight: number) {
  const element = document.createElement("div");
  let current = initialHeight;
  element.getBoundingClientRect = () => ({ height: current }) as DOMRect;
  return {
    element,
    setHeight: (next: number) => {
      current = next;
    },
  };
}

function renderMeasured(target: HTMLElement) {
  return renderHook(() => {
    const measured = useMeasuredHeight<HTMLDivElement>();
    if (measured.ref.current === null) measured.ref.current = target;
    return measured;
  });
}

beforeEach(() => {
  FakeResizeObserver.instances = [];
  observerInstances = FakeResizeObserver.instances;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useMeasuredHeight", () => {
  it("reports 0 before an element is attached to the ref", () => {
    const { result } = renderHook(() => useMeasuredHeight<HTMLDivElement>());
    expect(result.current.height).toBe(0);
    expect(observerInstances).toHaveLength(0);
  });

  it("measures the initial height once mounted", () => {
    const { element } = measureTarget(120);
    const { result } = renderMeasured(element);
    expect(result.current.height).toBe(120);
    expect(observerInstances).toHaveLength(1);
    expect(observerInstances[0]?.observed).toEqual([element]);
  });

  it("follows resize notifications with fresh measurements", () => {
    const target = measureTarget(120);
    const { result } = renderMeasured(target.element);
    expect(result.current.height).toBe(120);

    target.setHeight(300);
    act(() => {
      observerInstances[0]?.trigger();
    });
    expect(result.current.height).toBe(300);
  });

  it("disconnects the observer on unmount", () => {
    const { element } = measureTarget(80);
    const { unmount } = renderMeasured(element);
    const observer = observerInstances[0];
    expect(observer).toBeDefined();

    unmount();
    expect(observer?.disconnect).toHaveBeenCalledTimes(1);
  });

  it("stays inert when ResizeObserver is unavailable", () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("ResizeObserver", undefined);
    const { element } = measureTarget(80);
    const { result } = renderMeasured(element);
    expect(result.current.height).toBe(0);
  });
});
