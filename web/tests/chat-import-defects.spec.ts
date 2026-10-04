import { File as NodeFile } from "node:buffer";
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { parseClaudeSession, scanClaude } from "@/lib/chat-import/claude-code";
import { parseCodexSession } from "@/lib/chat-import/codex";
import type { SessionRef } from "@/lib/chat-import/types";

/**
 * Regression tests for corrupt/truncated transcript tolerance in the chat
 * export/import pipeline: a JSONL row that parses but is not an object
 * (e.g. literal `null`) must be skipped like any other bad row, never abort
 * a whole folder scan or parse, and never hide the well-formed rows around
 * it. Paired with the non-object guards in `parseJsonl` and the parse loops.
 */

function fixture(name: string): string {
  return readFileSync(
    path.join(process.cwd(), "tests", "fixtures", "chat-import", name),
    "utf-8",
  );
}

function fileHandle(
  name: string,
  jsonl: string,
  lastModified: number,
): FileSystemFileHandle {
  const file = new NodeFile([jsonl], name, { lastModified });
  return {
    kind: "file",
    name,
    getFile: async () => file as unknown as File,
  } as unknown as FileSystemFileHandle;
}

function dirHandle(
  name: string,
  entries: Array<FileSystemFileHandle | FileSystemDirectoryHandle>,
): FileSystemDirectoryHandle {
  const lookup = new Map(entries.map((entry) => [entry.name, entry]));
  return {
    kind: "directory",
    name,
    getDirectoryHandle: async (child: string) => {
      const hit = lookup.get(child);
      if (!hit || hit.kind !== "directory") {
        throw new DOMException("not found", "NotFoundError");
      }
      return hit as FileSystemDirectoryHandle;
    },
    async *values() {
      for (const entry of entries) yield entry;
    },
  } as unknown as FileSystemDirectoryHandle;
}

function refFrom(handle: FileSystemFileHandle, overrides: Partial<SessionRef> = {}): SessionRef {
  return {
    externalId: handle.name.replace(/\.jsonl$/, ""),
    provisionalTitle: "",
    cwd: "",
    date: "2026-06-25",
    lastModified: 0,
    sizeBytes: 0,
    handle,
    ...overrides,
  };
}

const PROJECT_DIR = "-home-user-work-demo";
const T_NEW = Date.parse("2026-06-25T12:00:00Z");

describe("corrupt/truncated transcript tolerance", () => {
  // A JSONL row whose text is valid JSON but not an object (e.g. `null`)
  // must be skipped like any other bad row — it must not abort the whole
  // folder scan.
  it("scan survives a non-object row in a session head", async () => {
    const root = dirHandle("root", [
      dirHandle("projects", [
        dirHandle(PROJECT_DIR, [
          fileHandle(
            "session-corrupt.jsonl",
            fixture("claude-corrupt-rows.jsonl"),
            T_NEW,
          ),
        ]),
      ]),
    ]);

    const groups = await scanClaude(root);
    expect(groups).toHaveLength(1);
    expect(groups[0].sessions.map((s) => s.externalId)).toEqual([
      "session-corrupt",
    ]);
  });

  // Same contract for the parse pass: bad rows are skipped, every good row
  // (including after the corrupt one) still lands in the transcript.
  it("parse keeps all wellformed rows around corrupt and truncated ones", async () => {
    const handle = fileHandle(
      "session-corrupt.jsonl",
      fixture("claude-corrupt-rows.jsonl"),
      T_NEW,
    );

    const parsed = await parseClaudeSession(refFrom(handle));
    expect(parsed?.messages.map((m) => m.content)).toEqual([
      "first question",
      "first answer",
    ]);
  });

  it("codex parse keeps all wellformed rows around corrupt and truncated ones", async () => {
    const handle = fileHandle(
      "rollout-corrupt.jsonl",
      fixture("codex-corrupt-rows.jsonl"),
      T_NEW,
    );

    const parsed = await parseCodexSession(
      refFrom(handle, { externalId: "codex-corrupt-1" }),
    );
    expect(parsed?.messages.map((m) => m.content)).toEqual([
      "codex question",
      "codex answer",
    ]);
  });
});
