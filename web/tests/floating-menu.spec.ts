import { afterEach, describe, expect, it } from "vitest";

import { placeMenu } from "@/lib/floating-menu";

const viewport = {
  width: Object.getOwnPropertyDescriptor(window, "innerWidth")?.value ?? window.innerWidth,
  height: Object.getOwnPropertyDescriptor(window, "innerHeight")?.value ?? window.innerHeight,
};

function setViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
}

afterEach(() => {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: viewport.width,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: viewport.height,
  });
});

function rect(top: number, bottom: number, left: number, right: number): DOMRect {
  return { top, bottom, left, right } as DOMRect;
}

describe("placeMenu", () => {
  it("opens downward below the anchor when there is room", () => {
    setViewport(1280, 800);

    const position = placeMenu(rect(100, 124, 20, 220), 240);

    expect(position).toEqual({ left: 228, top: 132, maxHeight: 380, openUpward: false });
  });

  it("flips upward near the bottom of the window when above has more room", () => {
    setViewport(1280, 400);

    const position = placeMenu(rect(350, 374, 100, 300), 240);

    expect(position).toEqual({ left: 308, top: 342, maxHeight: 330, openUpward: true });
  });

  it("shrinks the menu to the available room below the anchor", () => {
    setViewport(1280, 300);

    const position = placeMenu(rect(0, 24, 20, 220), 240);

    expect(position).toEqual({ left: 228, top: 32, maxHeight: 256, openUpward: false });
  });

  it("keeps the minimum menu height in cramped panels", () => {
    setViewport(1280, 200);

    const position = placeMenu(rect(100, 124, 20, 220), 240);

    expect(position).toEqual({ left: 228, top: 92, maxHeight: 140, openUpward: true });
  });

  it("shrinks the preferred height for windows near the menu cap limit", () => {
    setViewport(1280, 404);

    const position = placeMenu(rect(0, 24, 20, 220), 240);

    expect(position).toEqual({ left: 228, top: 32, maxHeight: 360, openUpward: false });
  });

  it("prefers the right side even when it must be clamped to fit", () => {
    setViewport(600, 600);

    const position = placeMenu(rect(100, 124, 20, 60), 520);

    expect(position).toEqual({ left: 68, top: 132, maxHeight: 380, openUpward: false });
  });

  it("flips to the left of the anchor when the right side cannot fit", () => {
    setViewport(400, 800);

    const position = placeMenu(rect(100, 124, 300, 380), 240);

    expect(position).toEqual({ left: 52, top: 132, maxHeight: 380, openUpward: false });
  });

  it("keeps the roomier horizontal side when neither side fits", () => {
    setViewport(500, 800);

    const position = placeMenu(rect(100, 124, 100, 300), 470);

    expect(position.left).toBe(18);
  });

  it("never places the menu left of the viewport margin", () => {
    setViewport(500, 800);

    const position = placeMenu(rect(100, 124, 430, 460), 470);

    expect(position.left).toBe(12);
  });
});
