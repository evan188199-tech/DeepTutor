import React from "react";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReaderPane } from "@/components/reading/ReaderPane";
import { READER_TURN_END_EVENT } from "@/lib/reading-reader-action";

// A citation aimed at another material makes the turn-end safety net call
// `getMaterial` — an effect that stays observable even after the pane is gone.
const api = vi.hoisted(() => ({
  getMaterial: vi.fn(),
}));

const material = {
  material_id: "m-1",
  title: "A Book",
  render_mode: "text",
  unit: "section",
  unit_count: 100,
  unit_refs: [],
  has_raw_view: false,
  status: "ready",
  source_kind: "upload",
  extractor: "",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

vi.mock("@/context/ReadingContext", () => ({
  useReading: () => ({
    material,
    annotations: [],
    loading: false,
    error: "",
    openMaterial: vi.fn(async () => true),
    closeMaterial: vi.fn(),
    saveMark: vi.fn(),
    removeMark: vi.fn(),
    mergeMark: vi.fn(),
    dismissError: vi.fn(),
    setError: vi.fn(),
    reportViewport: vi.fn(),
  }),
}));

vi.mock("@/lib/reading-api", () => ({
  fetchExport: vi.fn(),
  getMaterial: api.getMaterial,
  getReadingPosition: vi.fn(async () => ({ locator: 1 })),
  saveReadingPosition: vi.fn(async () => undefined),
  listReadingExtensions: vi.fn(async () => []),
}));

vi.mock("@/components/reading/TextUnitView", () => ({
  unitLabel: () => "section",
  TextUnitView: () => <div>text view</div>,
}));

function mountCitedAnswer() {
  const article = document.createElement("div");
  article.setAttribute("role", "article");
  article.innerHTML =
    '<a href="#dt-material-0123456789abcdef-locator-3">p.3</a>';
  document.body.appendChild(article);
  return article;
}

function endTurn() {
  window.dispatchEvent(
    new CustomEvent(READER_TURN_END_EVENT, { detail: { moved: false } }),
  );
}

describe("the turn-end citation safety net", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.getMaterial.mockReset();
    api.getMaterial.mockResolvedValue({
      material_id: "0123456789abcdef",
      revision: 1,
      title: "Other book",
      filename: "other.epub",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("follows the last answer's citation once the turn closes", async () => {
    const article = mountCitedAnswer();
    const view = render(<ReaderPane onClose={vi.fn()} />);

    act(() => endTurn());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(api.getMaterial).toHaveBeenCalledTimes(1);
    view.unmount();
    article.remove();
  });

  it("does not navigate a citation after the pane unmounts", async () => {
    const article = mountCitedAnswer();
    const view = render(<ReaderPane onClose={vi.fn()} />);

    act(() => endTurn());
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(api.getMaterial).not.toHaveBeenCalled();
    article.remove();
  });
});
