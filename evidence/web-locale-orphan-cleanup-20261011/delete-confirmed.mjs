// delete-confirmed.mjs — AGEN-1729: delete scan-confirmed orphan keys from en/zh/de/fr app.json.
// Enforces: deletion == report en confirmed (750) + fr confirmed passing published raw-guard rule (1400);
// guarded keys untouched; produces deletion lists + guarded checklist data.
import fs from "node:fs";
import path from "node:path";

const webRoot = path.resolve(new URL(".", import.meta.url).pathname, "../../web");
const evDir = path.resolve(new URL(".", import.meta.url).pathname);
const GREP_DIRS = ["app", "components", "features", "hooks", "lib", "shared", "i18n", "context", "contracts", "types"];
const report = JSON.parse(fs.readFileSync(path.join(evDir, "report-orphan-keys.json"), "utf8"));
const frLists = JSON.parse(fs.readFileSync(path.join(evDir, "fr-lists.json"), "utf8"));

const enConfirmed = report.en_orphans.filter((o) => !o.guarded).map((o) => o.key);
if (enConfirmed.length !== 750) throw new Error(`en confirmed=${enConfirmed.length}, expect 750`);
const frConfirmed = frLists.fr.confirmed;
const frGuarded = frLists.fr.guarded;
if (frConfirmed.length !== 1400) throw new Error(`fr confirmed=${frConfirmed.length}, expect 1400`);
if (frGuarded.length !== 510) throw new Error(`fr guarded=${frGuarded.length}, expect 510`);
const enGuarded = report.en_orphans.filter((o) => o.guarded).map((o) => o.key);
if (enGuarded.length !== 729) throw new Error(`en guarded=${enGuarded.length}, expect 729`);

// False orphans restored before deletion: keys composed at runtime
// ('prefix.' + value, e.g. readiness.detail.<code>) and wire-passthrough row
// labels demanded by repo tests (web/tests/settings-readiness-i18n.test.ts).
// restored-dynamic-keys.json records them per locale.
const restored = JSON.parse(fs.readFileSync(path.join(evDir, "restored-dynamic-keys.json"), "utf8"));
const restoredEn = new Set(restored.en);
const restoredFr = new Set(restored.fr);
const deletedEn = enConfirmed.filter((k) => !restoredEn.has(k));
const deletedFr = frConfirmed.filter((k) => !restoredFr.has(k));
for (const loc of ["zh", "de"]) {
  const extra = restored[loc].filter((k) => !restoredEn.has(k));
  if (extra.length) throw new Error(`zh/de restore set must equal en's; extra: ${extra[0]}`);
}
console.error(`restored false orphans: en/zh/de=${restoredEn.size} fr=${restoredFr.size}; deleting en/zh/de=${deletedEn.length} fr=${deletedFr.length}`);

const delSets = { en: deletedEn, zh: deletedEn, de: deletedEn, fr: deletedFr };
const catalogs = {};
for (const loc of ["en", "zh", "de", "fr"]) {
  const p = path.join(webRoot, "locales", loc, "app.json");
  catalogs[loc] = { path: p, data: JSON.parse(fs.readFileSync(p, "utf8")), before: Object.keys(JSON.parse(fs.readFileSync(p, "utf8"))).length };
}

// pre-asserts
for (const loc of ["en", "zh", "de"]) {
  const keys = new Set(Object.keys(catalogs[loc].data));
  const missing = enConfirmed.filter((k) => !keys.has(k));
  if (missing.length) throw new Error(`${loc}: ${missing.length} confirmed keys absent from catalog`);
}
const frKeys = new Set(Object.keys(catalogs.fr.data));
const frMissing = frConfirmed.filter((k) => !frKeys.has(k));
if (frMissing.length) throw new Error(`fr: ${frMissing.length} confirmed keys absent from catalog`);
const confSet = new Set([...enConfirmed, ...frConfirmed]);
const guardSet = new Set([...enGuarded, ...frGuarded]);
for (const k of confSet) if (guardSet.has(k)) throw new Error(`key both confirmed and guarded: ${k}`);

// guarded hit evidence (first 3 hits each) over web source + tests
function listFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listFiles(full));
    else if (ent.isFile() && /\.tsx?$/.test(ent.name)) out.push(full);
  }
  return out;
}
const corpusFiles = [];
for (const d of GREP_DIRS) {
  const abs = path.join(webRoot, d);
  if (fs.existsSync(abs)) corpusFiles.push(...listFiles(abs));
}
const testsAbs = path.join(webRoot, "tests");
if (fs.existsSync(testsAbs)) corpusFiles.push(...listFiles(testsAbs));
const corpus = corpusFiles.map((f) => ({ rel: path.relative(webRoot, f).replaceAll("\\", "/"), lines: fs.readFileSync(f, "utf8").split("\n") }));
function hits(key) {
  const out = [];
  for (const f of corpus) {
    for (let i = 0; i < f.lines.length; i++) {
      if (f.lines[i].includes(key)) {
        out.push(`${f.rel}:${i + 1}`);
        if (out.length >= 3) return out;
      }
    }
  }
  return out;
}

const guardedEvidence = {};
for (const k of enGuarded) guardedEvidence[k] = { locales: ["en", "zh", "de"], hits: hits(k) };
for (const k of frGuarded) guardedEvidence[k] = guardedEvidence[k] ? { ...guardedEvidence[k], locales: [...guardedEvidence[k].locales, "fr"] } : { locales: ["fr"], hits: hits(k) };

// delete
for (const loc of Object.keys(delSets)) {
  for (const k of delSets[loc]) delete catalogs[loc].data[k];
  const out = JSON.stringify(catalogs[loc].data, null, 2) + "\n";
  fs.writeFileSync(catalogs[loc].path, out);
}

// post-asserts
const post = {};
for (const loc of ["en", "zh", "de", "fr"]) {
  const data = JSON.parse(fs.readFileSync(catalogs[loc].path, "utf8"));
  post[loc] = Object.keys(data).length;
  const expectBefore = catalogs[loc].before;
  const expectAfter = expectBefore - delSets[loc].length;
  if (post[loc] !== expectAfter) throw new Error(`${loc}: post=${post[loc]} expect=${expectAfter}`);
  const remaining = new Set(Object.keys(data));
  const guardLeak = (loc === "fr" ? frGuarded : enGuarded).filter((k) => !remaining.has(k));
  if (guardLeak.length) throw new Error(`${loc}: ${guardLeak.length} guarded keys were deleted: ${guardLeak.slice(0, 5)}`);
  const restoredMissing = restored[loc].filter((k) => !remaining.has(k));
  if (restoredMissing.length) throw new Error(`${loc}: ${restoredMissing.length} restored keys absent after deletion: ${restoredMissing.slice(0, 5)}`);
}

// write artifacts
for (const loc of Object.keys(delSets)) {
  fs.writeFileSync(path.join(evDir, `deletion-list-${loc}.json`), JSON.stringify(delSets[loc].slice().sort(), null, 1) + "\n");
}
fs.writeFileSync(path.join(evDir, "guarded-keys.json"), JSON.stringify({ en_guarded: enGuarded, fr_guarded_extra_vs_en: frGuarded.filter((k) => !enGuarded.includes(k)), evidence: guardedEvidence }, null, 2));
console.log(JSON.stringify({
  deleted: { en: delSets.en.length, zh: delSets.zh.length, de: delSets.de.length, fr: delSets.fr.length },
  counts: Object.fromEntries(Object.entries(catalogs).map(([l, c]) => [l, { before: c.before, after: post[l] }])),
  guardedUntouched: { en: enGuarded.length, fr: frGuarded.length },
  guardedWithHits: Object.values(guardedEvidence).filter((e) => e.hits.length > 0).length,
  guardedWithoutHits: Object.values(guardedEvidence).filter((e) => e.hits.length === 0).length,
}, null, 2));
