import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IconButton } from "@/shared/ui/IconButton";

describe("IconButton rendering behavior", () => {
  it("labels the button accessibly and defaults to medium square of type button", () => {
    const ref = createRef<HTMLButtonElement>();
    render(
      <IconButton
        ref={ref}
        label="Open details"
        icon={<span aria-hidden>+</span>}
      />,
    );
    const button = screen.getByRole("button", { name: "Open details" });
    expect(ref.current).toBe(button);
    expect(button).toHaveAttribute("aria-label", "Open details");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("h-10", "w-10", "rounded-xl");
  });

  it("stays named and styled when disabled", () => {
    render(
      <IconButton label="Mute" icon={<span aria-hidden>m</span>} disabled />,
    );
    const button = screen.getByRole("button", { name: "Mute" });
    expect(button).toBeDisabled();
    expect(button).toHaveClass("disabled:opacity-45");
    expect(button).toHaveAttribute("aria-label", "Mute");
  });

  it("follows the controlled size prop across all variants", () => {
    const { rerender } = render(
      <IconButton label="Zoom" icon={<span aria-hidden>z</span>} size="sm" />,
    );
    expect(screen.getByRole("button", { name: "Zoom" })).toHaveClass(
      "h-8",
      "w-8",
      "rounded-lg",
    );
    rerender(
      <IconButton label="Zoom" icon={<span aria-hidden>z</span>} size="lg" />,
    );
    expect(screen.getByRole("button", { name: "Zoom" })).toHaveClass(
      "h-12",
      "w-12",
      "rounded-xl",
    );
    expect(
      screen.getByRole("button", { name: "Zoom" }),
    ).not.toHaveClass("h-8");
  });

  it("keeps the full long tooltip text as the accessible name without changing shape", () => {
    const longLabel = "Navigate".repeat(300);
    render(
      <IconButton
        label={longLabel}
        icon={<span aria-hidden>x</span>}
        size="sm"
      />,
    );
    const button = screen.getByRole("button", { name: longLabel });
    expect(button).toHaveClass("h-8", "w-8");
  });
});
