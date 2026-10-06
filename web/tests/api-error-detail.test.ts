import assert from "node:assert/strict";
import test from "node:test";

import { asJsonOrThrow } from "@/shared/api/client";
import {
  normalizeErrorCode,
  parseErrorDetail,
} from "@/shared/api/error-detail";
import { CodexOAuthApiError, requestCodex } from "@/lib/codex-oauth";
import { getMcpSettings, McpApiError } from "@/lib/mcp-api";
import {
  normalizeReadinessSnapshot,
  type SettingsReadinessRow,
  type SettingsReadinessSnapshot,
} from "@/lib/settings-readiness";

// Node's undici Response leaves statusText "" where a browser fills
// "Internal Server Error"; build the expected status line the same way the
// production fallback does so the assertion holds in both runtimes.
function statusLine(status: number): string {
  return `${status} ${new Response(null, { status }).statusText}`;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function readinessRow(detail_code: unknown): SettingsReadinessRow {
  return {
    id: "catalog.llm",
    section: "catalog",
    label: "LLM",
    state: "misconfigured",
    detail_code: detail_code as SettingsReadinessRow["detail_code"],
    enabled: false,
    available: true,
    configured: false,
    verified: false,
    required: true,
  };
}

function readinessSnapshot(rows: SettingsReadinessRow[]): SettingsReadinessSnapshot {
  return {
    schema_version: "deeptutor.settings-readiness/v2",
    ok: true,
    summary: {
      enabled_verified: 0,
      available_disabled: 0,
      unavailable: 0,
      misconfigured: rows.length,
      not_selected: 0,
    },
    rows,
    notices: [],
  };
}

test("normalizeErrorCode passes non-empty strings and collapses everything else", () => {
  assert.equal(normalizeErrorCode("login_timeout"), "login_timeout");
  assert.equal(normalizeErrorCode(""), "");
  assert.equal(normalizeErrorCode("   "), "");
  assert.equal(normalizeErrorCode(42), "");
  assert.equal(normalizeErrorCode(null), "");
  assert.equal(normalizeErrorCode({ code: "x" }), "");
});

test("parseErrorDetail reads the structured {code, message} envelope", () => {
  assert.deepEqual(parseErrorDetail({ detail: { code: "login_timeout", message: "Login timed out." } }), {
    code: "login_timeout",
    message: "Login timed out.",
  });
});

test("parseErrorDetail treats a plain-string detail as the message", () => {
  assert.deepEqual(parseErrorDetail({ detail: "Rate limit exceeded" }), {
    code: "",
    message: "Rate limit exceeded",
  });
});

test("parseErrorDetail keeps only string code/message fields", () => {
  assert.deepEqual(
    parseErrorDetail({ detail: { code: 404, message: { text: "no" } } }),
    { code: "", message: "" },
  );
});

test("parseErrorDetail falls back to empty fields on malformed bodies", () => {
  assert.deepEqual(parseErrorDetail(null), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail("oops"), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({}), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: null }), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: "" }), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: "   " }), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: 42 }), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: [] }), { code: "", message: "" });
  assert.deepEqual(parseErrorDetail({ detail: {} }), { code: "", message: "" });
});

test("asJsonOrThrow surfaces the structured detail message instead of [object Object]", async () => {
  await assert.rejects(
    asJsonOrThrow(jsonResponse(409, { detail: { code: "name_taken", message: "That name is taken." } })),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, "That name is taken.");
      assert.equal(error.message.includes("object Object"), false);
      return true;
    },
  );
});

test("asJsonOrThrow falls back to the detail code when no message is sent", async () => {
  await assert.rejects(
    asJsonOrThrow(jsonResponse(409, { detail: { code: "name_taken" } })),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, "name_taken");
      return true;
    },
  );
});

test("asJsonOrThrow keeps the plain-string detail verbatim", async () => {
  await assert.rejects(
    asJsonOrThrow(jsonResponse(503, { detail: "Re-indexing in progress" })),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, "Re-indexing in progress");
      return true;
    },
  );
});

test("asJsonOrThrow falls back to the status line on malformed details", async () => {
  for (const body of [null, "oops", 42, { detail: null }, { detail: 42 }, {}, undefined]) {
    await assert.rejects(
      asJsonOrThrow(jsonResponse(500, body)),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(error.message, statusLine(500));
        return true;
      },
    );
  }
});

test("asJsonOrThrow passes successful responses through", async () => {
  assert.deepEqual(await asJsonOrThrow(jsonResponse(200, { ok: 1 })), { ok: 1 });
});

async function mcpErrorFrom(status: number, body: unknown): Promise<McpApiError> {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = async () => jsonResponse(status, body);
  try {
    await getMcpSettings("/api/mcp/settings");
    throw new Error("expected getMcpSettings to reject");
  } catch (error) {
    if (!(error instanceof McpApiError)) throw error;
    return error;
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
}

test("MCP refusals carry the structured code and message", async () => {
  const error = await mcpErrorFrom(409, { detail: { code: "mcp_busy", message: "Reload in progress." } });
  assert.equal(error.code, "mcp_busy");
  assert.equal(error.message, "Reload in progress.");
});

test("MCP refusals fall back to the status line without a usable detail", async () => {
  const stringDetail = await mcpErrorFrom(502, { detail: "Bad gateway" });
  assert.equal(stringDetail.code, "");
  assert.equal(stringDetail.message, "Bad gateway");

  const malformed = await mcpErrorFrom(500, { detail: 42 });
  assert.equal(malformed.code, "");
  assert.equal(malformed.message, statusLine(500));

  const noBody = await mcpErrorFrom(503, undefined);
  assert.equal(noBody.code, "");
  assert.equal(noBody.message, statusLine(503));
});

test("Codex OAuth keeps its stable defaults and applies the structured detail", async () => {
  const structured = async (): Promise<Response> =>
    jsonResponse(408, { detail: { code: "login_timeout", message: "Login timed out." } });
  await assert.rejects(
    requestCodex("/oauth/status", "GET", structured),
    (error: unknown) => {
      assert.ok(error instanceof CodexOAuthApiError);
      assert.equal(error.code, "login_timeout");
      assert.equal(error.message, "Login timed out.");
      return true;
    },
  );

  const stringDetail = async (): Promise<Response> =>
    jsonResponse(502, { detail: "Proxy exploded" });
  await assert.rejects(
    requestCodex("/oauth/status", "GET", stringDetail),
    (error: unknown) => {
      assert.ok(error instanceof CodexOAuthApiError);
      assert.equal(error.code, "http_502");
      assert.equal(error.message, "Proxy exploded");
      return true;
    },
  );

  const malformed = async (): Promise<Response> =>
    jsonResponse(500, { detail: 42 });
  await assert.rejects(
    requestCodex("/oauth/status", "GET", malformed),
    (error: unknown) => {
      assert.ok(error instanceof CodexOAuthApiError);
      assert.equal(error.code, "http_500");
      assert.equal(error.message, "Codex request failed.");
      return true;
    },
  );
});

test("readiness snapshot normalization enforces the detail_code string contract", () => {
  const normalized = normalizeReadinessSnapshot(
    readinessSnapshot([
      readinessRow("cli_missing"),
      readinessRow(null),
      readinessRow(42),
      readinessRow({ code: "x" }),
      readinessRow(""),
    ]),
  );
  assert.deepEqual(
    normalized.rows.map((row) => row.detail_code),
    ["cli_missing", "", "", "", ""],
  );
});
