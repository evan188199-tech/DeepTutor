import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import {
  BILINGUAL_CLICK_LOOKUP_STORAGE_KEY,
  BILINGUAL_DUAL_PANE_MEDIA_QUERY,
  BILINGUAL_READER_MODE_STORAGE_KEY,
  parseBilingualReaderMode,
  parseStoredBoolean,
} from "../lib/bilingual-reader-ux";

test("reader mode and tap lookup preferences parse only supported values", () => {
  assert.equal(parseBilingualReaderMode("inline"), "inline");
  assert.equal(parseBilingualReaderMode("dual"), "dual");
  assert.equal(parseBilingualReaderMode("hover"), "hover");
  assert.equal(parseBilingualReaderMode("unknown"), "inline");
  assert.equal(parseBilingualReaderMode(null), "inline");

  assert.equal(parseStoredBoolean("true"), true);
  assert.equal(parseStoredBoolean("false"), false);
  assert.equal(parseStoredBoolean(null), false);

  assert.equal(BILINGUAL_READER_MODE_STORAGE_KEY, "deeptutor.bilingual-reader.mode");
  assert.equal(BILINGUAL_CLICK_LOOKUP_STORAGE_KEY, "deeptutor.bilingual-reader.click-lookup");
  assert.equal(BILINGUAL_DUAL_PANE_MEDIA_QUERY, "(min-width: 1180px)");
});

test("bilingual reader exposes responsive modes and synchronized dual panes", async () => {
  const source = await readFile(
    join(process.cwd(), "components/immersive-reading/BilingualReader.tsx"),
    "utf8",
  );

  assert.match(source, /preferredReaderMode === "dual" && !dualPaneSupported/);
  assert.match(source, /renderGroups\("english"\)/);
  assert.match(source, /renderGroups\("chinese"\)/);
  assert.match(source, /const handleDualScroll = \(source: HTMLDivElement, other: HTMLDivElement\)/);
  assert.match(source, /englishPaneRef\.current, next, "smooth", 60/);
  assert.match(source, /chinesePaneRef\.current, next, "smooth", 60/);
  assert.match(source, /\}, \[chapterIndex, readerMode\]\);/);
  assert.match(source, /env\(safe-area-inset-bottom, 12px\)/);
});

test("tap lookup uses quick definitions without hijacking reader controls", async () => {
  const source = await readFile(
    join(process.cwd(), "components/immersive-reading/BilingualReader.tsx"),
    "utf8",
  );

  assert.match(source, /shouldIgnoreLookupTarget\(target\)/);
  assert.match(source, /wordRangeAtPoint\(paragraph, x, y\)/);
  assert.match(source, /presentation: "mini"/);
  assert.match(source, /dictPopover\?\.presentation === "mini"/);
  assert.match(source, /dictPopover\?\.presentation === "full"/);
  assert.match(source, /event\.detail !== 1/);
  assert.match(source, /performance\.now\(\) - miniLookupRef\.current\.at < 400/);
});
