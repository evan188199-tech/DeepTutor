import { File as NodeFile } from "node:buffer";
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { parseChatGptExport } from "@/lib/chat-import/chatgpt";
import { parseClaudeSession } from "@/lib/chat-import/claude-code";
import { parseCodexSession } from "@/lib/chat-import/codex";
import type { SessionRef } from "@/lib/chat-import/types";

// Golden cross-source fixtures: one minimal real-format file per source,
// parsed to the exact NormalizedSession the upload would carry. Each fixture
// has one row per matrix-B edge — an image turn, a branch, an empty row — so
// the snapshots pin how every source treats them (tagged, kept-and-stripped,
// or silently dropped). Behavior-level edge cases stay in the per-source
// specs; this file freezes the cross-source shapes.

const fixture = (name: string): string =>
  fs.readFileSync(
    path.resolve(process.cwd(), "tests/fixtures/chat-import", name),
    "utf8",
  );

const LAST_MODIFIED = Date.parse("2026-06-25T12:00:00Z");

function jsonlRef(text: string, externalId: string, cwd: string): SessionRef {
  const file = new NodeFile([text], `${externalId}.jsonl`, {
    lastModified: LAST_MODIFIED,
  });
  return {
    externalId,
    provisionalTitle: "",
    cwd,
    date: "2026-06-25",
    lastModified: file.lastModified,
    sizeBytes: file.size,
    handle: {
      getFile: async () => file as unknown as File,
    } as FileSystemFileHandle,
  };
}

describe("golden chat-import fixtures (source → NormalizedSession)", () => {
  it("claude_code: text turns, image turn tagged, side-branch and empty rows dropped", async () => {
    const parsed = await parseClaudeSession(
      jsonlRef(fixture("claude-code-session.jsonl"), "session-golden-claude", ""),
    );

    expect(parsed).not.toBeNull();
    expect(parsed?.source_cwd).toBe("/workspace/project");
    expect(parsed?.messages).toHaveLength(2);
    expect(parsed?.messages[1].metadata).toEqual({ had_images: true });
    expect(parsed).toMatchSnapshot();
  });

  it("codex: text turns kept, image and empty rows silently dropped", async () => {
    const parsed = await parseCodexSession(
      jsonlRef(fixture("codex-session.jsonl"), "rollout-golden-1", ""),
    );

    expect(parsed).not.toBeNull();
    expect(parsed?.source_cwd).toBe("/workspace/project");
    expect(parsed?.messages).toHaveLength(2);
    expect(parsed?.messages.every((message) => !("metadata" in message))).toBe(
      true,
    );
    expect(parsed).toMatchSnapshot();
  });

  it("codex: a subagent branch session is skipped whole", async () => {
    const parsed = await parseCodexSession(
      jsonlRef(fixture("codex-subagent.jsonl"), "rollout-golden-2", ""),
    );

    expect(parsed).toBeNull();
  });

  it("chatgpt: active branch only, image parts stripped, empty rows dropped", () => {
    const parsed = parseChatGptExport(
      JSON.parse(fixture("chatgpt-conversations.json")) as unknown,
    );

    expect(parsed).toHaveLength(1);
    expect(parsed[0].messages.map((message) => message.content)).toEqual([
      "Differentiate x squared for me",
      "The derivative is 2x.",
      "Differentiate again for higher orders.",
    ]);
    expect(parsed).toMatchSnapshot();
  });
});
