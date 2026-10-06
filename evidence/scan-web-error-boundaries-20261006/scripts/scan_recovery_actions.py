#!/usr/bin/env python3
"""Inventory error-recovery affordances in web/ (axis C).

C1  Retry/reload/resend affordances in UI code: visible text, aria-label,
    or handler identifiers matching retry/try-again/reload/resend/reconnect.
C2  Consumption of AppError.retryable / ApiError.retryable (the data model
    that classifies which failures may be retried).
C3  Dedicated recovery infrastructure: resend/reconnect/recovery modules and
    banner components with a retry action.

Deterministic: sorted walks, stable JSON, no timestamps.
Usage: python3 scan_recovery_actions.py <repo-root>
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {"node_modules", ".next", "coverage", "dist", ".turbo", ".git"}
SOURCE_SUFFIXES = {".ts", ".tsx"}

AFFORDANCE_TEXT_RE = re.compile(
    r"""(?:(?:>\s*[^<>{}]*?\b(?:[Rr]etry|[Tt]ry [Aa]gain|重试|重新加载|重新尝试|reconnect|Reconnect)\b[^<>{}]*?\s*<)"""
    r"""|(?:aria-[Ll]abel=\{?["'][^"']*\b(?:retry|try again|reload|resend|reconnect)[^"']*["'])"""
    r"""|(?:[Tt]itle=\{?["'][^"']*\b(?:retry|reload|resend)[^"']*["'])"""
    r"""|(?:[^A-Za-z]t\(\s*["'][^"']*(?:retry|try again|重试|重新加载|重新尝试|reload|resend)[^"']*["']))""",
    re.I)
HANDLER_IDENT_RE = re.compile(
    r"\b(?:handle|on|do)?[A-Z]?(?:retry|resend|reconnect|reload)[A-Za-z0-9]*\b")
RETRYABLE_CONSUME_RE = re.compile(r"\.retryable\b")
RESET_BOUNDARY_RE = re.compile(r"resetErrorBoundary|resetKeys")
WINDOW_RELOAD_RE = re.compile(r"window\.location\.reload\s*\(")
INFRA_MODULE_HINTS = {
    "send-retry.ts": "chat send retry queue",
    "chat-resend.ts": "chat message resend decision",
    "chat-idle-recovery.ts": "chat idle recovery",
    "failed-submissions.ts": "chat failed submission store",
    "reconnecting-websocket.ts": "websocket reconnect wrapper",
    "reading-failure.ts": "reading failure taxonomy",
    "session-load.ts": "session load retry",
    "book-errors.ts": "book error taxonomy",
}
BANNER_COMPONENT_RE = re.compile(r"[A-Za-z0-9]*(?:Banner|HealthBanner)[A-Za-z0-9]*\.tsx$")


def iter_source(root: Path, extra_skip=("tests", "__tests__", "e2e")):
    for path in sorted((root / "web").rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(part in extra_skip for part in rel.parts):
            continue
        yield rel


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def main(repo_root: str) -> None:
    root = Path(repo_root).resolve()
    affordances = []
    handler_ids = []
    retryable_consumers = []
    infra_modules = []
    banners = []
    window_reloads = []

    for rel in iter_source(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        name = rel.name
        if name in INFRA_MODULE_HINTS:
            infra_modules.append(
                {"file": str(rel), "role": INFRA_MODULE_HINTS[name]})
        if BANNER_COMPONENT_RE.search(name):
            banners.append(str(rel))
        for m in AFFORDANCE_TEXT_RE.finditer(text):
            affordances.append({
                "file": str(rel), "line": line_of(text, m.start()),
                "kind": "visible_or_aria_text",
                "text": " ".join(m.group(0).split())[:120],
            })
        for m in HANDLER_IDENT_RE.finditer(text):
            ident = m.group(0)
            if ident[0].islower() and not ident.startswith(("on", "handle", "do")):
                # plain nouns like "retries" counters — keep only obvious handlers
                if ident in {"retries", "retrying", "retryable"}:
                    continue
            handler_ids.append({
                "file": str(rel), "line": line_of(text, m.start()),
                "identifier": ident,
            })
        for m in RETRYABLE_CONSUME_RE.finditer(text):
            retryable_consumers.append({
                "file": str(rel), "line": line_of(text, m.start()),
            })
        for m in RESET_BOUNDARY_RE.finditer(text):
            retryable_consumers.append({
                "file": str(rel), "line": line_of(text, m.start()),
                "note": "boundary-reset-api",
            })
        for m in WINDOW_RELOAD_RE.finditer(text):
            window_reloads.append({
                "file": str(rel), "line": line_of(text, m.start()),
            })

    def dedup(seq):
        seen = set()
        out = []
        for item in sorted(seq, key=lambda e: json.dumps(e, sort_keys=True)):
            key = json.dumps(item, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    affordance_files = sorted({a["file"] for a in affordances})
    result = {
        "scan": "web-recovery-actions",
        "c1_affordances_visible_text": dedup(affordances),
        "c1_affordance_file_count": len(affordance_files),
        "c1_affordance_files": affordance_files,
        "c1_handler_identifiers": {
            "count": len(handler_ids),
            "by_file": dedup(
                {"file": h["file"], "identifier": h["identifier"]}
                for h in handler_ids),
        },
        "c2_retryable_consumers": dedup(retryable_consumers),
        "c2_retryable_consumer_files": sorted(
            {c["file"] for c in retryable_consumers}),
        "c3_infra_modules": sorted(
            infra_modules, key=lambda e: e["file"]),
        "c3_banner_components": banners,
        "c3_window_reload_calls": dedup(window_reloads),
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
