import { File as NodeFile } from "node:buffer";

import assert from "node:assert/strict";
import test from "node:test";

import { parseClaudeSession, scanClaude } from "@/lib/chat-import/claude-code";
import type { NormalizedMessage, SessionRef } from "@/lib/chat-import/types";

const MTIME = Date.parse("2026-06-25T12:00:00Z");

function jsonlFile(records: unknown[], name = "session.jsonl"): NodeFile {
  const text = records
    .map((record) =>
      typeof record === "string" ? record : JSON.stringify(record),
    )
    .join("\n");
  return new NodeFile([text], name, { lastModified: MTIME });
}

function sessionRef(
  file: NodeFile,
  overrides: Partial<SessionRef> = {},
): SessionRef {
  return {
    externalId: "session-1",
    provisionalTitle: "",
    cwd: "/repo/alpha",
    date: "2026-06-25",
    lastModified: file.lastModified,
    sizeBytes: file.size,
    handle: {
      getFile: async () => file,
    } as unknown as FileSystemFileHandle,
    ...overrides,
  };
}

function messageShape(message: NormalizedMessage) {
  return {
    role: message.role,
    content: message.content,
    created_at: message.created_at,
    metadata: message.metadata,
  };
}

function textBlock(text: string) {
  return { type: "text", text };
}

function userTurn(text: string, timestamp = "2026-06-25T10:00:00Z") {
  return {
    type: "user",
    timestamp,
    cwd: "/repo/alpha",
    message: { role: "user", content: [textBlock(text)] },
  };
}

function assistantTurn(text: string, timestamp = "2026-06-25T10:00:01Z") {
  return {
    type: "assistant",
    timestamp,
    cwd: "/repo/alpha",
    message: { role: "assistant", content: [textBlock(text)] },
  };
}

function fileHandleEntry(name: string, file: NodeFile) {
  return {
    kind: "file" as const,
    name,
    getFile: async () => file,
  };
}

function dirHandleEntry(name: string, children: unknown[]) {
  return {
    kind: "directory" as const,
    name,
    values: async function* () {
      yield* children;
    },
  };
}

function projectsRoot(projectDirs: unknown[]) {
  return {
    getDirectoryHandle: async (name: string) => {
      assert.equal(name, "projects");
      return dirHandleEntry("projects", projectDirs);
    },
  } as unknown as FileSystemDirectoryHandle;
}

test("parseClaudeSession keeps human turns with text blocks, epochs, and derived title", async () => {
  const file = jsonlFile([
    {
      type: "user",
      timestamp: "2026-06-25T10:00:00Z",
      cwd: "/repo/alpha",
      message: {
        role: "user",
        content: [
          textBlock("Explain Fourier transforms"),
          textBlock("Keep it short."),
        ],
      },
    },
    {
      type: "assistant",
      timestamp: "2026-06-25T10:00:05Z",
      cwd: "/repo/alpha",
      message: { role: "assistant", content: [textBlock("A Fourier transform decomposes a signal.")] },
    },
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.equal(parsed.external_id, "session-1");
  assert.equal(parsed.source_cwd, "/repo/alpha");
  assert.equal(parsed.title, "Explain Fourier transforms Keep it short.");
  assert.equal(parsed.created_at, Date.parse("2026-06-25T10:00:00Z") / 1000);
  assert.equal(parsed.updated_at, Date.parse("2026-06-25T10:00:05Z") / 1000);
  assert.deepEqual(parsed.messages.map(messageShape), [
    {
      role: "user",
      content: "Explain Fourier transforms\nKeep it short.",
      created_at: Date.parse("2026-06-25T10:00:00Z") / 1000,
      metadata: undefined,
    },
    {
      role: "assistant",
      content: "A Fourier transform decomposes a signal.",
      created_at: Date.parse("2026-06-25T10:00:05Z") / 1000,
      metadata: undefined,
    },
  ]);
});

test("parseClaudeSession prefers the ai-title record for the session title", async () => {
  const file = jsonlFile([
    { type: "ai-title", aiTitle: "Fourier deep dive" },
    userTurn("What is a transform?"),
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.equal(parsed.title, "Fourier deep dive");
});

test("parseClaudeSession keeps only human user/assistant turns and drops tool content", async () => {
  const file = jsonlFile([
    {
      type: "user",
      isSidechain: true,
      message: { role: "user", content: [textBlock("sub-agent branch")] },
    },
    {
      type: "user",
      isMeta: true,
      message: { role: "user", content: [textBlock("harness meta turn")] },
    },
    {
      type: "system",
      message: { role: "system", content: [textBlock("system turn")] },
    },
    {
      type: "assistant",
      timestamp: "2026-06-25T10:00:02Z",
      message: {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "private reasoning" },
          { type: "tool_use", name: "grep" },
          { type: "tool_result", content: "matches" },
          textBlock("Visible answer"),
          { type: "image", source: { type: "base64" } },
        ],
      },
    },
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.deepEqual(parsed.messages.map(messageShape), [
    {
      role: "assistant",
      content: "Visible answer",
      created_at: Date.parse("2026-06-25T10:00:02Z") / 1000,
      metadata: { had_images: true },
    },
  ]);
});

test("parseClaudeSession strips system-reminder markup and drops turns it empties", async () => {
  const file = jsonlFile([
    {
      type: "user",
      timestamp: "2026-06-25T10:00:00Z",
      message: {
        role: "user",
        content: [
          textBlock("Real question\n<system-reminder>injected context</system-reminder>"),
        ],
      },
    },
    {
      type: "user",
      timestamp: "2026-06-25T10:00:01Z",
      message: {
        role: "user",
        content: [textBlock("<system-reminder>only injected</system-reminder>")],
      },
    },
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.deepEqual(
    parsed.messages.map((message) => message.content),
    ["Real question"],
  );
});

test("parseClaudeSession skips malformed rows without losing valid neighbours", async () => {
  const file = jsonlFile([
    "{",
    "not-json",
    { message: { role: "user", content: [textBlock("kept before garbage")] } },
    "[]",
    '"a plain string row"',
    userTurn("kept after garbage", "2026-06-25T10:00:03Z"),
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.deepEqual(
    parsed.messages.map((message) => message.content),
    ["kept before garbage", "kept after garbage"],
  );
  assert.equal(parsed.messages[0].created_at, undefined);
  assert.equal(
    parsed.messages[1].created_at,
    Date.parse("2026-06-25T10:00:03Z") / 1000,
  );
});

test("parseClaudeSession drops a truncated final record", async () => {
  const file = jsonlFile([
    userTurn("Complete question"),
    assistantTurn("Complete answer", "2026-06-25T10:00:01Z"),
    '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"cut off mid reco',
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.deepEqual(
    parsed.messages.map((message) => message.content),
    ["Complete question", "Complete answer"],
  );
});

test("parseClaudeSession returns null for sessions without readable dialogue", async () => {
  const onlyNonDialogue = jsonlFile([
    { type: "summary", summary: "nothing readable" },
    {
      type: "assistant",
      message: {
        role: "assistant",
        content: [{ type: "tool_use", name: "grep" }],
      },
    },
    { isMeta: true, message: { role: "user", content: [textBlock("meta")] } },
  ]);
  assert.equal(await parseClaudeSession(sessionRef(onlyNonDialogue)), null);

  const blank = new NodeFile(["\n \n"], "blank.jsonl", { lastModified: MTIME });
  assert.equal(await parseClaudeSession(sessionRef(blank)), null);
});

test("parseClaudeSession falls back to the file mtime when rows carry no timestamps", async () => {
  const file = jsonlFile([
    { message: { role: "user", content: [textBlock("No clocks here")] } },
    { message: { role: "assistant", content: [textBlock("Nor here")] } },
  ]);

  const parsed = await parseClaudeSession(sessionRef(file));

  assert.ok(parsed);
  assert.ok(parsed.messages.every((message) => message.created_at === undefined));
  assert.equal(parsed.created_at, MTIME / 1000);
  assert.equal(parsed.updated_at, MTIME / 1000);
});

test("parseClaudeSession backfills source_cwd from records when the scan ref has none", async () => {
  const file = jsonlFile([
    {
      type: "user",
      cwd: "/repo/beta",
      message: { role: "user", content: [textBlock("Where am I?")] },
    },
  ]);

  const parsed = await parseClaudeSession(sessionRef(file, { cwd: "" }));

  assert.ok(parsed);
  assert.equal(parsed.source_cwd, "/repo/beta");
});

test("scanClaude groups project sessions newest-first with head-derived titles", async () => {
  const newer = jsonlFile(
    [
      { type: "ai-title", aiTitle: "Newest conversation" },
      {
        type: "user",
        timestamp: "2026-06-25T10:00:00Z",
        cwd: "/repo/alpha",
        message: { role: "user", content: [textBlock("First newer line")] },
      },
    ],
    "newer.jsonl",
  );
  const older = new NodeFile(
    [
      JSON.stringify({
        type: "user",
        timestamp: "2026-06-24T10:00:00Z",
        cwd: "/repo/alpha",
        message: { role: "user", content: [textBlock("Older opener")] },
      }),
    ],
    "older.jsonl",
    { lastModified: MTIME - 60_000 },
  );

  const groups = await scanClaude(
    projectsRoot([dirHandleEntry("alpha", [fileHandleEntry("newer.jsonl", newer), fileHandleEntry("older.jsonl", older)])]),
  );

  assert.equal(groups.length, 1);
  const [group] = groups;
  assert.equal(group.cwd, "/repo/alpha");
  assert.equal(group.label, "alpha");
  assert.deepEqual(
    group.sessions.map((session) => session.externalId),
    ["newer", "older"],
  );
  assert.deepEqual(
    group.sessions.map((session) => session.provisionalTitle),
    ["Newest conversation", "Older opener"],
  );
  assert.ok(group.sessions.every((session) => /^\d{4}-\d{2}-\d{2}$/.test(session.date)));
  assert.equal(group.sessions[0].cwd, "/repo/alpha");
});

test("scanClaude decodes the project dir name when no head row carries cwd and pins the group", async () => {
  const newer = jsonlFile(
    [
      {
        type: "assistant",
        timestamp: "2026-06-25T10:00:00Z",
        message: { role: "assistant", content: [textBlock("No cwd recorded")] },
      },
    ],
    "newer.jsonl",
  );
  const older = new NodeFile(
    [
      JSON.stringify({
        type: "user",
        cwd: "/repo/other",
        message: { role: "user", content: [textBlock("Carries its own cwd")] },
      }),
    ],
    "older.jsonl",
    { lastModified: MTIME - 60_000 },
  );

  const groups = await scanClaude(
    projectsRoot([dirHandleEntry("-Users-alice-proj", [fileHandleEntry("newer.jsonl", newer), fileHandleEntry("older.jsonl", older)])]),
  );

  assert.equal(groups.length, 1);
  const [group] = groups;
  assert.equal(group.cwd, "/Users/alice/proj");
  assert.equal(group.label, "proj");
  assert.ok(group.sessions.every((session) => session.cwd === "/Users/alice/proj"));
});

test("scanClaude skips non-jsonl files and empty project dirs and survives a head cut mid-row", async () => {
  const padding = "x".repeat(70 * 1024);
  const text = [
    JSON.stringify({
      type: "user",
      timestamp: "2026-06-25T10:00:00Z",
      cwd: "/repo/alpha",
      message: { role: "user", content: [textBlock("Head window opener")] },
    }),
    `{"type":"assistant","timestamp":"2026-06-25T10:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"${padding}`,
  ].join("\n");
  const big = new NodeFile([text], "big.jsonl", { lastModified: MTIME });

  const groups = await scanClaude(
    projectsRoot([
      dirHandleEntry("alpha", [
        fileHandleEntry("notes.txt", new NodeFile(["ignored"], "notes.txt")),
        fileHandleEntry("big.jsonl", big),
      ]),
      dirHandleEntry("hollow", [
        fileHandleEntry("readme.txt", new NodeFile(["ignored"], "readme.txt")),
      ]),
    ]),
  );

  assert.equal(groups.length, 1);
  const [group] = groups;
  assert.equal(group.cwd, "/repo/alpha");
  assert.deepEqual(
    group.sessions.map((session) => session.externalId),
    ["big"],
  );
  assert.equal(group.sessions[0].provisionalTitle, "Head window opener");
});
