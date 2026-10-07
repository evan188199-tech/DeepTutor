#!/usr/bin/env python3
"""Render report.md from findings.json (reproducible evidence builder)."""
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
EVID = Path(__file__).parent
data = json.loads((EVID / "findings.json").read_text())
fs = data["findings"]

commit = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
).stdout.strip()

RULES = {
    "E1": ("missing-explicit-cause",
           "`raise <new>` inside an except handler without `from` — implicit `__context__` survives "
           "but `__cause__` is unset (traceback shows 'During handling…', not 'direct cause')",
           "`raise X(...) from e`"),
    "E2": ("suppressed-cause-from-none",
           "`raise ... from None` inside a handler — root-cause traceback deliberately dropped",
           "restore `from e`, or keep `from None` only after `logger.debug(..., exc_info=True)`"),
    "E3": ("from-none-outside-handler", "`from None` with no active handler", "remove `from None`"),
    "E4": ("bare-raise-outside-handler", "bare `raise` outside except — RuntimeError at runtime", "restructure"),
    "E5": ("raise-non-exception", "raising a string literal — TypeError at raise time", "wrap in an exception class"),
    "E6": ("return-in-finally", "return/break/continue in finally swallows in-flight exceptions", "move out of finally"),
    "E7": ("wrong-cause-target", "`from <name>` bound to neither the caught exception nor a local", "fix cause target"),
}

sev_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
sev_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "⚪"}
by_sev = Counter(f["severity"] for f in fs)
by_rule = Counter(f["rule"] for f in fs)
mods = {}
for f in fs:
    parts = Path(f["path"]).parts
    mod = ".".join(parts[:2]) if len(parts) > 2 else "deeptutor(root)"
    m = mods.setdefault(mod, Counter())
    m[f["severity"]] += 1
    m["total"] += 1
top_mods = sorted(mods.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
dedup_n = sum(1 for f in fs if "dedup" in f)
logged_n = sum(1 for f in fs if "likely intentional" in f["detail"])

L = []
w = L.append
w("# Exception-chain integrity scan (raise…from / cause loss) — deeptutor/")
w("")
w(f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
w(f"- Revision: origin/main @ `{commit}` (v1.6.13)")
w(f"- Scope: `deeptutor/**` — {data['files_scanned']} files parsed (0 syntax failures), AST-level, read-only")
w("- Scanner: `scan_exception_chain.py` (this directory); raw results in `findings.json`")
w("- Dedup axes: findings inside broad handlers (`except Exception` / `BaseException` / bare) carry "
  "`dedup: scan-broad-excepts` (**%d** findings) — overlap with the broad-capture scan, not double-counted "
  "here. Error-message wording and error-utility axes (scan-error-messages / fix-error-utils-sanitize) "
  "are orthogonal: this scan only judges chain integrity, not message text." % dedup_n)
w("")
w("## Summary")
w("")
w("| Severity | Count |")
w("|---|---|")
for s in ("high", "medium", "low", "info"):
    if by_sev.get(s):
        w(f"| {sev_emoji[s]} {s} | {by_sev[s]} |")
w(f"| **total** | **{len(fs)}** |")
w("")
w("| Rule | Meaning | Count |")
w("|---|---|---|")
for r, (name, desc, _) in RULES.items():
    if by_rule.get(r):
        w(f"| {r} {name} | {desc} | {by_rule[r]} |")
w("")
w("Rules with 0 findings: " + ", ".join(r for r in RULES if not by_rule.get(r)) + ".")
w("")
w("## Top modules")
w("")
w("| Module | Total | high | medium | low |")
w("|---|---|---|---|---|")
for mod, m in top_mods:
    w(f"| `{mod}` | {m['total']} | {m.get('high', 0)} | {m.get('medium', 0)} | {m.get('low', 0)} |")
w("")
w("## Findings")
w("")

def esc(s):
    return s.replace("|", "\\|").replace("`", "'")

def finding_row(f, excerpt=True):
    code = esc(f["code"]) if excerpt else ""
    dedup = " ·dedup:broad" if "dedup" in f else ""
    log = " ·logged" if "likely intentional" in f["detail"] else ""
    return (f"| `{f['path']}:{f['line']}` | {f['rule']} | {esc(f['detail'][:150])}{dedup}{log} "
            f"| `{code}` |")

high = [f for f in fs if f["severity"] == "high"]
w(f"### 🔴 High — {len(high)} (root cause fully lost; triage each as accidental vs intentional sanitization)")
w("")
w("| Location | Rule | Detail | Code |")
w("|---|---|---|---|")
for f in high:
    w(finding_row(f))
w("")
w("Triage notes for High:")
w("")
w("- **Likely intentional sanitization** (keep suppression, but make root cause reachable): "
  "`auth.py:1045`, `session_handoff.py:176` (JWE/crypto internals → generic HandoffRejected), "
  "`gemini.py:374` (redacted body), `openai_codex_provider.py:102` (auth renewal), "
  "`turn_runtime_shared.py:1300`. Recommended pattern: `logger.debug(\"…\", exc_info=True)` immediately "
  "before `raise ... from None`, so production debugging keeps the chain server-side.")
w("- **Likely accidental / low value suppression**: `app_update.py:388/418/435` (ValueError → "
  "VersionCheckError), `cron/service.py:141/170` + `cron_tool.py:51` (parse/lookup errors), "
  "`registry_edit.py:80`, `opencode_server.py:150`, `slack.py:123`, `auth.py:1105`. "
  "Recommended: replace `from None` with `from e` (or embed `e` and use `from e`).")
w("")

med = [f for f in fs if f["severity"] == "medium"]
w(f"### 🟡 Medium — {len(med)} (missing `from`; implicit `__context__` still preserves the chain)")
w("")
w("Dominant pattern: FastAPI routers converting caught domain errors to `HTTPException` without `from` "
  "(`raise HTTPException(status_code=…, detail=str(e))`). Server logs still show the implicit chain, but "
  "`__cause__` is unset and any handler that inspects `__cause__`/re-wraps loses the direct link.")
w("")
w("| Module | Count | Representative locations |")
w("|---|---|---|")
for mod, m in top_mods:
    mm = [f for f in med if ".".join(Path(f["path"]).parts[:2]) == mod or (len(Path(f["path"]).parts) <= 2)]
    if not mm:
        continue
    locs = ", ".join(f"`{f['path'].split('/', 1)[1]}:{f['line']}`" for f in mm[:6])
    more = f" …(+{len(mm) - 6})" if len(mm) > 6 else ""
    w(f"| `{mod}` | {len(mm)} | {locs}{more} |")
w("")
w("<details><summary>Full medium list (path:line, rule)</summary>")
w("")
w("```")
for f in med:
    tag = " [dedup:broad]" if "dedup" in f else ""
    w(f"{f['path']}:{f['line']}  {f['rule']}{tag}  {f['code'][:90]}")
w("```")
w("")
w("</details>")
w("")

low = [f for f in fs if f["severity"] == "low"]
w(f"### 🟢 Low — {len(low)} (recognized idioms; no action needed)")
w("")
for f in low:
    w(f"- `{f['path']}:{f['line']}` — {f['detail']}")
w("")
w("## Executable fix patterns")
w("")
w("```python")
w("# E1 — add the missing cause link")
w("except ValueError as e:")
w("    raise HTTPException(status_code=400, detail=str(e))          # before")
w("    raise HTTPException(status_code=400, detail=str(e)) from e   # after")
w("")
w("# E2 — accidental suppression: restore the chain")
w("except ValueError:")
w("    raise VersionCheckError(\"The latest release has an invalid version\") from None  # before")
w("except ValueError as e:")
w("    raise VersionCheckError(\"The latest release has an invalid version\") from e     # after")
w("")
w("# E2 — intentional sanitization (API boundary): keep from None, log the cause")
w("except (JWEError, JWSError):")
w("    logger.debug(\"handoff ticket rejected\", exc_info=True)       # server-side root cause")
w("    raise HandoffRejected(\"Invalid handoff ticket\") from None")
w("```")
w("")
w("## Method & limitations")
w("")
w("- Pure `ast` analysis; no code executed, no files modified.")
w("- A raise is attributed to a handler when it executes within the handler's dynamic scope "
  "(control-flow bodies included; nested handlers, nested function/class bodies excluded).")
w("- E1 severity assumes FastAPI-style re-wrapping; implicit `__context__` means nothing is silently "
  "swallowed by E1 findings — the gap is `__cause__` explicitness and tooling that reads it.")
w("- `from None` intent (sanitization vs accidental) cannot be proven from AST; the `logged` tag marks "
  "handlers that log before raising. Human triage recommended for the 16 High items.")
w("")

out = EVID / "report.md"
out.write_text("\n".join(L), encoding="utf-8")
print(f"wrote {out} ({len(L)} lines)")
