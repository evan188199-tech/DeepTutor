import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useOutsideClick } from "@/hooks/use-outside-click";

function press(target: Element) {
  act(() => {
    target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  });
}

describe("useOutsideClick", () => {
  let host: HTMLDivElement;
  let ref: { current: HTMLElement | null };

  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    ref = { current: host };
  });

  afterEach(() => {
    cleanup();
    host.remove();
  });

  it("fires onOutside for mousedown outside the ref and not inside", () => {
    const onOutside = vi.fn();
    renderHook(() => useOutsideClick(ref, true, onOutside));

    press(host);
    expect(onOutside).not.toHaveBeenCalled();

    const outside = document.createElement("div");
    document.body.appendChild(outside);
    press(outside);
    expect(onOutside).toHaveBeenCalledTimes(1);
    outside.remove();
  });

  it("does nothing while disabled and starts listening once enabled", () => {
    const onOutside = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) => useOutsideClick(ref, enabled, onOutside),
      { initialProps: { enabled: false } },
    );

    press(document.body);
    expect(onOutside).not.toHaveBeenCalled();

    rerender({ enabled: true });
    press(document.body);
    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("keeps a single listener across handler changes and uses the latest handler", () => {
    const addSpy = vi.spyOn(document, "addEventListener");
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(
      ({ handler }) => useOutsideClick(ref, true, handler),
      { initialProps: { handler: first } },
    );
    const attached = addSpy.mock.calls.filter(([type]) => type === "mousedown")
      .length;

    rerender({ handler: second });
    rerender({ handler: second });
    expect(
      addSpy.mock.calls.filter(([type]) => type === "mousedown").length,
    ).toBe(attached);

    press(document.body);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    addSpy.mockRestore();
  });

  it("stops firing after unmount removes the listener", () => {
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const addSpy = vi.spyOn(document, "addEventListener");
    const onOutside = vi.fn();
    const { unmount } = renderHook(() =>
      useOutsideClick(ref, true, onOutside),
    );

    const listener = addSpy.mock.calls.find(([type]) => type === "mousedown")
      ?.[1];
    unmount();

    expect(removeSpy).toHaveBeenCalledWith("mousedown", listener);
    press(document.body);
    expect(onOutside).not.toHaveBeenCalled();
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it("removes the listener when disabled again without firing", () => {
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const addSpy = vi.spyOn(document, "addEventListener");
    const onOutside = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) => useOutsideClick(ref, enabled, onOutside),
      { initialProps: { enabled: true } },
    );
    const listener = addSpy.mock.calls.find(([type]) => type === "mousedown")
      ?.[1];

    rerender({ enabled: false });
    expect(removeSpy).toHaveBeenCalledWith("mousedown", listener);

    press(document.body);
    expect(onOutside).not.toHaveBeenCalled();
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});
