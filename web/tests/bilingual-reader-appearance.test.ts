import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import {
  BILINGUAL_FONT_FAMILY_STORAGE_KEY,
  BILINGUAL_FONT_SIZE_STORAGE_KEY,
  BILINGUAL_THEME_STORAGE_KEY,
  parseBilingualFontFamily,
  parseBilingualFontSize,
  parseBilingualTheme,
} from "../lib/bilingual-reader-ux";

test("appearance preferences parse only supported values and use stable keys", () => {
  assert.deepEqual(
    ["system", "sepia", "dark", "oled"].map(parseBilingualTheme),
    ["system", "sepia", "dark", "oled"],
  );
  assert.equal(parseBilingualTheme("unknown"), "system");
  assert.equal(parseBilingualTheme(null), "system");

  assert.deepEqual(
    ["sm", "base", "lg", "xl", "2xl"].map(parseBilingualFontSize),
    ["sm", "base", "lg", "xl", "2xl"],
  );
  assert.equal(parseBilingualFontSize("invalid"), "base");
  assert.equal(parseBilingualFontSize(null), "base");

  assert.equal(parseBilingualFontFamily("sans"), "sans");
  assert.equal(parseBilingualFontFamily("serif"), "serif");
  assert.equal(parseBilingualFontFamily("other"), "sans");
  assert.equal(parseBilingualFontFamily(null), "sans");

  assert.equal(BILINGUAL_THEME_STORAGE_KEY, "deeptutor.bilingual-reader.theme");
  assert.equal(BILINGUAL_FONT_SIZE_STORAGE_KEY, "deeptutor.bilingual-reader.font-size");
  assert.equal(BILINGUAL_FONT_FAMILY_STORAGE_KEY, "deeptutor.bilingual-reader.font-family");
});

test("bilingual reader exposes persistent themes and typography controls", async () => {
  const source = await readFile(
    join(process.cwd(), "components/immersive-reading/BilingualReader.tsx"),
    "utf8",
  );

  assert.match(source, /style=\{THEME_STYLES\[theme\]\}/);
  assert.match(source, /setShowAppearanceModal\(true\)/);
  assert.match(source, /setTheme\(item\.key as BilingualTheme\)/);
  assert.match(source, /setFontSize\(size\)/);
  assert.match(source, /setFontFamily\(item\.key as BilingualFontFamily\)/);
  assert.match(source, /BILINGUAL_THEME_STORAGE_KEY, theme/);
  assert.match(source, /BILINGUAL_FONT_SIZE_STORAGE_KEY, fontSize/);
  assert.match(source, /BILINGUAL_FONT_FAMILY_STORAGE_KEY, fontFamily/);
  assert.match(source, /fontClass.*sizeStyles\.en/);
  assert.match(source, /fontClass.*sizeStyles\.zh/);
  assert.match(source, /showAppearanceModal \|\|/);
});
