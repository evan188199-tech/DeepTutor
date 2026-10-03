#!/usr/bin/env python3
"""Read-only classifier for `void` fire-and-forget statements and no-op catch
handlers in web/ (TS/TSX). stdlib only, deterministic, modifies nothing.

Usage: python3 scan_void_promises.py [web_root] [out_json]
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TS_EXT = {".ts", ".tsx"}
SKIP_DIRS = {"node_modules", ".next", "out", "dist", "coverage", ".turbo"}

BEST_EFFORT_VERBS = (
    "progress position draft telemetry analytics prefetch preload warm beacon ping "
    "log logevent track close cleanup dispose teardown reset poll refresh load reload "
    "fetch list hydrate copy play exit focus blur scroll syncstate prune dedupe"
).split()
RISK_VERBS = (
    "delete remove unlink destroy submit send save update write create import migrate "
    "retry resolve complete finish publish commit approve revoke disable enable archive "
    "restore reorder rename toggle invoke execute report flag queue enroll checkout "
    "confirm finalize export download upload attach detach signin signout login logout"
).split()
READ_VERBS = "load fetch list get refresh query poll scan overview detail history search".split()

# Promise-returning browser/platform APIs commonly used fire-and-forget on purpose.
BROWSER_BEST_EFFORT = {
    "document.exitFullscreen", "document.requestFullscreen",
    "navigator.clipboard.writeText", "navigator.clipboard.readText",
    "navigator.sendBeacon", "window.close",
    "Element.requestFullscreen", "HTMLMediaElement.play",
}
# Sync / void-returning APIs that cannot produce unhandled rejections.
SYNC_APIS = {
    "router.push", "router.replace", "router.back", "router.prefetch",
    "router.refresh", "window.scrollTo", "window.addEventListener",
    "console.log", "console.warn", "console.error", "console.info", "console.debug",
    "startTransition", "flushSync", "requestAnimationFrame", "setTimeout", "queueMicrotask",
}


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.suffix in TS_EXT and not any(part in SKIP_DIRS for part in p.parts):
            yield p


REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
REGEX_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await", "throw",
}


def mask(src: str, strings: bool = True) -> str:
    """Replace comments (and optionally string/template/regex-literal contents)
    with spaces (offset-stable)."""
    out = list(src)
    i, n = 0, len(src)
    quote = ""
    in_regex = False
    regex_class = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_regex:
            if c == "\\" and i + 1 < n:
                if strings:
                    out[i] = " "
                    if src[i + 1] != "\n":
                        out[i + 1] = " "
                i += 2
                continue
            if c == "[":
                regex_class = True
            elif c == "]":
                regex_class = False
            elif c == "/" and not regex_class:
                in_regex = False
                i += 1
                continue
            elif c == "\n":
                in_regex = False
                continue
            if strings:
                out[i] = " " if c != "\n" else "\n"
            i += 1
            continue
        if quote:
            if c == "\\" and i + 1 < n:
                if strings:
                    out[i] = " "
                    if src[i + 1] != "\n":
                        out[i + 1] = " "
                i += 2
                continue
            if c == quote:
                quote = ""
            elif c == "\n" and quote in "'\"":
                quote = ""
            elif strings:
                out[i] = " " if c != "\n" else "\n"
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if c == "/" and nxt == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out[i] = " " if src[i] != "\n" else "\n"
                i += 1
            if i < n:
                out[i] = out[i + 1] = " "
                i += 2
            continue
        if strings and c in "'\"`":
            quote = c
            i += 1
            continue
        if strings and c == "/":
            j = i - 1
            while j >= 0 and src[j] in " \t\n":
                j -= 1
            prev = src[j] if j >= 0 else ""
            is_regex = prev == "" or prev in REGEX_PREV
            if prev and (prev.isalnum() or prev in "_$"):
                w = re.search(r"([A-Za-z_$][\w$]*)$", src[: j + 1])
                is_regex = bool(w and w.group(1) in REGEX_KEYWORDS)
            if is_regex:
                in_regex = True
                regex_class = False
                out[i] = " "
                i += 1
                continue
        i += 1
    return "".join(out)


def stmt_void_ok(masked: str, pos: int) -> bool:
    """True if `void` at `pos` is an expression statement / arrow body, not a type."""
    i = pos - 1
    while i >= 0 and masked[i] in " \t\n":
        i -= 1
    prev = masked[i] if i >= 0 else ""
    if prev in ":=<,|&+-%/":
        return False
    if prev and (prev.isalnum() or prev in "_$"):
        word = re.search(r"([A-Za-z_$][\w$]*)$", masked[: i + 1])
        # only gate when the preceding word sits on the same line as `void`
        # (a word on an earlier line still makes this a statement start)
        if word and "\n" not in masked[word.end(): pos] and word.group(1) not in {
            "else", "return", "do", "default", "yield", "then",
        }:
            return False
    j = pos + 4
    # next-char gate: skip only blanks on the SAME line — a type like
    # `() => void` ends at the newline, an expression operand never does
    while j < len(masked) and masked[j] in " \t":
        j += 1
    if j >= len(masked) or not (masked[j].isalnum() or masked[j] in "_$(["):
        return False
    if masked[j] == "(" and masked[j + 1: j + 2].isdigit():
        return False
    return True


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def match_brace(text: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def stmt_end(masked: str, start: int) -> int:
    """End offset of the expression statement beginning at `start` (masked text)."""
    depth = 0
    i = start
    n = len(masked)
    while i < n:
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if c == "}" and depth == 0:
                return i
            if depth == 0:
                i += 1
                continue
            depth -= 1
        elif c == ";" and depth <= 0:
            return i
        elif c == "\n" and depth == 0:
            j = i + 1
            while j < n and masked[j] in " \t":
                j += 1
            if j >= n or masked[j] not in ".&|?]:,+-*/":
                return i
        i += 1
    return n


VOID_RE = re.compile(r"(?<![\w$.])void\s*(?!0\b)(?!\(\s*0\s*\))")
CALLEE_RE = re.compile(
    r"^\s*\(?\s*(?:await\s+)?([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*[(.]"
)
IIFE_RE = re.compile(r"^\s*\(?\s*(async\s*)?(\(|function\b)")
CATCH_NOOP_RE = re.compile(
    r"\.catch\(\s*(?:\(\s*\)|[\w$]+)?\s*=>\s*(?:\{\s*(?:return;?)?\s*\}|undefined|null|void 0)\s*\)"
)
THEN_RE = re.compile(r"\.then\s*\(")
EMPTY_CATCH_RE = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}")

DEF_PATTERNS = [
    re.compile(r"\b(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*useCallback\("),
]
DESTRUCTURE_RE = re.compile(
    r"\{[^{}]{0,800}?\b([A-Za-z_$][\w$]*)\b[^{}]{0,800}?\}\s*=\s*(?:await\s+)?[\w$.]+\("
)
HOOK_OBJECT_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*use[A-Z]\w*\("
)
OBJ_METHOD_RE = re.compile(r"^\s+(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.M)
EXPORTED_OBJ_RE = re.compile(r"\bexport\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*\{")


def handler_quality(expr_masked: str) -> str:
    """none | empty | real  — rejection handling attached to the expression itself."""
    m = CATCH_NOOP_RE.search(expr_masked)
    if m:
        return "empty"
    if re.search(r"\.catch\s*\(", expr_masked):
        # any .catch whose body is not a noop literal
        if re.search(r"\.catch\s*\(\s*[\w$]+\s*\)", expr_masked) or re.search(
            r"\.catch\s*\([^)]*=>\s*(?!\{\s*\})(?!\s*(?:undefined|null|void 0)\s*\))", expr_masked
        ):
            return "real"
        return "empty"
    for tm in THEN_RE.finditer(expr_masked):
        # crude top-level comma check for .then(a, b)
        depth = 0
        for i in range(tm.end(), min(tm.end() + 4000, len(expr_masked))):
            c = expr_masked[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if c == ")" and depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 1:
                return "real"
    return "none"


def await_outside_try(body_masked: str):
    """True if body has await/then outside any try{...} region (rejection can escape)."""
    regions = []
    for m in re.finditer(r"\btry\s*\{", body_masked):
        open_pos = m.end() - 1
        regions.append((m.start(), match_brace(body_masked, open_pos)))
    for m in re.finditer(r"\bawait\b|\.then\s*\(", body_masked):
        if not any(s <= m.start() <= e for s, e in regions):
            return True
    return False


def brace_after_arrow(masked: str, arrow_pos: int):
    """Body brace of a block-bodied arrow: `{` after `=>` (only whitespace
    between). Concise arrows `(expr)` return -1 so the def is skipped."""
    i = arrow_pos + 2
    n = len(masked)
    while i < n and masked[i] in " \t\n":
        i += 1
    if i < n and masked[i] == "{":
        return i
    return -1


def find_def_arrow(masked: str, start: int, window: int):
    """Position of a definition's own `=>` (first at minimal paren depth)."""
    best = None
    best_depth = None
    depth = 0
    i = start
    n = min(len(masked), start + window)
    while i < n - 1:
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "=" and masked[i + 1] == ">" and masked[i - 1] not in "=<>!=":
            if best_depth is None or depth < best_depth:
                best, best_depth = i, depth
        i += 1
    return best if best is not None else -1


def def_body_start(masked: str, start: int) -> int:
    """Body brace of a non-arrow function definition: brace after the balanced
    parameter list."""
    p = masked.find("(", start, start + 400)
    if p == -1:
        return -1
    depth = 0
    for i in range(p, len(masked)):
        c = masked[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                nb = masked.find("{", i + 1)
                a2 = masked.find("=>", i + 1, i + 200)
                if a2 != -1 and (nb == -1 or a2 < nb):
                    return brace_after_arrow(masked, a2)
                return nb
    return -1


def build_def_index(files):
    """name -> list of {file, line, body_start, body_end, exported}"""
    index = {}
    destructured = set()
    hook_objects = set()
    for path, masked in files:
        rel = str(path)
        is_test = "/tests/" in rel or rel.endswith(".spec.ts") or rel.endswith(".test.tsx")
        for dm in DESTRUCTURE_RE.finditer(masked):
            destructured.add(dm.group(1))
        for hm in HOOK_OBJECT_RE.finditer(masked):
            hook_objects.add(hm.group(1))
        exported_objects = {m.start(): m.group(1) for m in EXPORTED_OBJ_RE.finditer(masked)}
        for pi, pat in enumerate(DEF_PATTERNS):
            for m in pat.finditer(masked):
                name = m.group(1)
                if pi == 0:
                    body_start = def_body_start(masked, m.end())
                    if body_start == -1:
                        continue
                    body_end = match_brace(masked, body_start)
                else:
                    apos = find_def_arrow(
                        masked, m.end() if pi == 2 else m.start(), 400)
                    if apos == -1:
                        body_start = def_body_start(masked, m.end())
                        if body_start == -1:
                            continue
                        body_end = match_brace(masked, body_start)
                    else:
                        body_start = brace_after_arrow(masked, apos)
                        if body_start == -1:
                            # concise arrow (`=> expr`): index the expression
                            # span so a delegation target like guard(...) stays
                            # visible to the transitive helper check
                            body_start = apos + 2
                            while (body_start < len(masked)
                                   and masked[body_start] in " \t\n"):
                                body_start += 1
                            body_end = stmt_end(masked, body_start)
                        else:
                            body_end = match_brace(masked, body_start)
                index.setdefault(name, []).append({
                    "file": rel, "line": line_of(masked, m.start()),
                    "hs": m.start(), "bs": body_start, "be": body_end,
                    "masked_file_id": id(masked), "test": is_test,
                })
        for m in OBJ_METHOD_RE.finditer(masked):
            name = m.group(1)
            body_start = masked.rfind("{", m.start(), m.end())
            body_end = match_brace(masked, body_start)
            owner = ""
            for opos, oname in exported_objects.items():
                if opos < m.start():
                    owner = oname
            index.setdefault(name, []).append({
                "file": rel, "line": line_of(masked, m.start()),
                "hs": m.start(), "bs": body_start, "be": body_end,
                "masked_file_id": id(masked), "test": is_test, "owner": owner,
            })
    return index, destructured, hook_objects


def classify(files_by_id, def_index, destructured, hook_objects, rel, masked, m, expr_end, kind, is_test):
    expr = masked[m.start():expr_end].strip()
    line = line_of(masked, m.start())
    q = handler_quality(expr)
    body_from = masked[m.end():expr_end].strip()
    callee_m = CALLEE_RE.match(body_from)
    callee = callee_m.group(1) if callee_m else ""
    iife = bool(IIFE_RE.match(body_from)) and not callee
    item = {
        "file": rel, "line": line, "kind": kind, "expr": expr[:240],
        "callee": callee, "rejection_handler": q, "is_test": is_test,
        "category": None, "risk": None, "confidence": "medium",
        "reason": "", "internal_handling": None,
    }
    if q == "real":
        item.update(category="handled_internally", risk="LOW", confidence="high",
                    reason="call site attaches a non-empty rejection handler")
        return item
    if ".then(" in expr:
        # .then(onFulfilled) with no catch: the callback's own rejection escapes
        item.update(category="swallow", risk="MEDIUM", confidence="medium",
                    reason=".then(...) chain has no rejection handler; failure inside the "
                           "then callback escapes as an unhandled rejection")
        return item
    if q == "empty":
        verb_hit = any(v in expr.lower() for v in RISK_VERBS)
        item.update(
            category="swallow" if verb_hit else "best_effort",
            risk="MEDIUM" if verb_hit else "LOW",
            confidence="medium",
            reason="attached .catch(() => {}) swallows rejection silently; "
                   + ("expression carries a mutation verb" if verb_hit
                      else "expression reads as best-effort (no mutation verb)"),
        )
        return item
    # no attached rejection handler -> resolve callee
    if callee:
        lower = callee.lower()
        if callee == "import":
            item.update(category="best_effort", risk="LOW", confidence="high",
                        reason="dynamic import(...) used as chunk prefetch; "
                               "failure only means the lazy chunk loads on demand later")
            return item
        if re.match(r"on[A-Z]", callee.split(".")[-1]):
            item.update(category="swallow", risk="MEDIUM", confidence="low",
                        reason="callback prop: failure handling is defined by the "
                               "consumer's implementation, not visible at this site")
            return item
        if callee.endswith(".start"):
            item.update(category="best_effort", risk="LOW", confidence="medium",
                        reason="animation control .start() fire-and-forget "
                               "(framer-motion convention); rejection only affects animation")
            return item
        if re.match(r"set[A-Z]", callee.split(".")[-1]) or lower in SYNC_APIS or callee in SYNC_APIS:
            item.update(category="best_effort", risk="LOW", confidence="high",
                        reason=f"{callee} is a local state setter or sync/void-returning API; "
                               "no rejection possible")
            return item
        if callee in BROWSER_BEST_EFFORT:
            item.update(category="best_effort", risk="LOW", confidence="medium",
                        reason=f"{callee} is a platform API used best-effort; "
                               "rejection ignored by design (e.g. clipboard/fullscreen/play)")
            return item
        if "." in callee and callee.split(".")[0] in hook_objects:
            item.update(category="swallow", risk="MEDIUM", confidence="low",
                        reason="member of a hook return value; internal error handling "
                               "not visible at this site")
            return item
        defs = def_index.get(callee.split(".")[-1], [])
        owner = callee.split(".")[0]
        same_file = [d for d in defs if d["file"] == rel]
        owner_defs = [d for d in defs if d.get("owner") == owner] if "." in callee else []
        # bare names resolve only within the same file; cross-file picks need an
        # explicit owner (dotted callee) to avoid unrelated-name false matches
        pick = owner_defs or same_file
        if pick:
            d = pick[0]
            body = files_by_id[d["masked_file_id"]][d["bs"]:d["be"] + 1]
            head = masked[d["hs"]:d["bs"]]
            async_callee = "async" in head
            has_awaits = bool(re.search(r"\bawait\b|\.then\s*\(", body))
            has_throw = bool(re.search(r"\bthrow\b", body))
            has_catch = bool(re.search(r"\bcatch\b|\.catch\s*\(", body))
            partial = has_catch and await_outside_try(body)
            item["callee_def"] = f"{d['file']}:{d['line']}"
            if not has_awaits and not has_throw:
                item.update(category="best_effort", risk="LOW", confidence="medium",
                            internal_handling="sync",
                            reason=f"callee at {d['file']}:{d['line']} has no await/.then "
                                   "and no throw; cannot reject")
                return item
            if has_catch and not partial:
                item.update(category="handled_internally", risk="LOW", confidence="high",
                            internal_handling="full",
                            reason=f"callee defined at {d['file']}:{d['line']} catches internally "
                                   "(all awaits inside try/catch or chained .catch)")
                return item
            if has_catch and partial:
                item.update(category="swallow", risk="MEDIUM", confidence="low",
                            internal_handling="partial",
                            reason=f"callee at {d['file']}:{d['line']} has try/catch but some "
                                   "await/.then sits outside it; rejection can still escape")
                return item
            # no direct catch: one-level transitive check via same-file helpers
            # (e.g. guard('label', async () => {...}) wrappers)
            helper_hit = None
            called = re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", head + body)
            for cn in dict.fromkeys(called):
                if cn == callee.split(".")[-1] or cn in ("if", "for", "while", "switch", "catch", "return"):
                    continue
                for d2 in def_index.get(cn, []):
                    if d2["file"] != d["file"]:
                        continue
                    body2 = files_by_id[d2["masked_file_id"]][d2["bs"]:d2["be"] + 1]
                    if re.search(r"\bcatch\b|\.catch\s*\(", body2):
                        helper_hit = cn
                        break
                if helper_hit:
                    break
            if helper_hit:
                item.update(category="handled_internally", risk="LOW", confidence="medium",
                            internal_handling=f"via_helper:{helper_hit}",
                            reason=f"callee delegates to same-file helper {helper_hit}() "
                                   "which catches internally")
                return item
            verb_hit = any(v in lower for v in RISK_VERBS)
            read_hit = any(v in lower for v in READ_VERBS)
            item.update(category="swallow" if verb_hit else ("best_effort" if read_hit else "swallow"),
                        risk="HIGH" if verb_hit else "MEDIUM",
                        confidence="medium" if (verb_hit or read_hit) else "low",
                        internal_handling="none",
                        reason=f"callee at {d['file']}:{d['line']} has no internal catch; "
                               + ("mutation verb and no handler -> silent failure + unhandled rejection"
                                  if verb_hit else
                                  ("read-only call; failure leaves stale/empty UI silently" if read_hit
                                   else "no handler found on either side")))
            return item
        if iife or body_from.lstrip().startswith("("):
            body_start = masked.find("{", m.end())
            body = masked[body_start:expr_end] if body_start != -1 else expr
            has_catch = bool(re.search(r"\bcatch\b|\.catch\s*\(", body))
            if has_catch:
                item.update(category="handled_internally", risk="LOW", confidence="high",
                            internal_handling="full",
                            reason="inline async body catches internally")
            else:
                item.update(category="swallow", risk="MEDIUM", confidence="medium",
                            internal_handling="none",
                            reason="inline async body has no catch; rejection escapes")
            return item
    lower_full = expr.lower()
    if "(" not in expr:
        item.update(category="best_effort", risk="LOW", confidence="high",
                    reason="void of a non-call expression (unused-var suppression "
                           "or forced-reflow idiom); no promise involved")
        return item
    if callee.split(".")[-1] in {"destroy", "abort", "dispose", "unregister", "teardown", "cancel"}:
        item.update(category="best_effort", risk="LOW", confidence="medium",
                    reason="teardown-style call; failure to cancel/release only leaks "
                           "until the page unloads")
        return item
    if callee and callee.split(".")[-1] in destructured:
        item.update(category="swallow", risk="MEDIUM", confidence="low",
                    reason="callee comes from a hook/object destructure; internal "
                           "error handling not visible at this site")
        return item
    verb_hit = any(v in lower_full for v in RISK_VERBS)
    read_hit = any(v in lower_full for v in READ_VERBS)
    item.update(
        category="swallow" if verb_hit or not read_hit else "best_effort",
        risk="MEDIUM",
        confidence="low",
        reason="callee definition not visible in web/ (hook/context/prop provided); "
               + ("mutation verb, suspected silent failure" if verb_hit
                  else ("read-only call, silent failure" if read_hit
                        else "handling unverifiable at this site")),
    )
    return item


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "web")
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "void-promises.json")
    files = []
    for p in iter_files(root):
        src = p.read_text(encoding="utf-8", errors="replace")
        files.append((p, mask(src), src))
    files_by_id = {id(masked): masked for _, masked, _ in files}
    def_index, destructured, hook_objects = build_def_index([(p, masked) for p, masked, _ in files])

    items = []
    for path, masked, code_masked in files:
        rel = str(path)
        is_test = "/tests/" in rel or rel.endswith(".spec.ts") or rel.endswith(".test.tsx")
        for m in VOID_RE.finditer(masked):
            if not stmt_void_ok(masked, m.start()):
                continue
            expr_end = stmt_end(masked, m.end())
            items.append(classify(files_by_id, def_index, destructured, hook_objects, rel, masked, m,
                                  expr_end, "void_statement", is_test))
        for m in CATCH_NOOP_RE.finditer(masked):
            stmt_start = max(masked.rfind("\n", 0, m.start()), 0)
            ctx = masked[stmt_start:m.end()].strip()
            expr = ctx[-200:]
            callee_m = CALLEE_RE.match(re.sub(r"^\s*(?:await|return)\s+", "", ctx.lstrip()))
            callee = callee_m.group(1) if callee_m else ""
            verb_hit = any(v in expr.lower() for v in RISK_VERBS)
            read_hit = any(v in expr.lower() for v in READ_VERBS)
            items.append({
                "file": rel, "line": line_of(masked, m.start()), "kind": "noop_catch",
                "expr": expr, "callee": callee, "rejection_handler": "empty",
                "is_test": is_test,
                "category": "swallow" if verb_hit else ("best_effort" if read_hit else "swallow"),
                "risk": "MEDIUM" if verb_hit else ("LOW" if read_hit else "MEDIUM"),
                "confidence": "medium",
                "internal_handling": None,
                "reason": "no-op .catch: rejection swallowed at "
                          + ("mutation call site" if verb_hit else ("read-only call site" if read_hit else "call site")),
            })
        for m in EMPTY_CATCH_RE.finditer(masked):
            if CATCH_NOOP_RE.search(masked[max(0, m.start() - 30):m.end()]):
                continue
            ctx = masked[max(0, m.start() - 200):m.end()]
            # truly empty = brace interior is whitespace in the RAW source;
            # comment-only bodies keep their comment text in raw text
            raw_slice = code_masked[m.start():m.end() + 2]
            open_b = raw_slice.find("{")
            close_b = raw_slice.rfind("}")
            truly_empty = (
                open_b != -1 and close_b > open_b
                and raw_slice[open_b + 1:close_b].strip() == ""
            )
            items.append({
                "file": rel, "line": line_of(masked, m.start()),
                "kind": "empty_catch_block" if truly_empty else "comment_only_catch",
                "expr": ctx[-200:].strip(), "callee": "", "rejection_handler": "empty",
                "is_test": is_test,
                "category": "swallow", "risk": "MEDIUM" if truly_empty else "LOW",
                "confidence": "medium",
                "internal_handling": None,
                "reason": ("empty catch {} block: any thrown error disappears without trace"
                           if truly_empty else
                           "catch block contains only a comment: error swallowed "
                           "with an explanatory note only"),
            })

    for i, item in enumerate(items, 1):
        item["id"] = f"VP-{i:04d}"
        if item["is_test"]:
            item["category"], item["risk"], item["confidence"] = "best_effort", "LOW", "high"
            item["reason"] = "test/e2e code; production impact none"

    totals = {
        "files_scanned": len(files),
        "total_items": len(items),
        "by_kind": {},
        "by_category": {},
        "by_risk": {},
    }
    for it in items:
        totals["by_kind"][it["kind"]] = totals["by_kind"].get(it["kind"], 0) + 1
        totals["by_category"][it["category"]] = totals["by_category"].get(it["category"], 0) + 1
        totals["by_risk"][it["risk"]] = totals["by_risk"].get(it["risk"], 0) + 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": str(root),
        "note": "read-only static scan; masked strings/comments before matching; "
                "definition index covers function/const-arrow/useCallback/exported-object methods in web/",
        "totals": totals,
        "items": items,
    }
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
