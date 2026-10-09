import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMemoryRun, type RunHandle } from "@/components/memory/useMemoryRun";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  readRaw: vi.fn(),
  writeRaw: vi.fn(),
  removeRaw: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));

vi.mock("@/shared/storage", () => ({
  browserStorage: {
    readRaw: (...args: unknown[]) => mocks.readRaw(...args),
    writeRaw: (...args: unknown[]) => mocks.writeRaw(...args),
    removeRaw: (...args: unknown[]) => mocks.removeRaw(...args),
  },
}));

vi.mock("i18next", () => ({
  default: { t: (key: string) => key },
}));

const encoder = new TextEncoder();

type ReadResult = { value: Uint8Array | undefined; done: boolean };

/** Manually stepped SSE body so tests observe intermediate hook states. */
class ManualStream {
  private queue: Uint8Array[] = [];
  private pending: ((result: ReadResult) => void) | null = null;
  private closed = false;

  getReader() {
    return { read: () => this.read() };
  }

  private read(): Promise<ReadResult> {
    if (this.queue.length > 0) {
      return Promise.resolve({ value: this.queue.shift(), done: false });
    }
    if (this.closed) {
      return Promise.resolve({ value: undefined, done: true });
    }
    return new Promise((resolve) => {
      this.pending = resolve;
    });
  }

  push(frame: unknown) {
    const chunk = encoder.encode(`data: ${JSON.stringify(frame)}\n\n`);
    if (this.pending) {
      const resolve = this.pending;
      this.pending = null;
      resolve({ value: chunk, done: false });
      return;
    }
    this.queue.push(chunk);
  }

  end() {
    this.closed = true;
    if (this.pending) {
      const resolve = this.pending;
      this.pending = null;
      resolve({ value: undefined, done: true });
    }
  }
}

function runHandle(overrides: Partial<RunHandle> = {}): RunHandle {
  return {
    id: "run-1",
    layer: "L2",
    key: "doc-1",
    mode: "update",
    status: "running",
    started_at: "2026-10-09T00:00:00Z",
    ended_at: null,
    error: null,
    event_count: 0,
    undo_count: 0,
    ...overrides,
  };
}

function jsonResponse(value: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => value,
    text: async () => JSON.stringify(value),
  };
}

function errorResponse(status: number, body: string) {
  return {
    ok: false,
    status,
    json: async () => ({}),
    text: async () => body,
  };
}

function streamResponse(stream: ManualStream) {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    text: async () => "",
    body: { getReader: () => stream.getReader() },
  };
}

const RUN_URL = "/api/memory/runs/run-1";
const EVENTS_URL = "/api/memory/runs/run-1/events?since=0";
const START_URL = "/api/memory/runs/start";
const PERSISTED_KEY = "dt:memory:active-run:L2:doc-1";

let streams: ManualStream[];

beforeEach(() => {
  streams = [];
  mocks.readRaw.mockReturnValue(null);
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/api/memory/runs?layer=")) {
      return jsonResponse({ runs: [] });
    }
    throw new Error(`unexpected apiFetch: ${url}`);
  });
});

afterEach(() => {
  cleanup();
  for (const stream of streams) stream.end();
});

function openStream(): ManualStream {
  const stream = new ManualStream();
  streams.push(stream);
  return stream;
}

function callsTo(predicate: (url: string) => boolean): number {
  return mocks.fetch.mock.calls.filter(([input]) =>
    predicate(String(input)),
  ).length;
}

it("stays idle on mount when nothing is persisted and the server has no active run", async () => {
  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("idle"));
  expect(callsTo((url) => url.includes("/api/memory/runs?layer="))).toBe(1);
  expect(result.current.run).toBeNull();
  expect(result.current.events).toEqual([]);
  expect(result.current.error).toBeNull();
  expect(result.current.isRunning).toBe(false);
  expect(mocks.writeRaw).not.toHaveBeenCalled();
});

it("re-attaches to a persisted running run on mount and finishes through its terminal event", async () => {
  mocks.readRaw.mockReturnValue("run-1");
  const stream = openStream();
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("running"));
  expect(result.current.run).toMatchObject({ id: "run-1", status: "running" });

  act(() => {
    stream.push({ seq: 0, ts: "t0", stage: "scanning" });
    stream.push({ seq: 1, ts: "t1", stage: "run_ended", status: "done" });
  });
  await waitFor(() => expect(result.current.status).toBe("done"));
  expect(result.current.events.map((event) => event.seq)).toEqual([0, 1]);
  expect(result.current.isRunning).toBe(false);
  expect(mocks.removeRaw).toHaveBeenCalledWith("local", PERSISTED_KEY);
});

it("adopts an active server run when nothing is persisted", async () => {
  const stream = openStream();
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/api/memory/runs?layer=")) {
      return jsonResponse({
        runs: [runHandle({ id: "run-1", status: "queued" })],
      });
    }
    if (url === RUN_URL) return jsonResponse(runHandle({ status: "queued" }));
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("queued"));
  expect(result.current.isRunning).toBe(true);
  expect(mocks.writeRaw).toHaveBeenCalledWith(
    "local",
    PERSISTED_KEY,
    "run-1",
  );
  act(() =>
    stream.push({ seq: 0, ts: "t0", stage: "run_ended", status: "done" }),
  );
  await waitFor(() => expect(result.current.status).toBe("done"));
});

it("start posts the run request, persists the id, and streams events to done in order", async () => {
  const stream = openStream();
  let startInit: RequestInit | undefined;
  mocks.fetch.mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url === START_URL) {
      startInit = init;
      return jsonResponse(runHandle());
    }
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("idle"));

  let startPromise: Promise<void> | undefined;
  act(() => {
    startPromise = result.current.start({ mode: "update", budget: 5 });
  });
  expect(result.current.status).toBe("queued");
  expect(result.current.isRunning).toBe(true);

  await waitFor(() => expect(result.current.status).toBe("running"));
  expect(startInit?.method).toBe("POST");
  expect(String(startInit?.body)).toContain('"mode":"update"');
  expect(mocks.writeRaw).toHaveBeenCalledWith(
    "local",
    PERSISTED_KEY,
    "run-1",
  );
  expect(result.current.events).toEqual([]);

  act(() => stream.push({ seq: 0, ts: "t0", stage: "scanning" }));
  await waitFor(() => expect(result.current.events).toHaveLength(1));
  expect(result.current.status).toBe("running");

  act(() =>
    stream.push({
      seq: 1,
      ts: "t1",
      stage: "run_ended",
      status: "done",
      undo_depth: 2,
    }),
  );
  act(() => stream.end());
  await waitFor(() => expect(result.current.status).toBe("done"));
  await act(async () => {
    await startPromise;
  });
  expect(result.current.run).toMatchObject({ status: "done", undo_count: 2 });
  expect(result.current.events.map((event) => event.seq)).toEqual([0, 1]);
  expect(result.current.isRunning).toBe(false);
  expect(mocks.removeRaw).toHaveBeenCalledWith("local", PERSISTED_KEY);
});

it("marks the run failed with the server detail when start is rejected", async () => {
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === START_URL) return errorResponse(409, "run already active");
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("idle"));

  await act(async () => {
    await result.current.start({ mode: "audit" });
  });
  expect(result.current.status).toBe("error");
  expect(result.current.error).toBe("run already active");
  expect(result.current.isRunning).toBe(false);
  expect(mocks.writeRaw).not.toHaveBeenCalled();
});

it("reconciles the run handle after a stream failure and keeps the surfaced error", async () => {
  mocks.readRaw.mockReturnValue("run-1");
  let runFetches = 0;
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === RUN_URL) {
      runFetches += 1;
      return jsonResponse(
        runHandle({ status: runFetches > 1 ? "done" : "running" }),
      );
    }
    if (url === EVENTS_URL) throw new Error("stream broke");
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("done"));
  expect(result.current.error).toBe("stream broke");
  // one handle fetch for the persisted-run mount check, one for the attach
  // prelude, one for the post-failure reconcile
  expect(runFetches).toBe(3);
  expect(result.current.run).toMatchObject({ status: "done" });
  expect(result.current.isRunning).toBe(false);
  expect(mocks.removeRaw).toHaveBeenCalledWith("local", PERSISTED_KEY);
});

it("reports an unavailable run when reconciliation finds it gone", async () => {
  mocks.readRaw.mockReturnValue("run-1");
  let runFetches = 0;
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === RUN_URL) {
      runFetches += 1;
      // mount verify and attach prelude succeed, the later reconcile 404s
      return runFetches === 3
        ? errorResponse(404, "not found")
        : jsonResponse(runHandle());
    }
    if (url === EVENTS_URL) throw new Error("stream broke");
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.error).toBe("memory run is no longer available");
  expect(runFetches).toBe(3);
  expect(result.current.run).toMatchObject({ status: "running" });
  expect(mocks.removeRaw).toHaveBeenCalledWith("local", PERSISTED_KEY);
});

it("dedupes repeated event sequences and drops stale out-of-order events", async () => {
  mocks.readRaw.mockReturnValue("run-1");
  const stream = openStream();
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("running"));

  act(() => {
    stream.push({ seq: 5, ts: "t5", stage: "scanning" });
    stream.push({ seq: 5, ts: "t5", stage: "scanning" });
    stream.push({ seq: 2, ts: "t2", stage: "scanning" });
    stream.push({ seq: 6, ts: "t6", stage: "scanning" });
  });
  await waitFor(() => expect(result.current.events).toHaveLength(2));
  expect(result.current.events.map((event) => event.seq)).toEqual([5, 6]);

  act(() =>
    stream.push({ seq: 7, ts: "t7", stage: "run_ended", status: "done" }),
  );
  await waitFor(() => expect(result.current.status).toBe("done"));
  expect(result.current.events).toHaveLength(3);
});

it("cancel posts to the active run endpoint and is a no-op without a run", async () => {
  const stream = openStream();
  const cancelCalls: string[] = [];
  mocks.fetch.mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/memory/runs/run-1/cancel") {
      cancelCalls.push(String(init?.method));
      return jsonResponse({ ok: true });
    }
    if (url === START_URL) return jsonResponse(runHandle());
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("idle"));
  await act(async () => {
    await result.current.cancel();
  });
  expect(cancelCalls).toEqual([]);

  let startPromise: Promise<void> | undefined;
  act(() => {
    startPromise = result.current.start({ mode: "update" });
  });
  await waitFor(() => expect(result.current.run).not.toBeNull());
  act(() => {
    stream.push({ seq: 0, ts: "t0", stage: "run_ended", status: "done" });
    stream.end();
  });
  await act(async () => {
    await startPromise;
  });

  await act(async () => {
    await result.current.cancel();
  });
  expect(cancelCalls).toEqual(["POST"]);
});

it("clear resets the state machine to idle and drops the persisted run id", async () => {
  mocks.readRaw.mockReturnValue("run-1");
  const stream = openStream();
  mocks.fetch.mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) return streamResponse(stream);
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  const { result } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("running"));
  expect(result.current.run).not.toBeNull();

  act(() => result.current.clear());
  expect(result.current.status).toBe("idle");
  expect(result.current.run).toBeNull();
  expect(result.current.events).toEqual([]);
  expect(result.current.error).toBeNull();
  expect(result.current.isRunning).toBe(false);
  expect(mocks.removeRaw).toHaveBeenCalledWith("local", PERSISTED_KEY);
  stream.end();
});

it("guards mount recovery against duplicate runs on parent re-renders and resets on key change", async () => {
  const { result, rerender } = renderHook(
    ({ layer, docKey }: { layer: "L2" | "L3"; docKey: string }) =>
      useMemoryRun(layer, docKey),
    { initialProps: { layer: "L2" as const, docKey: "doc-1" } },
  );
  await waitFor(() => expect(result.current.status).toBe("idle"));
  expect(callsTo((url) => url.endsWith("key=doc-1"))).toBe(1);

  rerender({ layer: "L2", docKey: "doc-1" });
  rerender({ layer: "L2", docKey: "doc-1" });
  expect(callsTo((url) => url.endsWith("key=doc-1"))).toBe(1);
  expect(result.current.status).toBe("idle");

  rerender({ layer: "L2", docKey: "doc-2" });
  await waitFor(() =>
    expect(callsTo((url) => url.endsWith("key=doc-2"))).toBe(1),
  );
  expect(result.current.status).toBe("idle");
  expect(result.current.run).toBeNull();
});

it("aborts the in-flight event stream when the hook unmounts", async () => {
  const stream = openStream();
  let eventsInit: RequestInit | undefined;
  mocks.fetch.mockImplementation(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url === RUN_URL) return jsonResponse(runHandle());
    if (url === EVENTS_URL) {
      eventsInit = init;
      return streamResponse(stream);
    }
    throw new Error(`unexpected apiFetch: ${url}`);
  });

  mocks.readRaw.mockReturnValue("run-1");
  const { result, unmount } = renderHook(() => useMemoryRun("L2", "doc-1"));
  await waitFor(() => expect(result.current.status).toBe("running"));
  expect(eventsInit).toBeDefined();
  expect((eventsInit?.signal as AbortSignal).aborted).toBe(false);

  unmount();
  expect((eventsInit?.signal as AbortSignal).aborted).toBe(true);
  stream.end();
});
