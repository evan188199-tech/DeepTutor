import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { DEFAULT_ATTACHMENT_LIMITS } from "@/lib/attachment-limits";
import {
  DEFAULT_MAX_ATTACHMENT_BYTES,
  DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
} from "@/lib/doc-attachments";

const apiFetchMock = vi.fn<() => Promise<Response>>();
const apiUrlMock = vi.fn<(path: string) => string>((path) => path);

vi.mock("@/lib/api", () => ({
  apiFetch: () => apiFetchMock(),
  apiUrl: (path: string) => apiUrlMock(path),
}));

// attachment-limits.ts keeps the resolved policy in module-level state; a
// fresh module instance per test keeps the fetch/caching behaviour isolated.
async function loadModule() {
  return await import("@/lib/attachment-limits");
}

function policyResponse(
  body: unknown,
  { ok = true, jsonError = false } = {},
): Response {
  return {
    ok,
    json: jsonError
      ? () => Promise.reject(new SyntaxError("Unexpected token"))
      : () => Promise.resolve(body),
  } as unknown as Response;
}

beforeEach(() => {
  vi.resetModules();
  apiFetchMock.mockReset();
  apiUrlMock.mockClear();
});

it("exposes the built-in defaults before the policy fetch resolves", async () => {
  apiFetchMock.mockReturnValue(new Promise<Response>(() => {}));
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  expect(result.current).toEqual({
    maxFileBytes: DEFAULT_MAX_ATTACHMENT_BYTES,
    maxTotalBytes: DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
  });
  expect(apiUrlMock).toHaveBeenCalledWith("/api/settings/chat-attachments");
});

it("adopts backend limits once the policy fetch resolves", async () => {
  apiFetchMock.mockResolvedValue(
    policyResponse({
      effective: {
        max_file_bytes: 5 * 1024 * 1024,
        max_total_bytes: 10 * 1024 * 1024,
      },
    }),
  );
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual({
      maxFileBytes: 5 * 1024 * 1024,
      maxTotalBytes: 10 * 1024 * 1024,
    });
  });
});

it("falls back to defaults when the response is not ok", async () => {
  apiFetchMock.mockResolvedValue(policyResponse(null, { ok: false }));
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual(DEFAULT_ATTACHMENT_LIMITS);
  });
  expect(apiFetchMock).toHaveBeenCalledTimes(1);
});

it("falls back to defaults when the policy body fails to parse", async () => {
  apiFetchMock.mockResolvedValue(
    policyResponse(null, { jsonError: true }),
  );
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual(DEFAULT_ATTACHMENT_LIMITS);
  });
});

it("falls back to defaults when the per-file cap is missing or non-positive", async () => {
  for (const fileBytes of [undefined, null, 0, -1024, "20 MB"]) {
    apiFetchMock.mockResolvedValue(
      policyResponse({
        effective: {
          max_file_bytes: fileBytes as number,
          max_total_bytes: 40 * 1024 * 1024,
        },
      }),
    );
    const { useAttachmentLimits } = await loadModule();

    const { result } = renderHook(() => useAttachmentLimits());

    await waitFor(() => {
      expect(result.current).toEqual(DEFAULT_ATTACHMENT_LIMITS);
    });
  }
});

it("clamps a total cap below the per-file cap up to the per-file cap", async () => {
  apiFetchMock.mockResolvedValue(
    policyResponse({
      effective: {
        max_file_bytes: 8 * 1024 * 1024,
        max_total_bytes: 4 * 1024 * 1024,
      },
    }),
  );
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual({
      maxFileBytes: 8 * 1024 * 1024,
      maxTotalBytes: 8 * 1024 * 1024,
    });
  });
});

it("keeps a total cap that meets the per-file cap exactly", async () => {
  const fileBytes = 8 * 1024 * 1024;
  apiFetchMock.mockResolvedValue(
    policyResponse({
      effective: { max_file_bytes: fileBytes, max_total_bytes: fileBytes },
    }),
  );
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual({
      maxFileBytes: fileBytes,
      maxTotalBytes: fileBytes,
    });
  });
});

it("falls back to defaults when the fetch itself rejects", async () => {
  apiFetchMock.mockRejectedValue(new TypeError("network down"));
  const { useAttachmentLimits } = await loadModule();

  const { result } = renderHook(() => useAttachmentLimits());

  await waitFor(() => {
    expect(result.current).toEqual(DEFAULT_ATTACHMENT_LIMITS);
  });
});

it("shares one in-flight fetch across simultaneous mounts", async () => {
  let release!: (value: Response) => void;
  apiFetchMock.mockReturnValue(
    new Promise<Response>((resolve) => {
      release = resolve;
    }),
  );
  const { useAttachmentLimits } = await loadModule();

  const first = renderHook(() => useAttachmentLimits());
  const second = renderHook(() => useAttachmentLimits());

  expect(apiFetchMock).toHaveBeenCalledTimes(1);

  release(
    policyResponse({
      effective: { max_file_bytes: 1024, max_total_bytes: 2048 },
    }),
  );

  await waitFor(() => {
    expect(first.result.current).toEqual({
      maxFileBytes: 1024,
      maxTotalBytes: 2048,
    });
  });
  await waitFor(() => {
    expect(second.result.current).toEqual({
      maxFileBytes: 1024,
      maxTotalBytes: 2048,
    });
  });
});

it("reuses the cached policy for later mounts without refetching", async () => {
  apiFetchMock.mockResolvedValue(
    policyResponse({
      effective: {
        max_file_bytes: 3 * 1024 * 1024,
        max_total_bytes: 6 * 1024 * 1024,
      },
    }),
  );
  const { useAttachmentLimits } = await loadModule();

  const first = renderHook(() => useAttachmentLimits());
  await waitFor(() => {
    expect(first.result.current.maxFileBytes).toBe(3 * 1024 * 1024);
  });

  const second = renderHook(() => useAttachmentLimits());
  expect(second.result.current).toEqual({
    maxFileBytes: 3 * 1024 * 1024,
    maxTotalBytes: 6 * 1024 * 1024,
  });
  expect(apiFetchMock).toHaveBeenCalledTimes(1);
});
