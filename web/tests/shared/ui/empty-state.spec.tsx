import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "@/shared/ui/EmptyState";

describe("EmptyState rendering behavior", () => {
  it("renders the roomy default layout and omits absent slots", () => {
    const { container } = render(
      <EmptyState title="No sessions yet" description="Start a conversation." />,
    );
    const section = container.querySelector("section");
    expect(section).toHaveClass("px-6", "py-12");
    expect(
      screen.getByRole("heading", { level: 3, name: "No sessions yet" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Start a conversation.")).toBeInTheDocument();
    expect(container.querySelector(".h-11")).toBeNull();
  });

  it("compacts padding and renders icon and action slots when controlled", () => {
    const { container } = render(
      <EmptyState
        title="Nothing here"
        icon={<span data-testid="glyph" aria-hidden />}
        action={<button type="button">Create one</button>}
        compact
      />,
    );
    expect(container.querySelector("section")).toHaveClass("px-4", "py-6");
    expect(container.querySelector("section")).not.toHaveClass("py-12");
    expect(screen.getByTestId("glyph")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create one" }),
    ).toBeInTheDocument();
  });

  it("contains extreme-length copy within the description width constraint", () => {
    const longTitle = "T".repeat(1200);
    const longDescription = "D".repeat(3000);
    render(
      <EmptyState title={longTitle} description={longDescription} compact />,
    );
    const heading = screen.getByRole("heading", { level: 3, name: longTitle });
    const description = heading
      .closest("div")
      ?.querySelector("p");
    expect(description).toHaveClass("max-w-sm");
    expect(description).toHaveTextContent(longDescription);
  });
});
