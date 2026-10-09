import test from "node:test";
import assert from "node:assert/strict";
import {
  SCROLL_EDGE_TOLERANCE_PX,
  chapterReadingPercent,
  sequentialReadTarget,
} from "../lib/book-reader-navigation";

test("long chapters advance by one readable screen with overlap", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3000, clientHeight: 600 },
      "next",
    ),
    540,
  );
});

test("long chapters retreat by one readable screen with overlap", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 700, scrollHeight: 3000, clientHeight: 600 },
      "previous",
    ),
    160,
  );
});

test("scroll targets clamp at chapter boundaries", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 2_300, scrollHeight: 3_000, clientHeight: 600 },
      "next",
    ),
    2_400,
  );
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 300, scrollHeight: 3_000, clientHeight: 600 },
      "previous",
    ),
    0,
  );
});

test("chapter edges and non-scrolling chapters request a page turn", () => {
  const atStart = { scrollTop: 0, scrollHeight: 3_000, clientHeight: 600 };
  const atEnd = { scrollTop: 2_400, scrollHeight: 3_000, clientHeight: 600 };
  const withoutScroll = {
    scrollTop: 0,
    scrollHeight: 600,
    clientHeight: 600,
  };

  assert.equal(sequentialReadTarget(atStart, "previous"), null);
  assert.equal(sequentialReadTarget(atEnd, "next"), null);
  assert.equal(sequentialReadTarget(withoutScroll, "next"), null);
  assert.equal(sequentialReadTarget(withoutScroll, "previous"), null);
});

test("hidden or detached readers do not fabricate scroll positions", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3_000, clientHeight: 0 },
      "next",
    ),
    null,
  );
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3_000, clientHeight: 1 },
      "previous",
    ),
    null,
  );
});

test("sub-pixel edges do not hide an unread remainder", () => {
  const nearEnd = { scrollTop: 2_399, scrollHeight: 3_000, clientHeight: 600 };
  assert.equal(sequentialReadTarget(nearEnd, "next"), null);
  assert.equal(chapterReadingPercent(nearEnd), 100);
});

test("chapter progress is bounded and zero when scrolling is unavailable", () => {
  assert.equal(
    chapterReadingPercent({
      scrollTop: 1_200,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    50,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: -20,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    0,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: 9_999,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    100,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: 0,
      scrollHeight: 601,
      clientHeight: 600,
    }),
    0,
  );
});

test("edge tolerance boundaries are inclusive", () => {
  // A client box of exactly the tolerance height is unreadable.
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 100, scrollHeight: 3_000, clientHeight: SCROLL_EDGE_TOLERANCE_PX },
      "next",
    ),
    null,
  );
  // A scroll range of exactly the tolerance has no readable screenfuls.
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 602, clientHeight: 600 },
      "next",
    ),
    null,
  );
  // Retreats from exactly the tolerance offset are already at the top.
  assert.equal(
    sequentialReadTarget(
      { scrollTop: SCROLL_EDGE_TOLERANCE_PX, scrollHeight: 3_000, clientHeight: 600 },
      "previous",
    ),
    null,
  );
});

test("the last readable remainder still steps to the bottom", () => {
  // Remaining scroll is one pixel past the tolerance: the page advances.
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 2_397, scrollHeight: 3_000, clientHeight: 600 },
      "next",
    ),
    2_400,
  );
  assert.equal(
    sequentialReadTarget(
      { scrollTop: SCROLL_EDGE_TOLERANCE_PX + 1, scrollHeight: 3_000, clientHeight: 600 },
      "previous",
    ),
    0,
  );
});

test("progress treats a zero-height client box as unread", () => {
  assert.equal(chapterReadingPercent({ scrollTop: 20, scrollHeight: 10_000, clientHeight: 0 }), 0);
});
