import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import { DEVICE_BREAKPOINTS, useDevice } from "@/hooks/useDevice";

/* jsdom has no layout engine, so the suite installs a controllable matchMedia:
   one persistent fake per media query whose `matches` is computed live from
   `viewportWidth`. The hook caches its MediaQueryList pair at module scope,
   so every fake must be stable for the life of the file rather than rebuilt
   per test. */
interface FakeQueryList {
  media: string;
  listeners: Set<() => void>;
}

const fakeQueries = new Map<string, FakeQueryList>();

let viewportWidth: number | null = null;

function fakeQueryOf(media: string): FakeQueryList {
  let list = fakeQueries.get(media);
  if (!list) {
    list = { media, listeners: new Set() };
    fakeQueries.set(media, list);
  }
  return list;
}

function matchesAt(width: number | null, media: string): boolean {
  if (width === null) return false;
  if (media === `(max-width: ${DEVICE_BREAKPOINTS.tablet - 1}px)`) {
    return width < DEVICE_BREAKPOINTS.tablet;
  }
  if (media === `(min-width: ${DEVICE_BREAKPOINTS.desktop}px)`) {
    return width >= DEVICE_BREAKPOINTS.desktop;
  }
  return false;
}

function setViewport(width: number | null): void {
  viewportWidth = width;
}

function fireViewportChange(): void {
  for (const list of fakeQueries.values()) {
    for (const listener of [...list.listeners]) listener();
  }
}

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: (media: string) => {
    const list = fakeQueryOf(media);
    return {
      get media() {
        return list.media;
      },
      get matches() {
        return matchesAt(viewportWidth, list.media);
      },
      addEventListener(_type: "change", listener: () => void) {
        list.listeners.add(listener);
      },
      removeEventListener(_type: "change", listener: () => void) {
        list.listeners.delete(listener);
      },
    };
  },
});

afterEach(() => {
  viewportWidth = null;
  for (const list of fakeQueries.values()) list.listeners.clear();
});

it.each([
  [767, "mobile"],
  [768, "tablet"],
  [1023, "tablet"],
  [1024, "desktop"],
] as const)("classifies a %ipx viewport as %s", (width, expected) => {
  setViewport(width);
  const { result } = renderHook(() => useDevice());
  expect(result.current.device).toBe(expected);
});

it.each([
  [767, { isMobile: true, isTablet: false, isDesktop: false, isCompact: true }],
  [768, { isMobile: false, isTablet: true, isDesktop: false, isCompact: true }],
  [
    1023,
    { isMobile: false, isTablet: true, isDesktop: false, isCompact: true },
  ],
  [
    1024,
    { isMobile: false, isTablet: false, isDesktop: true, isCompact: false },
  ],
])("derives the layout flags for a %ipx viewport", (width, expected) => {
  setViewport(width);
  const { result } = renderHook(() => useDevice());
  expect(result.current).toMatchObject(expected);
});

it("re-renders when the viewport crosses a breakpoint", () => {
  setViewport(1024);
  const { result } = renderHook(() => useDevice());
  expect(result.current.isDesktop).toBe(true);

  act(() => {
    setViewport(500);
    fireViewportChange();
  });

  expect(result.current.device).toBe("mobile");
  expect(result.current.isCompact).toBe(true);
});

it("subscribes to exactly the Tailwind md/lg mirror queries", () => {
  renderHook(() => useDevice());

  expect(DEVICE_BREAKPOINTS.tablet).toBe(768);
  expect(DEVICE_BREAKPOINTS.desktop).toBe(1024);
  expect([...fakeQueries.keys()].sort()).toEqual([
    "(max-width: 767px)",
    "(min-width: 1024px)",
  ]);
});

it("stops listening after unmount", () => {
  setViewport(1024);
  const { unmount } = renderHook(() => useDevice());
  expect(
    [...fakeQueries.values()].some((list) => list.listeners.size > 0),
  ).toBe(true);

  unmount();

  for (const list of fakeQueries.values()) {
    expect(list.listeners.size).toBe(0);
  }
  expect(() => fireViewportChange()).not.toThrow();
});

it("renders the desktop shell during SSR", () => {
  function Probe() {
    const device = useDevice();
    return <span>{device.device}</span>;
  }

  expect(renderToString(<Probe />)).toContain("desktop");
});
