import test from "node:test";
import assert from "node:assert/strict";

import {
  ATTACHMENT_ACCEPT,
  classifyFile,
  DEFAULT_MAX_ATTACHMENT_BYTES,
  DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
  docIconFor,
  extOf,
  formatBytes,
  isSvgFilename,
  OFFICE_EXTS,
  SUPPORTED_DOC_EXTS,
  SUPPORTED_DOC_MIMES,
  TEXT_LIKE_EXTS,
} from "../lib/doc-attachments";

function makeFile(name: string, type = "", size = 0): File {
  // File constructor available in modern Node runtimes.
  return new File([new Uint8Array(size)], name, { type });
}

// classifyFile ---------------------------------------------------------------

test("classifyFile: image via MIME", () => {
  assert.equal(classifyFile(makeFile("x.png", "image/png")), "image");
  assert.equal(classifyFile(makeFile("x.jpg", "image/jpeg")), "image");
});

test("classifyFile: doc via MIME", () => {
  assert.equal(
    classifyFile(
      makeFile(
        "a.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    ),
    "doc",
  );
  assert.equal(classifyFile(makeFile("b.pdf", "application/pdf")), "doc");
});

test("classifyFile: doc via extension fallback when MIME empty", () => {
  assert.equal(classifyFile(makeFile("report.pptx")), "doc");
  assert.equal(classifyFile(makeFile("REPORT.XLSX")), "doc");
});

test("classifyFile: accepts text & code", () => {
  assert.equal(classifyFile(makeFile("notes.txt", "text/plain")), "doc");
  assert.equal(classifyFile(makeFile("README.md", "text/markdown")), "doc");
  assert.equal(classifyFile(makeFile("main.py", "text/x-python")), "doc");
  // Empty MIME (common for code files) still accepted via extension
  assert.equal(classifyFile(makeFile("script.js")), "doc");
  assert.equal(classifyFile(makeFile("config.yaml")), "doc");
  assert.equal(classifyFile(makeFile("data.csv")), "doc");
});

test("classifyFile: SVG classified as doc (not image)", () => {
  // SVG has an image/* MIME but we route it through text extraction so the
  // LLM gets its XML source. Thumbnail preview still renders via <img>.
  assert.equal(classifyFile(makeFile("logo.svg", "image/svg+xml")), "doc");
  assert.equal(classifyFile(makeFile("icon.SVG")), "doc");
});

test("isSvgFilename: case-insensitive extension check", () => {
  assert.equal(isSvgFilename("foo.svg"), true);
  assert.equal(isSvgFilename("FOO.SVG"), true);
  assert.equal(isSvgFilename("foo.svg.bak"), false);
  assert.equal(isSvgFilename("foo.png"), false);
});

test("docIconFor: SVG gets its own label", () => {
  assert.equal(docIconFor("logo.svg").label, "SVG");
  assert.ok(docIconFor("logo.svg").tint.includes("teal"));
});

test("classifyFile: rejects unsupported", () => {
  assert.equal(classifyFile(makeFile("a.zip", "application/zip")), null);
  assert.equal(
    classifyFile(makeFile("a.exe", "application/x-msdownload")),
    null,
  );
  assert.equal(classifyFile(makeFile("noext")), null);
});

// formatBytes ----------------------------------------------------------------

test("formatBytes: B / KB / MB", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(1024 * 1024), "1.0 MB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.0 MB");
});

test("formatBytes: negative / NaN returns empty string", () => {
  assert.equal(formatBytes(-1), "");
  assert.equal(formatBytes(Number.NaN), "");
});

// docIconFor -----------------------------------------------------------------

test("docIconFor: office labels & tints", () => {
  assert.equal(docIconFor("report.pdf").label, "PDF");
  assert.ok(docIconFor("report.pdf").tint.includes("red"));
  assert.equal(docIconFor("report.docx").label, "DOCX");
  assert.equal(docIconFor("report.xlsx").label, "XLSX");
  assert.equal(docIconFor("report.pptx").label, "PPTX");
});

test("docIconFor: code files share a code icon", () => {
  assert.ok(docIconFor("main.py").tint.includes("violet"));
  assert.ok(docIconFor("main.js").tint.includes("violet"));
  assert.ok(docIconFor("main.rs").tint.includes("violet"));
});

test("docIconFor: json/config/data/markup categories", () => {
  assert.ok(docIconFor("data.json").tint.includes("amber"));
  assert.ok(docIconFor("config.yaml").tint.includes("slate"));
  assert.ok(docIconFor("run.sh").tint.includes("slate"));
  assert.ok(docIconFor("table.csv").tint.includes("emerald"));
  assert.ok(docIconFor("doc.md").tint.includes("sky"));
  assert.ok(docIconFor("style.css").tint.includes("pink"));
});

test("docIconFor: fallback for unknown extension", () => {
  assert.equal(docIconFor("mystery.bin").label, "BIN");
  assert.equal(docIconFor("noext").label, "FILE");
});

// Limits sanity check -------------------------------------------------------

test("DEFAULT_MAX_ATTACHMENT_BYTES is 20 MB", () => {
  assert.equal(DEFAULT_MAX_ATTACHMENT_BYTES, 20 * 1024 * 1024);
});

test("DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES is 25 MB", () => {
  assert.equal(DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES, 25 * 1024 * 1024);
});

// extOf ---------------------------------------------------------------------

test("extOf: extracts the lowercase extension from the last dot", () => {
  assert.equal(extOf("report.pdf"), ".pdf");
  assert.equal(extOf("archive.tar.gz"), ".gz");
  assert.equal(extOf("README.MD"), ".md");
});

test("extOf: returns empty string when there is no extension", () => {
  assert.equal(extOf("noext"), "");
  assert.equal(extOf(""), "");
});

// Extension / MIME sets ------------------------------------------------------

test("SUPPORTED_DOC_EXTS covers office and text-like sets without dupes", () => {
  assert.equal(SUPPORTED_DOC_EXTS.length, OFFICE_EXTS.length + TEXT_LIKE_EXTS.length);
  const seen = new Set<string>();
  for (const ext of SUPPORTED_DOC_EXTS) {
    assert.ok(ext.startsWith("."), `extension must start with '.': ${ext}`);
    assert.equal(ext, ext.toLowerCase(), `extension must be lowercase: ${ext}`);
    assert.ok(!seen.has(ext), `duplicate extension: ${ext}`);
    seen.add(ext);
  }
});

test("ATTACHMENT_ACCEPT merges image, extensions and MIMEs", () => {
  const parts = ATTACHMENT_ACCEPT.split(",");
  assert.equal(parts[0], "image/*");
  for (const ext of SUPPORTED_DOC_EXTS) {
    assert.ok(parts.includes(ext));
  }
  for (const mime of SUPPORTED_DOC_MIMES) {
    assert.ok(parts.includes(mime));
  }
});

// classifyFile boundary behaviour ---------------------------------------------

test("classifyFile: unsupported MIME falls back to a supported extension", () => {
  // Browsers commonly report octet-stream for code/config files.
  assert.equal(classifyFile(makeFile("data.json", "application/octet-stream")), "doc");
});

test("classifyFile: SVG via MIME alone even without the extension", () => {
  assert.equal(classifyFile(makeFile("drawing", "image/svg+xml")), "doc");
});

test("classifyFile: unknown MIME with unsupported extension is rejected", () => {
  assert.equal(classifyFile(makeFile("bundle.tar.gz", "application/gzip")), null);
  assert.equal(classifyFile(makeFile("payload.bin", "application/octet-stream")), null);
});

// formatBytes boundary values --------------------------------------------------

test("formatBytes: boundaries just below and at the unit thresholds", () => {
  assert.equal(formatBytes(1023), "1023 B");
  assert.equal(formatBytes(1024 * 1024 - 1), "1024.0 KB");
  assert.equal(formatBytes(1.5 * 1024 * 1024), "1.5 MB");
});

test("formatBytes: non-finite values return empty string", () => {
  assert.equal(formatBytes(Number.POSITIVE_INFINITY), "");
});

// docIconFor categories ----------------------------------------------------------

test("docIconFor: shell, config, code and plain categories stay distinct", () => {
  assert.equal(docIconFor("deploy.sh").label, "SH");
  assert.ok(docIconFor("deploy.sh").tint.includes("slate"));
  assert.ok(docIconFor("pyproject.toml").tint.includes("slate"));
  assert.equal(docIconFor("settings.json5").label, "JSON5");
  assert.ok(docIconFor("component.tsx").tint.includes("violet"));
  assert.ok(docIconFor("run.log").tint.includes("muted-foreground"));
});

test("docIconFor: dockerfile and protobuf map to config / markup groups", () => {
  assert.equal(docIconFor("app.dockerfile").label, "DOCKERFILE");
  assert.ok(docIconFor("schema.proto").tint.includes("sky"));
});
