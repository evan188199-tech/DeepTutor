#!/usr/bin/env python3
"""Read-only static accessibility basics scanner for web/.

Categories (static only; no runtime contrast/focus-order):
  A1 img-missing-alt        <img> / next/image <Image> without alt attribute
  A2 control-no-name        input/select/textarea without label/aria-label/aria-labelledby/title
  A3 button-no-text         <button> with no text content and no accessible name
  A4 heading-skip           heading level increase > +1 in per-file source order
  B1 aria-hidden-focusable  aria-hidden on button/a[href]/form control/tabindex element
  B2 invalid-role           role= value not a known ARIA role name (static strings only)
  B3 broken-aria-ref        aria-labelledby/aria-describedby id(s) absent from same file
  B4 positive-tabindex      tabindex > 0
  B5 duplicate-id           same static id= value appearing 2+ times in one file

Usage: python3 scan_a11y.py [WEB_ROOT] [--json OUT]
"""
import json
import os
import re
import sys

SKIP_DIRS = {"generated", "dist", "node_modules", ".next", ".turbo"}
EXTS = (".tsx", ".jsx", ".ts", ".js", ".mjs", ".mts")
IMG_EXTS = (".tsx", ".jsx")
ARIA_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "blockquote", "button",
    "caption", "cell", "checkbox", "code", "columnheader", "combobox", "command",
    "complementary", "composite", "contentinfo", "definition", "deletion", "dialog",
    "directory", "document", "emphasis", "feed", "figure", "form", "generic", "grid",
    "gridcell", "group", "heading", "img", "image", "input", "insertion", "link", "list",
    "listbox", "listitem", "log", "main", "mark", "marquee", "math", "menu", "menubar",
    "menuitem", "menuitemcheckbox", "menuitemradio", "meter", "navigation", "none",
    "note", "option", "paragraph", "presentation", "progressbar", "radio", "radiogroup",
    "range", "region", "row", "rowgroup", "rowheader", "scrollbar", "search", "searchbox",
    "section", "sectionhead", "select", "separator", "slider", "spinbutton", "status",
    "strong", "structure", "subscript", "superscript", "switch", "tab", "table", "tablist",
    "tabpanel", "term", "textbox", "time", "timer", "toolbar", "tooltip", "tree",
    "treegrid", "treeitem", "widget", "window",
}
CONTROL_TAGS = {"input", "select", "textarea"}
INTERACTIVE_TAGS = {"button", "a", "input", "select", "textarea"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def mask_source(src):
    """Blank comments, string/template-literal contents and regex literals
    (keep newlines), keep code structure. Frame-stack based so ${}
    interpolations return to template mode correctly."""
    out = list(src)
    n = len(src)
    REGEX_PREV = set("(,=:[!&|?{;\n")
    REGEX_WORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                   "void", "do", "else", "case", "yield", "await"}
    # frames: list of dicts kind: 'file' | 'tmpl' | 'interp', depth for interp
    frames = [{"kind": "file", "depth": 0}]
    mode = "code"  # code|line|block|s|d|t|regex
    word = []
    prev_sig = "\n"

    def cur():
        return frames[-1]

    i = 0
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if mode == "code":
            if c.isalpha() or c == "_" or c == "$":
                word.append(c)
                prev_sig = "w"
                i += 1
                continue
            if word:
                if "".join(word) in REGEX_WORDS:
                    prev_sig = "\n"  # keyword: a following / starts a regex
                word = []
            if c == "/" and nxt == "/":
                mode = "line"; i += 2; continue
            if c == "/" and nxt == "*":
                mode = "block"; i += 2; continue
            if c == "'":
                mode = "s"; out[i] = " "; i += 1; continue
            if c == '"':
                mode = "d"; out[i] = " "; i += 1; continue
            if c == "`":
                if cur()["kind"] == "interp":
                    frames.pop(); mode = "t"  # inner template closes
                else:
                    frames.append({"kind": "tmpl", "depth": 0}); mode = "t"
                out[i] = " "; i += 1; continue
            if c == "/" and prev_sig in REGEX_PREV:
                mode = "regex"; out[i] = " "; i += 1; continue
            if c == "$" and nxt == "{" and mode == "code" and cur()["kind"] == "tmpl":
                frames.append({"kind": "interp", "depth": 0}); mode = "code"
                out[i] = out[i + 1] = " "; i += 2; continue
            if c == "{":
                cur()["depth"] += 1; prev_sig = "{"; i += 1; continue
            if c == "}":
                f = cur()
                if f["kind"] == "interp" and f["depth"] == 0:
                    frames.pop(); mode = "t"  # ${...} closes, back to template
                else:
                    f["depth"] = max(0, f["depth"] - 1); prev_sig = "}"
                i += 1; continue
            if not c.isspace():
                prev_sig = c
            i += 1; continue
        if mode == "line":
            if c == "\n":
                mode = "code"
            else:
                out[i] = " "
            i += 1; continue
        if mode == "block":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "; mode = "code"; i += 2; continue
            if c != "\n":
                out[i] = " "
            i += 1; continue
        if mode == "regex":
            if c == "\\":
                out[i] = " "
                if i + 1 < n and src[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2; continue
            if c == "[":
                mode = "regexcls"; out[i] = " "; i += 1; continue
            if c == "/":
                mode = "code"; out[i] = " "; i += 1; prev_sig = "w"; continue
            if c != "\n":
                out[i] = " "
            i += 1; continue
        if mode == "regexcls":
            if c == "\\":
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2; continue
            if c == "]":
                mode = "regex"; out[i] = " "; i += 1; continue
            if c != "\n":
                out[i] = " "
            i += 1; continue
        if mode in ("s", "d"):
            quote = "'" if mode == "s" else '"'
            if c == "\\":
                out[i] = " "
                if i + 1 < n and src[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2; continue
            if c == "\n":
                mode = "code"; i += 1; continue
            if c == quote:
                mode = "code"; out[i] = " "; prev_sig = "w"; i += 1; continue
            out[i] = " "; i += 1; continue
        # template literal
        if c == "\\":
            out[i] = " "
            if i + 1 < n and src[i + 1] != "\n":
                out[i + 1] = " "
            i += 2; continue
        if c == "`":
            mode = "code"; frames.pop(); out[i] = " "; prev_sig = "w"; i += 1; continue
        if c == "$" and nxt == "{":
            frames.append({"kind": "interp", "depth": 0}); mode = "code"
            out[i] = out[i + 1] = " "; i += 2; continue
        if c != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


TAG_START = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9._-]*)")


def find_tag_end(masked, start):
    """Return index just past the closing '>' of the tag starting at `start`, or -1."""
    i, n = start, len(masked)
    quote = None
    depth = 0
    while i < n:
        c = masked[i]
        if quote:
            if c == "\\":
                i += 2; continue
            if c == quote:
                quote = None
            i += 1; continue
        if c in "\"'":
            quote = c; i += 1; continue
        if c == "{":
            depth += 1; i += 1; continue
        if c == "}":
            depth = max(0, depth - 1); i += 1; continue
        if depth == 0 and c == ">":
            return i + 1
        i += 1
    return -1


def line_of(src, pos):
    return src.count("\n", 0, pos) + 1


ATTR_RE = re.compile(r"([:@A-Za-z_][\w:.-]*)\s*=\s*({[^{}]*}|\"[^\"]*\"|'[^']*'|[^\s>/]+)")


def parse_attrs(tag_text):
    """Return dict attr_name -> raw value text (may be None for bare attrs)."""
    inner = tag_text[1:]
    inner = re.sub(r"/?>\s*$", "", inner)
    # drop tag name
    m = re.match(r"^[A-Za-z][\w.-]*", inner)
    if m:
        inner = inner[m.end():]
    attrs = {}
    pos = 0
    while pos < len(inner):
        mm = ATTR_RE.search(inner, pos)
        if not mm:
            break
        name, val = mm.group(1), mm.group(2)
        attrs.setdefault(name.lower(), val)
        pos = mm.end()
    return attrs


def static_string(val):
    if val is None:
        return None
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]
    return None


def static_number(val):
    s = static_string(val)
    if s is None and val is not None:
        raw = val.strip()
        if raw.startswith("{") and raw.endswith("}"):
            s = raw[1:-1].strip()
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def truthy_aria_hidden(attrs):
    v = attrs.get("aria-hidden")
    if v is None:
        return False
    s = (v or "true").strip()
    if s in ("true", '{"true"}', "{true}"):
        return True
    inner = static_string(s)
    return inner == "true"


def has_attr(attrs, names):
    return any(a in attrs for a in names)


def strip_tag_spans(masked, orig, begin, end):
    """Recursively remove JSX element tag tokens from inner content.

    Returns (masked_rest, orig_rest) where only text/expressions remain.
    """
    changed = True
    m_rest, o_rest = masked[begin:end], orig[begin:end]
    while changed:
        changed = False
        spans = []
        for m in TAG_START.finditer(m_rest):
            e = find_tag_end(m_rest, m.start())
            if e >= 0:
                spans.append((m.start(), e))
        if spans:
            for a, b in reversed(spans):
                m_rest = m_rest[:a] + m_rest[b:]
                o_rest = o_rest[:a] + o_rest[b:]
            changed = True
    return m_rest, o_rest


def classify_button_inner(masked, src, begin, end):
    """Classify the inner content of a <button>: 'text' | 'ambiguous' | 'none'.

    text      — static text, i18n call or data-bound expression visible at runtime
    ambiguous — content depends on caller variables (children/label-style)
    none      — empty / only nested elements / conditional icon components
    """
    m_rest, o_rest = strip_tag_spans(masked, src, begin, end)
    if not o_rest.strip():
        return "none"
    has_text = bool(re.search(r"t\(|[\"'`]", o_rest))
    if has_text:
        return "text"
    # walk top-level expressions
    ambiguous = False
    i, n = 0, len(m_rest)
    while i < n:
        if m_rest[i] == "{":
            depth = 1
            j = i + 1
            while j < n and depth:
                if m_rest[j] == "{":
                    depth += 1
                elif m_rest[j] == "}":
                    depth -= 1
                j += 1
            expr_masked = m_rest[i + 1:j - 1]
            expr_orig = o_rest[i + 1:j - 1]
            # remove any JSX elements inside the expression (conditional renders)
            em2, eo2 = strip_tag_spans(expr_masked, expr_orig, 0, len(expr_masked))
            tokens = re.findall(r"[A-Za-z_$][\w$.]*", eo2)
            if tokens:
                meaningful = [
                    tk for tk in tokens
                    if tk not in ("true", "false", "null", "undefined")
                ]
                if meaningful:
                    if len(meaningful) == 1 and re.fullmatch(
                            r"[a-z][A-Za-z]*", meaningful[0]):
                        ambiguous = True  # lone prop-style variable (children/label)
                    else:
                        return "text"  # data binding renders visible text
            i = j
        else:
            i += 1
    return "ambiguous" if ambiguous else "none"


def scan_file(path, rel, src, jsx_only=True):
    masked = mask_source(src)
    tags = []
    for m in TAG_START.finditer(masked):
        end = find_tag_end(masked, m.start())
        if end < 0:
            continue
        closing, name = m.group(1) == "/", m.group(2)
        text = src[m.start():end]
        base = name.split(".")[0]
        tags.append({
            "start": m.start(), "end": end, "closing": closing,
            "name": base, "line": line_of(src, m.start()),
            "attrs": parse_attrs(text) if not closing else {},
            "text": text,
        })
    findings = []

    def add(cat, line, detail, tier="confirmed"):
        findings.append({
            "file": rel, "line": line, "category": cat,
            "detail": detail, "tier": tier,
        })

    uses_next_image = bool(re.search(r"from\s+['\"]next/image['\"]", src))

    # ---- A1 img / Image missing alt
    for t in tags:
        if t["closing"]:
            continue
        is_img = t["name"] == "img"
        is_nimg = uses_next_image and t["name"] == "Image"
        if not (is_img or is_nimg):
            continue
        if not has_attr(t["attrs"], ("alt",)):
            add("A1-img-missing-alt", t["line"],
                f"<{t['name']}> 无 alt 属性" + ("（next/image）" if is_nimg else ""))

    # ---- label association map for A2
    label_spans = []
    htmlfor_ids = set()
    for t in tags:
        if t["name"] != "label" or t["closing"]:
            continue
        close = None
        for u in tags:
            if u["name"] == "label" and u["closing"] and u["start"] > t["start"]:
                close = u
                break
        label_spans.append((t["start"], close["start"] if close else t["end"]))
    for t in tags:
        if not t["closing"] and "htmlfor" in t["attrs"]:
            v = static_string(t["attrs"]["htmlfor"])
            if v:
                htmlfor_ids.add(v)

    # ---- static ids
    id_positions = {}
    for t in tags:
        if t["closing"]:
            continue
        v = static_string(t["attrs"].get("id"))
        if v:
            id_positions.setdefault(v, []).append(t["line"])

    # ---- A2 control accessible name
    for t in tags:
        if t["closing"] or t["name"] not in CONTROL_TAGS:
            continue
        if t["name"] == "input" and (t["attrs"].get("type") or "").strip().strip("\"'") == "hidden":
            continue
        if (t["name"] == "input"
                and (t["attrs"].get("type") or "").strip().strip("\"'") == "file"):
            cls = static_string(t["attrs"].get("classname")) or ""
            if (truthy_aria_hidden(t["attrs"]) and
                    (static_number(t["attrs"].get("tabindex")) or 0) <= -1) \
                    or "hidden" in cls.split():
                continue  # neutralized programmatic file input idiom
        named = has_attr(t["attrs"], ("aria-label", "aria-labelledby", "title"))
        if not named:
            v = static_string(t["attrs"].get("id"))
            if v and v in htmlfor_ids:
                named = True
        if not named:
            inside = any(a <= t["start"] <= b for a, b in label_spans)
            named = inside
        if not named:
            ident = static_string(t["attrs"].get("id")) or static_string(t["attrs"].get("name")) or "?"
            ph = static_string(t["attrs"].get("placeholder"))
            suffix = f"，仅 placeholder" if ph else "，无 placeholder"
            add("A2-control-no-name", t["line"],
                f"<{t['name']}> 无 label 关联/aria-label/aria-labelledby/title（id/name≈{ident}）{suffix}")

    # ---- A3 button without text
    for t in tags:
        if t["closing"] or t["name"] != "button":
            continue
        if has_attr(t["attrs"], ("aria-label", "aria-labelledby", "title")):
            continue
        close = None
        for u in tags:
            if u["name"] == "button" and u["closing"] and u["start"] > t["start"]:
                close = u
                break
        inner_end = close["start"] if close else t["end"]
        verdict = classify_button_inner(masked, src, t["end"], inner_end)
        if verdict == "text":
            continue
        if verdict == "ambiguous":
            add("A3-button-no-text", t["line"],
                "<button> 无 aria-label/title，内容由调用方变量决定（children/label 等），可访问名取决于用法",
                tier="review")
        else:
            add("A3-button-no-text", t["line"],
                "<button> 无文本内容且无 aria-label/title（空/仅图标或条件图标）",
                tier="confirmed")

    # ---- A4 heading skips
    seq = [(t["name"], t["line"]) for t in tags
           if not t["closing"] and t["name"] in HEADINGS]
    prev = None
    for name, line in seq:
        lvl = int(name[1])
        if prev is not None:
            plvl, pline = prev
            if lvl - plvl > 1:
                add("A4-heading-skip", line,
                    f"h{plvl}(line {pline}) → {name} 跳级（+{lvl - plvl}）")
        prev = (lvl, line)

    # ---- B1 aria-hidden on focusable
    for t in tags:
        if t["closing"] or not truthy_aria_hidden(t["attrs"]):
            continue
        focusable = (
            t["name"] in INTERACTIVE_TAGS
            and not (t["name"] == "a" and "href" not in t["attrs"])
            and not (t["name"] == "input" and (t["attrs"].get("type") or "").strip().strip("\"'") == "hidden")
        ) or "tabindex" in t["attrs"]
        if focusable:
            add("B1-aria-hidden-focusable", t["line"],
                f"<{t['name']}> 带 aria-hidden=true 但可聚焦/可交互")

    # ---- B2 invalid role
    for t in tags:
        if t["closing"]:
            continue
        v = static_string(t["attrs"].get("role"))
        if v is None:
            continue
        for r in v.split():
            if r.lower() not in ARIA_ROLES:
                add("B2-invalid-role", t["line"],
                    f"role=\"{r}\" 不是合法 ARIA role")
                break

    # ---- B3 broken aria references
    known_ids = set(id_positions)
    for t in tags:
        if t["closing"]:
            continue
        for attr in ("aria-labelledby", "aria-describedby"):
            v = static_string(t["attrs"].get(attr))
            if v is None:
                continue
            missing = [i for i in v.split() if i not in known_ids]
            if missing:
                add("B3-broken-aria-ref", t["line"],
                    f"{attr}=\"{v}\" 引用的 id 在同文件未找到: {','.join(missing)}",
                    tier="review")

    # ---- B4 positive tabindex
    for t in tags:
        if t["closing"]:
            continue
        v = static_number(t["attrs"].get("tabindex"))
        if v is not None and v > 0:
            add("B4-positive-tabindex", t["line"], f"tabindex={v} > 0")

    # ---- B5 duplicate id in same file
    for val, lines in id_positions.items():
        if len(lines) > 1:
            add("B5-duplicate-id", lines[0],
                f"id=\"{val}\" 在同文件出现 {len(lines)} 次（lines {lines}）",
                tier="review")
            for extra in lines[1:]:
                add("B5-duplicate-id", extra,
                    f"id=\"{val}\" 在同文件出现 {len(lines)} 次（lines {lines}）",
                    tier="review")

    return findings, len(tags)


def iter_files(web_root):
    for dirpath, dirnames, filenames in os.walk(web_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(EXTS):
                yield os.path.join(dirpath, fn)


def main():
    web_root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "web"
    out_path = None
    if "--json" in sys.argv:
        out_path = sys.argv[sys.argv.index("--json") + 1]
    all_findings = []
    file_tag_counts = {}
    files_scanned = 0
    for fp in iter_files(web_root):
        rel = os.path.relpath(fp, web_root)
        is_test = ("/tests/" in rel or rel.startswith("tests/") or ".test." in fn_ok(rel)
                   or ".spec." in rel or "__tests__" in rel or ".stories." in rel)
        try:
            src = open(fp, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        files_scanned += 1
        if not rel.endswith((".tsx", ".jsx")):
            continue
        findings, ntags = scan_file(fp, rel, src)
        file_tag_counts[rel] = ntags
        for f in findings:
            f["test_file"] = is_test
            if not is_test:
                all_findings.append(f)
    result = {"files_scanned": files_scanned, "findings": all_findings}
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    by_cat = {}
    for f in all_findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    print(f"files: {files_scanned}, findings(app code): {len(all_findings)}")
    for cat in sorted(by_cat):
        print(f"  {cat}: {by_cat[cat]}")


def fn_ok(rel):
    return rel


if __name__ == "__main__":
    main()
