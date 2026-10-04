export type EpubPageTurnDirection = "previous" | "next";
export type EpubSpreadLayout = "single" | "double";

export const EPUB_PAGE_TURN_MIN_DRAG_PX = 48;
export const EPUB_PAGE_TURN_HORIZONTAL_RATIO = 1.25;

// A two-page spread needs room for a real book: a reader wide enough for a
// desk layout and leaves that can still hold a readable line of text (#1236).
export const EPUB_SPREAD_MIN_READER_WIDTH_PX = 900;
export const EPUB_SPREAD_MIN_LEAF_WIDTH_PX = 360;

export function epubSpreadModeForWidth(readerWidth: number): EpubSpreadLayout {
  return readerWidth >= EPUB_SPREAD_MIN_READER_WIDTH_PX &&
    readerWidth / 2 >= EPUB_SPREAD_MIN_LEAF_WIDTH_PX
    ? "double"
    : "single";
}

/** Combines the user's spread preference with the real available width. */
export function resolveEpubSpreadLayout(
  preference: "none" | "auto",
  readerWidth: number,
): EpubSpreadLayout {
  if (preference === "none") return "single";
  return epubSpreadModeForWidth(readerWidth);
}

/** The epub.js `spread` value that realizes each responsive layout. */
export function renditionSpreadForEpubMode(
  layout: EpubSpreadLayout,
): "none" | "always" {
  return layout === "double" ? "always" : "none";
}

/** The centered paper surface width cap for each layout (#1236). */
export function epubPaperMaxWidth(
  layout: EpubSpreadLayout,
  lineWidth: number,
): string {
  return layout === "double"
    ? `min(100%, calc(${lineWidth * 2}ch + 6rem))`
    : `min(100%, calc(${lineWidth}ch + 4rem))`;
}

const INTERACTIVE_SELECTOR = [
  "a",
  "button",
  "input",
  "textarea",
  "select",
  "video",
  "iframe",
  "svg",
  "pre",
  "[contenteditable='true']",
  "[data-reader-no-page-turn]",
].join(",");

export function allowsEpubPageTurn(target: EventTarget | null): boolean {
  const element = target as Element | null;
  if (!element || typeof element.closest !== "function") return false;
  return !element.closest(INTERACTIVE_SELECTOR);
}

export function resolveEpubPageTurnSwipe(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
): EpubPageTurnDirection | null {
  const dx = endX - startX;
  const dy = endY - startY;
  if (Math.abs(dx) < EPUB_PAGE_TURN_MIN_DRAG_PX) return null;
  if (Math.abs(dx) <= Math.abs(dy) * EPUB_PAGE_TURN_HORIZONTAL_RATIO)
    return null;
  return dx < 0 ? "next" : "previous";
}

export function directionForEpubLayout(
  direction: EpubPageTurnDirection,
  isRtl: boolean,
): EpubPageTurnDirection {
  if (!isRtl) return direction;
  return direction === "next" ? "previous" : "next";
}

export function hrefKey(href: string): string {
  const withoutFragment = (href || "").split("#", 1)[0];
  try {
    return decodeURIComponent(withoutFragment).replace(/^\.\//, "");
  } catch {
    return withoutFragment.replace(/^\.\//, "");
  }
}

export function locatorForEpubHref(
  href: string,
  refs: Array<{ locator: number; source_href: string }>,
): number {
  const wanted = hrefKey(href);
  const exact = refs.find((ref) => hrefKey(ref.source_href) === wanted);
  if (exact) return exact.locator;
  const suffix = refs.find(
    (ref) =>
      hrefKey(ref.source_href).endsWith(`/${wanted}`) ||
      wanted.endsWith(`/${hrefKey(ref.source_href)}`),
  );
  return suffix?.locator ?? 0;
}
