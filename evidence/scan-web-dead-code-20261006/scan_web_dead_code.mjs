#!/usr/bin/env node
// AGEN-923 read-only dead-code scan for web/ (TS/TSX).
// Parses with the TypeScript compiler API. Never writes outside --out.
// Usage: node scan_web_dead_code.mjs --web <web dir> --out <evidence out dir> [--ts <typescript path>]
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const argv = process.argv.slice(2);
function arg(name, dflt) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
}
const WEB = path.resolve(arg("--web", "web"));
const OUT = path.resolve(arg("--out", "evidence/scan-out"));
const require_ = createRequire(import.meta.url);
const ts = require_(arg("--ts", "/Users/Shared/DeepTutor/web/node_modules/typescript"));

if (!fs.existsSync(path.join(WEB, "package.json"))) {
  console.error(`web dir not found: ${WEB}`);
  process.exit(2);
}
fs.mkdirSync(OUT, { recursive: true });

const EXTS = ["", ".ts", ".tsx", ".d.ts", "/index.ts", "/index.tsx"];
const NEXT_ENTRY_BASENAMES = new Set([
  "page", "layout", "route", "loading", "error", "global-error", "not-found",
  "template", "default", "robots", "sitemap", "manifest", "icon", "apple-icon",
  "favicon", "opengraph-image", "twitter-image",
]);
const NEXT_FRAMEWORK_EXPORTS = new Set([
  "metadata", "generateMetadata", "generateStaticParams", "dynamic", "revalidate",
  "runtime", "fetchCache", "preferredRegion", "maxDuration", "dynamicParams",
  "viewport", "generateViewport", "generateImageMetadata", "contentType",
]);

function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name === "coverage" || e.name === "dist") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
}

function relWeb(abs) {
  return path.relative(WEB, abs).split(path.sep).join("/");
}

function classifyFile(abs) {
  const rel = relWeb(abs);
  const base = path.basename(rel).replace(/\.(ts|tsx)$/, "");
  const isTest = rel.startsWith("tests/") || /\.(spec|test)\.(ts|tsx)$/.test(rel);
  const isScript = rel.startsWith("scripts/");
  const isGenerated = rel.includes("/contracts/generated/") || rel.startsWith("contracts/generated/");
  const isVendor = rel.startsWith("vendor/");
  const isAmbient = rel.endsWith(".d.ts");
  const inApp = rel.startsWith("app/");
  const isNextEntry = (inApp && NEXT_ENTRY_BASENAMES.has(base)) ||
    ["middleware", "instrumentation", "proxy", "next-env"].includes(base);
  const isConfig = /\.config\.(ts|tsx)$/.test(rel);
  return { rel, isTest, isScript, isGenerated, isVendor, isAmbient, inApp, isNextEntry, isConfig };
}

function resolveSpecifier(fromFile, spec) {
  if (!spec) return null;
  let base = null;
  if (spec.startsWith("@/")) base = path.join(WEB, spec.slice(2));
  else if (spec.startsWith("./") || spec.startsWith("../")) base = path.resolve(path.dirname(fromFile), spec);
  else return null; // bare module (npm package)
  for (const ext of EXTS) {
    const cand = base + ext;
    if (fs.existsSync(cand) && fs.statSync(cand).isFile() && /\.(ts|tsx)$/.test(cand)) return cand;
  }
  return null;
}

// ---------- pass 1: parse every file ----------
const files = walk(WEB).filter((f) => /\.(ts|tsx)$/.test(f)).sort();
const info = new Map(); // abs -> file info

for (const abs of files) {
  const cls = classifyFile(abs);
  const text = fs.readFileSync(abs, "utf8");
  const sf = ts.createSourceFile(abs, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(abs) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

  const exports = [];      // {name, line, kind, isDefault, isType}
  const defaultExport = { present: false, line: 0 };
  let defaultName = null;
  const namedReexports = []; // {target, names:[{imported, local}]}
  const wildcardReexports = []; // target abs files
  const imports = [];      // {target, names:[], kind}
  const dynamicImports = []; // {target|null, prefix}
  const jsxTags = new Set();
  const idents = new Map(); // name -> count
  const constsWithJsx = new Set(); // exported const whose initializer contains JSX
  const strings = new Set();
  const dynamicKeyPrefixes = []; // t(`prefix.${x}`) heads
  const lines = text.split("\n");

  function lineOf(node) { return sf.getLineAndCharacterOfPosition(node.getStart()).line + 1; }

  function visit(node) {
    if (ts.isImportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const spec = node.moduleSpecifier.text;
      const target = resolveSpecifier(abs, spec);
      const clause = node.importClause;
      const names = [];
      let kind = "bare";
      if (clause) {
        if (clause.name) { names.push("default"); kind = "default"; }
        const nb = clause.namedBindings;
        if (nb && ts.isNamespaceImport(nb)) { kind = "namespace"; }
        else if (nb && ts.isNamedImports(nb)) {
          for (const el of nb.elements) names.push(el.propertyName ? el.propertyName.text : el.name.text);
          if (kind !== "default") kind = "named";
          else kind = "default+named";
        }
      }
      imports.push({ target: target ? relWeb(target) : null, spec, names, kind });
    } else if (ts.isExportDeclaration(node)) {
      const spec = node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier) ? node.moduleSpecifier.text : null;
      const target = spec ? resolveSpecifier(abs, spec) : null;
      if (node.exportClause && ts.isNamedExports(node.exportClause)) {
        const names = node.exportClause.elements.map((el) => ({
          imported: el.propertyName ? el.propertyName.text : el.name.text,
          local: el.name.text,
        }));
        if (target) namedReexports.push({ target: relWeb(target), names });
        // local `export { X }` / `export type { X }` handled in the statements pass below
        if (target && node.isTypeOnly) for (const n of names) { /* type re-exports still counted */ }
      } else if (target) {
        wildcardReexports.push(relWeb(target));
      }
    } else if (ts.isExportAssignment(node)) {
      defaultExport.present = true;
      defaultExport.line = lineOf(node);
      if (node.expression && ts.isIdentifier(node.expression)) defaultName = node.expression.text;
    } else if (node.modifiers && node.modifiers.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) {
      const isDefaultDecl = node.modifiers.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
      if (ts.isVariableStatement(node)) {
        for (const d of node.declarationList.declarations) {
          const kind = "const";
          if (ts.isObjectBindingPattern(d.name) || ts.isArrayBindingPattern(d.name)) continue;
          exports.push({ name: d.name.getText(sf), line: lineOf(node), kind, isDefault: false, isType: false });
          if (isDefaultDecl) defaultName = d.name.getText(sf);
          if (d.initializer) {
            let hasJsx = false;
            (function scanJsx(n) {
              if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) { hasJsx = true; return; }
              ts.forEachChild(n, scanJsx);
            })(d.initializer);
            if (hasJsx) constsWithJsx.add(d.name.getText(sf));
          }
        }
      } else if (ts.isFunctionDeclaration(node) && node.name) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "function", isDefault: false, isType: false });
        if (isDefaultDecl) defaultName = node.name.getText(sf);
      } else if (ts.isClassDeclaration(node) && node.name) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "class", isDefault: false, isType: false });
        if (isDefaultDecl) defaultName = node.name.getText(sf);
      } else if (ts.isTypeAliasDeclaration(node)) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "type", isDefault: false, isType: true });
      } else if (ts.isInterfaceDeclaration(node)) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "interface", isDefault: false, isType: true });
      } else if (ts.isEnumDeclaration(node)) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "enum", isDefault: false, isType: false });
      } else if (ts.isModuleDeclaration(node) && node.name && ts.isIdentifier(node.name)) {
        exports.push({ name: node.name.getText(sf), line: lineOf(node), kind: "namespace", isDefault: false, isType: false });
      }
    } else if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const isDynImport = callee.kind === ts.SyntaxKind.ImportKeyword;
      if (isDynImport && node.arguments.length === 1) {
        const a = node.arguments[0];
        if (ts.isStringLiteral(a)) {
          const target = resolveSpecifier(abs, a.text);
          dynamicImports.push({ target: target ? relWeb(target) : null, prefix: null, spec: a.text });
        } else if (ts.isTemplateExpression(a)) {
          dynamicImports.push({ target: null, prefix: a.head.text, spec: null });
        } else if (ts.isNoSubstitutionTemplateLiteral(a)) {
          const target = resolveSpecifier(abs, a.text);
          dynamicImports.push({ target: target ? relWeb(target) : null, prefix: null, spec: a.text });
        }
      } else if (ts.isIdentifier(callee) && node.arguments.length >= 1) {
        const a0 = node.arguments[0];
        if ((callee.text === "t" || callee.escapedText === "t" || /\.t$/.test(callee.getText(sf))) &&
            (ts.isTemplateExpression(a0))) {
          dynamicKeyPrefixes.push(a0.head.text);
        }
      }
    } else if (ts.isStringLiteral(node)) {
      strings.add(node.text);
    } else if (ts.isNoSubstitutionTemplateLiteral(node)) {
      strings.add(node.text);
    } else if (ts.isJsxText(node)) {
      const t = node.getText(sf).trim();
      if (t) strings.add(t);
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxClosingElement(node)) {
      const tag = node.tagName;
      if (ts.isIdentifier(tag)) jsxTags.add(tag.text);
    }
    if (ts.isIdentifier(node)) {
      // crude token guard: count every identifier token anywhere (conservative)
      const n = node.text;
      if (n) idents.set(n, (idents.get(n) || 0) + 1);
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);

  // names exported via `export { a, b }` / `export type { a }` (no module specifier)
  for (const st of sf.statements) {
    if (ts.isExportDeclaration(st) && !st.moduleSpecifier && st.exportClause && ts.isNamedExports(st.exportClause)) {
      for (const el of st.exportClause.elements) {
        exports.push({
          name: el.name.text,
          line: sf.getLineAndCharacterOfPosition(el.getStart()).line + 1,
          kind: st.isTypeOnly ? "reexport-local-type" : "reexport-local",
          isDefault: false,
          isType: st.isTypeOnly,
        });
      }
    }
  }

  info.set(abs, {
    abs, cls, text, sf, lines,
    exports, defaultExport, defaultName, namedReexports, wildcardReexports, imports, dynamicImports,
    jsxTags, idents, constsWithJsx, strings, dynamicKeyPrefixes,
  });
}

// unified consumer lookup: symbol X, or the file's default export if X is its default binding
function consumersOf(f, e) {
  const cmap = consumed.get(f.cls.rel) || new Map();
  const merge = (a, b) => {
    if (!b) return a;
    const out = a || { direct: new Set(), ns: new Set() };
    for (const x of b.direct) out.direct.add(x);
    for (const x of b.ns) out.ns.add(x);
    return out;
  };
  let entry = cmap.get(e.name) || null;
  if (f.defaultName === e.name || (e.name === "default")) entry = merge(entry, cmap.get("default"));
  return entry;
}

const absByRel = new Map();
for (const [abs, f] of info) absByRel.set(f.cls.rel, abs);

// ---------- pass 2: reference graph ----------
// consumed[targetRel][name] = { direct:Set<srcCls>, ns:Set<srcCls> }
const consumed = new Map();
function mark(targetRel, name, src, via) {
  if (!targetRel) return;
  if (!consumed.has(targetRel)) consumed.set(targetRel, new Map());
  const m = consumed.get(targetRel);
  if (!m.has(name)) m.set(name, { direct: new Set(), ns: new Set() });
  m.get(name)[via].add(src);
}
function markAll(targetRel, src, via) {
  const f = absByRel.get(targetRel);
  if (!f) return;
  for (const e of info.get(f).exports) mark(targetRel, e.name, src, via);
  for (const w of info.get(f).wildcardReexports) {
    markAll(w, src, via);
  }
}

for (const [abs, f] of info) {
  const src = f.cls.rel;
  for (const imp of f.imports) {
    if (!imp.target) continue;
    if (imp.kind === "namespace") markAll(imp.target, src, "ns");
    else if (imp.kind === "bare") { /* side-effect import: nothing */ }
    else for (const n of imp.names) mark(imp.target, n, src, "direct");
  }
  for (const re of f.namedReexports) {
    for (const n of re.names) {
      mark(re.target, n.imported, src, "direct");
      // consumers of this file's local name also consume the original
      const localMap = consumed.get(src);
      // handled transitively below
    }
  }
  for (const w of f.wildcardReexports) markAll(w, src, "ns");
  // dynamic imports consume default (and namespace) of target
  for (const d of f.dynamicImports) {
    if (d.target) mark(d.target, "default", src, "direct");
  }
}

// transitive: named re-export chains `export { X } from M` — a consumer of F for name X consumes X in M.
// We approximate: for every file F with namedReexports, for every entry in consumed[F] with name N
// matching a re-exported local name, mark N in the source module.
let changed = true;
let guard = 0;
while (changed && guard < 20) {
  changed = false;
  guard++;
  for (const [abs, f] of info) {
    const src = f.cls.rel;
    for (const re of f.namedReexports) {
      const cmap = consumed.get(src);
      if (!cmap) continue;
      for (const n of re.names) {
        const entry = cmap.get(n.local);
        if (!entry) continue;
        const before = JSON.stringify([...entry.direct].length);
        for (const consumer of entry.direct) mark(re.target, n.imported, consumer, "direct");
        if (JSON.stringify([...entry.direct].length) !== before) changed = true;
      }
    }
  }
}

// token usage across files (crude dynamic-usage guard)
const tokenFiles = new Map(); // name -> Set<rel>
for (const [abs, f] of info) {
  for (const n of f.idents.keys()) {
    if (!tokenFiles.has(n)) tokenFiles.set(n, new Set());
    tokenFiles.get(n).add(f.cls.rel);
  }
}

// ---------- analyses ----------
const isConsumerCls = (c) => !c.isGenerated && !c.isVendor;
const prodFiles = [...info.values()].filter((f) => isConsumerCls(f.cls) && !f.cls.isTest && !f.cls.isScript);
const testFiles = [...info.values()].filter((f) => f.cls.isTest);
const scriptFiles = [...info.values()].filter((f) => f.cls.isScript);

// A. unused files (source candidates, never imported by anyone)
const importedTargets = new Set();
for (const [abs, f] of info) {
  for (const imp of f.imports) if (imp.target) importedTargets.add(imp.target);
  for (const re of f.namedReexports) if (re.target) importedTargets.add(re.target);
  for (const w of f.wildcardReexports) importedTargets.add(w);
  for (const d of f.dynamicImports) if (d.target) importedTargets.add(d.target);
}
const unused_files = [];
for (const [abs, f] of info) {
  const c = f.cls;
  if (c.isTest || c.isScript || c.isGenerated || c.isVendor || c.isAmbient || c.isNextEntry || c.isConfig) continue;
  if (importedTargets.has(c.rel)) continue;
  const loc = f.lines.length;
  unused_files.push({
    file: c.rel, loc,
    jsx_import_possible: false,
    note: c.inApp ? "app/ non-entry file" : "",
  });
}

// B. unused exports
const unused_exports = [];
for (const [abs, f] of info) {
  const c = f.cls;
  if (c.isTest || c.isScript || c.isGenerated || c.isVendor || c.isAmbient || c.isConfig) continue;
  const cmap = consumed.get(c.rel) || new Map();
  const seen = new Set();
  for (const e of f.exports) {
    if (seen.has(e.name + ":" + e.line)) continue;
    seen.add(e.name + ":" + e.line);
    if (c.isNextEntry && (e.isDefault || NEXT_FRAMEWORK_EXPORTS.has(e.name))) continue;
    if (c.inApp && c.isNextEntry) continue;
    const entry = consumersOf(f, e);
    const directProd = entry ? [...entry.direct].filter((r) => {
      const tc = info.get(absByRel.get(r)).cls;
      return isConsumerCls(tc) && !tc.isTest && !tc.isScript;
    }) : [];
    const directTest = entry ? [...entry.direct].filter((r) => info.get(absByRel.get(r)).cls.isTest) : [];
    const directScript = entry ? [...entry.direct].filter((r) => info.get(absByRel.get(r)).cls.isScript) : [];
    const nsCovered = entry ? entry.ns.size > 0 : false;
    const elsewhere = (tokenFiles.get(e.name) || new Set());
    elsewhere.delete(c.rel);
    // crude guard: referenced as identifier elsewhere (any file) even without import
    const tokenFilesCount = elsewhere.size;
    if (directProd.length > 0) continue;            // consumed by prod -> alive
    if (nsCovered) continue;                        // wildcard/namespace covered -> not provably dead
    const cats = [];
    if (directTest.length > 0) cats.push("test");
    if (directScript.length > 0) cats.push("script");
    unused_exports.push({
      file: c.rel, line: e.line, name: e.name, kind: e.kind, isType: e.isType,
      cats, test_files: directTest, script_files: directScript,
      internal_refs: f.idents.get(e.name) || 0,
      name_elsewhere_n: tokenFilesCount,
      name_elsewhere: [...elsewhere].slice(0, 5),
    });
  }
  if (f.defaultExport.present && !c.isNextEntry) {
    const entry = cmap.get("default");
    const directProd = entry ? [...entry.direct].filter((r) => {
      const tc = info.get(absByRel.get(r)).cls;
      return isConsumerCls(tc) && !tc.isTest && !tc.isScript;
    }) : [];
    const directTest = entry ? [...entry.direct].filter((r) => info.get(absByRel.get(r)).cls.isTest) : [];
    const dyn = f.dynamicImports.length + [...info.values()].filter((o) => o.dynamicImports.some((d) => d.target === c.rel)).length;
    if (directProd.length === 0 && dyn === 0) {
      unused_exports.push({
        file: c.rel, line: f.defaultExport.line, name: "default", kind: "default", isType: false,
        cats: directTest.length ? ["test"] : [], test_files: directTest, script_files: [],
        name_elsewhere_n: 0, name_elsewhere: [],
      });
    }
  }
}

// C. unmounted components: capitalized exported component symbols
const component_like = [];
for (const [abs, f] of info) {
  const c = f.cls;
  if (c.isTest || c.isScript || c.isGenerated || c.isVendor || c.isAmbient || c.isConfig) continue;
  const usesJsx = f.jsxTags.size > 0;
  const isTsx = c.rel.endsWith(".tsx");
  const constsWithJsx = f.constsWithJsx;
  for (const e of f.exports) {
    if (!/^[A-Z]/.test(e.name)) continue;
    if (e.isType || e.kind === "type" || e.kind === "interface" || e.kind === "enum" ||
        e.kind === "reexport-local-type") continue;
    if (c.isNextEntry) continue;
    const isComponentCandidate =
      (isTsx && usesJsx && ["function", "class"].includes(e.kind)) ||
      (isTsx && e.kind === "const" && constsWithJsx.has(e.name)) ||
      (!isTsx && ["function", "class"].includes(e.kind) && /^(components|features|context|shared\/ui)\//.test(c.rel));
    if (!isComponentCandidate) continue;
    const jsxUseFiles = [...tokenFiles.get(e.name) || []].filter((r) => {
      const o = info.get(absByRel.get(r));
      return o && o.jsxTags.has(e.name);
    });
    const entry = consumersOf(f, e);
    const directProd = entry ? [...entry.direct].filter((r) => {
      const tc = info.get(absByRel.get(r)).cls;
      return isConsumerCls(tc) && !tc.isTest && !tc.isScript;
    }) : [];
    const directTest = entry ? [...entry.direct].filter((r) => info.get(absByRel.get(r)).cls.isTest) : [];
    const isDefaultBinding = f.defaultName === e.name;
    const aliveViaDefault = isDefaultBinding && directProd.length > 0;
    const mounted = jsxUseFiles.length > 0 || aliveViaDefault;
    component_like.push({
      file: c.rel, line: e.line, name: e.name, kind: e.kind,
      imported_prod: directProd.length, imported_test: directTest.length,
      jsx_mount_files: jsxUseFiles,
      is_default_binding: isDefaultBinding,
      mounted,
      mount_reason: jsxUseFiles.length > 0 ? "jsx" : (aliveViaDefault ? "default-chain" : "none"),
      referenced_outside: (tokenFiles.get(e.name) || new Set()).size,
    });
  }
}

// D. unreferenced functions: exported function symbols never called outside own file
const unreferenced_functions = [];
for (const [abs, f] of info) {
  const c = f.cls;
  if (c.isTest || c.isScript || c.isGenerated || c.isVendor || c.isAmbient || c.isConfig) continue;
  for (const e of f.exports) {
    if (e.kind !== "function") continue;
    // Next.js entry components are rendered by the framework, not called
    if (f.defaultName === e.name || c.isNextEntry) continue;
    const users = [...(tokenFiles.get(e.name) || new Set())].filter((r) => r !== c.rel);
    if (users.length === 0) {
      unreferenced_functions.push({
        file: c.rel, line: e.line, name: e.name,
        imported_anywhere: (consumed.get(c.rel)?.get(e.name)?.direct.size || 0),
      });
    }
  }
}

// ---------- E. locale keys ----------
const localesDir = path.join(WEB, "locales");
const langs = fs.existsSync(localesDir) ? fs.readdirSync(localesDir, { withFileTypes: true })
  .filter((e) => e.isDirectory()).map((e) => e.name).sort() : [];
const localeFiles = []; // {lang, ns, file, keys:[], imported_by:[]}
for (const lang of langs) {
  for (const e of fs.readdirSync(path.join(localesDir, lang))) {
    if (!e.endsWith(".json")) continue;
    const ns = e.replace(/\.json$/, "");
    const absF = path.join(localesDir, lang, e);
    const data = JSON.parse(fs.readFileSync(absF, "utf8"));
    // flatten (json may nest even though keySeparator=false; record both raw and flattened)
    const keys = [];
    (function flat(o, p) {
      for (const [k, v] of Object.entries(o)) {
        const kp = p ? p + "." + k : k;
        if (v && typeof v === "object") flat(v, kp);
        else keys.push(kp);
      }
    })(data, "");
    // who imports this file?
    const imported_by = [];
    for (const [abs, f] of info) {
      for (const imp of f.imports) {
        if (imp.spec.includes(`/locales/${lang}/${ns}`)) imported_by.push(f.cls.rel);
      }
      for (const d of f.dynamicImports) {
        if ((d.spec && d.spec.includes(`/locales/${lang}/${ns}`)) ||
            (d.target && absByRel.get(d.target) === absF)) imported_by.push(f.cls.rel);
      }
    }
    localeFiles.push({ lang, ns, file: `locales/${lang}/${e}`, keys_count: keys.length, keys, imported_by });
  }
}
// string usage across all source (excluding tests? include but mark) — collect all string literals
const srcStringSets = { prod: new Set(), all: new Set() };
for (const [abs, f] of info) {
  for (const s of f.strings) {
    srcStringSets.all.add(s);
    if (!f.cls.isTest) srcStringSets.prod.add(s);
  }
}
const dynamicPrefixes = [...info.values()].flatMap((f) => f.dynamicKeyPrefixes);
function keyCoveredByPrefix(key) {
  return dynamicPrefixes.some((p) => p && key.startsWith(p));
}
const enFiles = localeFiles.filter((l) => l.lang === "en");
const orphans = [];
for (const lf of localeFiles) {
  const enSame = localeFiles.find((l) => l.lang === "en" && l.ns === lf.ns);
  const enKeys = new Set(enSame ? enSame.keys : []);
  const missing_in_en = lf.keys.filter((k) => !enKeys.has(k));
  const o = [];
  for (const k of lf.keys) {
    if (srcStringSets.prod.has(k) || srcStringSets.all.has(k)) continue;
    if (keyCoveredByPrefix(k)) continue;
    o.push(k);
  }
  orphans.push({
    lang: lf.lang, ns: lf.ns, file: lf.file, total: lf.keys.length,
    orphan_count: o.length,
    missing_in_en_count: missing_in_en.length,
    orphans: o,
    runtime_registered: lf.imported_by.some((r) => !r.startsWith("tests/")),
    imported_by: lf.imported_by,
  });
}

// ---------- write outputs ----------
function writeJson(name, data) {
  fs.writeFileSync(path.join(OUT, name), JSON.stringify(data, null, 1) + "\n");
}
writeJson("files.json", {
  web: relWeb(WEB) === "" ? "web" : path.basename(WEB),
  total_files: files.length,
  prod_files: prodFiles.length,
  test_files: testFiles.length,
  script_files: scriptFiles.length,
});
writeJson("unused_files.json", unused_files);
writeJson("unused_exports.json", unused_exports);
writeJson("components.json", component_like);
writeJson("unreferenced_functions.json", unreferenced_functions);
writeJson("locale_orphans.json", {
  dynamic_t_prefixes: dynamicPrefixes,
  string_literal_count: srcStringSets.all.size,
  files: orphans.map(({ keys, ...rest }) => rest),
});
writeJson("summary.json", {
  unused_files: unused_files.length,
  unused_files_loc: unused_files.reduce((a, b) => a + b.loc, 0),
  unused_exports: unused_exports.length,
  unused_exports_prod_zero_ref: unused_exports.filter((e) => e.cats.length === 0 && e.name_elsewhere_n === 0).length,
  components_total: component_like.length,
  components_unmounted: component_like.filter((c) => !c.mounted && c.imported_prod === 0).length,
  components_imported_never_mounted: component_like.filter((c) => !c.mounted && c.imported_prod > 0).length,
  unreferenced_functions: unreferenced_functions.length,
  locale_files: orphans.length,
  locale_orphan_keys_total: orphans.reduce((a, b) => a + b.orphan_count, 0),
  locale_unregistered_files: orphans.filter((o) => !o.runtime_registered).map((o) => `${o.file} (${o.total} keys)`),
});
console.log("scan complete ->", OUT);
