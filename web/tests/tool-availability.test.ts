import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  toolAvailabilityCopy,
  toolEffectiveEnabled,
} from "../lib/tool-availability";

function localeCatalog(lang: string): Record<string, string> {
  return JSON.parse(
    readFileSync(path.resolve(process.cwd(), "locales", lang, "app.json"), "utf8"),
  );
}

test("configured runtime and saved preference are both required", () => {
  assert.equal(toolEffectiveEnabled(true, true, false), true);
  assert.equal(toolEffectiveEnabled(true, false, false), false);
  assert.equal(toolEffectiveEnabled(false, true, false), false);
  assert.equal(toolEffectiveEnabled(true, true, true), false);
});

test("search provider readiness has actionable localized copy", () => {
  for (const lang of ["en", "zh", "de", "fr", "pl", "uk"]) {
    const catalog = localeCatalog(lang);
    const translate = (key: string) => catalog[key] ?? key;
    const copy = toolAvailabilityCopy(
      "search_provider_not_configured",
      translate as never,
    );
    assert.equal(
      copy.badge,
      catalog["toolAvailability.searchProviderNotConfigured.badge"],
    );
    assert.equal(
      copy.detail,
      catalog["toolAvailability.searchProviderNotConfigured.detail"],
    );
    assert.equal(copy.href, "/settings#search");
    assert.ok(copy.badge.length > 0 && copy.detail.length > 0, `${lang} copy is empty`);
  }
});

test("every reason resolves through locale keys, never hardcoded copy", () => {
  const catalog = localeCatalog("en");
  const requested: string[] = [];
  const translate = (key: string) => {
    requested.push(key);
    return catalog[key] ?? key;
  };
  const reasons: (string | null | undefined)[] = [
    "search_provider_not_configured",
    "search_credentials_missing",
    "something_else",
    null,
    undefined,
  ];
  for (const reason of reasons) {
    const copy = toolAvailabilityCopy(reason, translate as never);
    assert.ok(copy.badge.length > 0 && copy.detail.length > 0);
  }
  assert.ok(requested.length > 0);
  for (const key of requested) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(catalog, key),
      `missing locale key: ${key}`,
    );
  }
});
