import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import {
  extractMarkdownText,
  hasRenderableDetailsBody,
  hasRenderableMarkdownChildren,
  markdownHeadingId,
  stripLeadingMarkdownHashes,
} from "@/components/common/markdown-renderer-core";

function Section({ children }: { children?: ReactNode }) {
  return <section>{children}</section>;
}

function Span({ children }: { children?: ReactNode }) {
  return <span>{children}</span>;
}

describe("extractMarkdownText", () => {
  it("flattens strings, numbers and nested element children", () => {
    expect(
      extractMarkdownText([
        "Intro ",
        <span key="s">
          wor<b key="b">ld</b>
          {7}
        </span>,
        42,
      ]),
    ).toBe("Intro world742");
  });

  it("drops null, boolean and empty-array children from malformed markdown nodes", () => {
    expect(
      extractMarkdownText([null, undefined, false, true, [], "kept"]),
    ).toBe("kept");
  });
});

describe("markdownHeadingId", () => {
  it("builds a kebab id from mixed-case text with punctuation", () => {
    expect(
      markdownHeadingId(["Release ", <em key="e">Notes</em>, " v2!"]),
    ).toBe("release-notes-v2");
  });

  it("returns undefined when no slug-safe characters survive sanitization", () => {
    expect(markdownHeadingId("!!!")).toBeUndefined();
    expect(markdownHeadingId("中文标题")).toBeUndefined();
    expect(markdownHeadingId([])).toBeUndefined();
  });

  it("collapses whitespace-only headings to a bare hyphen id", () => {
    expect(markdownHeadingId("   ")).toBe("-");
  });
});

describe("hasRenderableMarkdownChildren", () => {
  it("ignores whitespace and zero-width characters", () => {
    expect(hasRenderableMarkdownChildren(["\u200B", " \uFEFF "])).toBe(false);
    expect(hasRenderableMarkdownChildren("\u200C\u200D")).toBe(false);
    expect(hasRenderableMarkdownChildren([" ", "content"])).toBe(true);
  });

  it("treats numbers and text nested inside elements as renderable", () => {
    expect(hasRenderableMarkdownChildren(0)).toBe(true);
    expect(
      hasRenderableMarkdownChildren(
        <Section>
          <Span> </Span>
        </Section>,
      ),
    ).toBe(false);
    expect(
      hasRenderableMarkdownChildren(
        <Section>
          <Span>visible</Span>
        </Section>,
      ),
    ).toBe(true);
  });
});

describe("hasRenderableDetailsBody", () => {
  it("treats a details block holding only its summary and blank text as empty", () => {
    expect(hasRenderableDetailsBody([<summary key="s">Title</summary>])).toBe(
      false,
    );
    expect(
      hasRenderableDetailsBody([<summary key="s">Title</summary>, "   "]),
    ).toBe(false);
  });

  it("finds a body among the summary siblings", () => {
    expect(
      hasRenderableDetailsBody([
        <summary key="s">Title</summary>,
        <p key="p">Body</p>,
      ]),
    ).toBe(true);
    expect(
      hasRenderableDetailsBody([<summary key="s">Title</summary>, "Body"]),
    ).toBe(true);
  });

  it("counts custom components as body content", () => {
    expect(
      hasRenderableDetailsBody([
        <summary key="s">Title</summary>,
        <Section key="c">text</Section>,
      ]),
    ).toBe(true);
  });
});

describe("stripLeadingMarkdownHashes", () => {
  it("strips the leading hash run of one to six hashes from the first text child", () => {
    expect(stripLeadingMarkdownHashes(["### Title", " tail"])).toEqual([
      "Title",
      " tail",
    ]);
    expect(stripLeadingMarkdownHashes(["# Solo"])).toEqual(["Solo"]);
  });

  it("leaves malformed hash runs and non-string first children untouched", () => {
    const sevenHashes = ["####### x"];
    expect(stripLeadingMarkdownHashes(sevenHashes)).toBe(sevenHashes);

    const noSpace = ["###NoSpace"];
    expect(stripLeadingMarkdownHashes(noSpace)).toBe(noSpace);

    const elementFirst = [<Span key="s">### x</Span>, "### y"];
    expect(stripLeadingMarkdownHashes(elementFirst)).toBe(elementFirst);

    expect(stripLeadingMarkdownHashes([])).toEqual([]);
  });
});
