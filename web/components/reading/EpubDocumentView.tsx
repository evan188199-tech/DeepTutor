"use client";

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "@/lib/api";
import {
  getReadingPosition,
  renderMaterialUrl,
  saveReadingPosition,
  type AnnotationItem,
  type UnitReference,
} from "@/lib/reading-api";
import {
  allowsEpubPageTurn,
  directionForEpubLayout,
  epubPaperMaxWidth,
  EPUB_SPREAD_MIN_READER_WIDTH_PX,
  locatorForEpubHref,
  renditionSpreadForEpubMode,
  resolveEpubPageTurnSwipe,
  resolveEpubSpreadLayout,
  type EpubPageTurnDirection,
  type EpubSpreadLayout,
} from "@/lib/epub-page-turn";
import { extractEpubHeadings, type ReaderHeading } from "@/lib/reading-outline";
import {
  DEFAULT_READER_DISPLAY_PREFERENCES,
  loadReaderDisplayPreferences,
  saveReaderDisplayPreferences,
  type ReaderDisplayPreferences,
} from "@/lib/reading-display-preferences";
import { cleanQuote } from "@/lib/reading-selection";
import type { JumpRequest, SelectionPayload } from "./PdfDocumentView";
import { ReaderDisplayControls } from "./ReaderDisplayControls";

type EpubLocation = {
  start?: { cfi?: string; href?: string; percentage?: number };
  atEnd?: boolean;
};

type EpubContents = {
  document?: Document;
  window?: Window;
};

type EpubAnnotationLayer = {
  highlight: (
    cfi: string,
    data?: Record<string, string>,
    callback?: () => void,
    className?: string,
    styles?: Record<string, string>,
  ) => void;
  remove: (cfi: string, type?: string) => void;
};

type EpubRendition = {
  display: (target?: string) => Promise<unknown>;
  currentLocation: () => EpubLocation | undefined;
  next: () => Promise<unknown>;
  prev: () => Promise<unknown>;
  resize: (width: number, height: number) => void;
  spread: (mode: "none" | "always" | "auto", min?: number) => void;
  destroy: () => void;
  on: (event: string, callback: (...args: unknown[]) => void) => void;
  off: (event: string, callback: (...args: unknown[]) => void) => void;
  annotations: EpubAnnotationLayer;
  hooks: {
    content: {
      register: (callback: (contents: EpubContents) => void) => void;
    };
  };
  themes: {
    registerCss: (name: string, css: string) => void;
    select: (name: string) => void;
    fontSize: (size: string) => void;
    override: (name: string, value: string, priority?: boolean) => void;
  };
};

type EpubSection = {
  href?: string;
  load: (loader: (path: string) => Promise<unknown>) => Promise<unknown>;
  find: (query: string) => Array<{ cfi: string }>;
};

type EpubBook = {
  open: (input: ArrayBuffer) => Promise<unknown>;
  ready: Promise<unknown>;
  package?: { metadata?: { direction?: string } };
  load: (path: string) => Promise<unknown>;
  spine: { get: (target: string | number) => EpubSection | undefined };
  locations?: {
    percentageFromCfi?: (cfi: string) => number | null;
    generate?: (characters: number) => Promise<unknown>;
  };
  renderTo: (
    element: Element,
    options: Record<string, unknown>,
  ) => EpubRendition;
  destroy: () => void;
};

const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "rgba(250, 220, 90, 0.55)",
  green: "rgba(140, 219, 148, 0.55)",
  blue: "rgba(122, 192, 250, 0.55)",
  pink: "rgba(250, 161, 199, 0.55)",
  purple: "rgba(199, 174, 250, 0.55)",
};

function applyEpubDisplayPreferences(
  rendition: EpubRendition,
  preferences: ReaderDisplayPreferences,
  layout: EpubSpreadLayout,
) {
  const fontFamily = preferences.serif
    ? "ui-serif, Georgia, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', serif"
    : "ui-sans-serif, system-ui, -apple-system, 'PingFang SC', sans-serif";
  const paper =
    preferences.readerTheme === "sepia"
      ? { background: "#f4ecd8", color: "#473c2c" }
      : preferences.readerTheme === "night"
        ? { background: "#16181d", color: "#e8e5df" }
        : null;

  // Publisher styles stay authoritative in the default day theme: the theme
  // supplies only a root fallback font on <body>, plus image bounds and
  // overflow protection. Forcing font-family onto every paragraph and span
  // replaced publisher typography (#1236). Non-default themes must still
  // re-ink the text: EPUBs ship hard-coded black that is unreadable on sepia
  // or dark paper, so the color override from #1447 stays for those themes
  // while publisher fonts survive everywhere.
  const ink = paper
    ? `body { background-color: ${paper.background} !important; color: ${paper.color} !important; }
     body :is(p, span, div, li, blockquote) { color: ${paper.color} !important; }
     body :is(h1, h2, h3, h4, h5, h6) { color: ${paper.color} !important; }`
    : "";
  rendition.themes.registerCss(
    "deeptutor",
    `body { font-family: ${fontFamily}; font-size: ${preferences.fontSize}px; }
     ${ink}
     img { max-width: 100% !important; max-height: 85vh !important; height: auto !important; object-fit: contain !important; }
     body * { vertical-align: baseline; }`,
  );
  rendition.themes.select("deeptutor");
  rendition.themes.fontSize(`${preferences.fontSize}px`);
  // epub.js sets column-width but leaves column-count automatic. A wide pane
  // can fit a third visible column after the sidebar collapses (#1447).
  rendition.themes.override(
    "column-count",
    layout === "double" ? "2" : "1",
    true,
  );
}

/** The real available reader width, tolerating test layouts without layout. */
function elementWidth(element: HTMLElement): number {
  return (
    element.clientWidth || Math.round(element.getBoundingClientRect().width)
  );
}

/**
 * The width a paper leaf can actually occupy inside the book area. The desk
 * padding around the paper is not part of the host epub.js measures, so the
 * spread boundary must be applied to the content-box width, not clientWidth
 * (#1236).
 */
function availableReaderWidth(area: HTMLElement): number {
  const styles = window.getComputedStyle(area);
  const padding = (value: string) => Number.parseFloat(value) || 0;
  return (
    elementWidth(area) -
    padding(styles.paddingLeft) -
    padding(styles.paddingRight)
  );
}

export interface EpubDocumentViewProps {
  materialId: string;
  unitCount: number;
  unitRefs: UnitReference[];
  annotations: AnnotationItem[];
  jump: JumpRequest | null;
  highlightedAnnotationId?: string | null;
  onSelection: (payload: SelectionPayload | null) => void;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  onVisibleLocatorChange?: (locator: number) => void;
  onProgressChange?: (percentage: number | null) => void;
  onHeadingsChange?: (headings: ReaderHeading[]) => void;
  headingJump?: {
    id: string;
    nonce: number;
    locator?: number;
    sourceHref?: string;
  } | null;
  onError?: (message: string) => void;
}

/** Source-faithful, paginated EPUB renderer aligned to server locators. */
export function EpubDocumentView({
  materialId,
  unitCount,
  unitRefs,
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
  onProgressChange,
  onHeadingsChange,
  headingJump,
  onError,
}: EpubDocumentViewProps) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const bookAreaRef = useRef<HTMLDivElement | null>(null);
  const bookRef = useRef<EpubBook | null>(null);
  const renditionRef = useRef<EpubRendition | null>(null);
  const isRtlRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderedAnchorsRef = useRef<string[]>([]);
  const refsRef = useRef(unitRefs);
  const annotationClickRef = useRef(onAnnotationClick);
  const visibleChangeRef = useRef(onVisibleLocatorChange);
  const progressChangeRef = useRef(onProgressChange);
  const headingsChangeRef = useRef(onHeadingsChange);
  const headingsByLocatorRef = useRef<Map<number, ReaderHeading[]>>(new Map());
  const errorRef = useRef(onError);
  const locatorRef = useRef(1);
  const preferencesRef = useRef(DEFAULT_READER_DISPLAY_PREFERENCES);
  const spreadLayoutRef = useRef<EpubSpreadLayout>("single");
  const relayoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const relayoutAnchorRef = useRef<string | undefined>(undefined);
  const [preferences, setPreferences] = useState<ReaderDisplayPreferences>(
    DEFAULT_READER_DISPLAY_PREFERENCES,
  );
  const [spreadLayout, setSpreadLayout] = useState<EpubSpreadLayout>("single");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    const saved = loadReaderDisplayPreferences();
    preferencesRef.current = saved;
    setPreferences(saved);
  }, []);

  const updatePreferences = useCallback(
    (next: Partial<ReaderDisplayPreferences>) => {
      const merged = { ...preferencesRef.current, ...next };
      preferencesRef.current = merged;
      setPreferences(merged);
      saveReaderDisplayPreferences(merged);
    },
    [],
  );

  // Repaginate from the real available size whenever side panels, the window
  // or the preferences change. The layout is decided from the book area (the
  // pane width the reader actually owns), not from the paper it renders into,
  // so the width cap on the paper can never lock the layout in place (#1236).
  const relayout = useCallback(() => {
    const rendition = renditionRef.current;
    const area = bookAreaRef.current;
    const host = hostRef.current;
    if (!rendition || !area || !host) return;
    const nextLayout = resolveEpubSpreadLayout(
      preferencesRef.current.spreadMode,
      availableReaderWidth(area),
    );
    const bounds = host.getBoundingClientRect();
    const width = Math.round(bounds.width);
    const height = Math.round(bounds.height);
    if (!width || !height) return;
    if (spreadLayoutRef.current !== nextLayout) {
      spreadLayoutRef.current = nextLayout;
      setSpreadLayout(nextLayout);
      rendition.spread(
        renditionSpreadForEpubMode(nextLayout),
        EPUB_SPREAD_MIN_READER_WIDTH_PX,
      );
      applyEpubDisplayPreferences(
        rendition,
        preferencesRef.current,
        nextLayout,
      );
    }
    const cfi =
      relayoutAnchorRef.current ?? rendition.currentLocation()?.start?.cfi;
    relayoutAnchorRef.current = undefined;
    rendition.resize(width, height);
    if (cfi) {
      void rendition.display(cfi).catch(() => {
        // A stale publisher CFI must not break the current reading page.
      });
    }
  }, []);

  const scheduleRelayout = useCallback(
    (anchor?: string) => {
      if (anchor) relayoutAnchorRef.current = anchor;
      if (relayoutTimerRef.current) clearTimeout(relayoutTimerRef.current);
      relayoutTimerRef.current = setTimeout(() => {
        relayoutTimerRef.current = null;
        relayout();
      }, 100);
    },
    [relayout],
  );

  useEffect(() => {
    refsRef.current = unitRefs;
  }, [unitRefs]);
  useEffect(() => {
    annotationClickRef.current = onAnnotationClick;
  }, [onAnnotationClick]);
  useEffect(() => {
    progressChangeRef.current = onProgressChange;
  }, [onProgressChange]);

  useEffect(() => {
    visibleChangeRef.current = onVisibleLocatorChange;
  }, [onVisibleLocatorChange]);
  useEffect(() => {
    headingsChangeRef.current = onHeadingsChange;
  }, [onHeadingsChange]);
  useEffect(() => {
    headingsByLocatorRef.current.clear();
    headingsChangeRef.current?.([]);
  }, [materialId]);
  useEffect(() => {
    errorRef.current = onError;
  }, [onError]);

  const turnPage = useCallback((direction: EpubPageTurnDirection) => {
    const rendition = renditionRef.current;
    if (!rendition) return;
    const physical = directionForEpubLayout(direction, isRtlRef.current);
    void (physical === "next" ? rendition.next() : rendition.prev());
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    let rendition: EpubRendition | null = null;
    let book: EpubBook | null = null;

    const onRelocated = (raw: unknown) => {
      if (cancelled) return;
      const location = raw as EpubLocation;
      const href = location.start?.href ?? "";
      const nextLocator = locatorForEpubHref(href, refsRef.current) || 1;
      const cfi = location.start?.cfi ?? "";
      const observed = location.atEnd ? 1
        : book?.locations?.percentageFromCfi?.(cfi) ?? location.start?.percentage;
      const percentage = typeof observed === "number" && Number.isFinite(observed)
        ? Math.min(1, Math.max(0, observed)) : null;
      // A spine entry is a chapter, not a fraction of the whole text (#1673).
      // Until CFI locations are ready, publish uncertainty instead of 100%.
      progressChangeRef.current?.(percentage);
      locatorRef.current = nextLocator;
      visibleChangeRef.current?.(nextLocator);
      headingsChangeRef.current?.(
        headingsByLocatorRef.current.get(nextLocator) ?? [],
      );
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        void saveReadingPosition(materialId, {
          locator: nextLocator,
          source_anchor: cfi,
          ...(percentage === null ? {} : { percentage }),
        }).catch(() => {
          // Reading must continue when a background progress write fails.
        });
      }, 350);
    };

    const onSelected = (rawCfi: unknown, rawContents: unknown) => {
      const cfi = String(rawCfi || "");
      const contents = rawContents as EpubContents;
      const selection = contents.window?.getSelection?.();
      const quote = cleanQuote(selection?.toString() ?? "");
      if (!quote || !cfi) return;
      const rect = selection?.rangeCount
        ? selection.getRangeAt(0).getBoundingClientRect()
        : null;
      onSelection({
        locator:
          locatorForEpubHref(
            (contents.document?.location?.pathname ?? "").replace(/^\//, ""),
            refsRef.current,
          ) || locatorRef.current,
        quote,
        rects: [],
        sourceAnchor: cfi,
        anchor: rect
          ? { x: rect.left + rect.width / 2, y: rect.top }
          : { x: 0, y: 0 },
      });
    };

    const onRenditionKey = (rawEvent: unknown) => {
      const event = rawEvent as KeyboardEvent;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)
        return;
      if (!allowsEpubPageTurn(event.target)) return;
      event.preventDefault();
      turnPage(event.key === "ArrowLeft" ? "previous" : "next");
    };

    const installContentSafety = (rawContents: unknown) => {
      const contents = rawContents as EpubContents;
      const doc = contents.document;
      if (!doc?.body || doc.body.dataset.dtReaderReady === "true") return;
      doc.body.dataset.dtReaderReady = "true";
      const href = (doc.location?.pathname ?? "").replace(/^\//, "");
      const locator =
        locatorForEpubHref(href, refsRef.current) || locatorRef.current;
      const sourceHref = bookRef.current?.spine.get(locator - 1)?.href || href;
      const headingElements = Array.from(
        doc.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6"),
      ).filter((element) => (element.textContent ?? "").trim());
      const headings = extractEpubHeadings(
        headingElements,
        locator,
        sourceHref,
      );
      headingElements.forEach((element, index) => {
        element.id = headings[index].id;
      });
      headingsByLocatorRef.current.set(locator, headings);
      if (locator === locatorRef.current) headingsChangeRef.current?.(headings);
      let gesture: { x: number; y: number } | null = null;
      doc.addEventListener(
        "touchstart",
        (event) => {
          gesture = null;
          if (event.touches.length !== 1) return;
          const touch = event.touches[0];
          if (!allowsEpubPageTurn(touch.target)) return;
          gesture = { x: touch.clientX, y: touch.clientY };
        },
        { passive: true },
      );
      doc.addEventListener(
        "touchend",
        (event) => {
          if (!gesture || event.changedTouches.length !== 1) return;
          const start = gesture;
          gesture = null;
          if ((doc.getSelection?.()?.toString() ?? "").trim()) return;
          const touch = event.changedTouches[0];
          const direction = resolveEpubPageTurnSwipe(
            start.x,
            start.y,
            touch.clientX,
            touch.clientY,
          );
          if (!direction) return;
          event.preventDefault();
          turnPage(direction);
        },
        { passive: false },
      );
      doc.addEventListener("click", (event) => {
        const anchor = (event.target as Element | null)?.closest?.("a[href]");
        const href = anchor?.getAttribute("href") ?? "";
        if (!/^https?:\/\//i.test(href)) return;
        event.preventDefault();
        window.open(href, "_blank", "noopener,noreferrer");
      });
    };

    void (async () => {
      try {
        setLoading(true);
        setLoadError("");
        const [module, response, position] = await Promise.all([
          import("epubjs"),
          apiFetch(renderMaterialUrl(materialId), { cache: "no-store" }),
          getReadingPosition(materialId).catch(() => null),
        ]);
        if (!response.ok) throw new Error(t("Could not load this section."));
        const bytes = await response.arrayBuffer();
        if (cancelled) return;
        const createBook = module.default as unknown as (
          input?: ArrayBuffer,
        ) => EpubBook;
        // Calling epubjs with bytes in its constructor swallows open errors and
        // leaves `ready` pending forever. Open explicitly so damaged packages
        // reach the reader's error state instead of an endless skeleton.
        book = createBook();
        bookRef.current = book;
        await book.open(bytes);
        await book.ready;
        if (cancelled) return;
        isRtlRef.current = book.package?.metadata?.direction === "rtl";
        const initialLayout = resolveEpubSpreadLayout(
          preferencesRef.current.spreadMode,
          availableReaderWidth(bookAreaRef.current ?? host),
        );
        spreadLayoutRef.current = initialLayout;
        setSpreadLayout(initialLayout);
        rendition = book.renderTo(host, {
          width: "100%",
          height: "100%",
          flow: "paginated",
          spread: renditionSpreadForEpubMode(initialLayout),
          minSpreadWidth: EPUB_SPREAD_MIN_READER_WIDTH_PX,
          allowScriptedContent: false,
        });
        renditionRef.current = rendition;
        applyEpubDisplayPreferences(
          rendition,
          preferencesRef.current,
          initialLayout,
        );
        rendition.on("relocated", onRelocated);
        rendition.on("selected", onSelected);
        rendition.on("keydown", onRenditionKey);
        rendition.hooks.content.register(installContentSafety);
        const fallbackHref =
          book.spine.get((position?.locator ?? 1) - 1)?.href ??
          refsRef.current.find(
            (ref) => ref.locator === (position?.locator ?? 1),
          )?.source_href;
        try {
          await rendition.display(
            position?.source_anchor || fallbackHref || undefined,
          );
        } catch {
          await rendition.display(
            fallbackHref ??
              book.spine.get(0)?.href ??
              refsRef.current[0]?.source_href,
          );
        }
        if (cancelled) return;
        setLoading(false);
        void book.locations?.generate?.(1600).then(() => {
          if (cancelled || !rendition) return;
          const location = rendition.currentLocation();
          if (location) onRelocated(location);
        }).catch(() => {
          // CFI navigation still works when progress cannot be calculated.
        });
      } catch (error) {
        if (cancelled) return;
        const message =
          error instanceof Error
            ? error.message
            : t("Could not load this section.");
        setLoadError(message);
        errorRef.current?.(message);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      if (relayoutTimerRef.current) clearTimeout(relayoutTimerRef.current);
      relayoutTimerRef.current = null;
      relayoutAnchorRef.current = undefined;
      if (rendition) {
        rendition.off("relocated", onRelocated);
        rendition.off("selected", onSelected);
        rendition.off("keydown", onRenditionKey);
        rendition.destroy();
      }
      book?.destroy();
      renditionRef.current = null;
      bookRef.current = null;
      host.replaceChildren();
    };
  }, [materialId, unitCount, onSelection, t, turnPage]);

  useEffect(() => {
    const rendition = renditionRef.current;
    if (!rendition || loading) return;
    applyEpubDisplayPreferences(
      rendition,
      preferences,
      spreadLayoutRef.current,
    );
    // relayout() re-reads the preference and reconciles the spread layout
    // with the current available width, keeping the visible CFI anchored.
    scheduleRelayout();
  }, [loading, preferences, scheduleRelayout]);

  useEffect(() => {
    const area = bookAreaRef.current;
    const host = hostRef.current;
    if (loading || !area || !host || !renditionRef.current) return;
    if (typeof ResizeObserver === "undefined") return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        scheduleRelayout();
      });
    });
    observer.observe(area);
    observer.observe(host);
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [loading, scheduleRelayout]);

  useEffect(() => {
    if (!headingJump || !renditionRef.current || !bookRef.current) return;
    const section = bookRef.current.spine.get(
      (headingJump.locator ?? locatorRef.current) - 1,
    );
    const sourceHref = section?.href || headingJump.sourceHref;
    if (!sourceHref) return;
    void renditionRef.current
      .display(`${sourceHref}#${headingJump.id}`)
      .catch(() => {
        // A damaged publisher anchor leaves the reader on the current page.
      });
  }, [headingJump, loading]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)
        return;
      if (!allowsEpubPageTurn(event.target)) return;
      event.preventDefault();
      turnPage(event.key === "ArrowLeft" ? "previous" : "next");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [turnPage]);

  useEffect(() => {
    const rendition = renditionRef.current;
    const book = bookRef.current;
    if (!rendition || !book) return;
    let cancelled = false;
    for (const anchor of renderedAnchorsRef.current) {
      rendition.annotations.remove(anchor, "highlight");
    }
    renderedAnchorsRef.current = [];
    void (async () => {
      for (const annotation of annotations) {
        let anchor = annotation.source_anchor;
        if (!anchor && annotation.quote) {
          const section = book.spine.get(annotation.locator - 1);
          if (section) {
            try {
              await section.load(book.load.bind(book));
              const matches = section.find(annotation.quote);
              if (matches.length === 1) anchor = matches[0].cfi;
            } catch {
              // An ambiguous legacy quote stays in the list without fake ink.
            }
          }
        }
        if (!anchor || cancelled) continue;
        renderedAnchorsRef.current.push(anchor);
        rendition.annotations.highlight(
          anchor,
          { annotationId: annotation.annotation_id },
          () => annotationClickRef.current?.(annotation),
          `dt-epub-annotation-${annotation.annotation_id}`,
          {
            fill: HIGHLIGHT_COLORS[annotation.color] ?? HIGHLIGHT_COLORS.yellow,
            "fill-opacity":
              annotation.annotation_id === highlightedAnnotationId
                ? "0.8"
                : "0.55",
          },
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [annotations, highlightedAnnotationId, unitRefs]);

  useEffect(() => {
    if (!jump || !renditionRef.current) return;
    const sectionTarget = bookRef.current?.spine.get(jump.locator - 1);
    const ref = unitRefs.find((row) => row.locator === jump.locator);
    const target = sectionTarget?.href ?? ref?.source_href;
    if (!target) return;
    void renditionRef.current.display(target).then(async () => {
      if (!jump.quote || !bookRef.current || !renditionRef.current) return;
      const section = bookRef.current.spine.get(jump.locator - 1);
      if (!section) return;
      try {
        await section.load(bookRef.current.load.bind(bookRef.current));
        const matches = section.find(jump.quote);
        if (matches.length !== 1) return;
        renditionRef.current.annotations.highlight(
          matches[0].cfi,
          {},
          undefined,
          "dt-epub-jump",
          { fill: "rgba(99, 102, 241, 0.35)" },
        );
        window.setTimeout(() => {
          renditionRef.current?.annotations.remove(matches[0].cfi, "highlight");
        }, 2200);
      } catch {
        // Reaching the requested locator is still useful if quote search fails.
      }
    });
  }, [jump, unitRefs]);

  const surface =
    preferences.readerTheme === "sepia"
      ? { background: "#f4ecd8", color: "#473c2c" }
      : preferences.readerTheme === "night"
        ? { background: "#16181d", color: "#e8e5df" }
        : { background: "var(--background)" };

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden pb-[env(safe-area-inset-bottom)]"
      style={surface}
    >
      <div className="flex shrink-0 items-center gap-2 overflow-x-auto border-b border-[var(--border)] px-2 py-2 sm:px-3">
        <ReaderDisplayControls
          preferences={preferences}
          onChange={updatePreferences}
          showSpread
        />
      </div>
      <div
        ref={bookAreaRef}
        className="dt-epub-book-area relative min-h-0 flex-1"
      >
        <div
          className="dt-epub-book"
          data-spread={spreadLayout}
          data-reader-theme={preferences.readerTheme}
          style={{
            maxWidth: epubPaperMaxWidth(spreadLayout, preferences.lineWidth),
            fontSize: `${preferences.fontSize}px`,
          }}
        >
          <div
            ref={hostRef}
            className="dt-epub-rendition h-full w-full"
            aria-label={t("Immersive reading")}
          />
          {loading && (
            <div
              className="absolute inset-0 flex items-center justify-center gap-2 text-xs"
              style={{ background: "var(--dt-epub-paper)" }}
            >
              <Loader2 size={15} className="animate-spin" />
              {t("Opening document…")}
            </div>
          )}
          {!loading && loadError && (
            <div
              role="alert"
              className="absolute inset-0 grid place-items-center p-8 text-center text-sm text-[var(--destructive)]"
            >
              {loadError}
            </div>
          )}
        </div>
        {!loadError && (
          <>
            <button
              type="button"
              onClick={() => turnPage("previous")}
              className="absolute left-2 top-1/2 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-current/20 bg-[color-mix(in_srgb,currentColor_8%,transparent)] text-inherit shadow-sm backdrop-blur transition hover:bg-[color-mix(in_srgb,currentColor_14%,transparent)]"
              aria-label={t("Previous")}
            >
              <ChevronLeft size={19} />
            </button>
            <button
              type="button"
              onClick={() => turnPage("next")}
              className="absolute right-2 top-1/2 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-current/20 bg-[color-mix(in_srgb,currentColor_8%,transparent)] text-inherit shadow-sm backdrop-blur transition hover:bg-[color-mix(in_srgb,currentColor_14%,transparent)]"
              aria-label={t("Next")}
            >
              <ChevronRight size={19} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
