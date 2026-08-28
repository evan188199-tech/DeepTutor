import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  buildCoWriterDraftPayload,
  getCoWriterDraftStatus,
} from "../components/chat/home/ChatCoWriterTab";

test("chat Co-Writer drafts keep Markdown bytes and gain a usable fallback title", () => {
  const content = "# Note\n\n- keep  trailing spaces   \n\n```python\nx = 1\n```\n";

  assert.deepEqual(
    buildCoWriterDraftPayload({
      title: "   ",
      content,
      fallbackTitle: "Chat note",
    }),
    { title: "Chat note", content },
  );
  assert.deepEqual(
    buildCoWriterDraftPayload({
      title: "  Section 2  ",
      content,
      fallbackTitle: "Chat note",
    }),
    { title: "Section 2", content },
  );
});

test("chat Co-Writer status detects empty, unsaved, and persisted drafts", () => {
  const base = {
    documentId: "doc-1",
    title: "Notes",
    savedTitle: "Notes",
    savedContent: "# Notes",
  };

  assert.equal(
    getCoWriterDraftStatus({ ...base, content: "   " }),
    "empty",
  );
  assert.equal(getCoWriterDraftStatus({ ...base, content: "# Changed" }), "unsaved");
  assert.equal(
    getCoWriterDraftStatus({
      ...base,
      title: " Renamed ",
      content: "# Notes",
    }),
    "unsaved",
  );
  assert.equal(getCoWriterDraftStatus({ ...base, content: "# Notes" }), "saved");
  assert.equal(
    getCoWriterDraftStatus({
      ...base,
      documentId: null,
      content: "# New",
    }),
    "unsaved",
  );
});

test("chat page exposes Co-Writer through the existing side-panel contract", () => {
  const webRoot = process.cwd();
  const readSource = (relativePath: string) =>
    readFileSync(path.join(webRoot, relativePath), "utf8");
  const panel = readSource("components/chat/home/SessionViewerPanel.tsx");
  const chatPage = readSource(
    path.join("app", "(workspace)", "home", "[[...sessionId]]", "page.tsx"),
  );
  const editor = readSource("components/chat/home/ChatCoWriterTab.tsx");

  assert.match(panel, /openCoWriterTab\(\): void/);
  assert.match(panel, /kind: "co-writer"/);
  assert.match(panel, /<ChatCoWriterTab \/>/);
  assert.match(chatPage, /openChatCoWriterTab/);
  assert.match(chatPage, /label=\{t\("Chat note"\)\}/);
  assert.match(editor, /createCoWriterDocument/);
  assert.match(editor, /updateCoWriterDocument/);
  assert.match(editor, /role="alert"/);
});
