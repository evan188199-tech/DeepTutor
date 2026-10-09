import test from "node:test";
import assert from "node:assert/strict";
import React from "react";

import {
  extractMarkdownText,
  hasRenderableDetailsBody,
  hasRenderableMarkdownChildren,
  markdownHeadingId,
  stripLeadingMarkdownHashes,
} from "../components/common/markdown-renderer-core";
import type { MarkdownRendererProps } from "../components/common/markdown-renderer-types";

const badVariant: MarkdownRendererProps = {
  content: "text",
  // @ts-expect-error
  variant: "huge",
};
const missingContent = {} as MarkdownRendererProps;
const wrongContentType: MarkdownRendererProps = {
  // @ts-expect-error
  content: 42,
};
const extraProp = { content: "text", emoji: true } as MarkdownRendererProps;

test("MarkdownRendererProps accepts every documented variant and rejects others", () => {
  const variants: NonNullable<MarkdownRendererProps["variant"]>[] = [
    "default",
    "compact",
    "prose",
    "trace",
  ];
  assert.equal(variants.length, 4);

  const minimal: MarkdownRendererProps = { content: "" };
  const full: MarkdownRendererProps = {
    content: "body",
    className: "prose-sm",
    variant: "trace",
    enableMath: true,
    enableCode: false,
    enableMermaid: true,
    enableImages: false,
    allowHtml: false,
    trackSourceLines: true,
  };
  assert.equal(minimal.content, "");
  assert.equal(full.variant, "trace");
  assert.equal(full.trackSourceLines, true);

  assert.notEqual(badVariant.variant, "default");
  assert.equal(Object.keys(missingContent).length, 0);
  assert.equal(wrongContentType.content, 42);
  assert.equal((extraProp as unknown as Record<string, unknown>).emoji, true);
});

test("extractMarkdownText joins string and number children", () => {
  assert.equal(extractMarkdownText(["a", 1, "b", 0]), "a1b0");
  assert.equal(extractMarkdownText("solo"), "solo");
});

test("extractMarkdownText recurses into element and fragment children", () => {
  const nested = React.createElement(
    "p",
    null,
    "he",
    React.createElement("b", null, "ll"),
    "o",
  );
  assert.equal(extractMarkdownText(nested), "hello");

  const fragment = React.createElement(React.Fragment, null, [
    "x",
    React.createElement("i", null, "y"),
  ]);
  assert.equal(extractMarkdownText(fragment), "xy");
});

test("extractMarkdownText falls back to empty for invalid children", () => {
  assert.equal(extractMarkdownText(null), "");
  assert.equal(extractMarkdownText(undefined), "");
  assert.equal(extractMarkdownText(true), "");
  assert.equal(extractMarkdownText(false), "");
  assert.equal(extractMarkdownText([]), "");
  assert.equal(extractMarkdownText(React.createElement("span")), "");

  const invalid = [null, undefined, true, false, () => "gone", Symbol("s")];
  assert.equal(extractMarkdownText(invalid as React.ReactNode), "");

  const mixed = ["a", () => "x", "b", null];
  assert.equal(extractMarkdownText(mixed as React.ReactNode), "ab");
});

test("markdownHeadingId builds slug ids from text", () => {
  assert.equal(markdownHeadingId("Hello World"), "hello-world");
  assert.equal(markdownHeadingId("Hello, World!"), "hello-world");
  assert.equal(markdownHeadingId("A   B\tC"), "a-b-c");
  assert.equal(
    markdownHeadingId(["Deep", React.createElement("b", null, "Dive")]),
    "deepdive",
  );
});

test("markdownHeadingId returns undefined when no slug remains", () => {
  assert.equal(markdownHeadingId(""), undefined);
  assert.equal(markdownHeadingId("!!!"), undefined);
  assert.equal(markdownHeadingId(null), undefined);
  assert.equal(markdownHeadingId(React.createElement("span")), undefined);
});

test("hasRenderableMarkdownChildren detects visible text nodes", () => {
  assert.equal(hasRenderableMarkdownChildren("hello"), true);
  assert.equal(hasRenderableMarkdownChildren("0"), true);
  assert.equal(hasRenderableMarkdownChildren(0), true);
  assert.equal(
    hasRenderableMarkdownChildren(React.createElement("b", null, "x")),
    true,
  );
  assert.equal(
    hasRenderableMarkdownChildren([
      null,
      React.createElement("i", null, "y"),
    ]),
    true,
  );
});

test("hasRenderableMarkdownChildren rejects blank and invalid content", () => {
  assert.equal(hasRenderableMarkdownChildren(""), false);
  assert.equal(hasRenderableMarkdownChildren("   \n\t "), false);
  assert.equal(hasRenderableMarkdownChildren("\u200B\u200C\u200D\uFEFF"), false);
  assert.equal(hasRenderableMarkdownChildren(null), false);
  assert.equal(hasRenderableMarkdownChildren(false), false);
  assert.equal(hasRenderableMarkdownChildren([]), false);
  assert.equal(hasRenderableMarkdownChildren(React.createElement("span")), false);
});

test("hasRenderableDetailsBody finds content beyond the summary", () => {
  assert.equal(hasRenderableDetailsBody("body"), true);
  assert.equal(hasRenderableDetailsBody(0), true);
  assert.equal(
    hasRenderableDetailsBody(React.createElement("div", null, "x")),
    true,
  );
  assert.equal(
    hasRenderableDetailsBody([
      React.createElement("summary", null, "Title"),
      "rest",
    ]),
    true,
  );
  assert.equal(
    hasRenderableDetailsBody([
      "intro",
      React.createElement("summary", null, "Title"),
    ]),
    true,
  );
});

test("hasRenderableDetailsBody rejects blank or summary-only children", () => {
  assert.equal(hasRenderableDetailsBody(""), false);
  assert.equal(hasRenderableDetailsBody("  "), false);
  assert.equal(
    hasRenderableDetailsBody(React.createElement("summary", null, "Title")),
    false,
  );
  assert.equal(
    hasRenderableDetailsBody(React.createElement("SUMMARY", null, "Title")),
    false,
  );
  assert.equal(hasRenderableDetailsBody(null), false);
  assert.equal(hasRenderableDetailsBody(true), false);
  assert.equal(hasRenderableDetailsBody([]), false);
});

test("stripLeadingMarkdownHashes removes heading markers from leading text", () => {
  assert.deepEqual(stripLeadingMarkdownHashes("### Title"), ["Title"]);
  assert.deepEqual(
    stripLeadingMarkdownHashes(["###### Six", "tail"]),
    ["Six", "tail"],
  );
  const withElement = stripLeadingMarkdownHashes([
    "## Head",
    React.createElement("i", null, "x"),
  ]);
  assert.ok(Array.isArray(withElement));
  assert.equal(withElement.length, 2);
  assert.equal(withElement[0], "Head");
  const element = withElement[1] as React.ReactElement<{
    children?: React.ReactNode;
  }>;
  assert.equal(element.type, "i");
  assert.equal(element.props.children, "x");
});

test("stripLeadingMarkdownHashes keeps non-heading leading nodes intact", () => {
  assert.equal(stripLeadingMarkdownHashes("####### Seven"), "####### Seven");
  assert.equal(stripLeadingMarkdownHashes("#NoSpace"), "#NoSpace");
  const bold = React.createElement("b", null, "bold");
  const unchanged: React.ReactNode[] = [bold, "### tail"];
  assert.equal(stripLeadingMarkdownHashes(unchanged), unchanged);
  const empty: React.ReactNode[] = [];
  assert.equal(stripLeadingMarkdownHashes(empty), empty);
});
