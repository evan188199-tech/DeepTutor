import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBinarySource } from "@/components/chat/preview/previewers/useBinarySource";
import { useTextSource } from "@/components/chat/preview/previewers/useTextSource";
import { apiFetch } from "@/lib/api";

/**
 * Unit coverage for the preview source hooks (zero-triage seed).
 *
 * Both hooks drive the FilePreviewDrawer previewers through the same
 * state machine (loading → ready | error) with size guarding, stale
 * response suppression and abort-on-unmount. apiFetch is mocked at the
 * @/lib/api boundary so these tests exercise only the hooks' own
 * branching; the transport itself is covered elsewhere.
 */

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const MAX_TEXT_BYTES = 8 * 1024 * 1024;
const MAX_BINARY_BYTES = 25 * 1024 * 1024;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

interface FakeResponseInit {
  ok?: boolean;
  status?: number;
  contentLength?: string;
}

function fakeResponse(
  body: { text?: string; buffer?: ArrayBuffer },
  init: FakeResponseInit = {},
) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-length"
          ? (init.contentLength ?? null)
          : null,
    },
    text: vi.fn(async () => body.text ?? ""),
    arrayBuffer: vi.fn(async () => body.buffer ?? new ArrayBuffer(0)),
  };
}

type PreviewResponse = ReturnType<typeof fakeResponse>;

function makeBuffer(bytes: number): ArrayBuffer {
  return new ArrayBuffer(bytes);
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("useTextSource", () => {
  it("starts ready with the inline fallback text when no url is provided", () => {
    const { result } = renderHook(() =>
      useTextSource(null, "already extracted body"),
    );

    expect(result.current).toEqual({
      kind: "ready",
      text: "already extracted body",
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("reports an error when neither a url nor fallback text exists", () => {
    const { result } = renderHook(() => useTextSource(null));

    expect(result.current).toEqual({
      kind: "error",
      message: "Preview source is not available.",
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("loads the text body for the given url", async () => {
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({ text: "file body" }) as unknown as Response,
    );

    const { result } = renderHook(() => useTextSource("/api/files/1/raw"));
    expect(result.current).toEqual({ kind: "loading" });

    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(result.current).toEqual({ kind: "ready", text: "file body" });
    expect(apiFetchMock).toHaveBeenCalledWith("/api/files/1/raw", {
      signal: expect.any(AbortSignal),
    });
  });

  it("maps a non-ok response to an HTTP status error", async () => {
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({}, { ok: false, status: 404 }) as unknown as Response,
    );

    const { result } = renderHook(() => useTextSource("/api/files/missing"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({ kind: "error", message: "HTTP 404" });
  });

  it("rejects oversized bodies before reading the response", async () => {
    const response = fakeResponse(
      { text: "never read" },
      { contentLength: String(MAX_TEXT_BYTES + 1) },
    );
    apiFetchMock.mockResolvedValueOnce(response as unknown as Response);

    const { result } = renderHook(() => useTextSource("/api/logs/huge"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({
      kind: "error",
      message: "File is too large to preview as text. Use the Download button.",
    });
    expect(response.text).not.toHaveBeenCalled();
  });

  it("surfaces the message of Error rejections from the transport", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network unreachable"));

    const { result } = renderHook(() => useTextSource("/api/files/1/raw"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({
      kind: "error",
      message: "network unreachable",
    });
  });

  it("falls back to a generic message for non-Error rejections", async () => {
    apiFetchMock.mockRejectedValueOnce("boom");

    const { result } = renderHook(() => useTextSource("/api/files/1/raw"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({
      kind: "error",
      message: "Failed to load preview",
    });
  });

  it("aborts the in-flight request on unmount and ignores its late rejection", async () => {
    const pending = deferred<PreviewResponse>();
    let capturedSignal: AbortSignal | null = null;
    apiFetchMock.mockImplementationOnce(((_url: string, init?: RequestInit) => {
      capturedSignal = (init?.signal as AbortSignal) ?? null;
      return pending.promise as Promise<Response>;
    }) as typeof apiFetch);

    const { result, unmount } = renderHook(() =>
      useTextSource("/api/files/1/raw"),
    );
    expect(result.current).toEqual({ kind: "loading" });

    unmount();
    expect(capturedSignal?.aborted).toBe(true);

    await act(async () => {
      pending.reject(new Error("request aborted"));
    });
    expect(result.current).toEqual({ kind: "loading" });
  });

  it("ignores a superseded response after the url changes", async () => {
    const stale = deferred<PreviewResponse>();
    apiFetchMock.mockImplementationOnce(
      (() => stale.promise) as unknown as typeof apiFetch,
    );
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({ text: "fresh body" }) as unknown as Response,
    );

    const { result, rerender } = renderHook(
      ({ url }) => useTextSource(url),
      { initialProps: { url: "/api/files/1/raw" } },
    );
    rerender({ url: "/api/files/2/raw" });
    await waitFor(() => expect(result.current).toEqual({
      kind: "ready",
      text: "fresh body",
    }));

    await act(async () => {
      stale.resolve(fakeResponse({ text: "stale body" }));
      await stale.promise;
    });
    expect(result.current).toEqual({ kind: "ready", text: "fresh body" });
  });
});

describe("useBinarySource", () => {
  it("reports an error when no url is provided", () => {
    const { result } = renderHook(() => useBinarySource(null));

    expect(result.current).toEqual({
      kind: "error",
      message: "Preview source is not available.",
    });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("loads the response body as an ArrayBuffer", async () => {
    const buffer = makeBuffer(16);
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({ buffer }) as unknown as Response,
    );

    const { result } = renderHook(() => useBinarySource("/api/files/2/raw"));
    expect(result.current).toEqual({ kind: "loading" });

    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(result.current).toEqual({ kind: "ready", buffer });
    expect(apiFetchMock).toHaveBeenCalledWith("/api/files/2/raw", {
      signal: expect.any(AbortSignal),
    });
  });

  it("maps a non-ok response to an HTTP status error", async () => {
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({}, { ok: false, status: 500 }) as unknown as Response,
    );

    const { result } = renderHook(() => useBinarySource("/api/files/2/raw"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({ kind: "error", message: "HTTP 500" });
  });

  it("rejects oversized downloads before reading the body", async () => {
    const response = fakeResponse(
      { buffer: makeBuffer(4) },
      { contentLength: String(MAX_BINARY_BYTES + 1) },
    );
    apiFetchMock.mockResolvedValueOnce(response as unknown as Response);

    const { result } = renderHook(() => useBinarySource("/api/decks/huge"));
    await waitFor(() => expect(result.current.kind).toBe("error"));

    expect(result.current).toEqual({
      kind: "error",
      message: "File is too large to preview. Use the Download button.",
    });
    expect(response.arrayBuffer).not.toHaveBeenCalled();
  });

  it("aborts the in-flight request on unmount and ignores its late rejection", async () => {
    const pending = deferred<PreviewResponse>();
    let capturedSignal: AbortSignal | null = null;
    apiFetchMock.mockImplementationOnce(((_url: string, init?: RequestInit) => {
      capturedSignal = (init?.signal as AbortSignal) ?? null;
      return pending.promise as Promise<Response>;
    }) as typeof apiFetch);

    const { result, unmount } = renderHook(() =>
      useBinarySource("/api/files/2/raw"),
    );
    expect(result.current).toEqual({ kind: "loading" });

    unmount();
    expect(capturedSignal?.aborted).toBe(true);

    await act(async () => {
      pending.reject(new Error("request aborted"));
    });
    expect(result.current).toEqual({ kind: "loading" });
  });

  it("ignores a superseded response after the url changes", async () => {
    const stale = deferred<PreviewResponse>();
    apiFetchMock.mockImplementationOnce(
      (() => stale.promise) as unknown as typeof apiFetch,
    );
    const freshBuffer = makeBuffer(8);
    apiFetchMock.mockResolvedValueOnce(
      fakeResponse({ buffer: freshBuffer }) as unknown as Response,
    );

    const { result, rerender } = renderHook(
      ({ url }) => useBinarySource(url),
      { initialProps: { url: "/api/files/1/raw" } },
    );
    rerender({ url: "/api/files/2/raw" });
    await waitFor(() => expect(result.current).toEqual({
      kind: "ready",
      buffer: freshBuffer,
    }));

    const staleBuffer = makeBuffer(4);
    await act(async () => {
      stale.resolve(fakeResponse({ buffer: staleBuffer }));
      await stale.promise;
    });
    expect(result.current).toEqual({ kind: "ready", buffer: freshBuffer });
  });
});
