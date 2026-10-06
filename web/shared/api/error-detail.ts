/**
 * Shared parser for the backend's error envelope.
 *
 * FastAPI answers refusals with `{"detail": ...}`, where `detail` is either a
 * plain string or a structured `{code, message}` object (the shape the
 * per-user routes use so the client can render its own copy). Every call site
 * used to re-implement that walk by hand; two of them stringified the object
 * and reached the UI as "[object Object]". These helpers are the single place
 * that knows the shape; call sites keep their own fallback copy.
 */

export interface ErrorDetail {
  /** Machine-readable reason (`detail.code`), or `""` when none was sent. */
  code: string;
  /** Human-readable text (`detail.message` or the string form), or `""`. */
  message: string;
}

/**
 * Coerce a wire value into a usable error code: only non-empty strings pass
 * through, everything else (numbers, objects, null) collapses to `""` so a
 * malformed payload can never reach a UI mapping as raw JSON.
 */
export function normalizeErrorCode(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

/**
 * Extract `{code, message}` from a parsed response body's `detail`.
 *
 * Returns empty strings for anything the body does not carry — the caller
 * decides what fallback copy to show. A plain-string `detail` lands in
 * `message` verbatim; a structured one is read field by field, and a
 * non-string `code`/`message` is treated as absent rather than stringified.
 */
export function parseErrorDetail(body: unknown): ErrorDetail {
  if (!body || typeof body !== "object") return { code: "", message: "" };
  const detail = (body as Record<string, unknown>).detail;
  if (typeof detail === "string")
    return { code: "", message: detail.trim() ? detail : "" };
  if (!detail || typeof detail !== "object")
    return { code: "", message: "" };
  const shaped = detail as Record<string, unknown>;
  return {
    code: normalizeErrorCode(shaped.code),
    message:
      typeof shaped.message === "string" && shaped.message.trim()
        ? shaped.message
        : "",
  };
}
