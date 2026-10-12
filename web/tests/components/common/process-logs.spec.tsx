import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import ProcessLogs from "@/components/common/ProcessLogs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function getScroller(container: HTMLElement): HTMLElement {
  const scroller = container.querySelector("details > div > div");
  expect(scroller).toBeTruthy();
  return scroller as HTMLElement;
}

describe("ProcessLogs", () => {
  beforeAll(() => {
    // jsdom has no Element.scrollTo; the component follows the log tail with it.
    Object.defineProperty(Element.prototype, "scrollTo", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  beforeEach(() => {
    vi.spyOn(Element.prototype, "scrollTo").mockImplementation(() => {});
  });

  it("renders nothing when idle with no output", () => {
    const { container } = render(<ProcessLogs logs={[]} executing={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the waiting message while executing without output", () => {
    render(
      <ProcessLogs
        logs={[]}
        executing={true}
        emptyMessage="booting engine..."
      />,
    );
    expect(screen.getByText("booting engine...")).toBeInTheDocument();
    expect(screen.getByRole("group")).toBeTruthy();
  });

  it("defaults the title to the translated label and honors overrides", () => {
    const { rerender } = render(
      <ProcessLogs logs={["line"]} executing={false} />,
    );
    expect(screen.getByText("Process Logs")).toBeInTheDocument();

    rerender(
      <ProcessLogs logs={["line"]} executing={false} title="Parser output" />,
    );
    expect(screen.queryByText("Process Logs")).toBeNull();
    expect(screen.getByText("Parser output")).toBeInTheDocument();
  });

  it("renders the output count badge next to the title", () => {
    render(
      <ProcessLogs logs={["a", "b", "c"]} executing={false} title="Logs" />,
    );
    const summary = screen.getByText("Logs").closest("summary");
    expect(summary).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("3")).toBeInTheDocument();
  });

  it("renders every log line in order with zero-padded line numbers", () => {
    const { container } = render(
      <ProcessLogs
        logs={["first", "second", "third"]}
        executing={false}
        title="Logs"
      />,
    );
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();
    expect(screen.getByText("third")).toBeInTheDocument();
    const numbers = within(getScroller(container)).getAllByText(/^\d+$/);
    expect(numbers).toHaveLength(3);
    expect(numbers.map((n) => n.textContent)).toEqual(["  1", "  2", "  3"]);
  });

  it("collapses and re-expands through the details toggle", () => {
    const { container } = render(
      <ProcessLogs logs={["only"]} executing={false} title="Logs" />,
    );
    const details = container.querySelector("details") as HTMLDetailsElement;
    expect(details).toHaveAttribute("open");

    act(() => {
      details.open = false;
      fireEvent(details, new Event("toggle"));
    });
    expect(details).not.toHaveAttribute("open");

    act(() => {
      details.open = true;
      fireEvent(details, new Event("toggle"));
    });
    expect(details).toHaveAttribute("open");
  });

  it("follows new output only while the view is pinned near the bottom", () => {
    const { container, rerender } = render(
      <ProcessLogs logs={["a", "b"]} executing={true} title="Logs" />,
    );
    const scrollTo = Element.prototype.scrollTo as ReturnType<typeof vi.fn>;
    // Mounting with output pins the view to the tail once.
    expect(scrollTo).toHaveBeenCalledTimes(1);

    const scroller = getScroller(container);
    Object.defineProperty(scroller, "scrollHeight", {
      value: 500,
      configurable: true,
    });
    Object.defineProperty(scroller, "scrollTop", {
      value: 0,
      configurable: true,
    });

    // Scrolled away from the bottom: new output must not yank the view.
    fireEvent.scroll(scroller);
    rerender(
      <ProcessLogs logs={["a", "b", "c"]} executing={true} title="Logs" />,
    );
    expect(scrollTo).toHaveBeenCalledTimes(1);

    // Back at the bottom: the view follows incoming output.
    Object.defineProperty(scroller, "scrollTop", {
      value: 480,
      configurable: true,
    });
    fireEvent.scroll(scroller);
    rerender(
      <ProcessLogs
        logs={["a", "b", "c", "d"]}
        executing={true}
        title="Logs"
      />,
    );
    expect(scrollTo).toHaveBeenCalledTimes(2);
    expect(scrollTo.mock.calls[1][0]).toEqual({
      top: expect.any(Number),
      behavior: "smooth",
    });
  });
});
