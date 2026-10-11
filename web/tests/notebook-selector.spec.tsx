import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    name: "Research",
    description: "depth-first runs",
    record_count: 2,
    color: "#123456",
  },
  {
    id: "nb-2",
    name: "Reading",
    description: "",
    record_count: 0,
    color: "",
  },
];

const rec1: NotebookRecord = {
  id: "rec-1",
  title: "Solver run",
  summary: "step-by-step derivation",
  user_query: "q1",
  output: "o1",
  type: "solve",
};
const rec2: NotebookRecord = {
  id: "rec-2",
  title: "Follow-up question",
  user_query: "q2",
  output: "o2",
  type: "question",
};

const recordsMap = new Map([
  ["nb-1", [rec1, rec2]],
  ["nb-2", []],
]);

function selected(rec: NotebookRecord, notebook: Notebook): SelectedRecord {
  return { ...rec, notebookId: notebook.id, notebookName: notebook.name };
}

function renderSelector(overrides: Partial<Parameters<typeof NotebookSelector>[0]> = {}) {
  const onToggleExpanded = vi.fn();
  const onToggleRecord = vi.fn();
  const onSelectAll = vi.fn();
  const onDeselectAll = vi.fn();
  const onClearAll = vi.fn();
  const onCreateSession = vi.fn();

  const utils = render(
    <NotebookSelector
      notebooks={notebooks}
      expandedNotebooks={new Set(["nb-1"])}
      notebookRecordsMap={recordsMap}
      selectedRecords={new Map()}
      loadingNotebooks={false}
      loadingRecordsFor={new Set()}
      isLoading={false}
      onToggleExpanded={onToggleExpanded}
      onToggleRecord={onToggleRecord}
      onSelectAll={onSelectAll}
      onDeselectAll={onDeselectAll}
      onClearAll={onClearAll}
      onCreateSession={onCreateSession}
      {...overrides}
    />,
  );

  return {
    utils,
    onToggleExpanded,
    onToggleRecord,
    onSelectAll,
    onDeselectAll,
    onClearAll,
    onCreateSession,
  };
}

describe("NotebookSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the header and a spinner while notebooks load", () => {
    renderSelector({ loadingNotebooks: true });

    expect(screen.getByText("Select Source (Cross-Notebook)")).toBeTruthy();
    expect(screen.queryByText("Research")).toBeNull();
    expect(screen.queryByText("Reading")).toBeNull();
    const footer = screen
      .getByText("Use Selected Records (0)")
      .closest("button") as HTMLButtonElement;
    expect(footer).toBeDisabled();
  });

  it("explains the empty state when no notebooks have records", () => {
    renderSelector({ notebooks: [], notebookRecordsMap: new Map() });

    expect(screen.getByText("No notebooks with records found")).toBeTruthy();
    expect(
      screen.getByText("Save a chat result first to populate a notebook."),
    ).toBeTruthy();
  });

  it("renders collapsed notebook headers with record counts", () => {
    renderSelector({ expandedNotebooks: new Set() });

    const researchHeader = screen
      .getByText("Research")
      .closest("button") as HTMLElement;
    const readingHeader = screen
      .getByText("Reading")
      .closest("button") as HTMLElement;
    expect(researchHeader).toHaveTextContent("2");
    expect(readingHeader).toHaveTextContent("0");
    expect(screen.queryByText("Solver run")).toBeNull();
    expect(screen.queryByText("No records")).toBeNull();
  });

  it("reports the toggled notebook id when a header is clicked", () => {
    const { onToggleExpanded } = renderSelector();

    fireEvent.click(screen.getByText("Reading"));
    expect(onToggleExpanded).toHaveBeenCalledTimes(1);
    expect(onToggleExpanded).toHaveBeenCalledWith("nb-2");
  });

  it("renders type badges, titles and summaries for expanded records", () => {
    renderSelector();

    expect(screen.getByText("solve")).toBeTruthy();
    expect(screen.getByText("question")).toBeTruthy();
    expect(screen.getByText("Solver run")).toBeTruthy();
    expect(screen.getByText("step-by-step derivation")).toBeTruthy();
    expect(screen.getByText("Follow-up question")).toBeTruthy();
  });

  it("hands the record, notebook id and name back on toggle", () => {
    const { onToggleRecord } = renderSelector();

    fireEvent.click(screen.getByText("Solver run"));
    expect(onToggleRecord).toHaveBeenCalledTimes(1);
    expect(onToggleRecord).toHaveBeenCalledWith(rec1, "nb-1", "Research");
  });

  it("shows a per-notebook selected fraction and a clear control", () => {
    const { onClearAll } = renderSelector({
      selectedRecords: new Map([["rec-1", selected(rec1, notebooks[0])]]),
    });

    const researchHeader = screen
      .getByText("Research")
      .closest("button") as HTMLElement;
    expect(researchHeader).toHaveTextContent("1/2");

    fireEvent.click(screen.getByText("Clear (1)"));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it("omits the clear control when nothing is selected", () => {
    renderSelector();

    expect(screen.queryByText(/^Clear/)).toBeNull();
  });

  it("select-all and deselect report the notebook without toggling it", () => {
    const { onSelectAll, onDeselectAll, onToggleExpanded } = renderSelector();

    fireEvent.click(screen.getByText("Select All"));
    expect(onSelectAll).toHaveBeenCalledTimes(1);
    expect(onSelectAll).toHaveBeenCalledWith("nb-1", "Research");

    fireEvent.click(screen.getByText("Deselect"));
    expect(onDeselectAll).toHaveBeenCalledTimes(1);
    expect(onDeselectAll).toHaveBeenCalledWith("nb-1");

    expect(onToggleExpanded).not.toHaveBeenCalled();
  });

  it("shows loading records instead of rows or the empty note", () => {
    renderSelector({ loadingRecordsFor: new Set(["nb-1"]) });

    expect(screen.queryByText("No records")).toBeNull();
    expect(screen.queryByText("Solver run")).toBeNull();
    expect(screen.queryByText("Select All")).toBeNull();
  });

  it("shows the per-notebook empty note when expansion finds no records", () => {
    renderSelector({ expandedNotebooks: new Set(["nb-2"]) });

    expect(screen.getByText("No records")).toBeTruthy();
    expect(screen.queryByText("Select All")).toBeNull();
  });

  it("disables session creation until records are selected", () => {
    const { onCreateSession } = renderSelector();

    const button = screen.getByText(
      "Use Selected Records (0)",
    ).closest("button") as HTMLButtonElement;
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onCreateSession).not.toHaveBeenCalled();
  });

  it("labels the create button with the selected count and fires it", () => {
    const { onCreateSession } = renderSelector({
      selectedRecords: new Map([
        ["rec-1", selected(rec1, notebooks[0])],
        ["rec-2", selected(rec2, notebooks[0])],
      ]),
    });

    const button = screen.getByText(
      "Use Selected Records (2)",
    ).closest("button") as HTMLButtonElement;
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onCreateSession).toHaveBeenCalledTimes(1);
  });

  it("honours a custom action label over the counted default", () => {
    renderSelector({
      actionLabel: "Start studying",
      selectedRecords: new Map([["rec-1", selected(rec1, notebooks[0])]]),
    });

    expect(screen.getByText("Start studying")).toBeTruthy();
    expect(screen.queryByText("Use Selected Records (1)")).toBeNull();
  });

  it("switches to a busy generating state while submitting", () => {
    const { onCreateSession } = renderSelector({
      isLoading: true,
      selectedRecords: new Map([["rec-1", selected(rec1, notebooks[0])]]),
    });

    const button = screen
      .getByText("Generating...")
      .closest("button") as HTMLButtonElement;
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onCreateSession).not.toHaveBeenCalled();
  });
});
