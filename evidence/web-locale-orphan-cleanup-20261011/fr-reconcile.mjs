// fr-reconcile.mjs — replicate evidence-scan.mjs orphan rule for fr's full key set.
// Validates against report: en 1479/750/729, fr 1910/1407/503. Prints fr lists.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

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
function literalKeys(expression) {
  if (!expression) return [];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return [expression.text];
  if (ts.isConditionalExpression(expression)) return [...literalKeys(expression.whenTrue), ...literalKeys(expression.whenFalse)];
  return [];
}
function scanUsed(file) {
  const content = fs.readFileSync(file, "utf8");
  const used = new Set();
  const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const isT =
        (ts.isIdentifier(callee) && callee.text === "t") ||
        (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
      if (isT && node.arguments.length) for (const key of literalKeys(node.arguments[0])) if (key) used.add(key);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return used;
}
const usedKeys = new Set();
for (const dir of CODE_DIRS) {
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) continue;
  for (const file of listCodeFiles(abs)) for (const k of scanUsed(file)) usedKeys.add(k);
}
const rawSource = [];
for (const dir of GREP_DIRS) {
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) continue;
  for (const file of listCodeFiles(abs)) rawSource.push(fs.readFileSync(file, "utf8"));
}
const testsDir = path.join(webRoot, "tests");
const testSources = fs.existsSync(testsDir) ? [...listCodeFiles(testsDir)].map((f) => fs.readFileSync(f, "utf8")) : [];
const rawCorpus = rawSource.join("\n");
const testCorpus = testSources.join("\n");
const pluralSuffix = /_(zero|one|two|few|many|other)$/;

function orphanStatus(key) {
  if (usedKeys.has(key)) return "used";
  const m = key.match(pluralSuffix);
  if (m && usedKeys.has(key.slice(0, -m[0].length))) return "used";
  const rawHit = rawCorpus.includes(key);
  const testHit = testCorpus.includes(key);
  return rawHit || testHit ? "guarded" : "confirmed";
}

const catalogs = {};
for (const locale of ["en", "fr"]) catalogs[locale] = JSON.parse(fs.readFileSync(path.join(webRoot, "locales", locale, "app.json"), "utf8"));

const result = {};
for (const locale of ["en", "fr"]) {
  const confirmed = [], guarded = [];
  let candidates = 0;
  for (const key of Object.keys(catalogs[locale])) {
    const st = orphanStatus(key);
    if (st === "used") continue;
    candidates++;
    (st === "confirmed" ? confirmed : guarded).push(key);
  }
  confirmed.sort(); guarded.sort();
  result[locale] = { candidates, confirmed, guarded };
  console.error(`${locale}: candidates=${candidates} confirmed=${confirmed.length} guarded=${guarded.length}`);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const enOk = result.en.candidates === 1479 && result.en.confirmed.length === 750 && result.en.guarded.length === 729;
const frOk = result.fr.candidates === 1910 && result.fr.confirmed.length === 1407 && result.fr.guarded.length === 503;
// per-key check en vs report en_orphans
const repEn = new Map(report.en_orphans.map((o) => [o.key, o.guarded ? "guarded" : "confirmed"]));
let enKeyDiff = 0;
for (const k of [...result.en.confirmed, ...result.en.guarded]) if (repEn.get(k) !== (result.en.confirmed.includes(k) ? "confirmed" : "guarded")) enKeyDiff++;
console.error(`VALIDATION en=${enOk ? "OK" : "MISMATCH"} fr=${frOk ? "OK" : "MISMATCH"} enKeyDiff=${enKeyDiff}`);
fs.writeFileSync(process.argv[3], JSON.stringify(result, null, 2));
