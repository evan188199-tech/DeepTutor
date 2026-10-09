import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useKnowledgeProgress } from "@/hooks/useKnowledgeProgress";

const fixture = vi.hoisted(() => ({ t: (key: string) => key }));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));

class Socket {
  static instances: Socket[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: () => void;
  onclose?: () => void;
  close = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
}

class Stream {
  static instances: Stream[] = [];
  listeners = new Map<string, (event: { data: string }) => void>();
  addEventListener = vi.fn(
    (type: string, listener: (event: { data: string }) => void) =>
      this.listeners.set(type, listener),
  );
  emit(type: string, payload: unknown) {
    this.listeners.get(type)?.({ data: JSON.stringify(payload) });
  }
  close = vi.fn();
  constructor(public url: string) {
    Stream.instances.push(this);
  }
}

beforeEach(() => {
  Socket.instances = [];
  Stream.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("EventSource", Stream);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("settles a task with a retryable error when progress reports an error stage", () => {
  const onComplete = vi.fn();
  const onTaskSettled = vi.fn();
  const { result } = renderHook(() =>
    useKnowledgeProgress({ onComplete, onTaskSettled }),
  );
  act(() =>
    result.current.startTask({
      kbName: "papers",
      taskId: "task-1",
      kind: "upload",
      label: "Upload papers",
      initialLogs: ["Queued"],
    }),
  );
  act(() =>
    Socket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "progress",
        data: {
          task_id: "task-1",
          stage: "error",
          message: "Index failed",
          error: "boom",
          error_code: "KB_INDEX_FAILED",
          retryable: true,
        },
      }),
    }),
  );
  expect(result.current.tasksByKb.papers).toMatchObject({
    executing: false,
    error: "boom",
    errorCode: "KB_INDEX_FAILED",
    retryable: true,
  });
  expect(result.current.tasksByKb.papers.logs).toContain("Index failed");
  expect(Socket.instances[0].close).toHaveBeenCalled();
  expect(Stream.instances[0].close).toHaveBeenCalled();
  expect(onComplete).toHaveBeenCalledWith("papers");
  expect(onTaskSettled).toHaveBeenCalledTimes(1);
  expect(onTaskSettled.mock.calls[0][0]).toBe("papers");
  expect(onTaskSettled.mock.calls[0][1]).toMatchObject({
    status: "error",
    error: "boom",
  });
  expect(onTaskSettled.mock.calls[0][1].startedAt).toBeLessThanOrEqual(
    onTaskSettled.mock.calls[0][1].completedAt,
  );
});

it("surfaces the backend failure detail from a failed stream event exactly once", () => {
  const onTaskSettled = vi.fn();
  const { result } = renderHook(() => useKnowledgeProgress({ onTaskSettled }));
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-9",
      kind: "sync",
      label: "Sync",
      initialLogs: [],
    }),
  );
  const stream = Stream.instances[0];
  act(() => {
    stream.emit("failed", {
      detail: "Disk full",
      error_code: "E_DISK",
      retryable: false,
    });
    // A duplicated terminal event must not settle the task a second time.
    stream.emit("failed", {
      detail: "Disk full",
      error_code: "E_DISK",
      retryable: false,
    });
  });
  expect(result.current.tasksByKb.kb).toMatchObject({
    executing: false,
    error: "Disk full",
    errorCode: "E_DISK",
    retryable: false,
  });
  expect(stream.close).toHaveBeenCalled();
  expect(onTaskSettled).toHaveBeenCalledTimes(1);
  expect(onTaskSettled.mock.calls[0][0]).toBe("kb");
  expect(onTaskSettled.mock.calls[0][1]).toMatchObject({
    error: "Disk full",
    errorCode: "E_DISK",
    executing: false,
  });
});

it("records timestamps on completion and ignores duplicate complete events", () => {
  const onComplete = vi.fn();
  const onTaskSettled = vi.fn();
  const { result } = renderHook(() =>
    useKnowledgeProgress({ onComplete, onTaskSettled }),
  );
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-2",
      kind: "create",
      label: "Create",
      initialLogs: [],
    }),
  );
  const stream = Stream.instances[0];
  act(() => stream.emit("complete", {}));
  expect(result.current.tasksByKb.kb).toMatchObject({
    executing: false,
    error: null,
  });
  expect(onComplete).toHaveBeenCalledWith("kb");
  expect(onTaskSettled).toHaveBeenCalledTimes(1);
  const settled = onTaskSettled.mock.calls[0][1];
  expect(settled.status).toBe("completed");
  expect(settled.startedAt).toBeLessThanOrEqual(settled.completedAt);
  // The closed stream's late duplicate is dropped by the source guard.
  act(() => stream.emit("complete", {}));
  expect(onTaskSettled).toHaveBeenCalledTimes(1);
  expect(onComplete).toHaveBeenCalledTimes(1);
});

it("reuses open streams when a refresh re-reports the same tracked task", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  const snapshot = {
    task_id: "kb_reindex_1",
    stage: "processing_documents",
    message: "Embedding batches: 1/3",
  };
  act(() => result.current.resumeTask("papers", snapshot));
  expect(Stream.instances).toHaveLength(1);
  expect(Socket.instances).toHaveLength(1);
  act(() => result.current.resumeTask("papers", { ...snapshot }));
  act(() => result.current.subscribeWs("papers", "kb_reindex_1"));
  expect(Stream.instances).toHaveLength(1);
  expect(Socket.instances).toHaveLength(1);
  expect(Stream.instances[0].close).not.toHaveBeenCalled();
  expect(Socket.instances[0].close).not.toHaveBeenCalled();
});

it("filters websocket traffic by the tracked task and unwraps envelopes", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-3",
      kind: "upload",
      label: "Upload",
      initialLogs: [],
    }),
  );
  const socket = Socket.instances[0];
  expect(socket.url).toContain("/kb/progress");
  expect(socket.url).toContain("task_id=task-3");
  act(() =>
    socket.onmessage?.({
      data: JSON.stringify({
        type: "progress",
        data: {
          task_id: "other",
          stage: "processing_documents",
          message: "not mine",
        },
      }),
    }),
  );
  expect(result.current.progressByKb.kb).toBeUndefined();
  expect(result.current.tasksByKb.kb.logs).toEqual([]);
  act(() =>
    socket.onmessage?.({
      data: JSON.stringify({
        type: "progress",
        data: { task_id: "task-3", stage: "parsing", message: "Parsing" },
      }),
    }),
  );
  expect(result.current.progressByKb.kb).toMatchObject({ stage: "parsing" });
  expect(result.current.tasksByKb.kb.logs).toEqual(["Parsing"]);
});

it("ignores malformed websocket payloads without corrupting state", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-4",
      kind: "upload",
      label: "Upload",
      initialLogs: ["Queued"],
    }),
  );
  const socket = Socket.instances[0];
  act(() => {
    socket.onmessage?.({ data: "not-json" });
    socket.onmessage?.({ data: "null" });
    socket.onmessage?.({ data: "{}" });
  });
  expect(result.current.tasksByKb.kb.executing).toBe(true);
  expect(result.current.tasksByKb.kb.logs).toEqual(["Queued"]);
});

it("reconnects with exponential backoff after a socket loss", () => {
  vi.useFakeTimers();
  try {
    const { result, unmount } = renderHook(() => useKnowledgeProgress());
    act(() => result.current.subscribeWs("papers", "task-5"));
    expect(Socket.instances).toHaveLength(1);
    act(() => Socket.instances[0].onclose?.());
    act(() => vi.advanceTimersByTime(499));
    expect(Socket.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(Socket.instances).toHaveLength(2);
    // Second failure doubles the delay to 1000ms before the next attempt.
    const second = Socket.instances[1];
    act(() => second.onclose?.());
    act(() => vi.advanceTimersByTime(999));
    expect(Socket.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(Socket.instances).toHaveLength(3);
    // Unmount closes live sockets and cancels any pending retry timer.
    unmount();
    expect(Socket.instances.map((s) => s.close)).toEqual([
      expect.anything(),
      expect.anything(),
      expect.anything(),
    ]);
  } finally {
    vi.useRealTimers();
  }
});

it("dismisses a task and drops late events from its closed connections", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-6",
      kind: "retry",
      label: "Retry",
      initialLogs: [],
    }),
  );
  const socket = Socket.instances[0];
  const stream = Stream.instances[0];
  act(() => result.current.dismissTask("kb"));
  expect(result.current.tasksByKb.kb).toBeUndefined();
  expect(socket.close).toHaveBeenCalled();
  expect(stream.close).toHaveBeenCalled();
  act(() => {
    socket.onmessage?.({
      data: JSON.stringify({ stage: "completed", task_id: "task-6" }),
    });
    stream.emit("complete", {});
  });
  expect(result.current.tasksByKb.kb).toBeUndefined();
});

it("cleans up progress and tracked state so a later refresh starts fresh", () => {
  const { result } = renderHook(() => useKnowledgeProgress());
  act(() =>
    result.current.startTask({
      kbName: "kb",
      taskId: "task-7",
      kind: "upload",
      label: "Upload",
      initialLogs: [],
    }),
  );
  act(() =>
    Socket.instances[0].onmessage?.({
      data: JSON.stringify({
        type: "progress",
        data: { task_id: "task-7", stage: "parsing" },
      }),
    }),
  );
  expect(result.current.progressByKb.kb).toBeDefined();
  act(() => result.current.cleanupKb("kb"));
  expect(result.current.progressByKb.kb).toBeUndefined();
  expect(result.current.tasksByKb.kb).toBeUndefined();
  expect(Socket.instances[0].close).toHaveBeenCalled();
  expect(Stream.instances[0].close).toHaveBeenCalled();
  // A refresh for the same task opens fresh streams again.
  act(() =>
    result.current.resumeTask("kb", {
      task_id: "task-7",
      stage: "processing_documents",
    }),
  );
  expect(Stream.instances).toHaveLength(2);
  expect(Socket.instances).toHaveLength(2);
});
