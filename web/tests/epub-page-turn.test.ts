import assert from "node:assert/strict";
import test from "node:test";

import {
  EPUB_PAGE_TURN_MIN_DRAG_PX,
  allowsEpubPageTurn,
  directionForEpubLayout,
  hrefKey,
  locatorForEpubHref,
  resolveEpubPageTurnSwipe,
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

test("drags just under the minimum distance never turn the page", () => {
  const shortRight = EPUB_PAGE_TURN_MIN_DRAG_PX - 1;
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 200 + shortRight, 200), null);
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 200 - shortRight, 200), null);
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 200, 200), null);
});

test("a drag exactly at the minimum distance turns the page", () => {
  assert.equal(
    resolveEpubPageTurnSwipe(200, 200, 200 + EPUB_PAGE_TURN_MIN_DRAG_PX, 200),
    "previous",
  );
  assert.equal(
    resolveEpubPageTurnSwipe(200, 200, 200 - EPUB_PAGE_TURN_MIN_DRAG_PX, 200),
    "next",
  );
});

test("diagonal drags at the horizontal ratio limit are rejected", () => {
  // |dx| <= |dy| * ratio is rejected, so the exact ratio boundary is too.
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 300, 280), null);
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 100, 280), null);
  // One pixel less vertical travel makes the drag count as horizontal.
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 300, 279), "previous");
  assert.equal(resolveEpubPageTurnSwipe(200, 200, 200, 500), null);
});

test("spine-less reader hrefs still resolve through path suffixes", () => {
  const refs = [
    { locator: 3, source_href: "OEBPS/text/ch1.xhtml" },
    { locator: 7, source_href: "text/ch2.xhtml" },
  ];
  // Reader href lacks the directory prefix the spine declares.
  assert.equal(locatorForEpubHref("text/ch1.xhtml", refs), 3);
  // Reader href carries the prefix the spine entry omits.
  assert.equal(locatorForEpubHref("OEBPS/text/ch2.xhtml", refs), 7);
});

test("href keys survive malformed escape sequences without decoding", () => {
  // An invalid % escape would throw decodeURIComponent; the key must fall
  // back to the raw fragment-less path instead.
  assert.equal(hrefKey("OEBPS/text/ch%zz.xhtml#p"), "OEBPS/text/ch%zz.xhtml");
  assert.equal(hrefKey(""), "");
});

test("page turns are rejected off elements and on interactive targets", () => {
  const asTarget = (closest: unknown) => ({ closest }) as unknown as EventTarget;
  assert.equal(allowsEpubPageTurn(null), false);
  assert.equal(allowsEpubPageTurn({} as unknown as EventTarget), false);
  assert.equal(allowsEpubPageTurn(asTarget(() => null)), true);
  assert.equal(allowsEpubPageTurn(asTarget(() => ({}) as Element)), false);
});
