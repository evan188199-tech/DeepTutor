#!/usr/bin/env python3
"""Read-only docs drift scanner for DeepTutor.

Extracts path / command / module / env-var references from root *.md and
docs-for-user/**/*.md, verifies each against the worktree, and emits JSON.
No file outside this evidence directory is written.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()

DOC_GLOBS = ["*.md"] + ["docs-for-user/**/*.md"]
EXTRA_DIRS = ["scripts", "deeptutor", "deeptutor_cli", "web", "tests", "packaging", "requirements", "docs-for-user"]

path_token_re = re.compile(
    r"`([^`\n]+)`"
)
standalone_path_re = re.compile(
    r"(?<![\w./-])((?:\./)?(?:[\w@+.-]+/)+[\w@+.-]+?)(?=[),.;:!?\s`\]]|$)"
)
bare_file_re = re.compile(
    r"(?<![\w./-])([\w@+.-]+\.(?:py|sh|bat|ps1|yaml|yml|json|toml|service|cjs|mjs|env|cff))(?![\w-])"
)
py_mod_re = re.compile(r"(?:python3?|uv run python3?)\s+(?:-\w+\s+)*-m\s+([A-Za-z_][\w.]*)")
uv_run_re = re.compile(r"\buv\s+run\s+([\w:.-]+)")
entry_re = re.compile(r"^\s*(?:sudo\s+)?(?:bash|sh|zsh|python3?)\s+(\.?/?[\w@+./-]+\.(?:py|sh|bat))", re.M)
direct_exec_re = re.compile(r"^\s*(\.?/[\w@+./-]+\.(?:py|sh|bat))", re.M)
docker_f_re = re.compile(r"docker(?:-|\s+)compose(?:\s+\S+)*?\s+-f\s+([\w@+./-]+)")
env_decl_re = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=", re.M)
env_use_re = re.compile(r"\$[({]?([A-Z][A-Z0-9_]{2,})[)}]?")
env_inline_re = re.compile(r"(?:^|\s)([A-Z][A-Z0-9_]{2,})=(?:\S+)", re.M)


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def path_exists(rel: str) -> bool:
    rel = rel.strip().strip("\"'")
    if rel.startswith("./"):
        rel = rel[2:]
    rel = rel.rstrip("/")
    if not rel or rel.startswith(("/", "http")):
        return False
    return (ROOT / rel).exists()


def module_exists(mod: str) -> bool:
    base = ROOT / mod.replace(".", "/")
    return (base.with_suffix(".py")).exists() or (base / "__init__.py").exists()


def grep_count(pattern: str) -> int:
    out = subprocess.run(
        ["git", "grep", "-I", "-c", pattern, "--", ":!evidence"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    n = 0
    for line in out.splitlines():
        _, _, cnt = line.rpartition(":")
        try:
            n += int(cnt)
        except ValueError:
            pass
    return n


docs = []
for pat in DOC_GLOBS:
    docs += [p for p in ROOT.glob(pat) if p.is_file()]
docs = sorted(set(docs))

refs = []
for doc in docs:
    rel_doc = doc.relative_to(ROOT).as_posix()
    text = doc.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    in_fence = False
    fence_lang = ""
    fence_start = 0
    for i, line in enumerate(lines, 1):
        m = re.match(r"^```\s*(\w*)", line)
        if m:
            if not in_fence:
                in_fence, fence_lang, fence_start = True, m.group(1), i
            else:
                in_fence = False
            continue

        def add(kind, token, ctx=None):
            refs.append({
                "doc": rel_doc, "line": i, "kind": kind, "token": token,
                "fence": fence_lang if in_fence else "",
                "context": (ctx if ctx is not None else line).strip()[:160],
            })

        for tok in path_token_re.findall(line):
            t = tok.strip()
            if "/" in t and not t.startswith(("http", "#")) and not re.fullmatch(r"[\w.,:()-]+", t):
                add("backtick_path", t)
        if not in_fence:
            for tok in standalone_path_re.findall(line):
                add("text_path", tok)
            for tok in bare_file_re.findall(line):
                add("bare_file", tok)
        if in_fence:
            for tok in py_mod_re.findall(line):
                add("py_module", tok)
            for tok in uv_run_re.findall(line):
                add("uv_run_entry", tok)
            for tok in docker_f_re.findall(line):
                add("compose_file", tok)
            em = entry_re.match(line)
            if em:
                add("script_exec", em.group(1))
            dm = direct_exec_re.match(line)
            if dm:
                add("script_exec", dm.group(1))
            for tok in env_decl_re.findall(line):
                add("env_decl", tok)
            for tok in env_inline_re.findall(line):
                add("env_decl", tok)
            for tok in env_use_re.findall(line):
                add("env_use", tok)

# ---- verification ----
report = []
for r in refs:
    kind, tok = r["kind"], r["token"]
    verdict = "ok"
    note = ""
    if kind in ("backtick_path", "text_path", "script_exec", "compose_file", "bare_file"):
        t = tok
        if "#" in t and t.endswith((".md",)):
            t = t.split("#")[0]
        t = t.split(":")[0] if re.search(r":\d+$", t) else t
        t = t.rstrip(".,;:!?")
        if re.fullmatch(r"https?://.*", t) or t.startswith("<"):
            verdict = "skip_url"
        elif path_exists(t) or path_exists(t.lstrip("./")):
            verdict = "ok"
        elif kind == "backtick_path" and r["doc"].startswith("docs-for-user/"):
            alt = Path("docs-for-user") / t
            if path_exists(alt.as_posix()) or path_exists(t.replace("docs-for-user/", "")):
                verdict = "ok"
            else:
                verdict, note = "MISSING", "not found at repo root nor docs-for-user-relative"
        else:
            verdict, note = "MISSING", "path not found in worktree"
    elif kind == "py_module":
        if not module_exists(tok):
            verdict, note = "MISSING", "module file not found"
    elif kind == "uv_run_entry":
        verdict, note = "manual", "uv entry — check pyproject/scripts manually"
    elif kind in ("env_decl", "env_use"):
        n = grep_count(tok)
        if n == 0:
            verdict, note = "MISSING", "no occurrence anywhere in tracked code"
        else:
            verdict, note = "ok", f"{n} occurrence(s) in tracked code"
    r2 = dict(r)
    r2["verdict"], r2["note"] = verdict, note
    report.append(r2)

OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
missing = [r for r in report if r["verdict"] == "MISSING"]
kinds = {}
for r in report:
    kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
print(f"docs scanned: {len(docs)}")
print(f"refs extracted: {len(report)}  by kind: {kinds}")
print(f"MISSING: {len(missing)}")
for r in missing:
    print(f"  {r['doc']}:{r['line']}  [{r['kind']}] {r['token']!r}  -- {r['note']}")
