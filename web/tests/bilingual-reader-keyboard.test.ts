import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import {
  readerShortcutFromKeyboardEvent,
  scrollPaneToGroup,
  visibleGroupFromElements,
} from "../lib/bilingual-reader-ux";

function keyboard(key: string, init: Partial<KeyboardEvent> = {}) {
  return {
    key,
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    ...init,
  } as KeyboardEvent;
}

function group(index: number, offsetTop: number, offsetHeight: number) {
  return {
    dataset: { groupIndex: String(index) },
    offsetTop,
    offsetHeight,
  } as unknown as HTMLElement;
}

test("visible group follows the first group entering the reading threshold", () => {
  const groups = [group(0, 0, 80), group(1, 80, 120), group(2, 200, 100)];
  assert.equal(visibleGroupFromElements(groups, 130, 600, 0), 1);
  assert.equal(visibleGroupFromElements(groups, 250, 600, 1), 2);
  assert.equal(visibleGroupFromElements([], 0, 600, 4), 4);
});

test("scrollPaneToGroup scrolls to target group with custom margin offset", () => {
  let scrolledTop = -1;
  let scrolledBehavior = "";
  const pane = {
    querySelector: (selector: string) =>
      selector === '[data-group-index="2"]' ? ({ offsetTop: 300 } as HTMLElement) : null,
    scrollTo: (options: { top: number; behavior: string }) => {
      scrolledTop = options.top;
      scrolledBehavior = options.behavior;
    },
  } as unknown as HTMLElement;

  assert.equal(scrollPaneToGroup(pane, 2, "smooth", 60), true);
  assert.equal(scrolledTop, 240);
  assert.equal(scrolledBehavior, "smooth");
  assert.equal(scrollPaneToGroup(pane, 99), false);
  assert.equal(scrollPaneToGroup(null, 2), false);
});

test("reader shortcuts map to immersive navigation actions", () => {
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("j")), "next-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("ArrowDown")), "next-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("K")), "previous-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("ArrowUp")), "previous-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("t")), "toggle-translation");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("d")), "lookup");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("b")), "bookmark");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("p")), "pronounce");
  assert.equal(
    readerShortcutFromKeyboardEvent(keyboard("P", { shiftKey: true })),
    "pronounce-uk",
  );
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("?")), "toggle-shortcuts");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("h")), "toggle-shortcuts");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("Escape")), "close-modal");
});

test("reader shortcuts do not steal browser or text-entry keys", () => {
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("p", { metaKey: true })), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("d", { ctrlKey: true })), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("b", { altKey: true })), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("b"), { modalOpen: true }), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("x")), null);
});

test("bilingual reader wires shortcuts to navigation and support actions", async () => {
  const source = await readFile(
    join(process.cwd(), "components/immersive-reading/BilingualReader.tsx"),
    "utf8",
  );

  assert.match(source, /readerShortcutFromKeyboardEvent\(event, \{ modalOpen \}\)/);
  assert.match(source, /scrollPaneToGroup\(contentRef\.current, next, "smooth", 60\)/);
  assert.match(source, /case "toggle-translation":/);
  assert.match(source, /case "lookup":/);
  assert.match(source, /case "bookmark":/);
  assert.match(source, /case "pronounce-uk":/);
  assert.match(source, /\{showShortcutsModal && \(/);
  assert.match(source, /isActive=\{activeGroup === gi\}/);
});
