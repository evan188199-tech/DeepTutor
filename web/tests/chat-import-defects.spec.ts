import { File as NodeFile } from "node:buffer";
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { parseClaudeSession, scanClaude } from "@/lib/chat-import/claude-code";
import { parseCodexSession } from "@/lib/chat-import/codex";
import type { SessionRef } from "@/lib/chat-import/types";

/**
 * Failing tests for the chat export/import pipeline. Each case pins one
 * reproducible defect: cross-project
 * misattribution, corrupt-row tolerance, lost attachment references, and
 * messages dropped at the codex storage-layer boundary.
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

const PROJECT_DIR = "-Users-xzh-work-demo";
const T_NEW = Date.parse("2026-06-25T12:00:00Z");
const T_OLD = Date.parse("2026-06-24T12:00:00Z");

describe("claude scan: session/cwd boundary", () => {
  // One encoded projects dir can hold sessions from two real cwds (`/`, `.`
  // and `-` all encode to `-`). The newest session's cwd must not be stamped
  // onto its siblings: each ref keeps the cwd its own transcript records.
  it("keeps each session's own recorded cwd", async () => {
    const root = dirHandle("root", [
      dirHandle("projects", [
        dirHandle(PROJECT_DIR, [
          fileHandle(
            "session-new.jsonl",
            fixture("claude-demo-project.jsonl"),
            T_NEW,
          ),
          fileHandle(
            "session-old.jsonl",
            fixture("claude-demo-sub-project.jsonl"),
            T_OLD,
          ),
        ]),
      ]),
    ]);

    const groups = await scanClaude(root);

    expect(groups).toHaveLength(1);
    const byName = new Map(
      groups[0].sessions.map((s) => [s.externalId, s.cwd] as const),
    );
    expect(byName.get("session-new")).toBe("/Users/xzh/work/demo");
    expect(byName.get("session-old")).toBe("/Users/xzh/work/demo.sub");
  });

  // The parse pass must trust the transcript's own `cwd` records over a cwd
  // a sibling session's scan left on the ref — otherwise the older session is
  // imported under the wrong project and the wrong scope bucket.
  it("prefers the transcript's own cwd when parsing", async () => {
    const older = fileHandle(
      "session-old.jsonl",
      fixture("claude-demo-sub-project.jsonl"),
      T_OLD,
    );
    const parsed = await parseClaudeSession(
      refFrom(older, { cwd: "/Users/xzh/work/demo" }),
    );

    expect(parsed).not.toBeNull();
    expect(parsed?.source_cwd).toBe("/Users/xzh/work/demo.sub");
  });
});

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

describe("attachment reference consistency", () => {
  // An image-only human turn carries no text, but the adapter has an explicit
  // `had_images` marker for exactly this case — the turn (and its marker) must
  // survive so the transcript does not show the assistant answering nobody.
  it("keeps an image-only user turn with its attachment marker", async () => {
    const handle = fileHandle(
      "session-image.jsonl",
      fixture("claude-image-only.jsonl"),
      T_NEW,
    );

    const parsed = await parseClaudeSession(refFrom(handle));

    expect(parsed?.messages[0]?.role).toBe("user");
    expect(parsed?.messages[0]?.metadata).toEqual({ had_images: true });
    expect(parsed?.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
  });
});

describe("codex storage-layer message boundary", () => {
  // A rollout that switched storage layers mid-session (upgrade) carries its
  // older turns on `event_msg` and its newer turns on `response_item`. Both
  // halves are the same conversation — neither may be dropped.
  it("keeps turns from both storage layers", async () => {
    const handle = fileHandle(
      "rollout-mixed.jsonl",
      fixture("codex-mixed-layers.jsonl"),
      T_NEW,
    );

    const parsed = await parseCodexSession(
      refFrom(handle, { externalId: "codex-mixed-1" }),
    );

    expect(parsed?.messages.map((m) => m.content)).toEqual([
      "pre-upgrade question",
      "post-upgrade answer",
    ]);
  });
});
