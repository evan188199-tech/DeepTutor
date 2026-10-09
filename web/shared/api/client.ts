import { ApiError, type AppError, type AppErrorScope } from "./errors";
import { browserReturnPath, loginHref } from "../auth/return-url";
import { scopedUrl } from "@/lib/workspace-scope";

export interface RequestOptions extends RequestInit {
  scope?: AppErrorScope;
  skipAuthRedirect?: boolean;
}

let runtimeAuthEnabled = false;

export function apiUrl(path: string): string {
  return scopedUrl(path);
}

export function wsUrl(path: string): string {
  return scopedUrl(path);
}

export function parseAuthEnabled(raw: string | undefined): boolean {
  return /^(1|true|yes|on)$/i.test((raw ?? "").trim());
}

export function setRuntimeAuthEnabled(enabled: boolean): void {
  runtimeAuthEnabled = enabled;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit & { skipAuthRedirect?: boolean },
): Promise<Response> {
  const { skipAuthRedirect, ...fetchInit } = init ?? {};
  const scopedInput = typeof input === "string" ? scopedUrl(input)
    : input instanceof URL ? new URL(scopedUrl(input.toString()))
    : new Request(scopedUrl(input.url), input);
  const response = await fetch(scopedInput, { credentials: "include", ...fetchInit });

  if (
    response.status === 401 &&
    runtimeAuthEnabled &&
    !skipAuthRedirect &&
    typeof window !== "undefined"
  ) {
    window.location.href = loginHref(browserReturnPath(window.location));
    return new Promise(() => {});
  }

  return response;
}

function correlationId(response: Response): string | undefined {
  return (
    response.headers.get("x-correlation-id") ??
    response.headers.get("x-request-id") ??
    undefined
  );
}

/** Longest error text shown to users; server prose beyond this is logs, not a toast. */
export const API_ERROR_MESSAGE_LIMIT = 200;

/**
 * Stable, user-facing wording for backend error codes that travel in HTTP
 * error envelopes, following the CODE_MESSAGES pattern of
 * `web/lib/book-errors.ts`. The raw backend `detail` is prose written for
 * whoever reads the logs; relaying it verbatim put it in ~250 toast and
 * banner call sites. The code is the stable part of the contract, so the
 * wording belongs here.
 */
const CODE_MESSAGES: Record<string, string> = {
  worker_lost: "The assistant worker stopped unexpectedly. Please try again.",
  knowledge_task_failed:
    "Background learning failed before finishing. Try starting it again.",
  knowledge_task_interrupted:
    "Background learning was interrupted. Try starting it again.",
};

/** The codes this module has wording for — exported for the test to assert on. */
export const KNOWN_API_ERROR_CODES = Object.keys(CODE_MESSAGES);

/** Stable per-status wording used when no code mapping applies. */
const STATUS_MESSAGES: Record<number, string> = {
  400: "The request was rejected.",
  401: "Please sign in again.",
  403: "You do not have access to this.",
  404: "This was not found. Refresh and try again.",
  409: "This conflicts with the current state. Refresh and try again.",
  413: "The upload is too large.",
  422: "The request was invalid.",
  429: "Too many requests. Wait a moment and try again.",
  500: "The server hit an unexpected error. Try again.",
  502: "The server is unreachable. Try again shortly.",
  503: "The server is unavailable. Try again shortly.",
  504: "The server took too long to respond. Try again.",
};

function truncateForDisplay(text: string): string {
  const trimmed = text.trim();
  return trimmed.length <= API_ERROR_MESSAGE_LIMIT
    ? trimmed
    : `${trimmed.slice(0, API_ERROR_MESSAGE_LIMIT - 3)}...`;
}

/**
 * The message to show a user for a failed response.
 *
 * Structured envelopes carry a curated top-level `message`; it stays. FastAPI's
 * `detail` (string or `detail.message`) never reaches the user: known codes map
 * to stable wording, everything else falls back to per-status copy. The dropped
 * detail goes to the console so debugging keeps the server's own text.
 */
function userFacingMessage(
  body: unknown,
  fallback: string,
  code: string,
  status: number,
): string {
  const value =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const nestedDetail =
    value.detail && typeof value.detail === "object"
      ? (value.detail as Record<string, unknown>)
      : {};

  const structuredMessage =
    typeof value.message === "string" && value.message.trim()
      ? value.message
      : undefined;
  const rawDetail =
    typeof value.detail === "string" && value.detail.trim()
      ? value.detail
      : typeof nestedDetail.message === "string" &&
          nestedDetail.message.trim()
        ? nestedDetail.message
        : undefined;

  const stable =
    (code && CODE_MESSAGES[code]) || STATUS_MESSAGES[status] || fallback;
  const chosen = structuredMessage ?? stable;

  if (rawDetail && rawDetail.trim() !== chosen.trim()) {
    console.warn(
      "[api] server error detail:",
      rawDetail,
      `(code=${code || "none"} status=${status})`,
    );
  }

  return truncateForDisplay(chosen);
}

function normalizedHttpError(
  response: Response,
  body: unknown,
  scope: AppErrorScope,
): AppError {
  const value =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const detail =
    value.detail && typeof value.detail === "object"
      ? (value.detail as Record<string, unknown>)
      : {};
  let retryable: boolean;
  if (typeof value.retryable === "boolean") {
    retryable = value.retryable;
  } else if (typeof detail.retryable === "boolean") {
    retryable = detail.retryable;
  } else {
    retryable =
      response.status === 408 ||
      response.status === 429 ||
      response.status >= 500;
  }
  const code =
    (typeof value.error_code === "string" && value.error_code) ||
    (typeof detail.error_code === "string" && detail.error_code) ||
    `http_${response.status}`;
  return {
    code,
    message: userFacingMessage(
      body,
      response.statusText || "Request failed",
      code,
      response.status,
    ),
    retryable,
    scope,
    correlationId:
      (typeof value.correlation_id === "string" && value.correlation_id) ||
      correlationId(response),
    status: response.status,
  };
}

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

async function performRequest(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<{ response: Response; body: unknown }> {
  const { scope = "network", ...init } = options;
  try {
    const response = await apiFetch(input, init);
    const body = await responseBody(response);
    if (!response.ok)
      throw new ApiError(normalizedHttpError(response, body, scope));
    return { response, body };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      {
        code: aborted ? "request_aborted" : "network_error",
        message: aborted
          ? "Request was cancelled"
          : "Unable to reach the server",
        retryable: !aborted,
        scope,
      },
      { cause: error },
    );
  }
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<T> {
  const { response, body } = await performRequest(input, options);
  if (body === undefined || typeof body === "string") {
    throw new ApiError({
      code: "invalid_response",
      message: "The server returned an invalid JSON response",
      retryable: true,
      scope: options.scope ?? "network",
      correlationId: correlationId(response),
      status: response.status,
    });
  }
  return body as T;
}

export async function requestVoid(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<void> {
  await performRequest(input, options);
}

export async function requestBlob(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<Blob> {
  const { scope = "network", ...init } = options;
  try {
    const response = await apiFetch(input, init);
    if (!response.ok) {
      const body = await responseBody(response);
      throw new ApiError(normalizedHttpError(response, body, scope));
    }
    return await response.blob();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      {
        code: aborted ? "request_aborted" : "network_error",
        message: aborted
          ? "Request was cancelled"
          : "Unable to reach the server",
        retryable: !aborted,
        scope,
      },
      { cause: error },
    );
  }
}

/**
 * Parse a response, throwing a stable message on failure.
 *
 * The backend's raw `detail` used to become the thrown message and reached
 * toasts verbatim; it now goes to the console, and the thrown message comes
 * from the error-code wording table (or a stable status fallback). Callers
 * wanting structured refusals (an error code, a log tail) parse the body
 * themselves.
 */
export async function asJsonOrThrow(response: Response): Promise<any> {
  if (!response.ok) {
    let code = "";
    let rawDetail = "";
    try {
      const body = await response.json();
      if (body && typeof body === "object") {
        const value = body as Record<string, unknown>;
        if (typeof value.error_code === "string") code = value.error_code;
        if (typeof value.detail === "string") rawDetail = value.detail;
      }
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    if (rawDetail) {
      console.warn(
        "[api] server error detail:",
        rawDetail,
        `(code=${code || "none"} status=${response.status})`,
      );
    }
    throw new Error(
      truncateForDisplay(
        (code && CODE_MESSAGES[code]) ||
          STATUS_MESSAGES[response.status] ||
          `${response.status} ${response.statusText}`,
      ),
    );
  }
  return response.json();
}
