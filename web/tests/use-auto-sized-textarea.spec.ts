import { renderHook } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { RefObject } from "react";

import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";

afterEach(() => {
  document.body.innerHTML = "";
});

function makeTextarea(naturalHeight: number) {
  const el = document.createElement("textarea");
  let natural = naturalHeight;
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => natural,
  });
  document.body.appendChild(el);
  return {
    el,
    setNatural(next: number) {
      natural = next;
    },
  };
}

function renderSize(value: string, options?: { min?: number; max?: number }) {
  const ref: RefObject<HTMLTextAreaElement | null> = { current: null };
  return renderHook(
    (props: { value: string; options?: { min?: number; max?: number } }) =>
      useAutoSizedTextarea(ref, props.value, props.options),
    { initialProps: { value, options } },
  );
}

it("sizes empty content up to the configured minimum", () => {
  const { el } = makeTextarea(0);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "", { min: 56 }));

  expect(el.style.height).toBe("56px");
  expect(el.style.overflowY).toBe("hidden");
});

it("keeps empty content at zero height when no minimum is configured", () => {
  const { el } = makeTextarea(0);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, ""));

  expect(el.style.height).toBe("0px");
  expect(el.style.overflowY).toBe("hidden");
});

it("sizes to the natural content height inside the bounds", () => {
  const { el } = makeTextarea(72);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "hello", { min: 24, max: 400 }));

  expect(el.style.height).toBe("72px");
  expect(el.style.overflowY).toBe("hidden");
});

it("clamps short content up to the minimum height", () => {
  const { el } = makeTextarea(12);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "hi", { min: 48 }));

  expect(el.style.height).toBe("48px");
  expect(el.style.overflowY).toBe("hidden");
});

it("scrolls extra-long content at the maximum height", () => {
  const longValue = "x".repeat(20_000);
  const { el } = makeTextarea(600);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, longValue, { max: 120 }));

  expect(el.style.height).toBe("120px");
  expect(el.style.overflowY).toBe("auto");
});

it("keeps overflow hidden at the exact maximum boundary", () => {
  const { el } = makeTextarea(120);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "edge", { max: 120 }));

  expect(el.style.height).toBe("120px");
  expect(el.style.overflowY).toBe("hidden");
});

it("recomputes height when the value changes", () => {
  const { el, setNatural } = makeTextarea(24);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  const { rerender } = renderHook(
    ({ value }: { value: string }) => useAutoSizedTextarea(ref, value),
    { initialProps: { value: "one line" } },
  );
  expect(el.style.height).toBe("24px");

  setNatural(200);
  rerender({ value: "one line\nplus more lines" });
  expect(el.style.height).toBe("200px");

  setNatural(24);
  rerender({ value: "" });
  expect(el.style.height).toBe("24px");
  expect(el.style.overflowY).toBe("hidden");
});

it("defaults to unbounded sizing without options", () => {
  const { el } = makeTextarea(96);
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "content"));

  expect(el.style.height).toBe("96px");
  expect(el.style.overflowY).toBe("hidden");
});

it("leaves a missing element untouched and does not throw", () => {
  renderHook(() => useAutoSizedTextarea({ current: null }, "orphan", { min: 40, max: 80 }));

  expect(true).toBe(true);
});

it("resets height from stale clipped values before measuring", () => {
  const { el } = makeTextarea(150);
  el.style.height = "40px";
  const ref: RefObject<HTMLTextAreaElement | null> = { current: el };
  renderHook(() => useAutoSizedTextarea(ref, "taller content"));

  expect(el.style.height).toBe("150px");
});
