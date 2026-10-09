import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { RuntimeStatusModel } from "@/features/runtime-status/model";

vi.mock("@/features/runtime-status/api", () => ({
  fetchRuntimeStatus: vi.fn(),
}));

type HookModule = typeof import("@/features/runtime-status/useRuntimeStatus");
type ApiModule = typeof import("@/features/runtime-status/api");

let hook: HookModule;
let api: ApiModule;

const fetchMock = () => vi.mocked(api.fetchRuntimeStatus);

function statusPayload(
  overrides: Partial<RuntimeStatusModel> = {},
): RuntimeStatusModel {
  return {
    workerId: "worker-a",
    workerCount: 2,
    coordinationMode: "redis",
    redisConfigured: true,
    redisStatus: "ok",
    leaderId: "worker-b",
    leaderHealthy: true,
    ownerTurnCount: 1,
    recoveryBacklog: 0,
    leaseTtlSeconds: 30,
    renewIntervalSeconds: 10,
    recoveryIntervalSeconds: 5,
    protocolVersion: "2.0",
    minimumWebProtocolVersion: "2.0",
    ...overrides,
  };
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: hidden ? "hidden" : "visible",
  });
}

beforeEach(async () => {
  vi.resetModules();
  api = await import("@/features/runtime-status/api");
  hook = await import("@/features/runtime-status/useRuntimeStatus");
  setHidden(false);
});

afterEach(() => {
  vi.useRealTimers();
  setHidden(false);
});

it("starts from the unavailable snapshot and fetches once on subscribe", () => {
  fetchMock().mockReturnValue(new Promise<RuntimeStatusModel>(() => {}));
  const { result } = renderHook(() => hook.useRuntimeStatus());
  expect(result.current.data).toBeNull();
  expect(result.current.health).toBe("unavailable");
  expect(result.current.error).toBeNull();
  expect(result.current.loading).toBe(true);
  expect(result.current.lastUpdated).toBeNull();
  expect(fetchMock()).toHaveBeenCalledTimes(1);
});

it("maps a successful fetch into data, health and lastUpdated", async () => {
  fetchMock().mockResolvedValue(statusPayload());
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  expect(result.current.loading).toBe(false);
  expect(result.current.error).toBeNull();
  expect(result.current.data?.workerId).toBe("worker-a");
  expect(result.current.health).toBe("healthy");
  expect(result.current.lastUpdated).not.toBeNull();
});

it("reports the error message and unavailable health when the first fetch fails", async () => {
  fetchMock().mockRejectedValue(new Error("worker offline"));
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(result.current.loading).toBe(false);
  expect(result.current.error).toBe("worker offline");
  expect(result.current.health).toBe("unavailable");
  expect(result.current.data).toBeNull();
});

it("falls back to a neutral message when the rejection is not an Error", async () => {
  fetchMock().mockRejectedValue("connection reset");
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(result.current.error).toBe("Runtime status is unavailable");
});

it("shares one in-flight request across concurrent refresh calls", async () => {
  let resolveFetch!: (value: RuntimeStatusModel) => void;
  fetchMock().mockImplementation(
    () =>
      new Promise<RuntimeStatusModel>((resolve) => {
        resolveFetch = resolve;
      }),
  );
  const { result } = renderHook(() => hook.useRuntimeStatus());
  const first = result.current.refresh();
  const second = result.current.refresh();
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  expect(second).toBe(first);
  await act(async () => {
    resolveFetch(statusPayload());
  });
  expect(result.current.data?.workerId).toBe("worker-a");
});

it("schedules the next poll 30s after a successful refresh", async () => {
  vi.useFakeTimers();
  fetchMock().mockResolvedValue(statusPayload());
  renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(29_999);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(2);
});

it("backs off exponentially after consecutive failures", async () => {
  vi.useFakeTimers();
  fetchMock()
    .mockRejectedValueOnce(new Error("boom 1"))
    .mockRejectedValueOnce(new Error("boom 2"))
    .mockResolvedValueOnce(statusPayload());
  renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4_999);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(2);
  await act(async () => {});
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9_999);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(2);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(3);
});

it("caps the retry delay at 120s after repeated failures", async () => {
  vi.useFakeTimers();
  fetchMock().mockRejectedValue(new Error("still down"));
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  for (let attempt = 0; attempt < 6; attempt += 1) {
    await act(async () => {
      await result.current.refresh();
    });
  }
  expect(fetchMock()).toHaveBeenCalledTimes(7);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(119_999);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(7);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(8);
});

it("stops polling after unmount", async () => {
  vi.useFakeTimers();
  fetchMock().mockResolvedValue(statusPayload());
  const { unmount } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(120_000);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(1);
});

it("aborts the in-flight request and pauses polling when the page hides", async () => {
  vi.useFakeTimers();
  let capturedSignal: AbortSignal | undefined;
  fetchMock().mockImplementation((signal?: AbortSignal) => {
    capturedSignal = signal;
    return new Promise<RuntimeStatusModel>(() => {});
  });
  renderHook(() => hook.useRuntimeStatus());
  expect(capturedSignal?.aborted).toBe(false);
  await act(() => {
    setHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(capturedSignal?.aborted).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(120_000);
  });
  expect(fetchMock()).toHaveBeenCalledTimes(1);
});

it.each([
  ["document visibilitychange", () => document.dispatchEvent(new Event("visibilitychange"))],
  ["window focus", () => window.dispatchEvent(new Event("focus"))],
])("refreshes when %s marks the page visible again", async (_label, fire) => {
  vi.useFakeTimers();
  setHidden(true);
  fetchMock().mockResolvedValue(statusPayload());
  renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(fetchMock()).toHaveBeenCalledTimes(1);
  await act(() => {
    setHidden(false);
    fire();
  });
  expect(fetchMock()).toHaveBeenCalledTimes(2);
});

it("does not toggle loading for manual refreshes that run after data exists", async () => {
  fetchMock().mockResolvedValueOnce(statusPayload());
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(result.current.loading).toBe(false);
  fetchMock().mockImplementation(
    () => new Promise<RuntimeStatusModel>(() => {}),
  );
  await act(async () => {
    void result.current.refresh();
  });
  expect(result.current.loading).toBe(false);
  expect(result.current.data).not.toBeNull();
});

it("keeps the last good data and recomputes health from it when a refetch fails", async () => {
  fetchMock().mockResolvedValueOnce(statusPayload({ recoveryBacklog: 2 }));
  const { result } = renderHook(() => hook.useRuntimeStatus());
  await act(async () => {});
  expect(result.current.health).toBe("recovering");
  fetchMock().mockRejectedValueOnce(new Error("refresh failed"));
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.error).toBe("refresh failed");
  expect(result.current.data?.recoveryBacklog).toBe(2);
  expect(result.current.health).toBe("recovering");
  expect(result.current.loading).toBe(false);
});
