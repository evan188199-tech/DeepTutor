import assert from "node:assert/strict";
import test from "node:test";

import {
  API_ERROR_MESSAGE_LIMIT,
  asJsonOrThrow,
  KNOWN_API_ERROR_CODES,
  requestJson,
} from "../shared/api/client";
import { ApiError } from "../shared/api/errors";

function withFetch(stub: typeof fetch): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = stub;
  return () => {
    globalThis.fetch = original;
  };
}

function withConsoleWarn(): { warnings: string[]; restore: () => void } {
  const warnings: string[] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args.map(String).join(" "));
  };
  return {
    warnings,
    restore: () => {
      console.warn = original;
    },
  };
}

async function expectApiError(run: () => Promise<unknown>): Promise<ApiError> {
  try {
    await run();
  } catch (error) {
    assert.ok(error instanceof ApiError);
    return error;
  }
  assert.fail("expected an ApiError");
}

test("plain FastAPI detail strings never become the user-facing message", async () => {
  const restoreFetch = withFetch(async () =>
    Response.json({ detail: "Book not found" }, { status: 404 }),
  );
  const captured = withConsoleWarn();
  try {
    const error = await expectApiError(() => requestJson("/books/b1"));
    assert.notEqual(error.appError.message, "Book not found");
    assert.equal(error.appError.message, "This was not found. Refresh and try again.");
    assert.ok(
      captured.warnings.some((line) => line.includes("Book not found")),
      "the dropped detail is preserved on the console",
    );
  } finally {
    captured.restore();
    restoreFetch();
  }
});

test("nested detail.message is blocked like a plain detail string", async () => {
  const restoreFetch = withFetch(async () =>
    Response.json(
      { detail: { message: "Owner exited unexpectedly", retryable: false } },
      { status: 503 },
    ),
  );
  const captured = withConsoleWarn();
  try {
    const error = await expectApiError(() => requestJson("/turn"));
    assert.notEqual(error.appError.message, "Owner exited unexpectedly");
    assert.equal(error.appError.message, "The server is unavailable. Try again shortly.");
    assert.ok(
      captured.warnings.some((line) =>
        line.includes("Owner exited unexpectedly"),
      ),
    );
  } finally {
    captured.restore();
    restoreFetch();
  }
});

test("known error codes map to stable wording instead of the detail", async () => {
  const restoreFetch = withFetch(async () =>
    Response.json(
      {
        error_code: "knowledge_task_failed",
        detail: "celery worker crashed mid-task while writing chunk 7/12",
      },
      { status: 500 },
    ),
  );
  const captured = withConsoleWarn();
  try {
    const error = await expectApiError(() => requestJson("/knowledge/tasks/t1"));
    assert.equal(
      error.appError.message,
      "Background learning failed before finishing. Try starting it again.",
    );
    assert.ok(captured.warnings.some((line) => line.includes("celery worker")));
  } finally {
    captured.restore();
    restoreFetch();
  }
});

test("unmapped codes on unmapped statuses fall back to stable copy", async () => {
  const restoreFetch = withFetch(async () =>
    Response.json(
      { detail: "teapot overflowed on the console" },
      { status: 418 },
    ),
  );
  const captured = withConsoleWarn();
  try {
    const error = await expectApiError(() => requestJson("/tea"));
    assert.equal(error.appError.message, "Request failed");
    assert.ok(captured.warnings.some((line) => line.includes("teapot")));
  } finally {
    captured.restore();
    restoreFetch();
  }
});

test("the structured top-level message contract is preserved but truncated", async () => {
  const longMessage = "x".repeat(API_ERROR_MESSAGE_LIMIT + 50);
  const restoreFetch = withFetch(async () =>
    Response.json(
      { error_code: "worker_lost", message: longMessage, retryable: true },
      { status: 503 },
    ),
  );
  try {
    const error = await expectApiError(() => requestJson("/turn"));
    assert.equal(error.appError.message.length, API_ERROR_MESSAGE_LIMIT);
    assert.ok(error.appError.message.endsWith("..."));
  } finally {
    restoreFetch();
  }
});

test("asJsonOrThrow throws stable wording and moves detail to the console", async () => {
  const restoreFetch = withFetch(
    async () =>
      new Response(JSON.stringify({ detail: "Finish the active conversation." }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
  );
  const captured = withConsoleWarn();
  try {
    await assert.rejects(
      asJsonOrThrow(await globalThis.fetch("/system/update/job")),
      /conflicts with the current state/,
    );
    assert.ok(
      captured.warnings.some((line) =>
        line.includes("Finish the active conversation."),
      ),
    );
  } finally {
    captured.restore();
    restoreFetch();
  }
});

test("asJsonOrThrow maps known codes without any detail present", async () => {
  const restoreFetch = withFetch(async () =>
    Response.json({ error_code: "knowledge_task_interrupted" }, { status: 500 }),
  );
  try {
    await assert.rejects(
      asJsonOrThrow(await globalThis.fetch("/knowledge/tasks/t1")),
      /Background learning was interrupted/,
    );
  } finally {
    restoreFetch();
  }
});

test("the exported wording contract stays intentional", () => {
  assert.deepEqual(KNOWN_API_ERROR_CODES, [
    "worker_lost",
    "knowledge_task_failed",
    "knowledge_task_interrupted",
  ]);
  assert.ok(API_ERROR_MESSAGE_LIMIT >= 80 && API_ERROR_MESSAGE_LIMIT <= 300);
});
