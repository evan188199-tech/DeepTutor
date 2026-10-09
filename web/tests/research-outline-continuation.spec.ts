import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MessageRequestSnapshot } from "@/features/chat/ChatStateAdapter";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";

const h = vi.hoisted(() => {
  const sendMessageA = vi.fn();
  const sendMessageB = vi.fn();
  return {
    sendMessageA,
    sendMessageB,
    adapter: { sendMessage: sendMessageA },
  };
});

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => h.adapter,
}));

const outlineA = [
  { title: "Background", overview: "Why the field matters" },
  { title: "Method", overview: "How we study it" },
];

const outlineB = [{ title: "Revised", overview: "Updated plan after edits" }];

const snapshot = {
  content: "Quantum batteries",
  capability: null,
  enabledTools: ["web_search"],
  knowledgeBases: ["kb-1"],
  language: "en",
  attachments: [{ id: "att-1", name: "notes.pdf" }],
  notebookReferences: [{ notebook_id: "nb-1" }],
  historyReferences: ["turn-1"],
  questionNotebookReferences: [3],
  persona: "socratic",
  memoryReferences: ["summary"],
  bookReferences: [{ book_id: "b-1" }],
} as unknown as MessageRequestSnapshot;

function lastCall(mock: ReturnType<typeof vi.fn>) {
  expect(mock).toHaveBeenCalledTimes(1);
  return mock.mock.calls[0];
}

describe("useResearchOutlineContinuation", () => {
  it("sends the confirmed outline merged over the original config without echoing the user message", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", {
      mode: "report",
      depth: "deep",
      style: "academic",
    });

    const [content, attachments, config, , , options] = lastCall(
      h.sendMessageA,
    );
    expect(content).toBe("Quantum batteries");
    expect(attachments).toEqual([]);
    expect(config).toEqual({
      mode: "report",
      depth: "deep",
      style: "academic",
      confirmed_outline: outlineA,
    });
    expect(options).toMatchObject({
      displayUserMessage: false,
      persistUserMessage: false,
    });
    expect(options?.requestSnapshotOverride).toBeUndefined();
  });

  it("falls back to a bare config when the original research config is missing", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", null);

    const [, , config] = lastCall(h.sendMessageA);
    expect(config).toEqual({ confirmed_outline: outlineA });
  });

  it("does not mutate the caller's original config object", () => {
    const original = { mode: "report", depth: "deep" };
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", original);

    lastCall(h.sendMessageA);
    expect(original).toEqual({ mode: "report", depth: "deep" });
    expect(original).not.toHaveProperty("confirmed_outline");
  });

  it("rebuilds the request snapshot with the confirm-time topic and deep_research capability", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", { mode: "report" }, snapshot);

    const [content, , config, , , options] = lastCall(h.sendMessageA);
    expect(content).toBe("Quantum batteries");
    expect(config).toEqual({
      mode: "report",
      confirmed_outline: outlineA,
    });
    expect(options?.requestSnapshotOverride).toEqual({
      ...snapshot,
      content: "Quantum batteries",
      capability: "deep_research",
      config: { mode: "report", confirmed_outline: outlineA },
    });
  });

  it("forwards the snapshot's attachments, references, persona and memory positionally", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", null, snapshot);

    const [
      ,
      attachments,
      ,
      notebookReferences,
      historyReferences,
      options,
      questionNotebookReferences,
      persona,
      memoryReferences,
    ] = lastCall(h.sendMessageA);
    expect(attachments).toEqual(snapshot.attachments);
    expect(notebookReferences).toEqual(snapshot.notebookReferences);
    expect(historyReferences).toEqual(snapshot.historyReferences);
    expect(options).toMatchObject({
      displayUserMessage: false,
      persistUserMessage: false,
      bookReferences: snapshot.bookReferences,
    });
    expect(questionNotebookReferences).toEqual(
      snapshot.questionNotebookReferences,
    );
    expect(persona).toBe("socratic");
    expect(memoryReferences).toEqual(snapshot.memoryReferences);
  });

  it("sends plain defaults when the original snapshot is missing", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", null, null);

    const [
      ,
      attachments,
      ,
      notebookReferences,
      historyReferences,
      options,
      questionNotebookReferences,
      persona,
      memoryReferences,
    ] = lastCall(h.sendMessageA);
    expect(attachments).toEqual([]);
    expect(notebookReferences).toBeUndefined();
    expect(historyReferences).toBeUndefined();
    expect(options?.requestSnapshotOverride).toBeUndefined();
    expect(options?.bookReferences).toBeUndefined();
    expect(questionNotebookReferences).toBeUndefined();
    expect(persona).toBeUndefined();
    expect(memoryReferences).toBeUndefined();
  });

  it("re-entry after an interrupted confirm sends the revised outline, not the stale one", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", { mode: "report" }, snapshot);
    result.current(outlineB, "Quantum batteries", { mode: "report" }, snapshot);

    expect(h.sendMessageA).toHaveBeenCalledTimes(2);
    const firstConfig = h.sendMessageA.mock.calls[0][2];
    const secondConfig = h.sendMessageA.mock.calls[1][2];
    expect(firstConfig.confirmed_outline).toEqual(outlineA);
    expect(secondConfig.confirmed_outline).toEqual(outlineB);
    const secondOverride = h.sendMessageA.mock.calls[1][5]
      .requestSnapshotOverride as MessageRequestSnapshot;
    expect(secondOverride.config?.confirmed_outline).toEqual(outlineB);
  });

  it("re-entry with a new topic rewrites the snapshot content and keeps deep_research", () => {
    const { result } = renderHook(() => useResearchOutlineContinuation());

    result.current(outlineA, "Quantum batteries", null, snapshot);
    result.current(outlineA, "Quantum-dot solar cells", null, snapshot);

    const firstOverride = h.sendMessageA.mock.calls[0][5]
      .requestSnapshotOverride as MessageRequestSnapshot;
    const secondOverride = h.sendMessageA.mock.calls[1][5]
      .requestSnapshotOverride as MessageRequestSnapshot;
    expect(firstOverride.content).toBe("Quantum batteries");
    expect(secondOverride.content).toBe("Quantum-dot solar cells");
    expect(secondOverride.capability).toBe("deep_research");
  });

  it("keeps a stable callback identity across re-renders while the adapter send is stable", () => {
    const { result, rerender } = renderHook(() =>
      useResearchOutlineContinuation(),
    );
    const first = result.current;

    rerender();
    rerender();

    expect(result.current).toBe(first);
  });

  it("rebinds to the new adapter send when the surface swaps its chat adapter", () => {
    const { result, rerender } = renderHook(() =>
      useResearchOutlineContinuation(),
    );
    const first = result.current;
    expect(first).not.toBeNull();

    h.adapter.sendMessage = h.sendMessageB;
    rerender();

    const second = result.current;
    expect(second).not.toBe(first);

    second(outlineA, "Quantum batteries", null);
    expect(h.sendMessageB).toHaveBeenCalledTimes(1);
    expect(h.sendMessageA).not.toHaveBeenCalled();
  });
});
