import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";

class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];

  callback: ResizeObserverCallback;
  observed: Element[] = [];
  disconnected = false;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe(target: Element) {
    this.observed.push(target);
  }

  unobserve() {}

  disconnect() {
    this.disconnected = true;
  }

  emit() {
    const entries = this.observed.map(
      (target) =>
        ({ target, contentRect: { height: 0 } }) as ResizeObserverEntry,
    );
    this.callback(entries, this as unknown as ResizeObserver);
  }
}

function installFakeResizeObserver() {
  FakeResizeObserver.instances = [];
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
}

function mockHeight(height: number) {
  return vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockReturnValue({ height } as DOMRect);
}

function MeasuredHarness() {
  const { ref, height } = useMeasuredHeight<HTMLDivElement>();
  return (
    <div ref={ref} data-testid="measured">
      {height}
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMeasuredHeight", () => {
  it("reports the measured height on mount", () => {
    installFakeResizeObserver();
    mockHeight(120);
    render(<MeasuredHarness />);
    expect(screen.getByTestId("measured").textContent).toBe("120");
  });

  it("observes the rendered element", () => {
    installFakeResizeObserver();
    mockHeight(120);
    render(<MeasuredHarness />);
    const observer = FakeResizeObserver.instances[0];
    expect(observer.observed).toEqual([screen.getByTestId("measured")]);
  });

  it("writes back a new height when the observer fires", () => {
    installFakeResizeObserver();
    const rect = mockHeight(120);
    render(<MeasuredHarness />);
    rect.mockReturnValue({ height: 240 } as DOMRect);
    act(() => {
      FakeResizeObserver.instances[0].emit();
    });
    expect(screen.getByTestId("measured").textContent).toBe("240");
  });

  it("disconnects the observer on unmount", () => {
    installFakeResizeObserver();
    mockHeight(120);
    const { unmount } = render(<MeasuredHarness />);
    unmount();
    expect(FakeResizeObserver.instances[0].disconnected).toBe(true);
  });

  it("leaves the height at 0 when ResizeObserver is unavailable", () => {
    render(<MeasuredHarness />);
    expect(screen.getByTestId("measured").textContent).toBe("0");
  });
});
