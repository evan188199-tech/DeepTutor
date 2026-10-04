import assert from "node:assert/strict";
import test from "node:test";

import {
  directionForEpubLayout,
  epubPaperMaxWidth,
  epubSpreadModeForWidth,
  hrefKey,
  locatorForEpubHref,
  renditionSpreadForEpubMode,
  resolveEpubPageTurnSwipe,
  resolveEpubSpreadLayout,
} from "../lib/epub-page-turn";

test("horizontal swipes turn pages but vertical scrolls do not", () => {
  assert.equal(resolveEpubPageTurnSwipe(200, 100, 100, 105), "next");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 200, 105), "previous");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 140, 100), null);
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 160, 180), null);
});

test("RTL reverses physical rendition direction", () => {
  assert.equal(directionForEpubLayout("next", false), "next");
  assert.equal(directionForEpubLayout("next", true), "previous");
  assert.equal(directionForEpubLayout("previous", true), "next");
});

test("responsive spread layout follows the real available width (#1236)", () => {
  assert.equal(epubSpreadModeForWidth(1440), "double");
  assert.equal(epubSpreadModeForWidth(900), "double");
  assert.equal(epubSpreadModeForWidth(899), "single");
  // Below the 900px reader floor a single page wins even if a leaf would fit.
  assert.equal(epubSpreadModeForWidth(720), "single");
  assert.equal(resolveEpubSpreadLayout("auto", 960), "double");
  assert.equal(resolveEpubSpreadLayout("auto", 640), "single");
  // The manual preference remains an opt-out of the responsive spread.
  assert.equal(resolveEpubSpreadLayout("none", 1440), "single");
});

test("spread layouts map to epub.js rendition values and paper widths", () => {
  assert.equal(renditionSpreadForEpubMode("double"), "always");
  assert.equal(renditionSpreadForEpubMode("single"), "none");
  assert.equal(epubPaperMaxWidth("single", 84), "min(100%, calc(84ch + 4rem))");
  assert.equal(
    epubPaperMaxWidth("double", 84),
    "min(100%, calc(168ch + 6rem))",
  );
});

test("source hrefs map to the server locator despite encoding and base paths", () => {
  const refs = [
    { locator: 1, source_href: "OEBPS/chapters/one.xhtml" },
    { locator: 2, source_href: "OEBPS/chapters/two%20words.xhtml" },
  ];
  assert.equal(locatorForEpubHref("OEBPS/chapters/one.xhtml#p1", refs), 1);
  assert.equal(locatorForEpubHref("chapters/two words.xhtml", refs), 2);
  assert.equal(locatorForEpubHref("missing.xhtml", refs), 0);
  assert.equal(hrefKey("./chapter.xhtml#here"), "chapter.xhtml");
});
