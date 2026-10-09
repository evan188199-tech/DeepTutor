import { describe, expect, it } from "vitest";

import {
  toolResultMetadata,
  toolResultPayload,
  toolResultScope,
} from "@/lib/tool-event";

describe("toolResultMetadata", () => {
  it("returns the nested tool_metadata block", () => {
    const nested = { citations: [1, 2], duration_ms: 42 };
    expect(toolResultMetadata({ tool_metadata: nested })).toEqual(nested);
  });

  it("returns null when the event carries no nested block", () => {
    expect(toolResultMetadata({ citations: [1] })).toBeNull();
  });

  it("returns null when tool_metadata is not a record", () => {
    expect(toolResultMetadata({ tool_metadata: "nope" })).toBeNull();
    expect(toolResultMetadata({ tool_metadata: ["nope"] })).toBeNull();
    expect(toolResultMetadata({ tool_metadata: null })).toBeNull();
  });

  it("returns null for non-record event payloads", () => {
    expect(toolResultMetadata(null)).toBeNull();
    expect(toolResultMetadata(undefined)).toBeNull();
    expect(toolResultMetadata(7)).toBeNull();
    expect(toolResultMetadata("metadata")).toBeNull();
    expect(toolResultMetadata([{ tool_metadata: {} }])).toBeNull();
  });
});

describe("toolResultScope", () => {
  it("prefers the nested tool_metadata block", () => {
    const nested = { answer: "nested" };
    expect(toolResultScope({ answer: "outer", tool_metadata: nested })).toEqual(
      nested,
    );
  });

  it("falls back to the top level when the block is not nested", () => {
    const outer = { answer: "flat" };
    expect(toolResultScope(outer)).toEqual(outer);
  });

  it("returns null for non-record payloads", () => {
    expect(toolResultScope(null)).toBeNull();
    expect(toolResultScope(undefined)).toBeNull();
    expect(toolResultScope(3.14)).toBeNull();
    expect(toolResultScope(["flat"])).toBeNull();
  });
});

describe("toolResultPayload", () => {
  it("reads the key from the nested block first", () => {
    expect(
      toolResultPayload({ tool_metadata: { key: "nested" } }, "key"),
    ).toBe("nested");
  });

  it("falls back to the top level when there is no nested block", () => {
    expect(toolResultPayload({ key: "flat" }, "key")).toBe("flat");
  });

  it("falls back to the top level when the nested block lacks the key", () => {
    expect(
      toolResultPayload({ key: "flat", tool_metadata: { other: 1 } }, "key"),
    ).toBe("flat");
  });

  it("returns falsy nested values instead of falling back", () => {
    const event = { key: "flat", tool_metadata: { key: null } };
    expect(toolResultPayload(event, "key")).toBeNull();
    expect(
      toolResultPayload({ key: "flat", tool_metadata: { key: false } }, "key"),
    ).toBe(false);
    expect(
      toolResultPayload({ key: "flat", tool_metadata: { key: 0 } }, "key"),
    ).toBe(0);
  });

  it("treats an array tool_metadata as absent", () => {
    expect(toolResultPayload({ key: "flat", tool_metadata: [] }, "key")).toBe(
      "flat",
    );
  });

  it("returns undefined for non-record payloads and missing keys", () => {
    expect(toolResultPayload(null, "key")).toBeUndefined();
    expect(toolResultPayload("payload", "key")).toBeUndefined();
    expect(toolResultPayload({ tool_metadata: {} }, "key")).toBeUndefined();
  });
});
