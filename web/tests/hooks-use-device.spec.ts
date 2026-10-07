import { act, cleanup, renderHook } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { useDevice } from "@/hooks/useDevice";

class FakeQueryList {
  matches = false;
  listeners = new Set<() => void>();

  addEventListener = (_type: string, listener: () => void) => {
    this.listeners.add(listener);
  };

  removeEventListener = (_type: string, listener: () => void) => {
    this.listeners.delete(listener);
  };

  set(matches: boolean) {
    this.matches = matches;
    for (const listener of [...this.listeners]) listener();
  }
}

const MOBILE_QUERY = "(max-width: 767px)";
const DESKTOP_QUERY = "(min-width: 1024px)";

const mobile = new FakeQueryList();
const desktop = new FakeQueryList();

beforeAll(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) =>
      query === MOBILE_QUERY ? mobile : query === DESKTOP_QUERY ? desktop : {
        matches: false,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      },
    ),
  );
});

afterAll(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  cleanup();
  mobile.set(false);
  desktop.set(false);
});

describe("useDevice", () => {
  it("reports tablet between the 768 and 1024 breakpoints by default", () => {
    const { result } = renderHook(() => useDevice());
    expect(result.current).toEqual({
      device: "tablet",
      isMobile: false,
      isTablet: true,
      isDesktop: false,
      isCompact: true,
    });
  });

  it("reports mobile at or below 767px", () => {
    mobile.set(true);
    const { result } = renderHook(() => useDevice());
    expect(result.current.device).toBe("mobile");
    expect(result.current.isMobile).toBe(true);
    expect(result.current.isCompact).toBe(true);
  });

  it("reports desktop at or above 1024px and clears isCompact", () => {
    desktop.set(true);
    const { result } = renderHook(() => useDevice());
    expect(result.current.device).toBe("desktop");
    expect(result.current.isDesktop).toBe(true);
    expect(result.current.isCompact).toBe(false);
  });

  it("mobile wins when both queries match", () => {
    mobile.set(true);
    desktop.set(true);
    const { result } = renderHook(() => useDevice());
    expect(result.current.device).toBe("mobile");
  });

  it("re-renders subscribers when a breakpoint flips at runtime", () => {
    const { result } = renderHook(() => useDevice());
    expect(result.current.device).toBe("tablet");

    act(() => {
      desktop.set(true);
    });
    expect(result.current.device).toBe("desktop");
    expect(result.current.isCompact).toBe(false);

    act(() => {
      mobile.set(true);
      desktop.set(false);
    });
    expect(result.current.device).toBe("mobile");
  });

  it("unsubscribes both media queries on unmount", () => {
    const { unmount } = renderHook(() => useDevice());
    expect(mobile.listeners.size).toBe(1);
    expect(desktop.listeners.size).toBe(1);

    unmount();
    expect(mobile.listeners.size).toBe(0);
    expect(desktop.listeners.size).toBe(0);

    act(() => {
      desktop.set(true);
    });
  });

  it("reuses one subscription across concurrent hook callers", () => {
    const a = renderHook(() => useDevice());
    const b = renderHook(() => useDevice());
    expect(mobile.listeners.size).toBe(2);
    expect(desktop.listeners.size).toBe(2);

    a.unmount();
    expect(mobile.listeners.size).toBe(1);
    b.unmount();
    expect(mobile.listeners.size).toBe(0);
  });
});
