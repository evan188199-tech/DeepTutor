/**
 * Low-level file reading helpers. Claude Code transcripts inline base64 images
 * and can reach tens of MB, so we never load a whole file as one string —
 * {@link iterLines} streams it line by line.
 */

/** Yield a blob's text content one line at a time (newline-delimited). */
export async function* iterLines(blob: Blob): AsyncGenerator<string> {
  const reader = blob.stream().getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl = buffer.indexOf("\n");
      while (nl !== -1) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if (line) yield line;
        nl = buffer.indexOf("\n");
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) yield buffer;
  } finally {
    reader.releaseLock();
  }
}

/** Read just the first `maxBytes` of a file as text (cheap scan-time peek). */
export async function readHead(file: File, maxBytes: number): Promise<string> {
  return file.slice(0, maxBytes).text();
}

/** Parse newline-delimited JSON, skipping blank, unparsable, or non-object
 *  rows (e.g. the truncated last line from a head read, or a literal `null`
 *  row in a corrupt file — callers treat every row as a record, so a non-
 *  object value must not leak through and crash them). */
export function parseJsonl(text: string): unknown[] {
  const out: unknown[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const value: unknown = JSON.parse(trimmed);
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        // corrupt row (parses but is not a record) — skip
        continue;
      }
      out.push(value);
    } catch {
      // partial/corrupt row — skip
    }
  }
  return out;
}
