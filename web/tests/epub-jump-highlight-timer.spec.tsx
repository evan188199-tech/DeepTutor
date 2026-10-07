import React from "react";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  const section = {
    href: "one.xhtml",
    load: vi.fn(async () => undefined),
    find: vi.fn(() => [{ cfi: "epubcfi(/6/2!/4/2)" }]),
  };
  return {
    rendition,
    section,
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
    spine: { get: () => fixture.section },
    locations: fixture.locations,
    load: vi.fn(),
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

const props = {
  materialId: "book",
  unitCount: 1,
  unitRefs: [] as Array<{ locator: number; source_href: string; title: string }>,
  annotations: [] as never[],
  onSelection: () => undefined,
};

describe("the jump highlight removal timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("removes a quoted jump's highlight after the dwell", async () => {
    const { rerender } = render(
      <EpubDocumentView {...props} jump={null} />,
    );
    await act(async () => {});
    expect(fixture.renderTo).toHaveBeenCalled();

    rerender(
      <EpubDocumentView
        {...props}
        jump={{ locator: 1, quote: "needle", nonce: 1 }}
      />,
    );
    await act(async () => {});
    expect(fixture.rendition.annotations.highlight).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2300);
    });
    expect(fixture.rendition.annotations.remove).toHaveBeenCalledTimes(1);
    expect(fixture.rendition.annotations.remove).toHaveBeenCalledWith(
      "epubcfi(/6/2!/4/2)",
      "highlight",
    );
  });

  it("drops a superseded jump's removal timer when the jump changes", async () => {
    const { rerender } = render(
      <EpubDocumentView {...props} jump={null} />,
    );
    await act(async () => {});

    rerender(
      <EpubDocumentView
        {...props}
        jump={{ locator: 1, quote: "needle", nonce: 1 }}
      />,
    );
    await act(async () => {});
    expect(fixture.rendition.annotations.highlight).toHaveBeenCalledTimes(1);

    // Retarget before the first dwell elapses: only the newest jump's timer
    // may remove the highlight.
    rerender(
      <EpubDocumentView
        {...props}
        jump={{ locator: 1, quote: "needle", nonce: 2 }}
      />,
    );
    await act(async () => {});
    expect(fixture.rendition.annotations.highlight).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2300);
    });
    expect(fixture.rendition.annotations.remove).toHaveBeenCalledTimes(1);
  });
});
