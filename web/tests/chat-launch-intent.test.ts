import test from "node:test";
import assert from "node:assert/strict";

import { readChatLaunchIntent } from "../lib/chat-launch-intent";

test("an absent capability stays unspecified, an empty one means plain chat", () => {
  assert.equal(readChatLaunchIntent("?tool=web_search").capability, null);
  assert.equal(readChatLaunchIntent("?capability=").capability, "");
});

test("tools are collected verbatim for the caller to validate", () => {
  assert.deepEqual(
    readChatLaunchIntent("?tool=web_search&tool=+reason+").tools,
    ["web_search", "reason"],
  );
});

test("an empty search has no launch intent", () => {
  assert.deepEqual(readChatLaunchIntent(""), {
    capability: null,
    tools: [],
  });
});

test("repeated capability parameters collapse to the first value", () => {
  assert.equal(
    readChatLaunchIntent("?capability=exam&capability=quiz").capability,
    "exam",
  );
});

test("a whitespace-only capability is trimmed to plain chat", () => {
  assert.equal(readChatLaunchIntent("?capability=%20").capability, "");
});

test("empty tool values are kept so the caller sees the parameter was there", () => {
  assert.deepEqual(readChatLaunchIntent("?tool=&tool=web_search").tools, [
    "",
    "web_search",
  ]);
});

test("the parser does not require the leading question mark", () => {
  assert.deepEqual(readChatLaunchIntent("capability=reading&tool=outline"), {
    capability: "reading",
    tools: ["outline"],
  });
});
