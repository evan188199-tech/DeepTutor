#!/usr/bin/env node
/**
 * dynamic-literals.mjs — same-file string-literal candidates for dynamic t() sites.
 * For every t(<identifier>) call, collect string-literal values of object literals
 * in the same file whose computed usage looks key-like, then flag values that are
 * NOT en-catalog keys (i18next would print the literal itself = hardcoded copy).
 * Heuristic evidence list — labeled as such.
 * Usage: node dynamic-literals.mjs  (cwd = web/)
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(path.join(process.cwd(), "package.json"));
const ts = require("typescript");
const webRoot = process.cwd();
const CODE_DIRS = ["app", "components", "features", "hooks", "lib", "shared"];

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

const en = JSON.parse(fs.readFileSync(path.join(webRoot, "locales", "en", "app.json"), "utf8"));
const enKeys = new Set(Object.keys(en));

function stringLiteralsOf(expr) {
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) return [expr.text];
  if (ts.isConditionalExpression(expr)) return [...stringLiteralsOf(expr.whenTrue), ...stringLiteralsOf(expr.whenFalse)];
  if (ts.isParenthesizedExpression(expr)) return stringLiteralsOf(expr.expression);
  return [];
}

const findings = [];
for (const dir of CODE_DIRS) {
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) continue;
  for (const file of listCodeFiles(abs)) {
    const content = fs.readFileSync(file, "utf8");
    const rel = path.relative(webRoot, file).replaceAll("\\", "/");
    const sf = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
    const lineOf = (n) => content.slice(0, n.getStart(sf)).split("\n").length;

    // pass 1: collect t() dynamic-arg identifiers
    const dynIdents = new Map(); // name -> first line
    // pass 2: collect object literals identifier -> string values
    const objValues = new Map(); // name -> [{value, line}]
    function collect(node) {
      if (ts.isCallExpression(node)) {
        const callee = node.expression;
        const isT =
          (ts.isIdentifier(callee) && callee.text === "t") ||
          (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
        if (isT && node.arguments.length) {
          const arg = node.arguments[0];
          if (ts.isIdentifier(arg)) {
            const name = arg.text;
            if (!dynIdents.has(name)) dynIdents.set(name, lineOf(node));
          } else if (ts.isElementAccessExpression(arg) && arg.argumentExpression) {
            // t({running:"Running"}[mark]) — literal map inline at call site
            const obj = ts.isParenthesizedExpression(arg.expression)
              ? arg.expression.expression
              : arg.expression;
            if (ts.isObjectLiteralExpression(obj)) {
              for (const prop of obj.properties) {
                if (ts.isPropertyAssignment(prop) && (ts.isStringLiteral(prop.initializer) || ts.isNoSubstitutionTemplateLiteral(prop.initializer))) {
                  const v = prop.initializer.text;
                  if (enKeys.has(v)) continue;
                  if (!/[A-Za-z\u4e00-\u9fff]/.test(v)) continue;
                  findings.push({ file: rel, ident: "<inline-map>", callLine: lineOf(node), valueLine: lineOf(prop), value: v });
                }
              }
            }
          }
        }
      }
      // helper functions returning string literals (e.g. accountRoleLabelKey())
      if ((ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node)) && node.name && ts.isIdentifier(node.name)) {
        const name = node.name.text;
        const vals = [];
        function walkReturns(n) {
          if (ts.isReturnStatement(n) && n.expression) {
            for (const lit of stringLiteralsOf(n.expression)) vals.push({ value: lit, line: lineOf(n) });
          }
          ts.forEachChild(n, walkReturns);
        }
        walkReturns(node);
        if (vals.length && !objValues.has(name)) objValues.set(name, vals);
      }
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && ts.isObjectLiteralExpression(node.initializer)) {
        const vals = [];
        for (const prop of node.initializer.properties) {
          if (ts.isPropertyAssignment(prop) && prop.initializer && (ts.isStringLiteral(prop.initializer) || ts.isNoSubstitutionTemplateLiteral(prop.initializer))) {
            vals.push({ value: prop.initializer.text, line: lineOf(prop) });
          }
        }
        if (vals.length && !objValues.has(node.name.text)) objValues.set(node.name.text, vals);
      }
      ts.forEachChild(node, collect);
    }
    collect(sf);

    for (const [name, line] of dynIdents) {
      const vals = objValues.get(name);
      if (!vals) continue;
      for (const { value, line: vline } of vals) {
        if (enKeys.has(value)) continue;
        if (!/[A-Za-z\u4e00-\u9fff]/.test(value)) continue;
        findings.push({ file: rel, ident: name, callLine: line, valueLine: vline, value });
      }
    }
  }
}
fs.writeFileSync(
  path.resolve(process.argv[2] || "dynamic-literals.json"),
  JSON.stringify(findings, null, 2),
);
const byFile = new Map();
for (const f of findings) byFile.set(f.file, (byFile.get(f.file) || 0) + 1);
console.log(`[dynamic-literals] ${findings.length} non-key literal candidates across ${byFile.size} files`);
for (const [f, n] of [...byFile].sort((a, b) => b[1] - a[1]).slice(0, 40)) console.log(`  ${String(n).padStart(3)}  ${f}`);
