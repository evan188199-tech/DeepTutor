import { describe, expect, it, vi } from "vitest";
import { BookApiError } from "@/lib/book-api";
import { bookErrorMessage, KNOWN_BOOK_ERROR_CODES } from "@/lib/book-errors";

const translate = vi.fn((key: string) => `译:${key}`);

describe("bookErrorMessage", () => {
  it("translates every known code through the message table instead of relaying server prose", () => {
    expect(KNOWN_BOOK_ERROR_CODES).toEqual([
      "book_revision_conflict",
      "book_revision_required",
      "book_paused",
    ]);
    for (const code of KNOWN_BOOK_ERROR_CODES) {
      translate.mockClear();
      const error = new BookApiError("English log prose", 409, code);
      const message = bookErrorMessage(error, translate);
      expect(translate).toHaveBeenCalledTimes(1);
      expect(message).toBe(`译:${translate.mock.calls[0]?.[0]}`);
      expect(translate.mock.calls[0]?.[0]).toEqual(expect.any(String));
      expect(message).not.toBe("English log prose");
    }
  });

  it("maps the revision conflict code to its documented wording", () => {
    const error = new BookApiError("another collaborator updated", 409, "book_revision_conflict");
    expect(bookErrorMessage(error, translate)).toBe(
      "译:This book changed while you were working on it. The latest version is loaded — try again.",
    );
  });

  it("falls back to the server message for unknown codes", () => {
    const error = new BookApiError("mystery failure", 500, "book_mystery_code");
    expect(bookErrorMessage(error, translate)).toBe("mystery failure");
    expect(translate).not.toHaveBeenCalled();
  });

  it("falls back to the server message when the error carries no code", () => {
    const error = new BookApiError("request timed out", 504);
    expect(bookErrorMessage(error, translate)).toBe("request timed out");
    expect(translate).not.toHaveBeenCalled();
  });

  it("falls back to the message of a plain Error", () => {
    expect(bookErrorMessage(new Error("socket closed"), translate)).toBe("socket closed");
    expect(translate).not.toHaveBeenCalled();
  });

  it("stringifies values that are not Error instances", () => {
    expect(bookErrorMessage("boom", translate)).toBe("boom");
    expect(bookErrorMessage(42, translate)).toBe("42");
    expect(translate).not.toHaveBeenCalled();
  });
});
