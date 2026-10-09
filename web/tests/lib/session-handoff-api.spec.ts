import { afterEach, describe, expect, it, vi } from "vitest";

import { setRuntimeAuthEnabled } from "@/lib/api";
import {
  completeSessionHandoff,
  createSessionHandoff,
  exchangeSessionHandoff,
} from "@/lib/session-handoff-api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function textResponse(text: string, status = 200): Response {
  return new Response(text, {
    status,
    headers: { "Content-Type": "text/plain" },
  });
}

async function readRequest(fetchMock: ReturnType<typeof vi.fn>) {
  const [input, init] = fetchMock.mock.calls.at(-1) as [
    string,
    RequestInit & { credentials: string },
  ];
  const url = new URL(input, "http://localhost");
  return {
    url,
    init,
    body: JSON.parse(String(init.body)) as Record<string, unknown>,
  };
}

describe("createSessionHandoff", () => {
  afterEach(() => {
    setRuntimeAuthEnabled(false);
    vi.unstubAllGlobals();
  });

  it("posts the public origin and returns the handoff contract", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        code: "pair-123",
        handoff_url: "http://localhost/pair",
        expires_at: 1700000000,
        expires_in: 300,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const handoff = await createSessionHandoff("http://localhost");

    expect(handoff).toEqual({
      code: "pair-123",
      handoff_url: "http://localhost/pair",
      expires_at: 1700000000,
      expires_in: 300,
    });
    const request = await readRequest(fetchMock);
    expect(request.url.pathname).toBe("/api/auth/session-handoff");
    expect(request.init.method).toBe("POST");
    expect(request.init.headers).toEqual({
      "Content-Type": "application/json",
    });
    expect(request.body).toEqual({ public_origin: "http://localhost" });
  });

  it("rejects with the backend detail on a failed create", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "origin not allowed" }, 403)),
    );

    await expect(createSessionHandoff("http://localhost")).rejects.toThrow(
      "origin not allowed",
    );
  });

  it("falls back to the default message when the error body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => textResponse("gateway timeout", 504)),
    );

    await expect(createSessionHandoff("http://localhost")).rejects.toThrow(
      "Could not create pairing link",
    );
  });

  it("does not trigger the login redirect on a 401", async () => {
    setRuntimeAuthEnabled(true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "unauthenticated" }, 401)),
    );

    await expect(createSessionHandoff("http://localhost")).rejects.toThrow(
      "unauthenticated",
    );
  });
});

describe("exchangeSessionHandoff", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the pairing code and returns the ticket", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ticket: "ticket-abc" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(exchangeSessionHandoff("pair-123")).resolves.toBe("ticket-abc");

    const request = await readRequest(fetchMock);
    expect(request.url.pathname).toBe(
      "/api/auth/session-handoff/exchange",
    );
    expect(request.init.method).toBe("POST");
    expect(request.body).toEqual({ code: "pair-123" });
  });

  it("coerces a numeric ticket to a string", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ ticket: 424242 })),
    );

    await expect(exchangeSessionHandoff("pair-123")).resolves.toBe("424242");
  });

  it("rejects with the backend detail for an invalid code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "code expired" }, 410)),
    );

    await expect(exchangeSessionHandoff("pair-123")).rejects.toThrow(
      "code expired",
    );
  });

  it("rejects with the default message when the error body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => textResponse("nope", 500)),
    );

    await expect(exchangeSessionHandoff("pair-123")).rejects.toThrow(
      "Pairing code is invalid",
    );
  });
});

describe("completeSessionHandoff", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the ticket and resolves without a payload", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(completeSessionHandoff("ticket-abc")).resolves.toBeUndefined();

    const request = await readRequest(fetchMock);
    expect(request.url.pathname).toBe(
      "/api/auth/session-handoff/complete",
    );
    expect(request.init.method).toBe("POST");
    expect(request.body).toEqual({ ticket: "ticket-abc" });
  });

  it("rejects with the backend detail when completion fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "ticket already used" }, 409)),
    );

    await expect(completeSessionHandoff("ticket-abc")).rejects.toThrow(
      "ticket already used",
    );
  });

  it("rejects with the default message when the error body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => textResponse("conflict", 409)),
    );

    await expect(completeSessionHandoff("ticket-abc")).rejects.toThrow(
      "Pairing could not be completed",
    );
  });
});
