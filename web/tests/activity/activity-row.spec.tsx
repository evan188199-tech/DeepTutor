import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityRow } from "@/components/activity/ActivityRow";

function statusDot(container: HTMLElement): HTMLElement | null {
  return container.querySelector('[class*="rounded-full"]');
}

describe("ActivityRow", () => {
  it("renders the title with its trailing detail on one line", () => {
    const { container } = render(
      <ActivityRow state="done" title="编译第 3 章" detail="chapters/03.md" detailMono />,
    );

    const title = screen.getByText("编译第 3 章");
    expect(title).toHaveClass("shrink-0", "font-medium");

    const detail = screen.getByText("chapters/03.md");
    expect(detail).toHaveClass("truncate");
    expect(detail).toHaveClass("font-mono");
    expect(container.textContent).toContain("编译第 3 章");
  });

  it("renders the mono face on the detail only when asked", () => {
    render(<ActivityRow state="done" title="搜索完成" detail="perplexity" />);

    expect(screen.getByText("perplexity")).not.toHaveClass("font-mono");
  });

  it("clamps prose titles on request and leaves labelled titles alone", () => {
    const two = render(<ActivityRow state="done" title="长标题" clampTitle={2} />);
    expect(screen.getByText("长标题")).toHaveClass("line-clamp-2");
    two.unmount();

    const three = render(<ActivityRow state="done" title="长标题" clampTitle={3} />);
    expect(screen.getByText("长标题")).toHaveClass("line-clamp-3");
    three.unmount();

    render(<ActivityRow state="done" title="长标题" />);
    expect(screen.getByText("长标题")).toHaveClass("block");
  });

  it("passes the row state through to the status dot", () => {
    const cases: Array<
      ["running" | "awaiting" | "error" | "done", string[]]
    > = [
      ["running", ["bg-blue-600", "dt-dot-live"]],
      ["awaiting", ["bg-[var(--warning)]"]],
      ["error", ["bg-[var(--destructive)]"]],
      ["done", ["opacity-40"]],
    ];

    for (const [state, classes] of cases) {
      const { container, unmount } = render(
        <ActivityRow state={state} title="T" />,
      );
      const dot = statusDot(container);
      expect(dot).not.toBeNull();
      for (const cls of classes) expect(dot).toHaveClass(cls);
      unmount();
    }
  });

  it("breathes the title only while the work is live", () => {
    const live = render(<ActivityRow state="running" title="T" breathing />);
    expect(screen.getByText("T")).toHaveClass("dt-breathing-text");
    live.unmount();

    render(<ActivityRow state="running" title="T" />);
    expect(screen.getByText("T")).not.toHaveClass("dt-breathing-text");
  });

  it("is not a disclosure without a second level", () => {
    const { container } = render(
      <ActivityRow state="done" title="T" detail="d">
        {null}
      </ActivityRow>,
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("toggles its second level on click and reports the state", () => {
    render(
      <ActivityRow state="running" title="编译中">
        <div>LEVEL TWO</div>
      </ActivityRow>,
    );

    const row = screen.getByRole("button");
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("LEVEL TWO")).toBeNull();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("LEVEL TWO")).toBeInTheDocument();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("LEVEL TWO")).toBeNull();
  });

  it("opens for followOpen and lets the reader's click win", () => {
    render(
      <ActivityRow state="running" title="流式输出" followOpen>
        <div>STREAM</div>
      </ActivityRow>,
    );

    const row = screen.getByRole("button");
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("STREAM")).toBeInTheDocument();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("STREAM")).toBeNull();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps the streamed second level pinned while autoScrollDetail holds", () => {
    const { container } = render(
      <ActivityRow state="running" title="流式输出" followOpen autoScrollDetail>
        <div>TAIL LINE</div>
      </ActivityRow>,
    );

    const scroller = container.querySelector("[class*='dt-detail-in']");
    expect(scroller).not.toBeNull();
    expect(scroller!.textContent).toContain("TAIL LINE");

    fireEvent.scroll(scroller!);
    expect(scroller!.textContent).toContain("TAIL LINE");
  });
});
