import { describe, expect, it } from "vitest";
import {
  countSelectedBookPages,
  normalizeBookReferences,
  selectedBooksToPayload,
  type SelectedBookReference,
} from "@/lib/book-references";

const reference = (
  bookId: string,
  ...pageIds: string[]
): SelectedBookReference => ({
  bookId,
  bookTitle: `Title of ${bookId}`,
  pages: pageIds.map((pageId) => ({
    bookId,
    bookTitle: `Title of ${bookId}`,
    pageId,
    pageTitle: `Page ${pageId}`,
  })),
});

describe("selectedBooksToPayload", () => {
  it("maps camelCase selections to snake_case payloads with deduplicated page ids", () => {
    expect(selectedBooksToPayload([reference("book-1", "p1", "p2", "p1")])).toEqual([
      { book_id: "book-1", page_ids: ["p1", "p2"] },
    ]);
  });

  it("drops references without a book id or without pages", () => {
    expect(
      selectedBooksToPayload([
        reference("", "p1"),
        reference("book-2"),
        reference("book-3", "p1"),
      ]),
    ).toEqual([{ book_id: "book-3", page_ids: ["p1"] }]);
  });

  it("filters empty page ids out of otherwise valid references", () => {
    expect(
      selectedBooksToPayload([reference("book-1", "", "p1", "")]),
    ).toEqual([{ book_id: "book-1", page_ids: ["p1"] }]);
  });
});

describe("countSelectedBookPages", () => {
  it("sums page counts across references", () => {
    expect(
      countSelectedBookPages([
        reference("book-1", "p1", "p2"),
        reference("book-2", "p1"),
        reference("book-3"),
      ]),
    ).toBe(3);
  });

  it("returns zero for an empty selection", () => {
    expect(countSelectedBookPages([])).toBe(0);
  });
});

describe("normalizeBookReferences", () => {
  it("returns no payloads for non-array input", () => {
    for (const value of [null, undefined, {}, "[]", 42]) {
      expect(normalizeBookReferences(value)).toEqual([]);
    }
  });

  it("keeps valid payloads and deduplicates page ids", () => {
    expect(
      normalizeBookReferences([
        { book_id: "book-1", page_ids: ["p1", "p2", "p1"] },
        { book_id: "book-2", page_ids: ["p1"] },
      ]),
    ).toEqual([
      { book_id: "book-1", page_ids: ["p1", "p2"] },
      { book_id: "book-2", page_ids: ["p1"] },
    ]);
  });

  it("drops malformed entries instead of throwing", () => {
    expect(
      normalizeBookReferences([
        null,
        "book-1",
        42,
        {},
        { book_id: "", page_ids: ["p1"] },
        { book_id: "book-1" },
        { book_id: "book-1", page_ids: [] },
        { book_id: "book-1", page_ids: ["p1", 7, null, ""] },
        { book_id: 9, page_ids: ["p1"] },
      ]),
    ).toEqual([{ book_id: "book-1", page_ids: ["p1"] }]);
  });

  it("feeds selectedBooksToPayload with the same shapes the payload builder emits", () => {
    const payload = [{ book_id: "book-1", page_ids: ["p1", "p2"] }];
    expect(selectedBooksToPayloadFromNormalized(payload)).toEqual(payload);
  });
});

function selectedBooksToPayloadFromNormalized(
  value: unknown,
): ReturnType<typeof selectedBooksToPayload> {
  return selectedBooksToPayload(
    normalizeBookReferences(value).map((payload) => ({
      bookId: payload.book_id,
      bookTitle: payload.book_id,
      pages: payload.page_ids.map((pageId) => ({
        bookId: payload.book_id,
        bookTitle: payload.book_id,
        pageId,
        pageTitle: pageId,
      })),
    })),
  );
}
