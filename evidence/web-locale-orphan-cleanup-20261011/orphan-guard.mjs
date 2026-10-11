// orphan-guard.mjs — AGEN-1729 anti-regression assertion.
// Asserts that every key deleted by this cleanup (evidence/deletion-list-*.txt)
// still has zero raw-substring references in web source and tests. A hit means
// new code started referencing a deleted key without re-adding translations —
// restore the key (or add it back to all locales) before merging.
//
// Run from anywhere:  node evidence/web-locale-orphan-cleanup-20261011/orphan-guard.mjs
// Exit 0 = clean; exit 1 = hits found (listed).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const evDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(evDir, "../../web");
const GREP_DIRS = ["app", "components", "features", "hooks", "lib", "shared", "i18n", "context", "contracts", "types"];

const keys = new Set();
for (const loc of ["en", "zh", "de", "fr"]) {
  const list = path.join(evDir, `deletion-list-${loc}.json`);
  if (!fs.existsSync(list)) throw new Error(`missing ${list}`);
  for (const k of JSON.parse(fs.readFileSync(list, "utf8"))) keys.add(k);
}

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
const files = [];
for (const d of GREP_DIRS) {
  const abs = path.join(webRoot, d);
  if (fs.existsSync(abs)) files.push(...listFiles(abs));
}
const testsAbs = path.join(webRoot, "tests");
if (fs.existsSync(testsAbs)) files.push(...listFiles(testsAbs));

const deleted = new Set();
for (const loc of ["en", "zh", "de", "fr"]) {
  const data = JSON.parse(fs.readFileSync(path.join(webRoot, "locales", loc, "app.json"), "utf8"));
  for (const k of keys) if (Object.hasOwn(data, k)) throw new Error(`deleted key "${k}" re-added to ${loc}/app.json`);
}

const violations = [];
const keyArr = [...keys];
for (const f of files) {
  const rel = path.relative(webRoot, f).replaceAll("\\", "/");
  const lines = fs.readFileSync(f, "utf8").split("\n");
  for (let i = 0; i < lines.length; i++) {
    for (const k of keyArr) {
      if (lines[i].includes(k)) {
        violations.push(`${rel}:${i + 1} references deleted key "${k}"`);
        if (violations.length >= 50) {
          console.error(orphanGuardReport());
          process.exit(1);
        }
      }
    }
  }
}
function orphanGuardReport() {
  return `orphan-guard: ${violations.length}+ of ${keys.size} deleted keys are referenced again\n` + violations.join("\n");
}
if (violations.length) {
  console.error(orphanGuardReport());
  process.exit(1);
}
console.log(`orphan-guard OK: ${keys.size} deleted keys have zero references in web source+tests; deleted keys absent from en/zh/de/fr app.json`);
