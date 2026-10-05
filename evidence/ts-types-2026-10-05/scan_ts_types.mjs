#!/usr/bin/env node
// AGEN-664 read-only scan: web/ TS type debt (@ts-ignore/@ts-expect-error, explicit any,
// non-null assertions, as-casts). Parses with the TypeScript compiler API for accuracy.
// Writes findings only under evidence/. No product code is modified.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const ts = require("/Users/Shared/DeepTutor/web/node_modules/typescript");

const ROOT = "/Users/Shared/DeepTutor/dt-agen664-tstypes-wt";
const WEB = path.join(ROOT, "web");
const OUT = path.join(ROOT, "evidence/ts-types-2026-10-05");

function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
}

const files = walk(WEB)
  .filter((f) => /\.(ts|tsx)$/.test(f))
  .sort();

function classifyFile(rel) {
  const posix = rel.split(path.sep).join("/");
  return {
    is_generated: posix.includes("/contracts/generated/"),
    is_vendor: posix.includes("/vendor/"),
    is_test: posix.includes("/tests/") || /\.(spec|test)\.(ts|tsx)$/.test(posix),
    is_ambient: posix.endsWith(".d.ts"),
  };
}

const tsCatchPath =
  "/Users/Shared/DeepTutor/dt-agen421-scan-wt/evidence/ts-catch-scan-2026-10-04/ts_catch_classified.json";
const tsCatchItems = JSON.parse(fs.readFileSync(tsCatchPath, "utf8")).items;
const tsCatchKeys = new Set(tsCatchItems.map((i) => `${i.file}:${i.line}`));
const tsCatchFiles = new Set(tsCatchItems.map((i) => i.file));

const findings = [];
const directives = [];

for (const abs of files) {
  const rel = path.relative(ROOT, abs);
  const flags = classifyFile(rel);
  const text = fs.readFileSync(abs, "utf8");
  const sf = ts.createSourceFile(abs, text, ts.ScriptTarget.Latest, true, /\.tsx$/.test(abs) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

  // suppression directives (comment-based; count every textual occurrence)
  const lines = text.split("\n");
  lines.forEach((line, idx) => {
    const m = line.match(/@ts-(ignore|expect-error|nocheck)\b/g);
    if (m) {
      for (const kind of m) {
        directives.push({
          file: rel,
          line: idx + 1,
          kind,
          snippet: line.trim().slice(0, 200),
          ...flags,
        });
      }
    }
  });

  const visit = (node) => {
    const kind = node.kind;
    if (
      kind === ts.SyntaxKind.AnyKeyword ||
      kind === ts.SyntaxKind.NonNullExpression ||
      kind === ts.SyntaxKind.AsExpression ||
      kind === ts.SyntaxKind.TypeAssertionExpression
    ) {
      const pos = node.getStart(sf);
      const lc = sf.getLineAndCharacterOfPosition(pos);
      const kindName =
        kind === ts.SyntaxKind.AnyKeyword
          ? "any"
          : kind === ts.SyntaxKind.NonNullExpression
            ? "nonnull"
            : kind === ts.SyntaxKind.AsExpression
              ? "as"
              : "typeassert";
      const typeText = node.type ? node.type.getText(sf) : undefined;
      const isConst =
        kindName === "as" && node.type && node.type.kind === ts.SyntaxKind.TypeReferenceNode
          ? false
          : kindName === "as" && typeText === "const";
      findings.push({
        file: rel,
        line: lc.line + 1,
        col: lc.character + 1,
        kind: kindName,
        type: typeText,
        as_const: kindName === "as" ? Boolean(isConst) : undefined,
        snippet: (lines[lc.line] || "").trim().slice(0, 200),
        ...flags,
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

// dedup vs scan-ts-catch (exact file:line, ts-catch paths are repo-relative like web/...)
for (const f of findings) {
  f.dedup_ts_catch_exact = tsCatchKeys.has(`${f.file}:${f.line}`);
  f.dedup_ts_catch_same_file = tsCatchFiles.has(f.file);
}
for (const d of directives) {
  d.dedup_ts_catch_exact = tsCatchKeys.has(`${d.file}:${d.line}`);
  d.dedup_ts_catch_same_file = tsCatchFiles.has(d.file);
}

function agg(rows, keyFn) {
  const m = new Map();
  for (const r of rows) {
    const k = keyFn(r);
    m.set(k, (m.get(k) || 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

const productFindings = findings.filter(
  (f) => !f.is_generated && !f.is_vendor && !f.is_test && !f.is_ambient
);
const topDirs = agg(productFindings, (f) => {
  const parts = f.file.split("/");
  return parts.slice(0, 3).join("/") + (parts.length > 3 ? "/…" : "");
});
const topDirs4 = agg(productFindings, (f) => f.file.split("/").slice(0, 4).join("/"));
const byFile = agg(productFindings, (f) => f.file);
const byKind = agg(findings, (f) => f.kind);
const byKindProduct = agg(productFindings, (f) => f.kind);
const asAny = findings.filter((f) => f.kind === "as" && f.type === "any");
const asUnknownChain = findings.filter((f) => f.kind === "as" && /\bunknown\b/.test(f.type || "") && !f.as_const);
const asConstCount = findings.filter((f) => f.kind === "as" && f.as_const).length;

const summary = {
  scanned_at: new Date().toISOString(),
  repo_commit: fs.readFileSync(path.join(ROOT, ".git")).toString().match(/gitdir:\s*(.*)/)?.[1] || null,
  scope: "web/**/*.{ts,tsx} (exclude node_modules, .next; vendor + contracts/generated + tests + *.d.ts tagged separately)",
  files_scanned: files.length,
  totals: {
    ts_ignore: directives.filter((d) => d.kind === "@ts-ignore").length,
    ts_expect_error: directives.filter((d) => d.kind === "@ts-expect-error").length,
    ts_nocheck: directives.filter((d) => d.kind === "@ts-nocheck").length,
    explicit_any: findings.filter((f) => f.kind === "any").length,
    nonnull_assertion: findings.filter((f) => f.kind === "nonnull").length,
    as_cast: findings.filter((f) => f.kind === "as").length,
    as_const: asConstCount,
    as_any: asAny.length,
    as_unknown_chain: asUnknownChain.length,
    type_assertion_angle: findings.filter((f) => f.kind === "typeassert").length,
  },
  product_only_totals: {
    all: productFindings.length,
    byKind: Object.fromEntries(byKindProduct),
  },
  top_dirs_3seg: Object.fromEntries(topDirs),
  top_dirs_4seg: Object.fromEntries(topDirs4.slice(0, 25)),
  top_files: byFile.slice(0, 40).map(([file, n]) => ({
    file,
    count: n,
    breakdown: agg(
      productFindings.filter((f) => f.file === file),
      (f) => f.kind
    ).map(([k, c]) => `${k}:${c}`).join(", "),
    ts_catch_overlap_file: tsCatchFiles.has(file),
  })),
  dedup: {
    ts_catch_source: "AGEN-421 scan-ts-catch @ agent/agen421-ts-catch-scan (41 items, ef2d9e5c3 / v1.6.12)",
    exact_line_matches_findings: findings.filter((f) => f.dedup_ts_catch_exact).map((f) => `${f.file}:${f.line} (${f.kind})`),
    exact_line_matches_directives: directives.filter((f) => f.dedup_ts_catch_exact).map((f) => `${f.file}:${f.line} (${f.kind})`),
    same_file_overlap_files: [...tsCatchFiles].filter((file) =>
      [...byFile.keys()].some((bf) => bf === file)
    ),
  },
};

fs.mkdirSync(OUT, { recursive: true });
fs.writeFileSync(path.join(OUT, "ts_types_details.json"), JSON.stringify({ summary, directives, findings }, null, 2));
fs.writeFileSync(path.join(OUT, "ts_types_summary.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary.totals));
console.log("product_only:", JSON.stringify(summary.product_only_totals));
console.log("files_scanned:", files.length);
console.log("top_dirs:", JSON.stringify(topDirs.slice(0, 12)));
console.log("top_files:", JSON.stringify(byFile.slice(0, 25)));
console.log("dedup_exact:", JSON.stringify([...summary.dedup.exact_line_matches_findings, ...summary.dedup.exact_line_matches_directives]));
