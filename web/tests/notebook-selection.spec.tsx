import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNotebookSelection } from "@/components/notebook/useNotebookSelection";
import type {
  NotebookDetail,
  NotebookRecordItem,
  NotebookSummary,
} from "@/lib/notebook-api";

const fixture = vi.hoisted(() => ({
  listNotebooks: vi.fn(),
  getNotebook: vi.fn(),
}));

vi.mock("@/lib/notebook-api", () => ({
  listNotebooks: fixture.listNotebooks,
  getNotebook: fixture.getNotebook,
}));

const summaries: NotebookSummary[] = [
  {
    id: "nb-1",
    name: "Math",
    description: "derivatives",
    record_count: 2,
    color: "#ff0000",
  },
  {
    id: "nb-empty",
    name: "Empty",
    record_count: 0,
  },
  {
    id: "nb-2",
    name: "Papers",
    record_count: 1,
  },
];

const nb1Records: NotebookRecordItem[] = [
  {
    id: "10",
    type: "solve",
    title: "Problem 1",
    summary: "first",
    user_query: "derive x^2",
    output: "2x",
  },
  {
    id: "11",
    type: "chat",
    title: "Problem 2",
    user_query: "integrate x",
    output: "x^2/2",
  },
];

function detail(id: string, records: NotebookRecordItem[]): NotebookDetail {
  return {
    id,
    name: id,
    record_count: records.length,
    records,
  };
}

beforeEach(() => {
  fixture.listNotebooks.mockReset().mockResolvedValue(summaries);
  fixture.getNotebook.mockReset().mockImplementation(async (id: string) =>
    id === "nb-1" ? detail("nb-1", nb1Records) : detail(id, []),
  );
});

afterEach(() => {
  cleanup();
});

async function renderWithNotebooks() {
  const hook = renderHook(() => useNotebookSelection());
  await act(async () => {
    await hook.result.current.fetchNotebooks();
  });
  return hook;
}

describe("useNotebookSelection", () => {
  it("keeps only notebooks with records and applies display defaults", async () => {
    const { result } = renderHook(() => useNotebookSelection());
    expect(result.current.loadingNotebooks).toBe(true);
    await act(async () => {
      await result.current.fetchNotebooks();
    });
    expect(result.current.loadingNotebooks).toBe(false);
    expect(result.current.notebooks).toEqual([
      {
        id: "nb-1",
        name: "Math",
        description: "derivatives",
        record_count: 2,
        color: "#ff0000",
      },
      {
        id: "nb-2",
        name: "Papers",
        description: "",
        record_count: 1,
        color: "",
      },
    ]);
  });

  it("falls back to an empty list when listing fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    fixture.listNotebooks.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useNotebookSelection());
    await act(async () => {
      await result.current.fetchNotebooks();
    });
    expect(result.current.notebooks).toEqual([]);
    expect(result.current.loadingNotebooks).toBe(false);
  });

  it("expands a notebook, loads its records once and caches them", async () => {
    const { result } = await renderWithNotebooks();
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    await waitFor(() =>
      expect(result.current.loadingRecordsFor.has("nb-1")).toBe(false),
    );
    expect(result.current.expandedNotebooks.has("nb-1")).toBe(true);
    const records = result.current.notebookRecordsMap.get("nb-1");
    expect(records).toHaveLength(2);
    expect(records?.[0]).toMatchObject({ id: "10", type: "solve" });
    expect(records?.[1]).toMatchObject({ id: "11", type: "chat" });
    expect(fixture.getNotebook).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    await waitFor(() =>
      expect(result.current.loadingRecordsFor.has("nb-1")).toBe(false),
    );
    expect(fixture.getNotebook).toHaveBeenCalledTimes(1);
  });

  it("ignores expansion of an unknown notebook", async () => {
    const { result } = await renderWithNotebooks();
    act(() => {
      result.current.toggleNotebookExpanded("ghost");
    });
    expect(result.current.expandedNotebooks.size).toBe(0);
    expect(result.current.loadingRecordsFor.size).toBe(0);
    expect(fixture.getNotebook).not.toHaveBeenCalled();
  });

  it("collapses without dropping cached records", async () => {
    const { result } = await renderWithNotebooks();
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    await waitFor(() =>
      expect(result.current.loadingRecordsFor.has("nb-1")).toBe(false),
    );
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    expect(result.current.expandedNotebooks.has("nb-1")).toBe(false);
    expect(result.current.notebookRecordsMap.get("nb-1")).toHaveLength(2);
    expect(fixture.getNotebook).toHaveBeenCalledTimes(1);
  });

  it("clears the loading marker when record loading fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = await renderWithNotebooks();
    fixture.getNotebook.mockRejectedValue(new Error("boom"));
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    await waitFor(() =>
      expect(result.current.loadingRecordsFor.has("nb-1")).toBe(false),
    );
    expect(result.current.notebookRecordsMap.has("nb-1")).toBe(false);
  });

  it("toggles a single record selection with notebook annotations", async () => {
    const { result } = await renderWithNotebooks();
    const record = {
      id: "10",
      title: "Problem 1",
      summary: "first",
      user_query: "derive x^2",
      output: "2x",
      type: "solve",
    };
    act(() => {
      result.current.toggleRecordSelection(record, "nb-1", "Math");
    });
    expect(result.current.selectedRecords.get("10")).toEqual({
      ...record,
      notebookId: "nb-1",
      notebookName: "Math",
    });
    act(() => {
      result.current.toggleRecordSelection(record, "nb-1", "Math");
    });
    expect(result.current.selectedRecords.size).toBe(0);
  });

  it("accumulates selections across notebooks", async () => {
    const { result } = await renderWithNotebooks();
    const fromNb1 = {
      id: "10",
      title: "Problem 1",
      user_query: "q",
      output: "o",
      type: "solve",
    };
    const fromNb2 = {
      id: "20",
      title: "Paper note",
      user_query: "q2",
      output: "o2",
      type: "research",
    };
    act(() => {
      result.current.toggleRecordSelection(fromNb1, "nb-1", "Math");
      result.current.toggleRecordSelection(fromNb2, "nb-2", "Papers");
    });
    expect(result.current.selectedRecords.size).toBe(2);
    expect(result.current.selectedRecords.get("10")?.notebookName).toBe("Math");
    expect(result.current.selectedRecords.get("20")?.notebookName).toBe(
      "Papers",
    );
  });

  it("selects and deselects per notebook and clears everything", async () => {
    const { result } = await renderWithNotebooks();
    act(() => {
      result.current.toggleNotebookExpanded("nb-1");
    });
    await waitFor(() =>
      expect(result.current.loadingRecordsFor.has("nb-1")).toBe(false),
    );
    act(() => {
      result.current.selectAllFromNotebook("nb-1", "Math");
    });
    expect(result.current.selectedRecords.size).toBe(2);
    expect(result.current.selectedRecords.get("11")?.notebookId).toBe("nb-1");

    act(() => {
      result.current.selectAllFromNotebook("unknown", "Nowhere");
    });
    expect(result.current.selectedRecords.size).toBe(2);

    act(() => {
      result.current.deselectAllFromNotebook("nb-1");
    });
    expect(result.current.selectedRecords.size).toBe(0);

    act(() => {
      result.current.selectAllFromNotebook("nb-1", "Math");
      result.current.toggleRecordSelection(
        {
          id: "99",
          title: "extra",
          user_query: "q",
          output: "o",
          type: "chat",
        },
        "nb-2",
        "Papers",
      );
    });
    act(() => {
      result.current.clearAllSelections();
    });
    expect(result.current.selectedRecords.size).toBe(0);
  });
});
