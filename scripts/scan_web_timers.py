#!/usr/bin/env python3
"""Static inventory of web/ frontend timer & listener leaks (read-only).

Axis: setTimeout/setInterval without a saved handle or without clear,
addEventListener without removeEventListener, React effects missing
cleanup functions, and post-unmount state updates.

Dedup boundaries (other scan cards own these axes):
  - backend session/handle/subprocess leaks  -> scan_resource_leaks.py (AGEN-964)
  - React hooks rule violations (deps/order) -> scan-react-hooks axis
  - dead / unused code                       -> scan-web-dead-code axis

Pure stdlib, read-only, deterministic: same tree -> same findings JSON.

Usage:
    python3 scripts/scan_web_timers.py [--root .] [--json OUT] [--summary-only]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# File collection
# --------------------------------------------------------------------------

WEB_DIR = "web"
SKIP_DIRS = {
    "node_modules", ".next", "coverage", "vendor", "generated",
    "locales", "public", ".turbo", "dist", "playwright-report",
    "test-results",
}
EXTS = (".ts", ".tsx")

TEST_MARKERS = ("/tests/", ".test.", ".spec.", "/__tests__/", "/e2e/")
CONFIG_MARKERS = ("playwright.config", "vitest.config", "eslint.config",
                  "next.config", "postcss.config", "tailwind.config",
                  "tsconfig", "proxy.ts")


def collect_files(root: str) -> List[str]:
    files: List[str] = []
    web_root = os.path.join(root, WEB_DIR)
    for dirpath, dirnames, filenames in os.walk(web_root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(EXTS):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            files.append(rel.replace(os.sep, "/"))
    return sorted(files)


def zone_of(rel: str) -> str:
    if any(m in rel for m in TEST_MARKERS):
        return "tests"
    if rel.startswith(WEB_DIR + "/scripts/"):
        return "scripts"
    if any(os.path.basename(rel).startswith(m) or rel.endswith(m)
           for m in CONFIG_MARKERS):
        return "config"
    return "product"


# Component-ish files: React components / hooks / context / pages.
COMPONENT_DIRS = (
    "web/components/", "web/features/", "web/hooks/", "web/context/",
    "web/app/", "web/shared/ui/", "web/shared/auth/", "web/shared/storage/",
)


def component_file(rel: str) -> bool:
    z = zone_of(rel)
    if z not in ("product",):
        return False
    return any(rel.startswith(p) for p in COMPONENT_DIRS) or \
        rel in ("web/proxy.ts",)


# --------------------------------------------------------------------------
# JS/TS masking: blank out comment bodies and string-literal interiors,
# preserving every offset and line break so anchors keep their positions.
# --------------------------------------------------------------------------

def mask_source(src: str) -> str:
    out = list(src)
    i, n = 0, len(src)
    state = "code"  # code | line_comment | block_comment | squote | dquote | template
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line_comment"
                out[i] = out[i + 1] = " "
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block_comment"
                out[i] = out[i + 1] = " "
                i += 2
                continue
            if c == "'":
                state = "squote"
                i += 1
                continue
            if c == '"':
                state = "dquote"
                i += 1
                continue
            if c == "`":
                state = "template"
                i += 1
                continue
            i += 1
            continue
        if state == "line_comment":
            if c == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = "code"
                i += 2
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        if state in ("squote", "dquote"):
            quote = "'" if state == "squote" else '"'
            if c == "\\":
                out[i] = " "
                if i + 1 < n and src[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if c == quote:
                state = "code"
                i += 1
                continue
            if c == "\n":
                # Unterminated single-line string: likely a regex literal
                # artifact; leave the newline, bail out of string state and
                # keep the raw text (deterministic fallback).
                state = "code"
                i += 1
                continue
            out[i] = " "
            i += 1
            continue
        if state == "template":
            if c == "\\":
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
                continue
            if c == "`":
                state = "code"
                i += 1
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
    return "".join(out)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def col_of(text: str, pos: int) -> int:
    nl = text.rfind("\n", 0, pos)
    return pos - nl if nl >= 0 else pos + 1


# --------------------------------------------------------------------------
# Balanced-delimiter helpers (operate on masked text)
# --------------------------------------------------------------------------

OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {")": "(", "]": "[", "}": "{"}


def match_delim(text: str, open_pos: int) -> Optional[int]:
    """Return the position of the delimiter closing text[open_pos].

    Counts all bracket kinds uniformly; comment/string interiors are already
    masked out by mask_source, so residual imbalance (regex literals) only
    degrades to no-match, never to a wrong span.
    """
    opener = text[open_pos]
    if opener not in OPEN:
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        c = text[i]
        if c in OPEN:
            depth += 1
        elif c in CLOSE:
            depth -= 1
            if depth == 0:
                return i
    return None


CALL_ARG0 = re.compile(r"\s*(.*)$", re.S)


def first_call_arg(text: str, open_pos: int) -> Optional[Tuple[int, int]]:
    """Span (start, end) of the first top-level argument of a call whose '('
    is at open_pos."""
    close = match_delim(text, open_pos)
    if close is None:
        return None
    depth = 0
    start = open_pos + 1
    for i in range(open_pos + 1, close):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            return (start, i)
    return (start, close)


def call_span(text: str, open_pos: int) -> Tuple[int, int]:
    close = match_delim(text, open_pos)
    return (open_pos, close if close is not None else len(text) - 1)


# --------------------------------------------------------------------------
# Regexes for anchors (applied to masked text)
# --------------------------------------------------------------------------

RE_TIMER = re.compile(r"\b(setTimeout|setInterval)\s*\(")
RE_CLEAR = re.compile(r"\b(clearTimeout|clearInterval)\s*\(\s*([A-Za-z_$][\w$.]*)")
RE_ASSIGN_HANDLE = re.compile(
    r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*=\s*(?:(?:window|globalThis|self)\s*\.\s*)?"
    r"(setTimeout|setInterval)\s*\($"
)
RE_ADD_LISTENER = re.compile(
    r"((?:[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*|\[[^\]\n]*\])*))\s*\.\s*"
    r"addEventListener\s*\(\s*(['\"])([^'\"\\\n]+?)\2"
    r"\s*,\s*([A-Za-z_$][\w$.]*|[\s\S]{0,4}\(|\bfunction\b|this\.)?"
)
RE_BARE_ADD = re.compile(r"(?<![.\w])addEventListener\s*\(\s*(['\"])([^'\"\\\n]+?)\1")
RE_REMOVE_LISTENER = re.compile(
    r"((?:[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*|\[[^\]\n]*\])*))\s*\.\s*"
    r"(removeEventListener|off|removeListener)\s*\(\s*(['\"])([^'\"\\\n]+?)\3"
)
RE_BARE_REMOVE = re.compile(
    r"(?<![.\w])(removeEventListener|off|removeListener)\s*\(\s*(['\"])([^'\"\\\n]+?)\2"
)
RE_USEEFFECT = re.compile(r"(?<![.\w])useEffect\s*\(")
RE_USESTATE = re.compile(r"(?<![.\w])useState\s*\(")
RE_SETTER_CALL = re.compile(r"(?<![.\w])(set[A-Z][\w$]*)\s*\(|(?<![.\w])dispatch\s*\(")
RE_RETURN_FN = re.compile(r"\breturn\b[^;\n]{0,120}")
CLEANUP_VERB = re.compile(
    r"(clear|remove|disconnect|unsubscri|abort|cancel|dispose|teardown|destroy|\.off\(|close)"
)
GUARD_TOKENS = re.compile(
    r"\b(isMounted|hasMounted|mounted|cancelled|canceled|disposed|alive|"
    r"stale|aborted|AbortController|unmounted|active)\b"
)
IDENT = re.compile(r"[A-Za-z_$][\w$]*")

DOM_GLOBAL = re.compile(r"^\s*(window|document|globalThis|self)\s*(\??\.)?$")
TIMER_WINDOW_PREFIX = re.compile(
    r"(?<![.\w])(?:(?:window|globalThis|self)\s*\.\s*)?(?:setTimeout|setInterval)\s*\("
)
INLINE_ARROW = re.compile(r"^\s*\(?\s*(?:async\s*)?\(")


# --------------------------------------------------------------------------
# Per-file analysis
# --------------------------------------------------------------------------

CONTROL_BLOCK = re.compile(
    r"\b(if|else|for|while|switch|try)\b[^\n{};]*\{$")


def _is_control_block(masked: str, brace_pos: int) -> bool:
    start = max(0, brace_pos - 200)
    return bool(CONTROL_BLOCK.search(masked[start:brace_pos + 1]))


def find_effects(masked: str) -> List[Dict]:
    """Locate useEffect(...) calls; extract callback body span + cleanup flag."""
    effects: List[Dict] = []
    for m in RE_USEEFFECT.finditer(masked):
        open_pos = m.end() - 1
        call_close = match_delim(masked, open_pos)
        if call_close is None:
            continue
        arg0 = first_call_arg(masked, open_pos)
        if arg0 is None:
            continue
        body = masked[arg0[0]:arg0[1]]
        # Locate the callback body braces if present.
        body_span: Optional[Tuple[int, int]] = None
        brace = body.find("{")
        if brace >= 0:
            abs_brace = arg0[0] + brace
            bclose = match_delim(masked, abs_brace)
            if bclose is not None:
                body_span = (abs_brace + 1, bclose)
        # `return` of a function value == cleanup (React contract: any
        # function returned from the effect callback is the cleanup). A
        # return inside plain control blocks (if/else) of the callback body
        # still returns from the callback, so it counts too.
        has_cleanup = False
        cleanup_pos: Optional[int] = None
        if body_span:
            seg = masked[body_span[0]:body_span[1]]
            stack: List[str] = []  # "fn" | "ctrl"
            i = 0
            while i < len(seg):
                c = seg[i]
                if c == "{":
                    stack.append("ctrl" if _is_control_block(
                        masked, body_span[0] + i) else "fn")
                elif c == "}":
                    if stack:
                        stack.pop()
                elif seg.startswith("return", i) and \
                        (i == 0 or not (seg[i - 1].isalnum() or seg[i - 1] in "_$")) and \
                        all(k == "ctrl" for k in stack):
                    rest = seg[i + 6:i + 6 + 120]
                    # `return;` / `return null;` / `return <JSX>` etc are not
                    # cleanups; returning a function value is.
                    payload = rest.lstrip()
                    if re.match(
                            r"\(\s*\)?[^;)]*\)\s*=>", payload) or \
                            re.match(r"\(\s*\)\s*=>", payload) or \
                            payload.startswith("function") or \
                            re.match(r"[A-Za-z_$][\w$.]*\s*\(", payload) or \
                            re.match(r"[A-Za-z_$][\w$.]*\s*;", payload) and not \
                            re.match(r"(null|undefined|true|false|void)\b", payload):
                        has_cleanup = True
                        cleanup_pos = body_span[0] + i
                        break
                i += 1
        effects.append({
            "line": line_of(masked, m.start()),
            "open": open_pos,
            "close": call_close,
            "body": body_span,
            "has_cleanup": has_cleanup,
            "cleanup_pos": cleanup_pos,
        })
    return effects


def effect_at(effects: List[Dict], pos: int) -> Optional[Dict]:
    for eff in effects:
        if eff["body"] and eff["body"][0] <= pos < eff["body"][1]:
            return eff
        if eff["open"] <= pos <= eff["close"] and not eff["body"]:
            return eff
    return None


def enclosing_function_span(masked: str, pos: int,
                            limit: int = 6000) -> Optional[Tuple[int, int]]:
    """Find the nearest function-ish declaration/assignment containing pos by
    scanning backwards for `function name` / `const name = (...) =>` heads."""
    seg_start = max(0, pos - limit)
    best: Optional[Tuple[int, int]] = None
    for head in re.finditer(
            r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(|"
            r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*(?:\s*:\s*[^=;]{0,80})?=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
            masked[seg_start:pos]):
        head_abs = seg_start + head.end() - 1
        # find the brace body after head
        brace = masked.find("{", head_abs, pos + 1)
        if brace < 0:
            continue
        bclose = match_delim(masked, brace)
        if bclose is not None and brace < pos < bclose:
            best = (brace, bclose)
    return best


def idents_of(expr: str) -> List[str]:
    return IDENT.findall(expr)


def analyze(rel: str) -> List[Dict]:
    path = os.path.join(os.getcwd(), rel)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
    except OSError as exc:
        return [{"rule": "read-error", "severity": "low", "file": rel,
                 "line": 0, "col": 0,
                 "detail": f"unreadable: {exc}", "suggestion": "",
                 "zone": zone_of(rel), "context": ""}]
    masked = mask_source(src)
    zone = zone_of(rel)
    comp = component_file(rel)
    effects = find_effects(masked)
    findings: List[Dict] = []

    def add(rule: str, severity: str, pos: int, detail: str,
            suggestion: str, context: str) -> None:
        sev = severity
        if zone == "tests" and sev == "high":
            sev = "medium"
        if zone in ("tests", "scripts", "config") and sev == "medium":
            sev = "low"
        findings.append({
            "rule": rule, "severity": sev, "file": rel,
            "line": line_of(masked, pos), "col": col_of(masked, pos),
            "detail": detail, "suggestion": suggestion,
            "zone": zone, "context": context,
        })

    # ---- collect timer/clear anchors -------------------------------------
    clear_ids: List[str] = []
    for m in RE_CLEAR.finditer(masked):
        clear_ids.append(m.group(2))

    timer_anchors = []
    for m in RE_TIMER.finditer(masked):
        kind = m.group(1)
        open_pos = m.end() - 1
        line_start = masked.rfind("\n", 0, m.start()) + 1
        assign = None
        handle = ""
        assigned = False
        # relaxed same-line assignment: `name = [ ...ternary... ] setInterval(`
        # (covers `const t = cond ? window.setInterval(..) : null`)
        am = re.search(
            r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*=\s*[^;]{0,120}?"
            r"(?:(?:window|globalThis|self)\s*\.\s*)?" + kind + r"\s*\($",
            masked[line_start:m.end()])
        if am and am.group(1) not in ("return", "typeof", "await", "case"):
            handle = am.group(1)
            assigned = True
        span = call_span(masked, open_pos)
        arg0 = first_call_arg(masked, open_pos)
        timer_anchors.append({
            "kind": kind, "pos": m.start(), "line": line_of(masked, m.start()),
            "assigned": assigned, "handle": handle, "span": span,
            "arg0": arg0, "ret_transfer": bool(
                re.search(r"\breturn\s+(?:window\s*\.\s*)?" + kind + r"\s*\($",
                          masked[max(0, m.start() - 40):m.start() + 4])),
        })

    clear_span_positions = [m.start() for m in
                            re.finditer(r"\bclear(Timeout|Interval)\s*\(", masked)]
    clear_call_spans = []
    for p in clear_span_positions:
        op = masked.find("(", p)
        clear_call_spans.append((p, call_span(masked, op)))

    def handle_cleared(anchor: Dict) -> bool:
        if not anchor["assigned"]:
            return False
        ids = idents_of(anchor["handle"])
        base = ids[-1] if ids else anchor["handle"]
        for (cp, cspan) in clear_call_spans:
            seg = masked[cspan[0]:cspan[1]]
            cids = idents_of(seg)
            if base in cids or anchor["handle"] in seg:
                return True
        return False

    # ---- R1 interval-uncleared --------------------------------------------
    for anchor in timer_anchors:
        if anchor["kind"] != "setInterval":
            continue
        eff = effect_at(effects, anchor["pos"])
        ctx = "effect" if eff else ("component" if comp else "module")
        cleared = handle_cleared(anchor)
        if cleared:
            continue
        if anchor["ret_transfer"]:
            add("interval-ownership-transfer", "low", anchor["pos"],
                "setInterval returned to caller; lifetime owned by caller",
                "document the transfer or wrap in a stop() helper", ctx)
            continue
        if not anchor["assigned"]:
            add("interval-dropped-handle", "high", anchor["pos"],
                "setInterval return value discarded; interval cannot be stopped",
                "save the handle and clearInterval on teardown/unmount", ctx)
        else:
            sev = "high" if (comp or eff) else "medium"
            add("interval-never-cleared", sev, anchor["pos"],
                f"handle '{anchor['handle']}' is never passed to clearInterval "
                f"anywhere in this file",
                "clear the interval in the effect cleanup / teardown path", ctx)

    # ---- R2 timeout-in-effect-no-cleanup ----------------------------------
    def cleanup_neutralizes_timer(masked: str, eff: Dict,
                                  body_txt: str) -> bool:
        tail = masked[eff["cleanup_pos"]:eff["body"][1]]
        if re.search(r"\bclear(Timeout|Interval)\b", tail):
            return True
        # guard-flag pattern: cleanup sets `cancelled = true` and the body
        # checks the same flag before doing timer work
        for gm in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*=\s*true\b", tail):
            flag = gm.group(1)
            if re.search(r"\b" + flag + r"\b", body_txt):
                return True
        # `return stopFn;` — resolve a named teardown function in body scope
        bm = re.match(r"\s*return\s+([A-Za-z_$][\w$]*)\s*;", tail)
        if bm:
            fname = bm.group(1)
            fm = re.search(
                r"(?:function\s+" + fname +
                r"\s*\(|(?:const|let|var)\s+" + fname +
                r"\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)",
                body_txt)
            if fm:
                brace = body_txt.find("{", fm.start())
                if brace >= 0:
                    abs_brace = eff["body"][0] + brace
                    bclose = match_delim(masked, abs_brace)
                    if bclose is not None:
                        fn_body = masked[abs_brace:bclose + 1]
                        if re.search(r"\bclear(Timeout|Interval)\b", fn_body) \
                                or any(re.search(r"\b" + f + r"\s*=\s*true\b",
                                                 fn_body) and
                                       re.search(r"\b" + f + r"\b", body_txt)
                                       for f in ("cancelled", "canceled",
                                                 "disposed", "stopped",
                                                 "alive", "aborted")):
                            return True
        return False

    for anchor in timer_anchors:
        if anchor["kind"] != "setTimeout":
            continue
        eff = effect_at(effects, anchor["pos"])
        if not eff:
            continue
        if not eff["has_cleanup"]:
            add("timeout-in-effect-no-cleanup", "medium", anchor["pos"],
                "setTimeout inside useEffect that has no cleanup return; "
                "callback can still fire after unmount",
                "keep the handle (ref or local) and clearTimeout in an effect "
                "cleanup", "effect-no-cleanup")
        elif eff["cleanup_pos"] is not None and eff["body"] is not None:
            body_txt = masked[eff["body"][0]:eff["body"][1]]
            if not cleanup_neutralizes_timer(masked, eff, body_txt):
                add("timeout-in-effect-no-cleanup", "medium", anchor["pos"],
                    "setTimeout inside useEffect whose cleanup return does "
                    "not clearTimeout it; callback can still fire after "
                    "unmount",
                    "clear the timer in the effect cleanup return",
                    "effect-no-cleanup")

    # ---- R3 post-unmount-update -------------------------------------------
    guard_present = bool(GUARD_TOKENS.search(masked))
    for anchor in timer_anchors:
        if anchor["kind"] != "setTimeout" or not comp:
            continue
        eff = effect_at(effects, anchor["pos"])
        if eff:
            continue  # covered by R2 (or cleanup exists)
        # a handle that is actually cleared somewhere in the file is tracked;
        # unmount-clear verification for ref-based handles needs flow
        # analysis beyond this scan's scope
        if anchor["assigned"] and handle_cleared(anchor):
            continue
        if not anchor["arg0"]:
            continue
        cb = masked[anchor["arg0"][0]:anchor["arg0"][1]]
        if not RE_SETTER_CALL.search(cb):
            continue
        if guard_present:
            continue
        add("post-unmount-state-update", "medium", anchor["pos"],
            "fire-and-forget setTimeout callback updates component state "
            "without a mounted/cancelled guard",
            "track the handle and clear on unmount, or guard with a "
            "cancelled ref", "component")

    # ---- R4 listener-no-removal -------------------------------------------
    # Event names live inside string literals, which mask_source blanks out;
    # read them from the original source at identical offsets.
    remove_events: Dict[str, List[Tuple[str, int]]] = {}
    for m in RE_REMOVE_LISTENER.finditer(masked):
        remove_events.setdefault(src[m.start(4):m.end(4)],
                                 []).append((m.group(1), m.start()))
    for m in RE_BARE_REMOVE.finditer(masked):
        remove_events.setdefault(src[m.start(3):m.end(3)],
                                 []).append(("<bare>", m.start()))

    # lifetime-managed receivers: `<ident>.close()/.abort()/.disconnect()`
    managed_rx = re.compile(
        r"([A-Za-z_$][\w$]*)\s*\??\.\s*(?:close|abort|disconnect)\s*\(")
    managed_ids = {m.group(1) for m in managed_rx.finditer(masked)}
    file_has_close = bool(managed_rx.search(masked))

    add_listeners = []
    for m in RE_ADD_LISTENER.finditer(masked):
        target = m.group(1)
        event = src[m.start(3):m.end(3)]
        op = masked.rfind("(", 0, m.start(3))
        arg0 = first_call_arg(masked, op)
        handler_txt = masked[arg0[0]:arg0[1]] if arg0 else ""
        inline = bool(re.match(r"^\s*(\(?[^=)]*)?\s*=>|\bfunction\s*\(", handler_txt))
        # `{ once: true }` listeners remove themselves after first fire
        args_txt = masked[op:match_delim(masked, op) + 1] \
            if match_delim(masked, op) else ""
        once_opt = bool(re.search(r"\bonce\s*:\s*true\b", args_txt))
        add_listeners.append({
            "pos": m.start(), "target": target, "event": event,
            "inline": inline, "once": once_opt,
            "handler": handler_txt.strip()[:60],
            "line": line_of(masked, m.start()),
        })

    seen_listener = set()
    for lst in add_listeners:
        key = (lst["target"], lst["event"], lst["pos"])
        if key in seen_listener:
            continue
        seen_listener.add(key)
        if lst["once"]:
            continue
        is_dom = bool(DOM_GLOBAL.match(lst["target"]))
        if lst["event"] in remove_events:
            continue
        tids = idents_of(lst["target"])
        tbase = tids[-1] if tids else lst["target"]
        # AbortSignal listeners are removed by abort() itself; signal-owned
        # targets are not leak candidates.
        if tbase == "signal" or lst["target"].endswith(".signal"):
            continue
        lifetime_managed = (not is_dom) and tbase in managed_ids
        if lifetime_managed:
            continue
        eff = effect_at(effects, lst["pos"])
        ctx = "effect" if eff else ("component" if comp else "module")
        detail = f"addEventListener('{lst['event']}' on {lst['target']}"
        if lst["inline"]:
            detail += " with an inline handler that can never be removed"
        detail += f") has no matching removeEventListener('{lst['event']}') in this file"
        if is_dom:
            if comp or eff:
                sev = "high"
                sug = ("remove the listener with the same event name and "
                       "handler in the effect cleanup")
            else:
                sev = "low"
                sug = ("module-level listener lives for the page lifetime; "
                       "make the intent explicit or add a removal path")
        else:
            sev = "low"
            if file_has_close:
                detail += ("; note: target objects in this file are closed "
                           "via close()/abort()/disconnect(), so listeners "
                           "are discarded with the target")
            sug = ("element listeners are GC'd with the element, but repeated "
                   "registration (e.g. inside handlers) accumulates; add a "
                   "removal path or manage the target lifetime explicitly")
        add("listener-no-removal", sev, lst["pos"], detail, sug, ctx)

    # bare addEventListener(...) wrapper functions (subscription helpers)
    for m in RE_BARE_ADD.finditer(masked):
        event = src[m.start(2):m.end(2)]
        if event in remove_events:
            continue
        fspan = enclosing_function_span(masked, m.start())
        if fspan:
            seg = masked[fspan[0]:fspan[1]]
            depth_ret = RE_RETURN_FN.search(seg)
            if depth_ret and CLEANUP_VERB.search(seg[depth_ret.start():depth_ret.start() + 300]):
                continue
        add("listener-wrapper-no-removal", "low", m.start(),
            f"bare addEventListener('{event}') inside a helper that does not "
            f"return an unsubscribe function",
            "return () => target.removeEventListener(...) so callers can "
            "unsubscribe", "module")

    # ---- R5 effect registers subscription without any cleanup --------------
    for eff in effects:
        if eff["has_cleanup"] or not eff["body"]:
            continue
        seg = masked[eff["body"][0]:eff["body"][1]]
        has_dotted = RE_ADD_LISTENER.search(seg)
        has_bare = RE_BARE_ADD.search(seg)
        has_timer = RE_TIMER.search(seg)
        if has_dotted is None and not has_bare and not has_timer:
            continue
        inside_flagged = False
        for anchor in timer_anchors:
            if eff["body"][0] <= anchor["pos"] < eff["body"][1]:
                for f in findings:
                    if f["file"] == rel and f["line"] == anchor["line"]:
                        inside_flagged = True
        for lst in add_listeners:
            if eff["body"][0] <= lst["pos"] < eff["body"][1]:
                for f in findings:
                    if f["file"] == rel and f["line"] == lst["line"]:
                        inside_flagged = True
        if inside_flagged:
            continue
        what = []
        if has_dotted is not None:
            what.append("addEventListener")
        if has_bare:
            what.append("bare addEventListener")
        if has_timer:
            what.append("setInterval/setTimeout")
        add("effect-subscription-no-cleanup", "high", eff["open"],
            "useEffect registers " + "/".join(what) +
            " but has no cleanup return",
            "return a cleanup that removes the listener / clears the timer",
            "effect-no-cleanup")

    return findings


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def git_meta(root: str) -> Dict:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", root, *args],
                                  capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
    rev = run("rev-parse", "HEAD")
    subject = run("log", "-1", "--format=%s")
    return {"rev": rev, "subject": subject}


RULES_DOC = [
    ("interval-dropped-handle", "setInterval return value discarded; cannot be stopped"),
    ("interval-never-cleared", "saved handle but no clearInterval path in file"),
    ("interval-ownership-transfer", "interval returned to caller (informational)"),
    ("timeout-in-effect-no-cleanup", "setTimeout in useEffect without cleanup clear"),
    ("post-unmount-state-update", "detached setTimeout updates state without guard"),
    ("listener-no-removal", "addEventListener without matching removal in file"),
    ("listener-wrapper-no-removal", "subscription helper without unsubscribe return"),
    ("effect-subscription-no-cleanup", "useEffect registers subscription, no cleanup return"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="repo root containing web/")
    ap.add_argument("--json", default=None,
                    help="write findings JSON here (default: stdout summary only)")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--rev", default=None,
                    help="pin meta.rev (for byte-identical re-runs)")
    ap.add_argument("--subject", default=None,
                    help="pin meta.subject (for byte-identical re-runs)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    files = collect_files(root)
    all_findings: List[Dict] = []
    parsed = 0
    for rel in files:
        findings = analyze(rel)
        parsed += 1
        all_findings.extend(f for f in findings if f["rule"] != "read-error")

    all_findings.sort(key=lambda f: (f["file"], f["line"], f["rule"], f["col"]))
    for i, f in enumerate(all_findings, 1):
        f["id"] = f"WT-{i:04d}"

    sev_order = {"high": 0, "medium": 1, "low": 2}
    counts_rule: Dict[str, int] = {}
    counts_sev: Dict[str, int] = {}
    counts_zone: Dict[str, int] = {}
    for f in all_findings:
        counts_rule[f["rule"]] = counts_rule.get(f["rule"], 0) + 1
        counts_sev[f["severity"]] = counts_sev.get(f["severity"], 0) + 1
        counts_zone[f["zone"]] = counts_zone.get(f["zone"], 0) + 1

    meta = git_meta(root)
    if args.rev is not None:
        meta["rev"] = args.rev
    if args.subject is not None:
        meta["subject"] = args.subject
    payload = {
        "meta": {
            "scanner": "scripts/scan_web_timers.py",
            "rev": meta["rev"], "subject": meta["subject"],
            "files_scanned": parsed,
            "scope": WEB_DIR + "/**/*.{ts,tsx}",
            "excluded_dirs": sorted(SKIP_DIRS),
            "rules": [{"rule": r, "meaning": m} for r, m in RULES_DOC],
        },
        "counts": {
            "total": len(all_findings),
            "by_severity": {k: counts_sev.get(k, 0)
                            for k in ("high", "medium", "low")},
            "by_rule": dict(sorted(counts_rule.items())),
            "by_zone": dict(sorted(counts_zone.items())),
        },
        "findings": all_findings,
    }

    print(f"files scanned: {parsed}")
    print(f"findings: {len(all_findings)} "
          f"(high={counts_sev.get('high', 0)} "
          f"medium={counts_sev.get('medium', 0)} "
          f"low={counts_sev.get('low', 0)})")
    for r, c in sorted(counts_rule.items()):
        print(f"  {r}: {c}")

    if not args.summary_only and args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1,
                      sort_keys=False)
            fh.write("\n")
        print(f"findings JSON -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
