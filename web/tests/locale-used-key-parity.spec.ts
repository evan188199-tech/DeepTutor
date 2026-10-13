import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const webRoot = path.resolve();
const CODE_DIRS = ["app", "components", "features", "hooks", "lib", "shared"];
const LOCALES = ["en", "zh", "fr", "de", "uk", "pl"];

type UsedKey = { key: string; occurrences: string[] };

function listCodeFiles(dir: string): string[] {
  const out: string[] = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listCodeFiles(full));
    else if (ent.isFile() && /\.tsx?$/.test(ent.name)) out.push(full);
  }
  return out;
}

function literalKeys(expression: ts.Expression | undefined): string[] {
  if (!expression) return [];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return [expression.text];
  }
  if (ts.isConditionalExpression(expression)) {
    return [...literalKeys(expression.whenTrue), ...literalKeys(expression.whenFalse)];
  }
  return [];
}

function collectUsedKeys(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const dir of CODE_DIRS) {
    const abs = path.join(webRoot, dir);
    if (!fs.existsSync(abs)) continue;
    for (const file of listCodeFiles(abs)) {
      const content = fs.readFileSync(file, "utf8");
      const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
      const rel = path.relative(webRoot, file).replaceAll("\\", "/");
      function visit(node: ts.Node) {
        if (ts.isCallExpression(node)) {
          const callee = node.expression;
          const isTranslation =
            (ts.isIdentifier(callee) && callee.text === "t") ||
            (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
          if (isTranslation) {
            const line = content.slice(0, node.getStart(source)).split("\n").length;
            for (const key of literalKeys(node.arguments[0])) {
              if (!key) continue;
              if (!used.has(key)) used.set(key, []);
              used.get(key)!.push(`${rel}:${line}`);
            }
          }
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  return used;
}

function loadCatalog(locale: string): Record<string, string> {
  const file = path.join(webRoot, "locales", locale, "app.json");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function isMissing(entries: Record<string, string>, locale: string, key: string): boolean {
  if (Object.hasOwn(entries, key)) return false;
  const forms = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
  return !forms.every((form) => Object.hasOwn(entries, `${key}_${form}`));
}

const usedKeys = collectUsedKeys();
const catalogs = Object.fromEntries(LOCALES.map((l) => [l, loadCatalog(l)]));

describe("web locale used-key parity", () => {
  it("collects t() keys from web source", () => {
    expect(usedKeys.size).toBeGreaterThan(0);
  });

  it("loads app.json for all six locales", () => {
    for (const locale of LOCALES) {
      expect(Object.keys(catalogs[locale]).length, `${locale}/app.json is empty`).toBeGreaterThan(0);
    }
  });

  for (const locale of LOCALES) {
    it(`resolves every used t() key in ${locale}`, () => {
      const missing: UsedKey[] = [];
      for (const [key, occurrences] of usedKeys) {
        if (isMissing(catalogs[locale], locale, key)) {
          missing.push({ key, occurrences });
        }
      }
      const detail = missing
        .slice(0, 20)
        .map(({ key, occurrences }) => `  - ${JSON.stringify(key)} (${occurrences[0]})`)
        .join("\n");
      expect(
        missing.map(({ key }) => key),
        `${locale}: ${missing.length} used keys lack a locale entry${detail ? `:\n${detail}` : ""}`,
      ).toEqual([]);
    });
  }
});
