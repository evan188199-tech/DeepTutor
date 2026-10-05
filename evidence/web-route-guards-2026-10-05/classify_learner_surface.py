#!/usr/bin/env python3
"""Classify frontend API call literals against the learner learning-surface whitelist.

Read-only scan aid for evidence/web-route-guards-2026-10-05. Mirrors
_learning_surface_for_path (deeptutor/api/routers/auth.py:639) prefix/template
rules; a literal is learner-allowed only if the mirror returns non-empty.
"""
import json
import re
import subprocess
from pathlib import Path

ROOTS = ("/api/reading", "reading"), \
    ("/api/courses", "reading"), \
    ("/api/dashboard/learning-library/materials", "reading"), \
    ("/api/dashboard/learning-library/reading", "reading"), \
    ("/api/books", "books"), \
    ("/api/dashboard/learning-library/books", "books"), \
    ("/api/chat", "chat"), \
    ("/api/question", "chat"), \
    ("/api/question-notebook", "chat"), \
    ("/api/sessions", "chat"), \
    ("/api/task-board", "chat"), \
    ("/api/mastery-paths", "chat")

KB_READS = {
    "/api/knowledge-bases",
    "/api/knowledge-bases/list",
    "/api/knowledge-bases/{kb_name}",
    "/api/knowledge-bases/{kb_name}/files",
    "/api/knowledge-bases/{kb_name}/files/{filename:path}",
    "/api/knowledge-bases/{kb_name}/file-preview-text/{filename:path}",
    "/api/knowledge-bases/{kb_name}/visual-assets/{asset_id}",
    "/api/knowledge-bases/{kb_name}/progress",
}
SETTINGS_WRITES = {
    ("PUT", "/api/settings/ui"),
    ("PUT", "/api/settings/draft"),
    ("DELETE", "/api/settings/draft"),
    ("PUT", "/api/settings/workspace"),
    ("POST", "/api/settings/workspace/validate"),
    ("POST", "/api/settings/workspace/registrations"),
    ("PATCH", "/api/settings/workspace/registrations/{workspace_id}"),
}


def surface_for(path: str) -> str:
    normalized = "/" + str(path or "").lstrip("/")
    for root, surface in ROOTS:
        if normalized == root or normalized.startswith(f"{root}/"):
            return surface
    if (normalized == "/api/knowledge-bases" or normalized.startswith("/api/knowledge-bases/")):
        return "reading-if-GET-template"  # method/template resolved separately
    return ""


def main() -> None:
    out = subprocess.run(
        ["git", "grep", "-n", "-o", "-E",
         r"""["'`]/(api|files|ws)/[A-Za-z0-9_./{}$-]*""",
         "--", "web/app", "web/features", "web/components", "web/lib",
         "web/hooks", "web/context", "web/shared"],
        capture_output=True, text=True, check=True).stdout
    seen = {}
    for line in out.splitlines():
        m = re.match(r"^(web/[^:]+):(\d+):(.*)$", line)
        if not m:
            continue
        fpath, lineno, literal = m.group(1), m.group(2), m.group(3)
        path = literal.strip("\"'`")
        if path.endswith((".css", ".js", ".json", ".svg", ".png", ".md")):
            continue
        key = path
        seen.setdefault(key, []).append(f"{fpath}:{lineno}")
    rows = []
    for path, locs in sorted(seen.items()):
        rows.append({"literal": path, "surface": surface_for(path),
                     "call_sites": locs})
    out_path = Path(__file__).resolve().parent / "learner-surface-frontend-calls.json"
    out_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    denied = [r for r in rows if r["surface"] == ""]
    print(f"distinct literals: {len(rows)}; learner-denied: {len(denied)}")
    for r in denied:
        print(f"DENY {r['literal']}  <-  {r['call_sites'][0]}"
              + (f" (+{len(r['call_sites']) - 1} more)" if len(r['call_sites']) > 1 else ""))


if __name__ == "__main__":
    main()
