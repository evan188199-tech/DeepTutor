#!/usr/bin/env node
/**
 * scan-locale-keys.mjs — static i18n key usage scan for web/ (AGEN-1583).
 *
 * Three lists:
 *   1. missing keys  — t() literal keys used in code but absent from a locale catalog
 *   2. orphan keys   — catalog keys never referenced by code (AST pass + raw-source grep guard)
 *   3. hardcoded UI copy — JSX text / i18n-able attributes / alert+confirm literals
 *
 * Mirrors web/scripts/i18n_audit.mjs key-extraction semantics (flat namespace,
 * keySeparator:false, conditional literals, plural _suffix forms) and adds:
 *   - dynamic t() first-arg detection (unresolvable keys, reported separately)
 *   - raw-substring guard for orphan candidates (keys referenced outside t())
 *   - per-occurrence file:line evidence
 *
 * Usage: node evidence-scan.mjs [--json-out DIR]   (run with cwd = web/)
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

// resolve typescript from the web/ checkout (run with cwd = web/)
const require = createRequire(path.join(process.cwd(), "package.json"));
const ts = require("typescript");

const webRoot = process.cwd();
const CODE_DIRS = ["app", "components", "features", "hooks", "lib", "shared"];
const GREP_DIRS = [...CODE_DIRS, "i18n", "context", "contracts", "types"];
const LOCALES = ["en", "zh", "fr", "de", "uk", "pl"];

function listCodeFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listCodeFiles(full));
    else if (ent.isFile() && /\.tsx?$/.test(ent.name)) out.push(full);
  }
  return out;
}

function toRel(p, root = webRoot) {
  return path.relative(root, p).replaceAll("\\", "/");
}

function literalKeys(expression) {
  if (!expression) return [];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return [expression.text];
  }
  if (ts.isConditionalExpression(expression)) {
    return [...literalKeys(expression.whenTrue), ...literalKeys(expression.whenFalse)];
  }
  return [];
}

function isDynamicKey(expression) {
  if (!expression) return false;
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return false;
  if (ts.isConditionalExpression(expression)) {
    return isDynamicKey(expression.whenTrue) || isDynamicKey(expression.whenFalse);
  }
  return true;
}

function hasUiText(s) {
  return /[A-Za-z\u4e00-\u9fff]/.test(s);
}

const ATTRS = new Set(["title", "placeholder", "alt", "aria-label"]);
const BENIGN_HINTS = [
  /^(you@example\.com|my-server|npx|\/.*|https?:\/\/.*|sk-\.\.\.|gpt-.*|alloy|volc\..*|\{.*\}|\d+x\d+|\d+p|px|MB|tokens?|s( ·)?|·|&\w+;|L\d|Redis|SOUL\.md|English|中文|Σ)$/i,
];

function scanFile(file) {
  const content = fs.readFileSync(file, "utf8");
  const rel = toRel(file);
  const used = new Map(); // key -> [ {file,line} ]
  const dynamic = []; // {file,line,snippet}
  const literals = []; // {kind,text,line}
  const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);

  function lineOf(node) {
    return content.slice(0, node.getStart(source)).split("\n").length;
  }

  function addUsed(key, line) {
    if (!key) return;
    if (!used.has(key)) used.set(key, []);
    used.get(key).push({ file: rel, line });
  }

  function addLiteral(kind, raw, line) {
    const text = raw.replace(/\s+/g, " ").trim();
    if (text.length <= 1 || !hasUiText(text) || text === "DeepTutor") return;
    literals.push({ kind, text: raw.replace(/\s+/g, " ").trim(), line, file: rel });
  }

  function visit(node) {
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const isT =
        (ts.isIdentifier(callee) && callee.text === "t") ||
        (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
      if (isT && node.arguments.length) {
        const line = lineOf(node);
        for (const key of literalKeys(node.arguments[0])) addUsed(key, line);
        if (isDynamicKey(node.arguments[0])) {
          dynamic.push({
            file: rel,
            line,
            snippet: node.arguments[0].getText(source).slice(0, 120),
          });
        }
      }
    }
    if (ts.isJsxText(node)) addLiteral("jsxText", node.text, lineOf(node));
    if (ts.isJsxAttribute(node) && ATTRS.has(node.name.getText(source))) {
      if (node.initializer && ts.isStringLiteral(node.initializer)) {
        addLiteral(`attr:${node.name.getText(source)}`, node.initializer.text, lineOf(node));
      }
    }
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      ["alert", "confirm"].includes(node.expression.text)
    ) {
      for (const key of literalKeys(node.arguments[0])) {
        addLiteral(`${node.expression.text}()`, key, lineOf(node));
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return { used, dynamic, literals };
}

// ---------- run scan ----------
const allUsed = new Map(); // key -> occurrences[]
const allDynamic = [];
const allLiterals = [];
for (const dir of CODE_DIRS) {
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) continue;
  for (const file of listCodeFiles(abs)) {
    const { used, dynamic, literals } = scanFile(file);
    for (const [k, occ] of used) {
      if (!allUsed.has(k)) allUsed.set(k, []);
      allUsed.get(k).push(...occ);
    }
    allDynamic.push(...dynamic);
    allLiterals.push(...literals);
  }
}

// ---------- load catalogs ----------
function loadCatalog(locale, name) {
  const p = path.join(webRoot, "locales", locale, `${name}.json`);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    return { __error__: String(e) };
  }
}

const catalogs = {};
for (const locale of LOCALES) {
  catalogs[locale] = { app: loadCatalog(locale, "app"), common: loadCatalog(locale, "common") };
}

const pluralForms = new Map(
  LOCALES.map((l) => [
    l,
    new Intl.PluralRules(l).resolvedOptions().pluralCategories,
  ]),
);

function hasKeyOrPlural(entries, locale, key) {
  if (Object.hasOwn(entries, key)) return true;
  return pluralForms.get(locale).every((f) => Object.hasOwn(entries, `${key}_${f}`));
}

// ---------- list 1: missing keys ----------
const missing = {}; // locale -> [{key, occurrences}]
for (const locale of LOCALES) {
  const app = catalogs[locale].app || {};
  const list = [];
  for (const [key, occ] of [...allUsed].sort()) {
    if (!hasKeyOrPlural(app, locale, key)) list.push({ key, occurrences: occ });
  }
  // also record whether the key exists anywhere in en catalog (used-by-code but absent everywhere)
  missing[locale] = list;
}

// catalog-level parity: en catalog keys missing in each other locale
const enKeys = Object.keys(catalogs.en.app || {});
const catalogGaps = {};
for (const locale of LOCALES) {
  if (locale === "en") continue;
  const app = catalogs[locale].app || {};
  catalogGaps[locale] = enKeys.filter((k) => !Object.hasOwn(app, k)).sort();
}

// ---------- list 2: orphan keys ----------
// AST-based unused, then raw-source grep guard across GREP_DIRS (+tests).
const rawSource = [];
for (const dir of GREP_DIRS) {
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) continue;
  for (const file of listCodeFiles(abs)) rawSource.push(fs.readFileSync(file, "utf8"));
}
const testsDir = path.join(webRoot, "tests");
let testSources = [];
if (fs.existsSync(testsDir)) {
  for (const file of listCodeFiles(testsDir)) testSources.push(fs.readFileSync(file, "utf8"));
}
const rawCorpus = rawSource.join("\n");
const testCorpus = testSources.join("\n");

const pluralSuffix = /_(zero|one|two|few|many|other)$/;
const usedKeys = new Set(allUsed.keys());
const orphans = []; // {key, inLocales[], rawHit: bool, testHit: bool}
for (const key of enKeys) {
  if (usedKeys.has(key)) continue;
  // plural child of a used base key is not an orphan
  const m = key.match(pluralSuffix);
  if (m && usedKeys.has(key.slice(0, -m[0].length))) continue;
  const rawHit = rawCorpus.includes(key);
  const testHit = testCorpus.includes(key);
  const inLocales = LOCALES.filter((l) => Object.hasOwn(catalogs[l].app || {}, key));
  if (rawHit || testHit) {
    orphans.push({ key, inLocales, rawHit, testHit, guarded: true });
  } else {
    orphans.push({ key, inLocales, rawHit: false, testHit: false, guarded: false });
  }
}
orphans.sort((a, b) => Number(a.guarded) - Number(b.guarded) || a.key.localeCompare(b.key));

// per-locale extra keys vs en (drift in other direction)
const extraVsEn = {};
for (const locale of LOCALES) {
  if (locale === "en") continue;
  const app = catalogs[locale].app || {};
  extraVsEn[locale] = Object.keys(app).filter((k) => !Object.hasOwn(catalogs.en.app, k)).sort();
}

// common.json wiring: loaded by i18n/init.ts?
const initSrc = fs.readFileSync(path.join(webRoot, "i18n", "init.ts"), "utf8");
const commonWired = /common\.json/.test(initSrc) || /"common"/.test(initSrc);

// ---------- list 3: hardcoded copy (with benign classification) ----------
const hardcoded = allLiterals.map((f) => ({
  ...f,
  benign: BENIGN_HINTS.some((re) => re.test(f.text.trim())),
}));

// ---------- summary ----------
const summary = {
  scannedDirs: CODE_DIRS,
  usedKeyCount: allUsed.size,
  usedOccurrences: [...allUsed.values()].reduce((n, o) => n + o.length, 0),
  dynamicCallSites: allDynamic.length,
  missingUsedByLocale: Object.fromEntries(
    Object.entries(missing).map(([l, v]) => [l, v.length]),
  ),
  catalogGapsVsEn: Object.fromEntries(
    Object.entries(catalogGaps).map(([l, v]) => [l, v.length]),
  ),
  catalogSizes: Object.fromEntries(
    LOCALES.map((l) => [l, Object.keys(catalogs[l].app || {}).length]),
  ),
  orphanCandidates: orphans.length,
  orphanConfirmed: orphans.filter((o) => !o.guarded).length,
  orphanGuardedByRawHit: orphans.filter((o) => o.guarded).length,
  extraVsEn: Object.fromEntries(
    Object.entries(extraVsEn).map(([l, v]) => [l, v.length]),
  ),
  commonJsonWired: commonWired,
  hardcodedFindings: hardcoded.length,
  hardcodedSuspect: hardcoded.filter((h) => !h.benign).length,
};

const out = {
  summary,
  missing,
  catalogGaps,
  orphans,
  extraVsEn,
  commonJson: Object.fromEntries(
    LOCALES.map((l) => {
      const c = catalogs[l].common;
      return [l, c ? Object.keys(c).length : null];
    }),
  ),
  dynamic: allDynamic,
  hardcoded,
};

const jsonIdx = process.argv.indexOf("--json-out");
if (jsonIdx >= 0) {
  const dir = process.argv[jsonIdx + 1];
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "scan-result.json"), JSON.stringify(out, null, 2));
  console.log(`[scan] wrote ${path.join(dir, "scan-result.json")}`);
}
console.log(JSON.stringify(summary, null, 2));
