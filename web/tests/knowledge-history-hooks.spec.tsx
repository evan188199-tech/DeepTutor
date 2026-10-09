import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  useKnowledgeHistory,
  type HistoryEntry,
} from "@/hooks/useKnowledgeHistory";

const STORAGE_KEY = "knowledge:history:v1";

function makeEntry(
  overrides: Partial<Omit<HistoryEntry, "id">> = {},
): Omit<HistoryEntry, "id"> {
  return {
    taskId: "task-1",
    kind: "create",
    label: "papers",
    status: "completed",
    startedAt: 1000,
    completedAt: 2000,
    fileCount: 1,
    error: null,
    logTail: ["done"],
    ...overrides,
  };
}

function readPersisted(): { byKb: Record<string, HistoryEntry[]> } {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? JSON.parse(raw) : { byKb: {} };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("starts empty when no history was persisted", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  expect(result.current.historyByKb).toEqual({});
  expect(readPersisted().byKb).toEqual({});
});

it("hydrates a persisted store after mount", () => {
  const persisted = {
    byKb: {
      papers: [
        { ...makeEntry(), id: "task-1:2000" },
      ],
    },
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  const { result } = renderHook(() => useKnowledgeHistory());
  expect(result.current.historyByKb.papers).toHaveLength(1);
  expect(result.current.historyByKb.papers[0]).toMatchObject({
    id: "task-1:2000",
    taskId: "task-1",
  });
});

it("falls back to empty when the persisted store is corrupted or malformed", () => {
  localStorage.setItem(STORAGE_KEY, "{not json at all");
  const broken = renderHook(() => useKnowledgeHistory());
  expect(broken.result.current.historyByKb).toEqual({});
  broken.unmount();

  localStorage.setItem(STORAGE_KEY, JSON.stringify({ unexpected: true }));
  const missingBucket = renderHook(() => useKnowledgeHistory());
  expect(missingBucket.result.current.historyByKb).toEqual({});
});

it("appends a persisted record and dedupes repeated events for one task", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  act(() => {
    result.current.append("papers", makeEntry());
    // Final progress events sometimes fire twice — the duplicate is dropped.
    result.current.append("papers", makeEntry());
  });
  expect(result.current.historyByKb.papers).toHaveLength(1);
  expect(result.current.historyByKb.papers[0]).toMatchObject({
    id: "task-1:2000",
    taskId: "task-1",
    label: "papers",
  });
  expect(readPersisted().byKb.papers).toHaveLength(1);
});

it("keeps at most 20 newest-first entries per knowledge base", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  act(() => {
    for (let index = 0; index < 22; index += 1) {
      result.current.append(
        "papers",
        makeEntry({ taskId: `task-${index}`, completedAt: 2000 + index }),
      );
    }
  });
  const entries = result.current.historyByKb.papers;
  expect(entries).toHaveLength(20);
  expect(entries[0].taskId).toBe("task-21");
  expect(entries[19].taskId).toBe("task-2");
});

it("trims stored log tails to the last 80 lines", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  const longLog = Array.from({ length: 100 }, (_, index) => `line-${index}`);
  act(() => {
    result.current.append("papers", makeEntry({ logTail: longLog }));
  });
  const stored = result.current.historyByKb.papers[0].logTail;
  expect(stored).toHaveLength(80);
  expect(stored[0]).toBe("line-20");
  expect(stored[79]).toBe("line-99");
});

it("drops log lines that would blow the size budget, newest first", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  act(() => {
    result.current.append(
      "papers",
      makeEntry({
        logTail: [
          "ancient",
          "x".repeat(9 * 1024),
          "recent-1",
          "recent-2",
        ],
      }),
    );
  });
  // Walking back from the newest line stops at the first line that would
  // exceed the budget — everything older than it is dropped too.
  expect(result.current.historyByKb.papers[0].logTail).toEqual([
    "recent-1",
    "recent-2",
  ]);

  act(() => {
    result.current.append(
      "notes",
      makeEntry({ taskId: "task-2", logTail: ["x".repeat(9 * 1024)] }),
    );
  });
  expect(result.current.historyByKb.notes[0].logTail).toEqual([]);
});

it("renames a bucket and persists the move; unknown renames are no-ops", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  act(() => {
    result.current.append("old-name", makeEntry());
  });
  act(() => {
    result.current.renameKb("old-name", "new-name");
  });
  expect(result.current.historyByKb.old_name).toBeUndefined();
  expect(result.current.historyByKb["old-name"]).toBeUndefined();
  expect(result.current.historyByKb["new-name"]).toHaveLength(1);
  expect(readPersisted().byKb["new-name"]).toHaveLength(1);
  expect(readPersisted().byKb["old-name"]).toBeUndefined();

  act(() => {
    result.current.renameKb("missing", "elsewhere");
  });
  expect(Object.keys(result.current.historyByKb)).toEqual(["new-name"]);
});

it("removes and clears buckets from memory and storage", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  act(() => {
    result.current.append("papers", makeEntry());
    result.current.append("notes", makeEntry({ taskId: "task-2" }));
  });
  act(() => {
    result.current.removeKb("papers");
  });
  expect(result.current.historyByKb.papers).toBeUndefined();
  expect(result.current.historyByKb.notes).toHaveLength(1);
  act(() => {
    result.current.clearKb("notes");
  });
  expect(result.current.historyByKb).toEqual({});
  expect(readPersisted().byKb).toEqual({});

  act(() => {
    result.current.removeKb("already-gone");
    result.current.clearKb("already-gone");
  });
  expect(result.current.historyByKb).toEqual({});
});

it("re-reads the store when another tab writes it and ignores unrelated keys", () => {
  const { result } = renderHook(() => useKnowledgeHistory());
  const external = {
    byKb: {
      shared: [{ ...makeEntry({ taskId: "task-9" }), id: "task-9:2000" }],
    },
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(external));
  act(() => {
    window.dispatchEvent(
      new StorageEvent("storage", { key: "unrelated:key" }),
    );
  });
  expect(result.current.historyByKb.shared).toBeUndefined();
  act(() => {
    window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
  });
  expect(result.current.historyByKb.shared).toHaveLength(1);
  expect(result.current.historyByKb.shared[0].taskId).toBe("task-9");
});
