import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

const api = vi.hoisted(() => ({
  getEpubPairSession: vi.fn(async () => ({
    pairing_id: "pair1",
    english_material_id: "m1",
    chinese_material_id: "m2",
    opposite_material_id: "m2",
    opposite_language: "zh",
    opposite_title: "中文版",
  })),
  fetchEpubPairAlignment: vi.fn(async () => ({
    status: "aligned",
    granularity: "paragraph",
    degraded: false,
    excerpt: "河流刻出山谷。",
    excerpt_truncated: false,
    pairing_id: "pair1",
    opposite_material_id: "m2",
    opposite_title: "中文版",
    opposite_language: "zh",
    opposite_locator: 1,
    source_locator: 1,
    source_unit: "chapter",
  })),
}));

/** The EPUB view is stubbed down to "report this selection upward". */
const view = vi.hoisted(() => ({
  select: null as null | ((payload: unknown) => void),
}));

vi.mock("@/lib/reading-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...api,
  fetchExport: vi.fn(),
  getMaterial: vi.fn(async () => null),
  getReadingPosition: vi.fn(async () => ({ locator: 1, source_anchor: "" })),
  saveReadingPosition: vi.fn(),
}));

vi.mock("@/components/reading/EpubDocumentView", () => ({
  EpubDocumentView: ({
    onSelection,
  }: {
    onSelection: (payload: unknown) => void;
  }) => {
    view.select = onSelection;
    return <div data-testid="epub" />;
  },
}));

vi.mock("@/components/reading/TextUnitView", () => ({
  TextUnitView: () => null,
  unitLabel: () => "chapter",
}));

vi.mock("@/components/reading/AnnotationList", () => ({
  AnnotationList: () => null,
}));

vi.mock("@/lib/auth", () => ({
  fetchAuthStatus: vi.fn(async () => null),
}));

const material = {
  material_id: "m1",
  title: "Valley Shapes",
  filename: "valley.epub",
  unit: "chapter",
  mime: "application/epub+zip",
  render_mode: "epub",
  has_raw_view: true,
  unit_count: 2,
  unit_refs: [{ locator: 1, title: "Water" }, { locator: 2, title: "Stone" }],
};

vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({
    material,
    annotations: [],
    loading: false,
    error: "",
    openMaterial: vi.fn(),
    closeMaterial: vi.fn(),
    saveMark: vi.fn(),
    removeMark: vi.fn(),
    mergeMark: vi.fn(),
    dismissError: vi.fn(),
    setError: vi.fn(),
    reportViewport: vi.fn(),
  }),
}));

const { ReaderPane } = await import("@/components/reading/ReaderPane");

function selectParagraph(quote = "Rivers carve the valley.") {
  act(() =>
    view.select?.({
      locator: 1,
      quote,
      rects: [],
      anchor: { x: 100, y: 200 },
    }),
  );
}

describe("paired-edition alignment in the selection popover", () => {
  beforeEach(() => {
    api.getEpubPairSession.mockClear();
    api.fetchEpubPairAlignment.mockClear();
    api.fetchEpubPairAlignment.mockResolvedValue({
      status: "aligned",
      granularity: "paragraph",
      degraded: false,
      excerpt: "河流刻出山谷。",
      excerpt_truncated: false,
      pairing_id: "pair1",
      opposite_material_id: "m2",
      opposite_title: "中文版",
      opposite_language: "zh",
      opposite_locator: 1,
      source_locator: 1,
      source_unit: "chapter",
    });
    view.select = null;
  });

  it("shows the aligned opposite paragraph without a model call", async () => {
    render(<ReaderPane onClose={() => undefined} />);

    await waitFor(() => expect(view.select).not.toBeNull());
    await waitFor(() => expect(api.getEpubPairSession).toHaveBeenCalledWith("m1"));
    selectParagraph();

    const excerpt = await screen.findByText("河流刻出山谷。");
    expect(excerpt).toBeVisible();
    expect(screen.getByText(/Paired edition · 中文版/)).toBeVisible();
    // The alignment came from the pairing endpoint, not an extension run.
    expect(api.fetchEpubPairAlignment).toHaveBeenCalledWith("m1", 1, "Rivers carve the valley.");
  });

  it("marks a partial selection as a paragraph-level fallback", async () => {
    api.fetchEpubPairAlignment.mockResolvedValue({
      status: "aligned",
      granularity: "paragraph",
      degraded: true,
      excerpt: "水往低处流。",
      excerpt_truncated: false,
      pairing_id: "pair1",
      opposite_material_id: "m2",
      opposite_title: "中文版",
      opposite_language: "zh",
      opposite_locator: 1,
      source_locator: 1,
      source_unit: "chapter",
    });

    render(<ReaderPane onClose={() => undefined} />);
    await waitFor(() => expect(view.select).not.toBeNull());
    selectParagraph("flows downhill");

    expect(await screen.findByText("水往低处流。")).toBeVisible();
    expect(
      screen.getByText("Shown as the aligned paragraph."),
    ).toBeVisible();
  });

  it("shows an explicit miss instead of unrelated text", async () => {
    api.fetchEpubPairAlignment.mockResolvedValue({
      status: "paragraph_unaligned",
      granularity: "",
      degraded: false,
      excerpt: "",
      excerpt_truncated: false,
      pairing_id: "pair1",
      opposite_material_id: "m2",
      opposite_title: "中文版",
      opposite_language: "zh",
      opposite_locator: 0,
      source_locator: 1,
      source_unit: "chapter",
    });

    render(<ReaderPane onClose={() => undefined} />);
    await waitFor(() => expect(view.select).not.toBeNull());
    selectParagraph();

    expect(
      await screen.findByText(
        "No aligned passage was found in the paired edition.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("河流刻出山谷。")).not.toBeInTheDocument();
  });

  it("keeps the popover single-edition when no pairing is confirmed", async () => {
    api.getEpubPairSession.mockResolvedValue(null as never);

    render(<ReaderPane onClose={() => undefined} />);
    await waitFor(() => expect(view.select).not.toBeNull());
    selectParagraph();

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Annotate selection" })).toBeVisible(),
    );
    expect(
      screen.queryByText(/Paired edition/),
    ).not.toBeInTheDocument();
    expect(api.fetchEpubPairAlignment).not.toHaveBeenCalled();
  });
});
