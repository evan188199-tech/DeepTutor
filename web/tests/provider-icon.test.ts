import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  PROVIDER_ICONS,
  canonicalProviderBrand,
  providerIconSpec,
} from "../lib/provider-branding";

// ProviderIcon.tsx delegates every decision to providerIconSpec(); these
// fixtures are the contract under test. Fallback values below are chosen so a
// future provider entry (e.g. the `you` mark discussed in upstream #1915)
// cannot flip them from fallback to hit.
const root = path.resolve(process.cwd(), "..");
const assetPath = (file: string) =>
  path.join(root, "web", "public", "provider-icons", file);

test("known providers resolve to their bundled mark, case- and whitespace-insensitive", () => {
  const expectedFile: Record<string, string> = {
    openai: "openai.svg",
    anthropic: "anthropic.svg",
    gemini: "gemini-color.svg",
    deepseek: "deepseek-color.svg",
    duckduckgo: "duckduckgo.svg",
    searxng: "searxng.svg",
    tavily: "tavily-color.svg",
    azure_openai: "azure-color.svg",
    github_copilot: "githubcopilot.svg",
    llama_cpp: "llama-cpp.svg",
  };
  for (const [provider, file] of Object.entries(expectedFile)) {
    const spec = providerIconSpec(provider);
    assert.ok(spec, `expected ${provider} to have an icon`);
    assert.equal(spec!.file, file, `expected ${provider} to map to ${file}`);
    if (spec!.darkFile) {
      assert.ok(
        assetExists(spec!.darkFile),
        `${provider} dark variant must ship`,
      );
    }
  }
  // Callers pass raw account/config strings; normalization is part of the hit.
  for (const variant of ["OpenAI", "OPENAI", "  openai  ", "DeepSeek"]) {
    const spec = providerIconSpec(variant);
    assert.ok(spec, `expected ${variant} to hit via normalization`);
  }
});

function assetExists(file: string): boolean {
  return existsSync(assetPath(file));
}

test("every mapped asset ships, stays inside /provider-icons/, and is non-empty", () => {
  for (const [provider, spec] of Object.entries(PROVIDER_ICONS)) {
    for (const file of [spec.file, spec.darkFile].filter(Boolean) as string[]) {
      assert.equal(
        file.includes("..") || path.isAbsolute(file),
        false,
        `${provider}: ${file} would escape /provider-icons/`,
      );
      assert.ok(assetExists(file), `${provider}: ${file} is missing`);
      const content = readFileSync(assetPath(file));
      assert.ok(
        content.length > 0,
        `${provider}: ${file} is an empty asset`,
      );
    }
  }
});

test("unknown, empty, and junk values fall back to the generic mark", () => {
  // ProviderIcon renders the generic Bot glyph whenever the spec is undefined;
  // prototype-adjacent keys must stay fallbacks, not resolve via the prototype.
  for (const value of [
    "custom-thing",
    "definitely-not-a-provider",
    "",
    "   ",
    null,
    undefined,
    "__proto__",
    "constructor",
    "PROVIDER_ICONS",
  ]) {
    assert.doesNotThrow(() => providerIconSpec(value));
    assert.equal(
      providerIconSpec(value),
      undefined,
      `expected ${String(value)} to fall back, not hit`,
    );
  }
});

test("canonical icon keys are fixed points under normalization", () => {
  for (const key of Object.keys(PROVIDER_ICONS)) {
    assert.equal(
      canonicalProviderBrand(key),
      key,
      `${key} must canonicalize to itself`,
    );
    assert.equal(
      providerIconSpec(key.toUpperCase()),
      providerIconSpec(key),
      `${key} must hit regardless of case`,
    );
  }
});

test("aliases resolve to the same mark as their canonical id", () => {
  const aliasGroups: Record<string, string[]> = {
    azure_openai: ["azure", "azure-openai", "azureopenai"],
    anthropic: ["claude", "Claude"],
    gemini: ["google_genai"],
    codebuddy: ["workbuddy", "codebuddy-code", "codebuddy_code"],
    github_copilot: ["github-copilot"],
    openai_codex: ["openai-codex"],
    lm_studio: ["lm-studio"],
    atlascloud: ["atlas", "atlas_cloud", "atlas-cloud"],
    edenai: ["eden_ai"],
    novita: ["novita_ai"],
    orcarouter: ["orca_router", "orca-router"],
    cheaperinference: ["cheaper_inference"],
    api_route: ["api route", "API Route"],
    futureinfra: ["future_infra"],
    volcengine_coding_plan: ["volcenginecodingplan"],
    byteplus_coding_plan: ["bytepluscodingplan"],
  };
  for (const [canonical, aliases] of Object.entries(aliasGroups)) {
    const target = providerIconSpec(canonical);
    for (const alias of aliases) {
      assert.equal(
        canonicalProviderBrand(alias),
        canonical,
        `${alias} must canonicalize to ${canonical}`,
      );
      assert.equal(
        providerIconSpec(alias),
        target,
        `${alias} must render exactly like ${canonical}`,
      );
    }
    // Every group here names a real provider id, so the canonical side hits.
    assert.ok(target, `expected canonical ${canonical} to have an icon`);
  }
  // Y-API has no verified brand asset yet: both spellings canonicalize to
  // y_api and share its (currently generic) rendering — hit or fallback alike.
  for (const spelling of ["y-api", "yapi", "Y-API"]) {
    assert.equal(canonicalProviderBrand(spelling), "y_api");
    assert.equal(
      providerIconSpec(spelling),
      providerIconSpec("y_api"),
      `${spelling} must render exactly like y_api`,
    );
  }
});
