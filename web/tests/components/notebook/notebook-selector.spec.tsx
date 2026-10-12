import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import NotebookSelector from "@/components/notebook/NotebookSelector";
import type {
  Notebook,
  NotebookRecord,
  SelectedRecord,
} from "@/lib/notebook-selection-types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const notebooks: Notebook[] = [
  {
    id: "nb-1",
    name: "Algebra",
    description: "",
    record_count: 2,
    color: "#6366F1",
  },
  {
    id: "nb-2",
    name: "History",
    description: "",
    record_count: 0,
    color: "",
  },
];

const algebraRecords: NotebookRecord[] = [
  {
    id: "rec-1",
    title: "Quadratic equations",
    summary: "How to factor quadratics.",
    user_query: "Solve x^2 + 1 = 0",
    output: "No real roots.",
    type: "solve",
  },
  {
    id: "rec-2",
    title: "Matrix rank",
    user_query: "What is matrix rank?",
    output: "Dimension of the column space.",
    type: "question",
  },
];

function selectedMap(...records: NotebookRecord[]): Map<string, SelectedRecord> {
  return new Map(
    records.map((record) => [
      record.id,
      { ...record, notebookId: "nb-1", notebookName: "Algebra" },
    ]),
  );
}

type SelectorProps = Parameters<typeof NotebookSelector>[0];

function renderSelector(overrides: Partial<SelectorProps> = {}) {
  const props: SelectorProps = {
    notebooks,
    expandedNotebooks: new Set<string>(),
    notebookRecordsMap: new Map([["nb-1", algebraRecords]]),
    selectedRecords: new Map<string, SelectedRecord>(),
    loadingNotebooks: false,
    loadingRecordsFor: new Set<string>(),
    isLoading: false,
    onToggleExpanded: vi.fn(),
    onToggleRecord: vi.fn(),
    onSelectAll: vi.fn(),
    onDeselectAll: vi.fn(),
    onClearAll: vi.fn(),
    onCreateSession: vi.fn(),
    ...overrides,
  };
  const utils = render(<NotebookSelector {...props} />);
  return { props, ...utils };
}

function notebookHeader(name: string): HTMLElement {
  const heading = screen.getByText(name);
  const header = heading.closest("button");
  expect(header).not.toBeNull();
  return header!;
}

it("shows a loading spinner instead of notebooks while the list is loading", () => {
  const { container } = renderSelector({ loadingNotebooks: true });

  expect(screen.queryByText("Algebra")).not.toBeInTheDocument();
  expect(
    screen.queryByText("No notebooks with records found"),
  ).not.toBeInTheDocument();
  expect(container.querySelector(".animate-spin")).not.toBeNull();
});

it("shows the empty state when no notebooks have records", () => {
  renderSelector({ notebooks: [] });

  expect(screen.getByText("No notebooks with records found")).toBeInTheDocument();
  expect(
    screen.getByText("Save a chat result first to populate a notebook."),
  ).toBeInTheDocument();
});

it("renders collapsed notebook headers with their record counts", () => {
  renderSelector();

  const algebraHeader = notebookHeader("Algebra");
  expect(within(algebraHeader).getByText("2")).toBeInTheDocument();
  expect(within(notebookHeader("History")).getByText("0")).toBeInTheDocument();
  expect(screen.queryByText("Quadratic equations")).not.toBeInTheDocument();
});

it("dispatches onToggleExpanded with the notebook id from its header", () => {
  const { props } = renderSelector();

  fireEvent.click(notebookHeader("Algebra"));

  expect(props.onToggleExpanded).toHaveBeenCalledTimes(1);
  expect(props.onToggleExpanded).toHaveBeenCalledWith("nb-1");
});

it("lists the records of an expanded notebook with type and summary", () => {
  renderSelector({ expandedNotebooks: new Set(["nb-1"]) });

  expect(screen.getByText("Quadratic equations")).toBeInTheDocument();
  expect(screen.getByText("How to factor quadratics.")).toBeInTheDocument();
  expect(screen.getByText("solve")).toBeInTheDocument();
  expect(screen.getByText("Matrix rank")).toBeInTheDocument();
});

it("shows an empty records message for an expanded notebook without records", () => {
  renderSelector({ expandedNotebooks: new Set(["nb-2"]) });

  expect(screen.getByText("No records")).toBeInTheDocument();
  expect(screen.queryByText("Select All")).not.toBeInTheDocument();
});

it("shows a per-notebook loading spinner while its records are being fetched", () => {
  const { container } = renderSelector({
    expandedNotebooks: new Set(["nb-1"]),
    loadingRecordsFor: new Set(["nb-1"]),
  });

  expect(screen.queryByText("Select All")).not.toBeInTheDocument();
  expect(screen.queryByText("No records")).not.toBeInTheDocument();
  expect(screen.queryByText("Quadratic equations")).not.toBeInTheDocument();
  expect(container.querySelector(".animate-spin")).not.toBeNull();
});

it("dispatches onToggleRecord with record and notebook context when a record is clicked", () => {
  const { props } = renderSelector({
    expandedNotebooks: new Set(["nb-1"]),
  });

  fireEvent.click(screen.getByText("Matrix rank"));

  expect(props.onToggleRecord).toHaveBeenCalledTimes(1);
  expect(props.onToggleRecord).toHaveBeenCalledWith(
    algebraRecords[1],
    "nb-1",
    "Algebra",
  );
});

it("marks selected records and shows the per-notebook selection count", () => {
  renderSelector({
    expandedNotebooks: new Set(["nb-1"]),
    selectedRecords: selectedMap(algebraRecords[0]),
  });

  expect(screen.getByText("1/")).toBeInTheDocument();

  const recordRow = screen
    .getByText("Quadratic equations")
    .closest(".cursor-pointer");
  expect(recordRow).not.toBeNull();
  expect(recordRow!.querySelector("svg")).not.toBeNull();

  const unselectedRow = screen.getByText("Matrix rank").closest(".cursor-pointer");
  expect(unselectedRow).not.toBeNull();
  expect(unselectedRow!.querySelector("svg")).toBeNull();
});

it("dispatches Select All and Deselect with the notebook context", () => {
  const { props } = renderSelector({
    expandedNotebooks: new Set(["nb-1"]),
  });

  fireEvent.click(screen.getByText("Select All"));
  expect(props.onSelectAll).toHaveBeenCalledTimes(1);
  expect(props.onSelectAll).toHaveBeenCalledWith("nb-1", "Algebra");

  fireEvent.click(screen.getByText("Deselect"));
  expect(props.onDeselectAll).toHaveBeenCalledTimes(1);
  expect(props.onDeselectAll).toHaveBeenCalledWith("nb-1");
});

it("only shows the Clear action when a selection exists and dispatches onClearAll", () => {
  const first = renderSelector();
  expect(screen.queryByRole("button", { name: "Clear (1)" })).toBeNull();
  first.unmount();

  const { props } = renderSelector({
    selectedRecords: selectedMap(algebraRecords[0]),
  });
  const clearButton = screen.getByRole("button", { name: "Clear (1)" });
  fireEvent.click(clearButton);
  expect(props.onClearAll).toHaveBeenCalledTimes(1);
});

it("keeps the apply action disabled without a selection and blocks onCreateSession", () => {
  const { props } = renderSelector();

  const applyButton = screen.getByRole("button", {
    name: "Use Selected Records (0)",
  });
  expect(applyButton).toBeDisabled();

  fireEvent.click(applyButton);
  expect(props.onCreateSession).not.toHaveBeenCalled();
});

it("enables the apply action with a selection and dispatches onCreateSession", () => {
  const { props } = renderSelector({
    selectedRecords: selectedMap(...algebraRecords),
  });

  const applyButton = screen.getByRole("button", {
    name: "Use Selected Records (2)",
  });
  expect(applyButton).toBeEnabled();

  fireEvent.click(applyButton);
  expect(props.onCreateSession).toHaveBeenCalledTimes(1);
});

it("renders the custom action label with the selection count interpolated", () => {
  renderSelector({
    selectedRecords: selectedMap(algebraRecords[0]),
    actionLabel: "Create quiz ({n})",
  });

  expect(
    screen.getByRole("button", { name: "Create quiz (1)" }),
  ).toBeInTheDocument();
});

it("shows the generating state and disables the apply action while a session is being created", () => {
  renderSelector({
    selectedRecords: selectedMap(algebraRecords[0]),
    isLoading: true,
  });

  expect(screen.getByText("Generating...")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Generating..." }),
  ).toBeDisabled();
});
