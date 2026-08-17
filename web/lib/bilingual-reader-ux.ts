export function visibleGroupFromElements(
  elements: HTMLElement[],
  scrollTop: number,
  viewportHeight: number,
  fallback = 0,
): number {
  let visible = fallback;
  for (const element of elements) {
    const threshold = scrollTop + Math.min(24, viewportHeight / 8);
    if (element.offsetTop + element.offsetHeight >= threshold) {
      visible = Number(element.dataset.groupIndex || 0);
      break;
    }
  }
  return visible;
}

export function scrollPaneToGroup(
  pane: HTMLElement | null,
  groupIndex: number,
  behavior: ScrollBehavior = "auto",
  offsetTopOffset = 48,
): boolean {
  const group = pane?.querySelector<HTMLElement>(`[data-group-index="${groupIndex}"]`);
  if (!pane || !group) return false;
  pane.scrollTo({ top: Math.max(0, group.offsetTop - offsetTopOffset), behavior });
  return true;
}

export type BilingualReaderShortcut =
  | "previous-group"
  | "next-group"
  | "toggle-translation"
  | "lookup"
  | "bookmark"
  | "pronounce"
  | "pronounce-uk"
  | "toggle-shortcuts"
  | "close-modal";

export function readerShortcutFromKeyboardEvent(
  event: KeyboardEvent,
  options: { modalOpen?: boolean } = {},
): BilingualReaderShortcut | null {
  if (event.metaKey || event.ctrlKey || event.altKey) return null;
  const target = event.target;
  if (
    typeof HTMLElement !== "undefined" &&
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  ) {
    return null;
  }

  if (event.key === "Escape") return "close-modal";
  if (options.modalOpen) return null;
  if (event.shiftKey && (event.key === "P" || event.key === "p")) {
    return "pronounce-uk";
  }
  if (event.key === "?" || (event.shiftKey && event.key === "/")) {
    return "toggle-shortcuts";
  }

  switch (event.key.toLowerCase()) {
    case "j":
    case "arrowdown":
      return "next-group";
    case "k":
    case "arrowup":
      return "previous-group";
    case "t":
      return "toggle-translation";
    case "d":
      return "lookup";
    case "b":
      return "bookmark";
    case "p":
      return "pronounce";
    case "h":
      return "toggle-shortcuts";
    default:
      return null;
  }
}
