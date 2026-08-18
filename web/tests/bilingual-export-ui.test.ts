import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

test("bilingual reader renders the export options dialog it opens", async () => {
  const source = await readFile(
    join(process.cwd(), "components/immersive-reading/BilingualReader.tsx"),
    "utf8",
  );

  assert.match(source, /const \[showExportDialog, setShowExportDialog\]/);
  assert.match(source, /\{showExportDialog && \(/);
  assert.match(source, /style: exportStyle/);
  assert.match(source, /font_family: exportFontFamily/);
  assert.match(source, /custom_css: exportCss/);
  assert.match(source, /maxLength=\{100000\}/);
  assert.match(source, /Download EPUB/);
});
