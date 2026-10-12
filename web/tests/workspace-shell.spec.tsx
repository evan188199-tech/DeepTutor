import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  WorkspaceDetailEmpty,
  WorkspaceFieldGroup,
  WorkspaceRail,
  WorkspaceSplit,
  workspaceCardClass,
} from "@/components/settings/WorkspaceShell";

function railProps(overrides: Partial<Parameters<typeof WorkspaceRail>[0]> = {}) {
  return {
    search: {
      label: "Search models",
      value: "",
      onChange: () => {},
      placeholder: "Find a model…",
    },
    children: <p>row-one</p>,
    ...overrides,
  };
}

function fadeSpans(container: HTMLElement) {
  const spans = Array.from(
    container.querySelectorAll<HTMLSpanElement>("span[aria-hidden='true']"),
  );
  expect(spans).toHaveLength(2);
  return { top: spans[0], bottom: spans[1] };
}

it("marks the active workspace card with a ring and the idle one with a hover affordance", () => {
  const active = workspaceCardClass(true);
  const idle = workspaceCardClass(false);
  expect(active).toContain("ring-1");
  expect(active).not.toContain("hover:border-");
  expect(idle).toContain("hover:border-");
  expect(idle).not.toContain("ring-1");
  expect(active).toContain("rounded-xl");
  expect(idle).toContain("rounded-xl");
});

it("renders the rail before the detail pane inside one grid", () => {
  const { container } = render(
    <WorkspaceSplit rail={<div>rail-slot</div>} detail={<div>detail-slot</div>} />,
  );
  const grid = container.firstElementChild as HTMLElement;
  expect(grid.className).toContain("grid");
  expect(grid.children[0]).toHaveTextContent("rail-slot");
  expect(grid.children[1]).toHaveTextContent("detail-slot");
});

it("wires the rail search box to label, value, placeholder and change events", () => {
  const onChange = vi.fn();
  render(
    <WorkspaceRail
      {...railProps({ search: { label: "Search providers", value: "abc", onChange, placeholder: "Filter…" } })}
    />,
  );
  const input = screen.getByRole("searchbox", { name: "Search providers" });
  expect(input).toHaveValue("abc");
  expect(input).toHaveAttribute("placeholder", "Filter…");
  fireEvent.change(input, { target: { value: "abcd" } });
  expect(onChange).toHaveBeenCalledWith("abcd");
});

it("keeps the action and filter slots around the list", () => {
  render(
    <WorkspaceRail
      {...railProps()}
      action={<button type="button">add-provider</button>}
      filter={<div>filter-slot</div>}
    />,
  );
  expect(screen.getByRole("button", { name: "add-provider" })).toBeInTheDocument();
  expect(screen.getByText("filter-slot")).toBeInTheDocument();
  expect(screen.getByText("row-one")).toBeInTheDocument();
});

it("replaces the list with the empty hint when the rail has nothing to show", () => {
  render(
    <WorkspaceRail {...railProps({ empty: "No providers match your filters." })} />,
  );
  expect(screen.getByText("No providers match your filters.")).toBeInTheDocument();
  expect(screen.queryByText("row-one")).toBeNull();
});

it("reveals the continuation fades only on the edges that still scroll", () => {
  const { container } = render(<WorkspaceRail {...railProps()} />);
  let fades = fadeSpans(container);
  expect(fades.top.className).toContain("opacity-0");
  expect(fades.bottom.className).toContain("opacity-0");

  const scroller = Array.from(container.querySelectorAll("div")).find((div) =>
    div.className.includes("overflow-y-auto"),
  )! as HTMLElement;
  Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1200 });
  Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 300 });

  act(() => {
    Object.defineProperty(scroller, "scrollTop", { configurable: true, value: 500 });
    fireEvent.scroll(scroller);
  });
  fades = fadeSpans(container);
  expect(fades.top.className).toContain("opacity-100");
  expect(fades.bottom.className).toContain("opacity-100");

  act(() => {
    Object.defineProperty(scroller, "scrollTop", { configurable: true, value: 900 });
    fireEvent.scroll(scroller);
  });
  fades = fadeSpans(container);
  expect(fades.top.className).toContain("opacity-100");
  expect(fades.bottom.className).toContain("opacity-0");
});

it("renders the detail placeholder with icon, title and an optional hint", () => {
  const { rerender } = render(
    <WorkspaceDetailEmpty icon={<span>icon-node</span>} title="Pick a model" hint="Choose one to edit its keys." />,
  );
  expect(screen.getByText("icon-node")).toBeInTheDocument();
  expect(screen.getByText("Pick a model")).toBeInTheDocument();
  expect(screen.getByText("Choose one to edit its keys.")).toBeInTheDocument();

  rerender(<WorkspaceDetailEmpty icon={<span>icon-node</span>} title="Pick a model" />);
  expect(screen.getByText("Pick a model")).toBeInTheDocument();
  expect(screen.queryByText("Choose one to edit its keys.")).toBeNull();
});

it("heads a field group with its title, action and children", () => {
  render(
    <WorkspaceFieldGroup
      title="Credentials"
      action={<button type="button">test-connection</button>}
      className="extra-pad"
    >
      <p>field-child</p>
    </WorkspaceFieldGroup>,
  );
  expect(screen.getByRole("heading", { level: 4, name: "Credentials" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "test-connection" })).toBeInTheDocument();
  expect(screen.getByText("field-child")).toBeInTheDocument();
  const section = screen.getByText("field-child").closest("section");
  expect(section?.className).toContain("extra-pad");
});
