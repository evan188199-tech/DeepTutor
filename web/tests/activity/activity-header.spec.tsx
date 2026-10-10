import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityHeader } from "@/components/activity/ActivityHeader";

describe("ActivityHeader", () => {
  it("renders a status line with the phase label, duration and summary", () => {
    render(
      <ActivityHeader
        orb="working"
        label="正在编译"
        duration="33s"
        summary="4 tool calls"
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-atomic", "false");
    expect(screen.getByText("正在编译")).toBeInTheDocument();
    expect(screen.getByText("· 33s")).toBeInTheDocument();
    expect(screen.getByText("· 4 tool calls")).toBeInTheDocument();
  });

  it("omits the duration and summary slots when there is nothing to show", () => {
    render(
      <ActivityHeader orb="breathing" label="思考中" duration={null} summary={undefined} />,
    );

    expect(screen.getByText("思考中")).toBeInTheDocument();
    expect(screen.queryByText(/^·/)).toBeNull();
  });

  it("stops breathing the label and dims once settled", () => {
    const live = render(<ActivityHeader orb="working" label="L" />);
    expect(screen.getByText("L")).toHaveClass("dt-breathing-text");
    expect(live.container.firstElementChild).toHaveClass(
      "text-[var(--muted-foreground)]",
    );
    live.unmount();

    const done = render(<ActivityHeader orb="breathing" label="L" settled />);
    expect(screen.getByText("L")).not.toHaveClass("dt-breathing-text");
    expect(done.container.firstElementChild).toHaveClass(
      "text-[var(--muted-foreground)]/70",
    );
  });

  it("becomes a disclosure with a caret when expandable", () => {
    const onToggle = vi.fn();
    const closed = render(
      <ActivityHeader
        orb="working"
        label="编译轨迹"
        expandable
        expanded={false}
        onToggle={onToggle}
      />,
    );

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-live", "polite");

    const caret = button.querySelector("svg");
    expect(caret).not.toBeNull();
    expect(caret!.getAttribute("class")).not.toContain("rotate-90");

    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
    closed.unmount();

    render(
      <ActivityHeader orb="working" label="编译轨迹" expandable expanded onToggle={vi.fn()} />,
    );
    const openButton = screen.getByRole("button");
    expect(openButton).toHaveAttribute("aria-expanded", "true");
    expect(openButton.querySelector("svg")!.getAttribute("class")).toContain("rotate-90");
  });

  it("hands the leading slot to an avatar by hiding the orb", () => {
    const hidden = render(<ActivityHeader orb="working" label="L" showOrb={false} />);
    expect(hidden.container.querySelector("canvas")).toBeNull();
    hidden.unmount();

    const shown = render(<ActivityHeader orb="composing" label="L" />);
    expect(shown.container.querySelector("canvas")).not.toBeNull();
  });
});
