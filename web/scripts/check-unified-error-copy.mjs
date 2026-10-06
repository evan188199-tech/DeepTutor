#!/usr/bin/env node
/**
 * Guard the single-copy convergence of web network-failure and rate-limit
 * messages (error-messages scan #15): each family must resolve to exactly
 * one locale key, so the superseded writings must not reappear anywhere
 * under web/. Exits 1 listing every re-introduced occurrence.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "..");

const RETIRED_WRITINGS = [
  "Unable to reach the server",
  "Could not reach the server",
  "Couldn't confirm your answer",
  "The model provider was rate-limiting the requests.",
];

const SKIP_DIRS = new Set(["node_modules", ".next", ".turbo", "coverage"]);

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(path.join(dir, entry.name));
    } else if (/\.(ts|tsx|js|jsx|mjs|cjs|json)$/.test(entry.name)) {
      yield path.join(dir, entry.name);
    }
  }
}

const offenders = [];
for (const file of walk(WEB_ROOT)) {
  if (file === fileURLToPath(import.meta.url)) continue;
  const lines = fs.readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    for (const writing of RETIRED_WRITINGS) {
      if (line.includes(writing)) {
        offenders.push(
          `${path.relative(WEB_ROOT, file)}:${i + 1}: ${writing}`,
        );
      }
    }
  });
}

if (offenders.length > 0) {
  console.error("Retired error copy found (use the unified locale key instead):");
  for (const offender of offenders) console.error(`  ${offender}`);
  process.exit(1);
}
console.log("OK: no retired network-failure/rate-limit copy under web/");
