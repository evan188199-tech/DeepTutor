import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const fixture = vi.hoisted(() => {
  const rendition = {
    display: vi.fn(async (_target?: string) => undefined),
    currentLocation: vi.fn(() => ({ start: { cfi: "epubcfi(/6/2)" } })),
    next: vi.fn(async () => undefined),
    prev: vi.fn(async () => undefined),
    resize: vi.fn(),
    spread: vi.fn(),
    destroy: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    annotations: { highlight: vi.fn(), remove: vi.fn() },
    hooks: { content: { register: vi.fn() } },
    themes: {
      registerCss: vi.fn(),
      select: vi.fn(),
      fontSize: vi.fn(),
      override: vi.fn(),
    },
  };
  return {
    rendition,
    locations: {
      generate: vi.fn(async () => []),
      percentageFromCfi: vi.fn((): number | null => null),
    },
    renderTo: vi.fn(() => rendition),
    apiFetch: vi.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(8),
    })),
  };
});

vi.mock("epubjs", () => ({
  default: () => ({
    open: async () => undefined,
    ready: Promise.resolve(),
    renderTo: fixture.renderTo,
    spine: { get: () => ({ href: "one.xhtml" }) },
    locations: fixture.locations,
    destroy: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({ apiFetch: fixture.apiFetch }));
vi.mock("@/lib/reading-api", () => ({
  rawMaterialUrl: () => "/api/reading/materials/book/raw",
  renderMaterialUrl: () => "/api/reading/materials/book/render",
  getReadingPosition: async () => ({ locator: 1 }),
  saveReadingPosition: vi.fn(async () => undefined),
}));

import { EpubDocumentView } from "@/components/reading/EpubDocumentView";

let publisherParagraph: HTMLParagraphElement | null = null;
let themeStyle: HTMLStyleElement | null = null;

beforeEach(() => {
  localStorage.removeItem("dt.reader.textPreferences");
  fixture.locations.percentageFromCfi.mockReturnValue(null);
  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/2)" },
  });
  fixture.rendition.themes.registerCss.mockReset();
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 900,
    bottom: 600,
    width: 900,
    height: 600,
    toJSON: () => ({}),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  publisherParagraph?.remove();
  themeStyle?.remove();
  publisherParagraph = null;
  themeStyle = null;
});

it("opens a wide reader as a two-page spread and keeps the CFI when switching layouts", async () => {
  render(
    <EpubDocumentView
      materialId="book"
      unitCount={1}
      unitRefs={[]}
      annotations={[]}
      jump={null}
      onSelection={() => undefined}
    />,
  );

  await waitFor(() =>
    expect(fixture.renderTo).toHaveBeenCalledWith(
      expect.any(Element),
      expect.objectContaining({ spread: "always", minSpreadWidth: 900 }),
    ),
  );
  const paper = document.querySelector(".dt-epub-book");
  expect(paper?.getAttribute("data-spread")).toBe("double");
  expect((paper as HTMLElement).style.maxWidth).toContain("168ch");

  // The manual control remains an opt-out of the responsive spread.
  fireEvent.click(screen.getByRole("button", { name: "Switch to single-page view" }));

  await waitFor(() => expect(fixture.rendition.spread).toHaveBeenCalledWith("none", 900));
  await waitFor(() =>
    expect(fixture.rendition.resize).toHaveBeenCalledWith(900, 600),
  );
  expect(fixture.rendition.display).toHaveBeenCalledWith("epubcfi(/6/2)");
  expect(paper?.getAttribute("data-spread")).toBe("single");
  expect((paper as HTMLElement).style.maxWidth).toContain("84ch");
  expect(JSON.parse(localStorage.getItem("dt.reader.textPreferences") || "{}"))
    .toMatchObject({ spreadMode: "none" });
});

it("repaginates from the real available width when the reader pane narrows (#1236)", async () => {
  const resizeCallbacks: Array<() => void> = [];
  class FakeResizeObserver {
    constructor(private readonly callback: () => void) {}
    observe() {
      resizeCallbacks.push(this.callback);
    }
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  render(
    <EpubDocumentView
      materialId="book"
      unitCount={1}
      unitRefs={[]}
      annotations={[]}
      jump={null}
      onSelection={() => undefined}
    />,
  );

  await waitFor(() =>
    expect(fixture.renderTo).toHaveBeenCalledWith(
      expect.any(Element),
      expect.objectContaining({ spread: "always" }),
    ),
  );
  const paper = document.querySelector(".dt-epub-book");
  expect(paper?.getAttribute("data-spread")).toBe("double");

  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 640,
    bottom: 600,
    width: 640,
    height: 600,
    toJSON: () => ({}),
  });
  resizeCallbacks.forEach((notify) => notify());

  await waitFor(() =>
    expect(fixture.rendition.spread).toHaveBeenCalledWith("none", 900),
  );
  await waitFor(() =>
    expect(fixture.rendition.resize).toHaveBeenCalledWith(640, 600),
  );
  expect(fixture.rendition.display).toHaveBeenCalledWith("epubcfi(/6/2)");
  expect(paper?.getAttribute("data-spread")).toBe("single");
});

it("resolves outline anchors through epub.js spine-relative hrefs", async () => {
  const props = {
    materialId: "book",
    unitCount: 1,
    unitRefs: [],
    annotations: [],
    jump: null,
    onSelection: () => undefined,
  };
  const { rerender } = render(<EpubDocumentView {...props} />);
  await waitFor(() => expect(fixture.renderTo).toHaveBeenCalled());

  rerender(
    <EpubDocumentView
      {...props}
      headingJump={{
        id: "publisher-anchor",
        nonce: 1,
        locator: 1,
        sourceHref: "OEBPS/one.xhtml",
      }}
    />,
  );

  await waitFor(() =>
    expect(fixture.rendition.display).toHaveBeenCalledWith(
      "one.xhtml#publisher-anchor",
    ),
  );
  expect(fixture.rendition.display).not.toHaveBeenCalledWith(
    "OEBPS/one.xhtml#publisher-anchor",
  );
});

it("keeps publisher typography while supplying root fallbacks and image bounds (#1236)", async () => {
  publisherParagraph = document.createElement("p");
  publisherParagraph.innerHTML =
    '<span style="font-family: monospace; font-size: 11px; color: #000">Publisher text</span>';
  document.body.appendChild(publisherParagraph);
  themeStyle = document.createElement("style");
  document.head.appendChild(themeStyle);
  fixture.rendition.themes.registerCss.mockImplementation((_name, css) => {
    themeStyle!.textContent = css;
  });
  localStorage.setItem(
    "dt.reader.textPreferences",
    JSON.stringify({ fontSize: 23, serif: false, readerTheme: "night", spreadMode: "auto" }),
  );
  render(
    <EpubDocumentView
      materialId="book"
      unitCount={1}
      unitRefs={[]}
      annotations={[]}
      jump={null}
      onSelection={() => undefined}
    />,
  );

  await waitFor(() =>
    expect(fixture.renderTo).toHaveBeenCalledWith(
      expect.any(Element),
      expect.objectContaining({ spread: "always" }),
    ),
  );
  const publisherSpan = publisherParagraph.querySelector("span")!;
  await waitFor(() =>
    expect(getComputedStyle(publisherSpan).color).toBe("rgb(0, 0, 0)"),
  );
  // Publisher declarations survive: the span keeps its own type and ink.
  expect(getComputedStyle(publisherSpan).fontFamily).toBe("monospace");
  expect(getComputedStyle(publisherSpan).fontSize).toBe("11px");
  // The theme supplies only root fallbacks on <body>, never per-element ink.
  const bodyStyle = getComputedStyle(document.body);
  expect(bodyStyle.fontFamily).toContain("ui-sans-serif");
  expect(bodyStyle.fontSize).toBe("23px");
  expect(bodyStyle.color).toBe("rgb(232, 229, 223)");
  expect(bodyStyle.backgroundColor).toBe("rgb(22, 24, 29)");
  // Overflowing images stay constrained inside the page.
  expect(themeStyle!.textContent).toContain(
    "img { max-width: 100% !important",
  );
  expect(fixture.rendition.themes.fontSize).toHaveBeenCalledWith("23px");
  fireEvent.click(screen.getByRole("button", { name: "Reset reading display" }));
  await waitFor(() =>
    expect(getComputedStyle(publisherSpan).color).toBe("rgb(0, 0, 0)"),
  );
  expect(getComputedStyle(publisherSpan).fontFamily).toBe("monospace");
  expect(JSON.parse(localStorage.getItem("dt.reader.textPreferences") || "{}"))
    .toMatchObject({ fontSize: 17, readerTheme: "auto", spreadMode: "auto" });
});

it("drops a previous book's pending CFI before the next book relayout", async () => {
  const onSelection = () => undefined;
  const props = {
    unitCount: 1,
    unitRefs: [],
    annotations: [],
    jump: null,
    onSelection,
  };
  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/old-book)" },
  });
  const { rerender } = render(
    <EpubDocumentView materialId="old-book" {...props} />,
  );
  await waitFor(() => expect(fixture.renderTo).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Switch to single-page view" }));
  await waitFor(() => expect(fixture.rendition.spread).toHaveBeenCalledWith("none", 900));
  const oldCfiDisplays = fixture.rendition.display.mock.calls.filter(
    ([cfi]) => cfi === "epubcfi(/6/old-book)",
  ).length;

  fixture.rendition.currentLocation.mockReturnValue({
    start: { cfi: "epubcfi(/6/new-book)" },
  });
  rerender(<EpubDocumentView materialId="new-book" {...props} />);
  await waitFor(() => expect(fixture.renderTo).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(fixture.rendition.display).toHaveBeenLastCalledWith(
      "epubcfi(/6/new-book)",
    ),
  );
  expect(
    fixture.rendition.display.mock.calls.filter(
      ([cfi]) => cfi === "epubcfi(/6/old-book)",
    ),
  ).toHaveLength(oldCfiDisplays);
});

it("reports CFI progress inside the final chapter, including one-chapter books (#1673)", async () => {
  const progress = vi.fn();
  const visible = vi.fn();
  render(<EpubDocumentView materialId="book" unitCount={1}
    unitRefs={[{ locator: 1, source_href: "one.xhtml", title: "Only chapter" }]}
    annotations={[]} jump={null} onSelection={() => undefined}
    onProgressChange={progress} onVisibleLocatorChange={visible} />);
  await waitFor(() => expect(fixture.locations.generate).toHaveBeenCalledWith(1600));
  const relocated = fixture.rendition.on.mock.calls.find(([event]) => event === "relocated")?.[1] as unknown as (location: unknown) => void;
  fixture.locations.percentageFromCfi.mockReturnValue(0.32);
  relocated({ start: { href: "one.xhtml", cfi: "epubcfi(/6/2)", percentage: 0.32 }, atEnd: false });
  expect(visible).toHaveBeenLastCalledWith(1);
  expect(progress).toHaveBeenLastCalledWith(0.32);
  fixture.locations.percentageFromCfi.mockReturnValue(null);
  relocated({ start: { href: "one.xhtml", cfi: "epubcfi(/6/2)" } });
  expect(progress).toHaveBeenLastCalledWith(null);
  relocated({ start: { href: "one.xhtml", cfi: "epubcfi(/6/2)" }, atEnd: true });
  expect(progress).toHaveBeenLastCalledWith(1);
});
