import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  useKnowledgeHistory,
  type HistoryEntry,
} from "@/hooks/useKnowledgeHistory";

const STORAGE_KEY = "knowledge:history:v1";

function entryOf(
  overrides: Partial<Omit<HistoryEntry, "id">> = {},
): Omit<HistoryEntry, "id"> {
  return {
    taskId: "task-1",
    kind: "create",
    label: "KB",
    status: "completed",
    startedAt: 1,
    completedAt: 2,
    logTail: [],
    ...overrides,
  };
}

function persisted(entry: Omit<HistoryEntry, "id">): HistoryEntry {
  return {
    ...entry,
    logTail: entry.logTail ?? [],
    id: `${entry.taskId}:${entry.completedAt}`,
  };
}

function readPersisted(): { byKb: Record<string, HistoryEntry[]> } {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? (JSON.parse(raw) as { byKb: Record<string, HistoryEntry[]> }) : { byKb: {} };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("useKnowledgeHistory", () => {
  it("hydrates a previously persisted store on mount", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        byKb: { papers: [persisted(entryOf({ taskId: "kept" }))] },
      }),
    );
    const { result } = renderHook(() => useKnowledgeHistory());
    await waitFor(() =>
      expect(result.current.historyByKb.papers).toHaveLength(1),
    );
    expect(result.current.historyByKb.papers?.[0]?.taskId).toBe("kept");
  });

  it("treats corrupted storage as empty instead of throwing", async () => {
    localStorage.setItem(STORAGE_KEY, "{not json");
    const { result } = renderHook(() => useKnowledgeHistory());
    await waitFor(() =>
      expect(Object.keys(result.current.historyByKb)).toHaveLength(0),
    );
  });

  it("appends newest-first with a derived id and persists the store", async () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    act(() => {
      result.current.append("papers", entryOf({ taskId: "t-old" }));
    });
    act(() => {
      result.current.append(
        "papers",
        entryOf({ taskId: "t-new", completedAt: 9, logTail: ["done"] }),
      );
    });
    const list = result.current.historyByKb.papers;
    expect(list?.map((e) => e.taskId)).toEqual(["t-new", "t-old"]);
    expect(list?.[0]).toMatchObject({ id: "t-new:9", logTail: ["done"] });
    const persistedStore = readPersisted();
    expect(persistedStore.byKb.papers?.[0]?.taskId).toBe("t-new");
  });

  it("dedupes appends by taskId", () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    act(() => {
      result.current.append("papers", entryOf({ taskId: "same" }));
    });
    act(() => {
      result.current.append(
        "papers",
        entryOf({ taskId: "same", completedAt: 42 }),
      );
    });
    const list = result.current.historyByKb.papers;
    expect(list).toHaveLength(1);
    expect(list?.[0]?.id).toBe("same:2");
    expect(readPersisted().byKb.papers).toHaveLength(1);
  });

  it("caps per-KB history at 20 entries, newest first", () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    act(() => {
      for (let index = 1; index <= 22; index += 1) {
        result.current.append("papers", entryOf({ taskId: `task-${index}` }));
      }
    });
    const list = result.current.historyByKb.papers;
    expect(list).toHaveLength(20);
    expect(list?.[0]?.taskId).toBe("task-22");
    expect(list?.at(-1)?.taskId).toBe("task-3");
    expect(readPersisted().byKb.papers).toHaveLength(20);
  });

  it("keeps log tails within line and byte bounds", () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    const manyLines = Array.from({ length: 100 }, (_, i) => `line-${i}`);
    act(() => {
      result.current.append("papers", entryOf({ logTail: manyLines }));
    });
    const trimmed = result.current.historyByKb.papers?.[0]?.logTail;
    expect(trimmed).toHaveLength(80);
    expect(trimmed?.[0]).toBe("line-20");
    expect(trimmed?.at(-1)).toBe("line-99");

    const hugeLines = ["a".repeat(5000), "b".repeat(5000), "c".repeat(5000)];
    act(() => {
      result.current.append(
        "papers",
        entryOf({ taskId: "task-huge", logTail: hugeLines }),
      );
    });
    expect(result.current.historyByKb.papers?.[0]?.logTail).toEqual([
      "c".repeat(5000),
    ]);
  });

  it("renames a KB and treats unknown names as a no-op", () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    act(() => {
      result.current.append("kb-a", entryOf({ taskId: "t1" }));
    });
    act(() => {
      result.current.renameKb("kb-a", "kb-b");
    });
    expect(result.current.historyByKb["kb-a"]).toBeUndefined();
    expect(result.current.historyByKb["kb-b"]?.[0]?.taskId).toBe("t1");
    expect(Object.keys(readPersisted().byKb)).toEqual(["kb-b"]);

    act(() => {
      result.current.renameKb("ghost", "nowhere");
    });
    expect(Object.keys(result.current.historyByKb)).toEqual(["kb-b"]);
  });

  it("removes and clears a KB, ignoring unknown names", () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    act(() => {
      result.current.append("kb-a", entryOf({ taskId: "t1" }));
      result.current.append("kb-b", entryOf({ taskId: "t2" }));
    });
    act(() => {
      result.current.removeKb("ghost");
    });
    expect(Object.keys(result.current.historyByKb).sort()).toEqual([
      "kb-a",
      "kb-b",
    ]);
    act(() => {
      result.current.clearKb("kb-a");
    });
    expect(result.current.historyByKb["kb-a"]).toBeUndefined();
    expect(Object.keys(readPersisted().byKb)).toEqual(["kb-b"]);
  });

  it("refreshes from storage events for the history key only", async () => {
    const { result } = renderHook(() => useKnowledgeHistory());
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ byKb: { other: [persisted(entryOf())] } }),
    );
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
    });
    await waitFor(() =>
      expect(result.current.historyByKb.other).toHaveLength(1),
    );

    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ byKb: { other: [persisted(entryOf())] } }),
    );
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" }));
    });
    expect(result.current.historyByKb.other).toHaveLength(1);
  });
});
