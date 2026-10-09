import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Button from "@/shared/ui/Button";

describe("Button rendering behavior", () => {
  it("renders default state as a medium primary button of type button", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(ref.current).toBe(button);
    expect(button).toHaveAttribute("type", "button");
    expect(button).toBeEnabled();
    expect(button).toHaveClass("bg-primary", "min-h-10", "rounded-xl", "px-4");
  });

  it("swaps the icon for a spinner and back under controlled loading", () => {
    const icon = <span data-testid="lead-icon" aria-hidden />;
    const { rerender } = render(
      <Button loading icon={icon}>
        Deploy
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Deploy" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByTestId("lead-icon")).not.toBeInTheDocument();
    rerender(
      <Button icon={icon}>
        Deploy
      </Button>,
    );
    expect(screen.getByRole("button", { name: "Deploy" })).toBeEnabled();
    expect(screen.getByTestId("lead-icon")).toBeInTheDocument();
  });

  it("keeps a disabled button inert and styled while preserving its name", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button disabled onClick={onClick}>
        Delete
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toBeDisabled();
    expect(button).toHaveClass("disabled:opacity-50");
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps extreme-length labels fully accessible and lets className win conflicts", () => {
    const longLabel = "A".repeat(2000);
    render(
      <Button className="px-10" variant="danger" size="lg">
        {longLabel}
      </Button>,
    );
    const button = screen.getByRole("button", { name: longLabel });
    expect(button).toHaveClass("min-h-12", "px-10");
    expect(button).not.toHaveClass("px-4");
    expect(button).toHaveClass("bg-destructive");
  });
});
