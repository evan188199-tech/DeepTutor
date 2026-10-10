import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import BookReferencePicker from "@/components/chat/BookReferencePicker";
import type { Book, BookDetail, Chapter, Page } from "@/lib/book-types";
import type { SelectedBookReference } from "@/lib/book-references";
import { initI18n } from "@/i18n/init";

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/book-api", () => ({ bookApi: api }));
vi.mock("@/components/common/PickerShell", () => ({
  default: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div>{children}</div> : null,
}));
initI18n("en");

function makeBook(id: string, title: string, description: string, pageCount: number): Book {
  return {
    id,
    revision: 1,
    title,
    description,
    status: "ready",
    proposal: null,
    knowledge_bases: [],
    language: "en",
    page_count: pageCount,
    chapter_count: 1,
    created_at: 0,
    updated_at: 0,
    metadata: {},
  };
}

function makePage(id: string, chapterId: string, title: string, bookId = "a"): Page {
  return {
    id,
    book_id: bookId,
    chapter_id: chapterId,
    title,
    learning_objectives: [],
    content_type: "theory",
    status: "ready",
    order: 0,
    blocks: [],
    links: [],
    parent_page_id: "",
    error: "",
    created_at: 0,
    updated_at: 0,
  };
}

function makeChapter(id: string, title: string, pageIds: string[]): Chapter {
  return {
    id,
    title,
    learning_objectives: [],
    content_type: "theory",
    source_anchors: [],
    prerequisites: [],
    page_ids: pageIds,
    summary: "",
    order: 0,
  };
}

function makeDetail(book: Book, chapters: Chapter[], pages: Page[]): BookDetail {
  return {
    book,
    spine: { book_id: book.id, chapters, version: 1, updated_at: 0 },
    pages,
    progress: {
      book_id: book.id,
      current_page_id: "",
      visited_page_ids: [],
      bookmarked_page_ids: [],
      quiz_attempts: [],
      weak_chapters: [],
      score: 0,
      updated_at: 0,
    },
    generation: {
      book_id: book.id,
      status: "ready",
      can_resume: false,
      pause_reason: "",
      source_quality: null,
      pages: { total: pages.length },
      failed_blocks: 0,
      retryable_pages: 0,
      failure_categories: {},
    },
  };
}

const bookA = makeBook("a", "Algebra Basics", "Linear equations", 3);
const bookB = makeBook("b", "Geometry Primer", "Shapes and angles", 2);
const pageOne = makePage("p1", "c1", "Linear Equations");
const pageTwo = makePage("p2", "c1", "Quadratics");
const pageThree = makePage("p3", "c2", "Word Problems");
const detailA = makeDetail(bookA, [makeChapter("c1", "Foundations", ["p1", "p2"]), makeChapter("c2", "Applications", ["p3"])], [pageOne, pageTwo, pageThree]);
const seededPageOne: SelectedBookReference = {
  bookId: "a",
  bookTitle: "Algebra Basics",
  pages: [{ bookId: "a", bookTitle: "Algebra Basics", pageId: "p1", pageTitle: "Linear Equations", chapterId: "c1", chapterTitle: "Foundations" }],
};

function viewPicker(initial: SelectedBookReference[] = [], onApply = vi.fn(), onClose = vi.fn()) {
  return render(<BookReferencePicker open initialReferences={initial} onClose={onClose} onApply={onApply} />);
}

it("renders the book list, seeds the initial selection, and exposes chapter rows", async () => {
  api.list.mockResolvedValue({ books: [bookA, bookB] });
  api.get.mockResolvedValue(detailA);
  viewPicker([seededPageOne]);
  expect(await screen.findByRole("button", { name: "Linear Equations" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Algebra Basics/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Geometry Primer/ })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Algebra Basics" })).toBeTruthy();
  expect(screen.getByText("Linear equations")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Foundations/ })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Quadratics" })).toBeTruthy();
  expect(screen.getByText("1 chapters selected")).toBeTruthy();
});

it("filters books by keyword and shows the empty state when nothing matches", async () => {
  api.list.mockResolvedValue({ books: [bookA, bookB] });
  api.get.mockResolvedValue(detailA);
  viewPicker();
  await screen.findByRole("button", { name: "Linear Equations" });
  fireEvent.change(screen.getByPlaceholderText("Search books"), { target: { value: "geometry" } });
  expect(screen.getByRole("button", { name: /Geometry Primer/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Algebra Basics/ })).toBeNull();
  fireEvent.change(screen.getByPlaceholderText("Search books"), { target: { value: "zzz" } });
  expect(await screen.findByText("No books found.")).toBeTruthy();
});

it("shows a spinner while books load", async () => {
  api.list.mockReturnValue(new Promise(() => undefined));
  const { container } = viewPicker();
  expect(container.querySelector(".animate-spin")).toBeTruthy();
});

it("falls back to the empty list state when listing books fails", async () => {
  api.list.mockRejectedValue(new Error("offline"));
  viewPicker();
  expect(await screen.findByText("No books found.")).toBeTruthy();
});

it("shows a detail spinner while the active book loads", async () => {
  api.list.mockResolvedValue({ books: [bookA] });
  api.get.mockReturnValue(new Promise(() => undefined));
  const { container } = viewPicker();
  expect(await screen.findByRole("heading", { name: "Algebra Basics" })).toBeTruthy();
  await waitFor(() => expect(container.querySelector(".animate-spin")).toBeTruthy());
});

it("selects and deselects individual pages, then applies the payload", async () => {
  api.list.mockResolvedValue({ books: [bookA] });
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  const onClose = vi.fn();
  viewPicker([], onApply, onClose);
  fireEvent.click(await screen.findByRole("button", { name: "Linear Equations" }));
  expect(screen.getByText("1 chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Quadratics" }));
  expect(screen.getByText("2 chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Linear Equations" }));
  expect(screen.getByText("1 chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(onApply).toHaveBeenCalledExactlyOnceWith([
    {
      bookId: "a",
      bookTitle: "Algebra Basics",
      pages: [{ bookId: "a", bookTitle: "Algebra Basics", pageId: "p2", pageTitle: "Quadratics", chapterId: "c1", chapterTitle: "Foundations" }],
    },
  ]);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("toggles a whole chapter on and off from the chapter row", async () => {
  api.list.mockResolvedValue({ books: [bookA] });
  api.get.mockResolvedValue(detailA);
  viewPicker();
  fireEvent.click(await screen.findByRole("button", { name: /Foundations/ }));
  expect(screen.getByText("2 chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Foundations/ }));
  expect(screen.getByText("No chapters selected")).toBeTruthy();
});

it("groups orphan pages under Unassigned pages when switching books", async () => {
  const grouped = makePage("p5", "g1", "Triangles", "b");
  const orphan = makePage("p6", "", "", "b");
  const detailB = makeDetail(bookB, [makeChapter("g1", "Shapes", ["p5"])], [grouped, orphan]);
  api.list.mockResolvedValue({ books: [bookA, bookB] });
  api.get.mockImplementation(async (id: string) => (id === "b" ? detailB : detailA));
  viewPicker();
  await screen.findByRole("button", { name: "Linear Equations" });
  fireEvent.click(screen.getByRole("button", { name: /Geometry Primer/ }));
  expect(api.get).toHaveBeenCalledWith("b");
  expect(await screen.findByRole("button", { name: /Unassigned pages/ })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Unassigned pages/ }));
  expect(screen.getByText("1 chapters selected")).toBeTruthy();
});

it("Clear empties a seeded selection and Apply sends an empty list", async () => {
  api.list.mockResolvedValue({ books: [bookA] });
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  viewPicker([seededPageOne], onApply);
  await screen.findByRole("button", { name: "Linear Equations" });
  expect(screen.getByText("1 chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getByText("No chapters selected")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(onApply).toHaveBeenCalledExactlyOnceWith([]);
});

it("Close dismisses the picker without applying", async () => {
  api.list.mockResolvedValue({ books: [bookA] });
  api.get.mockResolvedValue(detailA);
  const onApply = vi.fn();
  const onClose = vi.fn();
  viewPicker([], onApply, onClose);
  await screen.findByRole("button", { name: "Linear Equations" });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onApply).not.toHaveBeenCalled();
});
