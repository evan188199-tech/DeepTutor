import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import NotebookRecordActions from "@/components/notebook/NotebookRecordActions";
import type { NotebookSummary } from "@/lib/notebook-api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const targets: NotebookSummary[] = [
  { id: "nb-1", name: "Algebra", color: "#6366F1", record_count: 3 },
  { id: "nb-2", name: "History", record_count: 0 },
];

type ActionsProps = Parameters<typeof NotebookRecordActions>[0];

function renderActions(overrides: Partial<ActionsProps> = {}) {
  const props: ActionsProps = {
    targets,
    disabled: false,
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onRelocate: vi.fn(),
    ...overrides,
  };
  const utils = render(<NotebookRecordActions {...props} />);
  return { props, ...utils };
}

function openMenu(props?: Partial<ActionsProps>) {
  const context = renderActions(props);
  fireEvent.click(screen.getByRole("button", { name: "Record actions" }));
  expect(screen.getByRole("menu")).toBeInTheDocument();
  return context;
}

it("renders a closed trigger button by default", () => {
  renderActions();

  const trigger = screen.getByRole("button", { name: "Record actions" });
  expect(trigger).toBeEnabled();
  expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("opens the root menu with edit and delete entries", () => {
  openMenu();

  const menu = screen.getByRole("menu");
  expect(within(menu).getByText("Edit record")).toBeInTheDocument();
  expect(within(menu).getByText("Delete")).toBeInTheDocument();
});

it("omits the relocate entries when there are no target notebooks", () => {
  openMenu({ targets: [] });

  const menu = screen.getByRole("menu");
  expect(within(menu).getByText("Edit record")).toBeInTheDocument();
  expect(within(menu).queryByText("Move to")).not.toBeInTheDocument();
  expect(within(menu).queryByText("Copy to")).not.toBeInTheDocument();
});

it("lists move and copy entries when relocation targets exist", () => {
  openMenu();

  const menu = screen.getByRole("menu");
  expect(within(menu).getByText("Move to")).toBeInTheDocument();
  expect(within(menu).getByText("Copy to")).toBeInTheDocument();
});

it("dispatches onEdit and closes the menu", () => {
  const { props } = openMenu();

  fireEvent.click(screen.getByText("Edit record"));

  expect(props.onEdit).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(
    screen
      .getByRole("button", { name: "Record actions" })
      .getAttribute("aria-expanded"),
  ).toBe("false");
});

it("dispatches onDelete and closes the menu", () => {
  const { props } = openMenu();

  fireEvent.click(screen.getByText("Delete"));

  expect(props.onDelete).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("moves the record to the chosen target notebook", () => {
  const { props } = openMenu();

  fireEvent.click(screen.getByText("Move to"));
  fireEvent.click(screen.getByText("History"));

  expect(props.onRelocate).toHaveBeenCalledTimes(1);
  expect(props.onRelocate).toHaveBeenCalledWith("nb-2", "move");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("copies the record to the chosen target notebook", () => {
  const { props } = openMenu();

  fireEvent.click(screen.getByText("Copy to"));
  fireEvent.click(screen.getByText("Algebra"));

  expect(props.onRelocate).toHaveBeenCalledTimes(1);
  expect(props.onRelocate).toHaveBeenCalledWith("nb-1", "copy");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("returns to the root panel from a destination list via the back button", () => {
  openMenu();

  fireEvent.click(screen.getByText("Move to"));
  expect(screen.getByText("History")).toBeInTheDocument();
  expect(screen.queryByText("Edit record")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Move to" }));
  expect(screen.getByText("Edit record")).toBeInTheDocument();
  expect(screen.queryByText("History")).not.toBeInTheDocument();
});

it("resets to the root panel after Escape closes the menu", () => {
  const first = openMenu();

  fireEvent.click(screen.getByText("Move to"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  first.unmount();

  openMenu();
  expect(screen.getByText("Edit record")).toBeInTheDocument();
  expect(screen.queryByText("History")).not.toBeInTheDocument();
});

it("closes the menu on a pointer down outside of it", () => {
  openMenu();

  fireEvent.pointerDown(document.body);

  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("closes the open menu when the trigger is activated again", () => {
  openMenu();

  fireEvent.click(screen.getByRole("button", { name: "Record actions" }));

  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("disables the trigger so no menu can open", () => {
  renderActions({ disabled: true });

  expect(screen.getByRole("button", { name: "Record actions" })).toBeDisabled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});
