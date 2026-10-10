import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityMark } from "@/components/activity/ActivityMark";

function layers(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll("span.absolute"));
}

function ring(container: HTMLElement): SVGSVGElement | null {
  return container.querySelector("svg");
}

describe("ActivityMark", () => {
  it("is decorative and honours the requested box size", () => {
    const { container } = render(<ActivityMark state="done" size={16} />);

    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    expect(wrapper.style.width).toBe("16px");
    expect(wrapper.style.height).toBe("16px");
  });

  it("cross-fades: the orb leads while running, the ring leads once settled", () => {
    const live = render(<ActivityMark state="running" />);
    const [liveOrb, liveRing] = layers(live.container);
    expect(liveOrb).toHaveClass("scale-100", "opacity-100");
    expect(liveRing).toHaveClass("scale-[1.55]", "opacity-0");
    live.unmount();

    const settled = render(<ActivityMark state="done" />);
    const [settledOrb, settledRing] = layers(settled.container);
    expect(settledOrb).toHaveClass("scale-[0.45]", "opacity-0");
    expect(settledRing).toHaveClass("scale-100", "opacity-100");
  });

  it("fills the ring only for work that produced something or failed", () => {
    const cases: Array<
      ["done" | "awaiting" | "error" | "running", "muted" | "accent", string, string[]]
    > = [
      ["done", "accent", "fill-current", ["text-blue-600"]],
      ["done", "muted", "fill-transparent", ["opacity-45"]],
      ["error", "muted", "fill-current", ["opacity-100"]],
      ["awaiting", "muted", "fill-transparent", ["opacity-100"]],
    ];

    for (const [state, tone, fillClass, inkFragments] of cases) {
      const { container, unmount } = render(
        <ActivityMark state={state} tone={tone} />,
      );
      const svg = ring(container);
      expect(svg).not.toBeNull();
      const className = svg!.getAttribute("class") ?? "";
      for (const fragment of inkFragments) {
        expect(className).toContain(fragment);
      }
      const circle = svg!.querySelector("circle");
      expect(circle!.getAttribute("class")).toContain(fillClass);
      unmount();
    }
  });

  it("keeps the error and waiting hues distinct from the accent hue", () => {
    const failed = render(<ActivityMark state="error" />);
    expect(ring(failed.container)!.getAttribute("class")).toContain("--destructive");
    failed.unmount();

    const waiting = render(<ActivityMark state="awaiting" />);
    expect(ring(waiting.container)!.getAttribute("class")).toContain("--warning");
    waiting.unmount();

    const produced = render(<ActivityMark state="done" tone="accent" />);
    expect(ring(produced.container)!.getAttribute("class")).toContain("text-blue-600");
  });

  it("scales the ring with the box", () => {
    const { container } = render(<ActivityMark state="done" size={20} />);
    const svg = ring(container)!;
    expect(svg.getAttribute("width")).toBe("12");
    expect(svg.getAttribute("height")).toBe("12");

    const { container: small } = render(<ActivityMark state="done" />);
    const defaultSvg = ring(small)!;
    expect(defaultSvg.getAttribute("width")).toBe("7");
  });
});
