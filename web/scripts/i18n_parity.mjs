import fs from "node:fs";
import path from "node:path";

function listJsonFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function flattenKeys(obj, prefix = "") {
  const keys = [];
  if (!obj || typeof obj !== "object") return keys;
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) keys.push(...flattenKeys(v, next));
    else keys.push(next);
  }
  return keys;
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll("\\", "/");
}

const webRoot = path.resolve(process.cwd());
const localesRoot = path.join(webRoot, "locales");
const enRoot = path.join(localesRoot, "en");
const zhRoot = path.join(localesRoot, "zh");

if (!fs.existsSync(enRoot) || !fs.existsSync(zhRoot)) {
  console.error(`[i18n:parity] Missing locales roots: ${enRoot} or ${zhRoot}`);
  process.exit(2);
}

// Locales that only need to cover every English key (one-directional).
// They may legitimately carry extra keys (e.g. stale French entries or
// language-specific plural forms), so extras are not reported for them.
const coverageOnlyLocales = fs
  .readdirSync(localesRoot, { withFileTypes: true })
  .filter((ent) => ent.isDirectory() && !["en", "zh"].includes(ent.name))
  .map((ent) => ent.name)
  .sort();

const enFiles = listJsonFiles(enRoot).map((p) => toRel(p, enRoot)).sort();
const zhFiles = listJsonFiles(zhRoot).map((p) => toRel(p, zhRoot)).sort();

const missingInZh = enFiles.filter((f) => !zhFiles.includes(f));
const extraInZh = zhFiles.filter((f) => !enFiles.includes(f));

let ok = true;
if (missingInZh.length) {
  ok = false;
  console.error("[i18n:parity] Missing zh files:");
  for (const f of missingInZh) console.error(`- ${f}`);
}
if (extraInZh.length) {
  ok = false;
  console.error("[i18n:parity] Extra zh files:");
  for (const f of extraInZh) console.error(`- ${f}`);
}

for (const rel of enFiles) {
  if (!zhFiles.includes(rel)) continue;
  const enPath = path.join(enRoot, rel);
  const zhPath = path.join(zhRoot, rel);
  const enJson = loadJson(enPath);
  const zhJson = loadJson(zhPath);
  const enKeys = new Set(flattenKeys(enJson));
  const zhKeys = new Set(flattenKeys(zhJson));

  const missingKeys = [...enKeys].filter((k) => !zhKeys.has(k)).sort();
  const extraKeys = [...zhKeys].filter((k) => !enKeys.has(k)).sort();

  if (missingKeys.length || extraKeys.length) {
    ok = false;
    console.error(`[i18n:parity] Key mismatch in ${rel}`);
    if (missingKeys.length) {
      console.error("  Missing zh keys:");
      for (const k of missingKeys) console.error(`  - ${k}`);
    }
    if (extraKeys.length) {
      console.error("  Extra zh keys:");
      for (const k of extraKeys) console.error(`  - ${k}`);
    }
  }
}

// Coverage check: every non-en/zh locale must provide every key the English
// catalog has (missing keys fall back to English at runtime). Extra keys are
// allowed for these locales.
const coverageReport = [];
for (const locale of coverageOnlyLocales) {
  const localeRoot = path.join(localesRoot, locale);
  const localeFiles = listJsonFiles(localeRoot).map((p) => toRel(p, localeRoot));
  for (const rel of enFiles) {
    if (!localeFiles.includes(rel)) {
      ok = false;
      coverageReport.push({ locale, rel, keys: null });
      continue;
    }
    const localeJson = loadJson(path.join(localeRoot, rel));
    const enKeys = new Set(flattenKeys(loadJson(path.join(enRoot, rel))));
    const localeKeys = new Set(flattenKeys(localeJson));
    const missingKeys = [...enKeys].filter((k) => !localeKeys.has(k)).sort();
    if (missingKeys.length) {
      ok = false;
      coverageReport.push({ locale, rel, keys: missingKeys });
    }
  }
}

if (coverageReport.length) {
  for (const { locale, rel, keys } of coverageReport) {
    if (keys === null) {
      console.error(`[i18n:parity] Missing ${locale} file: ${rel}`);
    } else {
      console.error(`[i18n:parity] ${locale} is missing ${keys.length} keys from ${rel}:`);
      for (const k of keys) console.error(`  - ${k}`);
    }
  }
} else {
  const langs = coverageOnlyLocales.join(", ");
  console.log(`[i18n:parity] OK coverage: ${langs} cover all English keys (0 missing)`);
}

if (!ok) process.exit(1);
console.log("[i18n:parity] OK");
