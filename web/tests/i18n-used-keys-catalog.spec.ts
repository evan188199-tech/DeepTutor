import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

import { collectUsedKeys, missingUsedKeys } from "../scripts/i18n_audit_lib.mjs";

const webRoot = path.resolve();

function loadCatalog(locale: string): Record<string, string> {
  return JSON.parse(
    readFileSync(path.join(webRoot, "locales", locale, "app.json"), "utf8"),
  ) as Record<string, string>;
}

const MIN_EXPECTED_USED_KEYS = 3000;

const usedKeys = collectUsedKeys(webRoot);

it("extracts a non-trivial set of literal t() keys from the real source tree", () => {
  expect(usedKeys.size).toBeGreaterThan(MIN_EXPECTED_USED_KEYS);
});

it("en locale defines every literal t() key used in the source tree", () => {
  expect(missingUsedKeys(loadCatalog("en"), usedKeys, "en")).toEqual([]);
});

it("zh locale defines every literal t() key used in the source tree", () => {
  expect(missingUsedKeys(loadCatalog("zh"), usedKeys, "zh")).toEqual([]);
});
