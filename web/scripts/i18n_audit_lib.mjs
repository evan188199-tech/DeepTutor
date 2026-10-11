import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

export const AUDIT_SOURCE_DIRS = ["app", "components", "features", "hooks", "lib", "shared"];

export function listCodeFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listCodeFiles(full));
    else if (ent.isFile() && /\.tsx?$/.test(ent.name)) out.push(full);
  }
  return out;
}

/** Parse literal keys without mistaking comments, escapes or plural keys for gaps. */
export function literalKeys(expression) {
  if (!expression) return [];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return [expression.text];
  }
  if (ts.isConditionalExpression(expression)) {
    return [...literalKeys(expression.whenTrue), ...literalKeys(expression.whenFalse)];
  }
  return [];
}

export function translationKeys(file, content) {
  const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
  const keys = new Set();
  function visit(node) {
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const isTranslation =
        (ts.isIdentifier(callee) && callee.text === "t") ||
        (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
      if (isTranslation) {
        for (const key of literalKeys(node.arguments[0])) keys.add(key);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return keys;
}

export function collectUsedKeys(webRoot, dirs = AUDIT_SOURCE_DIRS) {
  const usedKeys = new Set();
  for (const dir of dirs) {
    const full = path.join(webRoot, dir);
    if (!fs.existsSync(full)) continue;
    for (const file of listCodeFiles(full)) {
      const content = fs.readFileSync(file, "utf8");
      for (const key of translationKeys(file, content)) {
        if (key) usedKeys.add(key);
      }
    }
  }
  return usedKeys;
}

export function pluralCategories(locale) {
  return new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
}

export function hasTranslation(entries, pluralForms, key) {
  if (Object.hasOwn(entries, key)) return true;
  return pluralForms.every((form) => Object.hasOwn(entries, `${key}_${form}`));
}

export function missingUsedKeys(entries, usedKeys, locale) {
  const pluralForms = pluralCategories(locale);
  return [...usedKeys].filter((key) => !hasTranslation(entries, pluralForms, key));
}
