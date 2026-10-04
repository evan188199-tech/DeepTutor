#!/usr/bin/env python3
"""Read-only i18n audit for the DeepTutor web frontend (origin/main @ ef2d9e5c3).

Checks, per AGEN-460:
1. en/zh locale key-set differences (app + common).
2. t()/i18n.t() call sites referencing keys missing from the en key set.
3. User-visible hardcoded strings (CJK literals outside locale files, English JSX text).

keySeparator is false in web/i18n/init.ts, so keys are exact flat strings.
Usage: python3 scan_i18n.py <repo-web-root> > scan_raw.txt
"""
import json
import os
import re
import sys
from collections import defaultdict

WEB = sys.argv[1] if len(sys.argv) > 1 else "."
CODE_DIRS = ["app", "components", "context", "features", "hooks", "i18n", "lib", "shared", "contracts", "proxy.ts"]
CODE_EXTS = (".ts", ".tsx")
CODE_SKIP_PARTS = ("/tests/", "__tests__", ".test.", ".spec.", "scripts/", "eslint/", "vendor/")

# ---------- load locales ----------
def load(loc, ns):
    p = os.path.join(WEB, "locales", loc, f"{ns}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

en_app = load("en", "app") or {}
zh_app = load("zh", "app") or {}
en_common = load("en", "common") or {}
zh_common = load("zh", "common") or {}
en_keys = set(en_app)
PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")

print("== SECTION 1: en/zh key-set diff ==")
for ns, en, zh in (("app", en_app, zh_app), ("common", en_common, zh_common)):
    if en is None or zh is None:
        print(f"[{ns}] MISSING FILE: en={en is None} zh={zh is None}")
        continue
    ke, kz = set(en), set(zh)
    print(f"[{ns}] en={len(ke)} zh={len(kz)} en_only={len(ke-kz)} zh_only={len(kz-ke)}")
    for k in sorted(ke - kz):
        print(f"  EN_ONLY {k}")
    for k in sorted(kz - ke):
        print(f"  ZH_ONLY {k}")
print(f"[common] keys duplicated in app.json: {len(set(en_common) & en_keys)}/{len(en_common)} "
      f"(common ns never registered in i18n/init.ts)")

ph = re.compile(r"\{\{[^{}]+\}\}")
print("-- en/zh value-level anomalies --")
for k in sorted(en_app):
    if k in zh_app:
        if not str(zh_app[k]).strip():
            print(f"  EMPTY_ZH {k}")
        if sorted(ph.findall(str(en_app[k]))) != sorted(ph.findall(str(zh_app[k]))):
            print(f"  PLACEHOLDER_MISMATCH {k}")
        if en_app[k] == zh_app[k] and len(str(k)) > 24 and re.search(r"[a-zA-Z]{4}\s+[a-zA-Z]{3}", str(k)):
            print(f"  UNTRANSLATED_ECHO {k}")

# ---------- t() call-site scan ----------
STR_RE = re.compile(r"""\bt\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`]*)`)""")

def iter_code_files():
    for d in CODE_DIRS:
        p = os.path.join(WEB, d)
        if os.path.isfile(p):
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [x for x in dirs if x not in ("node_modules", ".next")]
            for fn in files:
                if fn.endswith(CODE_EXTS):
                    fp = os.path.join(root, fn)
                    norm = fp.replace(WEB, "").replace(os.sep, "/")
                    if any(s in norm for s in CODE_SKIP_PARTS):
                        continue
                    yield fp

def resolve(key, opts):
    if key in en_keys:
        return key
    for suf in PLURAL_SUFFIXES:
        if key + suf in en_keys:
            return key + suf
    if "count" in opts:
        for suf in PLURAL_SUFFIXES:
            if key + suf in en_keys:
                return key + suf
    return None

print("\n== SECTION 2: t() keys referenced but missing from en ==")
missing = []
dynamic_families = defaultdict(int)
checked = 0
for fp in iter_code_files():
    rel = os.path.relpath(fp, WEB)
    with open(fp, encoding="utf-8", errors="replace") as f:
        src = f.read()
    for m in STR_RE.finditer(src):
        key = next(g for g in m.groups() if g is not None)
        line = src.count("\n", 0, m.start()) + 1
        tail = src[m.end():m.end() + 220]
        if "${" in key:
            prefix = key.split("${")[0]
            dynamic_families[prefix] += 1
            fam = [k for k in en_keys if k.startswith(prefix)]
            if not fam:
                missing.append((rel, line, key, "DYNAMIC_PREFIX_NO_KEYS"))
            elif all(k == prefix + v[len(prefix):] for k, v in list(en_app.items())[:0]):  # noqa
                pass
            continue
        opts = {}
        cm = re.search(r"\bcount\s*[:=]", tail.split(")")[0])
        if cm:
            opts["count"] = 1
        checked += 1
        if resolve(key, opts) is None:
            missing.append((rel, line, key, "MISSING"))

for rel, line, key, kind in missing:
    print(f"  {kind} {rel}:{line} :: {key!r}")
print(f"-- static t() calls checked: {checked}; unresolved: {len(missing)}; dynamic families: {len(dynamic_families)}")
for pfx, n in sorted(dynamic_families.items(), key=lambda x: -x[1]):
    fam = [k for k in en_keys if k.startswith(pfx)]
    print(f"  DYN_FAMILY {n:3d} sites :: prefix={pfx!r} en_keys_matching={len(fam)}")

# ---------- hardcoded strings ----------
CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

def strip_comments(src):
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            end = n if j == -1 else j + 2
            out.append("\n" * src.count("\n", i, end))
            i = end
        else:
            out.append(c)
            i += 1
    return "".join(out)

print("\n== SECTION 3a: hardcoded CJK strings in code ==")
LANG_NAME_RE = re.compile(r"简体中文|繁體中文|日本語|English|Français|Deutsch|Ukrainian|>中文<|value=\"zh\"")
BILINGUAL_RE = re.compile(r"\bzh\s*:\s*['\"`]")
CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
cjk_hits = []
for fp in iter_code_files():
    rel = os.path.relpath(fp, WEB)
    with open(fp, encoding="utf-8", errors="replace") as f:
        src = f.read()
    clean = strip_comments(src)
    for i, line in enumerate(clean.split("\n"), 1):
        if CJK.search(line):
            if LANG_NAME_RE.search(line):
                cat = "A_LANG_NAME"
            elif BILINGUAL_RE.search(line):
                cat = "B_BILINGUAL_DATA"
            else:
                cat = "C_HARDCODED"
            cjk_hits.append((cat, rel, i, line.strip()[:200]))
for cat, rel, line, txt in cjk_hits:
    print(f"  {cat} {rel}:{line} :: {txt}")
counts = defaultdict(int)
for cat, _, _, _ in cjk_hits:
    counts[cat] += 1
print("-- CJK lines by category: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

print("\n== SECTION 3b: hardcoded English JSX text (heuristic) ==")
JSX_TEXT = re.compile(r">([^<>{}\n]*)<")
CODE_TOKENS = ("=>", "?.", "&&", "||", ";", "=", "(", ")", "[", "]", "`", "<")
eng_hits = []
for fp in iter_code_files():
    rel = os.path.relpath(fp, WEB)
    with open(fp, encoding="utf-8", errors="replace") as f:
        src = strip_comments(f.read())
    for m in JSX_TEXT.finditer(src):
        txt = m.group(1).strip()
        if len(txt) < 6 or len(re.findall(r"[A-Za-z]{2,}", txt)) < 2:
            continue
        if any(tok in txt for tok in CODE_TOKENS):
            continue
        if not re.match(r"^[A-Z(]", txt):
            continue
        line = src.count("\n", 0, m.start()) + 1
        eng_hits.append((rel, line, txt[:120]))
by_file = defaultdict(int)
for rel, _, _ in eng_hits:
    by_file[rel] += 1
print("-- files by count (top 30) --")
for rel, n in sorted(by_file.items(), key=lambda x: -x[1])[:30]:
    print(f"  {n:4d} {rel}")
print("-- total segments: %d" % len(eng_hits))
print("-- sample (first 60) --")
for rel, line, txt in eng_hits[:60]:
    print(f"  ENG {rel}:{line} :: {txt}")
