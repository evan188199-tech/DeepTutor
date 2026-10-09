import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { useOutsideClick } from "@/hooks/use-outside-click";

function OutsideHarness({
  enabled,
  onOutside,
}: {
  enabled: boolean;
  onOutside: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useOutsideClick(ref, enabled, onOutside);
  return (
    <div ref={ref} data-testid="panel">
      <button>Inside</button>
    </div>
  );
}

function mouseDown(target: Element) {
  act(() => {
    target.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, cancelable: true }),
    );
  });
}

describe("useOutsideClick", () => {
  it("fires onOutside for a mousedown outside the panel", () => {
    const onOutside = vi.fn();
    render(<OutsideHarness enabled onOutside={onOutside} />);
    mouseDown(document.body);
    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("fires for a nested element rendered outside the panel", () => {
    const onOutside = vi.fn();
    render(<OutsideHarness enabled onOutside={onOutside} />);
    const outside = document.createElement("div");
    const anchor = document.createElement("button");
    outside.appendChild(anchor);
    document.body.appendChild(outside);
    try {
      mouseDown(anchor);
    } finally {
      outside.remove();
    }
    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("ignores mousedown inside the panel", () => {
    const onOutside = vi.fn();
    render(<OutsideHarness enabled onOutside={onOutside} />);
    mouseDown(screen.getByText("Inside"));
    expect(onOutside).not.toHaveBeenCalled();
  });

  it("does not listen while disabled", () => {
    const onOutside = vi.fn();
    render(<OutsideHarness enabled={false} onOutside={onOutside} />);
    mouseDown(document.body);
    expect(onOutside).not.toHaveBeenCalled();
  });

  it("re-attaches when enabled flips back on", () => {
    const onOutside = vi.fn();
    const { rerender } = render(
      <OutsideHarness enabled={false} onOutside={onOutside} />,
    );
    mouseDown(document.body);
    rerender(<OutsideHarness enabled onOutside={onOutside} />);
    mouseDown(document.body);
    expect(onOutside).toHaveBeenCalledTimes(1);
  });

  it("invokes the latest handler even though the listener is attached once", () => {
    const stale = vi.fn();
    const latest = vi.fn();
    const { rerender } = render(
      <OutsideHarness enabled onOutside={stale} />,
    );
    rerender(<OutsideHarness enabled onOutside={latest} />);
    mouseDown(document.body);
    expect(stale).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledTimes(1);
  });

  it("detaches the listener on unmount", () => {
    const onOutside = vi.fn();
    const { unmount } = render(<OutsideHarness enabled onOutside={onOutside} />);
    unmount();
    mouseDown(document.body);
    expect(onOutside).not.toHaveBeenCalled();
  });
});
