#!/usr/bin/env python3
"""Triage scorer for web zero-test modules (AGEN-1181).

Ranks zero-status modules under components/hooks/lib by
  score = density(loc) * testability_factor
  density(loc) = log10(loc + 10)                 (same convention as the
                web-test-gaps-20261007 Top10: bigger module = more logic)
and assigns a deterministic per-module recommendation.

Signals are computed from source text at the given web root (read-only).
Dedup facts:
  - CARD_KEYS: modules already carded from this batch (board review 2026-10-08)
  - now-covered: origin/main tests reference the module by path (scan's
    non-meta vitest/node path_ref rule re-applied at current HEAD)

Usage:
  python3 triage_score.py --web-root <web dir> \
      --summary input_summary.json --out triage_top60.json [--limit 60]

Same inputs -> same output bytes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

POOL_CATS = ("components", "hooks", "lib")

RE_SERVER = re.compile(
    r"[\"']use server[\"']|from ['\"](node:[a-z]+|fs|path|os|crypto|child_process|next/server)['\"]"
)
RE_BROWSER = re.compile(
    r"\b(window\.|document\.|localStorage|sessionStorage|navigator\.|matchMedia"
    r"|ResizeObserver|IntersectionObserver|MutationObserver|addEventListener"
    r"|requestAnimationFrame|getBoundingClientRect|HTMLElement|Audio|WebSocket|MediaRecorder)"
)
RE_REACT = re.compile(r"from ['\"]react(/dom)?['\"]")
RE_HOOKNAME = re.compile(r"^use([-_][a-z0-9]+|[A-Z].*)$")
RE_JSX = re.compile(r"(<\/[A-Za-z]|<[A-Z][A-Za-z0-9]*[\s/>])")
RE_LOGIC = re.compile(
    r"\b(useState|useReducer|useEffect|useMemo|useCallback|useRef|useContext)\b"
    r"|\bon(Click|Submit|Change|Close|Select|KeyDown|Scroll|Toggle|Focus|Blur)="
)
RE_FETCH = re.compile(r"\bfetch\(")

META_TESTS = {
    "architecture-contracts.test.ts",
    "no-page-module-imports.test.ts",
    "no-unified-chat-context.test.ts",
    "no-v1-chat-surface.test.ts",
    "internal-route-contract.test.ts",
    "generated-contracts.test.ts",
    "design-token-parity.test.ts",
    "tooling-config.test.ts",
    "i18n-audit.spec.ts",
    "i18n-placeholders.test.ts",
}

# Modules already carded from the web-test-gaps-20261007 harvest
# (board review 2026-10-08: AGEN-1156/1165-1170/1173/1188/1189).
CARD_KEYS = {
    "hooks/useDragSort.ts": "AGEN-1156",
    "lib/code-languages.ts": "AGEN-1165",
    "lib/latex-commands.ts": "AGEN-1166",
    "lib/quiz-judge.ts": "AGEN-1167",
    "lib/personas-api.ts": "AGEN-1168",
    "lib/research-types.ts": "AGEN-1169",
    "lib/session-unread.ts": "AGEN-1170",
    "lib/youtube-iframe-api.ts": "AGEN-1173",
    "components/memory/MemoryGraph.tsx": "AGEN-1189",
    "components/memory/MemoryRunPanel.tsx": "AGEN-1189",
    "components/memory/MemorySection.tsx": "AGEN-1188",
    "components/memory/MemoryWorkbench.tsx": "AGEN-1188",
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def strip_comments(t: str) -> str:
    """Conservative comment removal so signal regexes see code only.

    - block comments /* ... */ removed
    - line comments removed at the first '//' not preceded by ':'
      (so URLs like https:// survive); occurrences inside string
      literals are a documented, accepted approximation
    """
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    out = []
    for ln in t.splitlines():
        m = re.search(r"(?<!:)//", ln)
        if m:
            ln = ln[: m.start()]
        out.append(ln)
    return "\n".join(out)


def signals(web: Path, rel: str) -> dict | None:
    p = web / rel
    if not p.is_file():
        return None
    raw = read(p)
    t = strip_comments(raw)
    # type-only imports don't create runtime react coupling
    t_code = re.sub(r"^\s*import\s+type[^;]*;?\s*$", "", t, flags=re.M)
    stem = p.name.rsplit(".", 1)[0]
    is_index = stem == "index"
    return {
        "loc": len(raw.splitlines()),
        "server": bool(RE_SERVER.search(t)),
        "browser": bool(RE_BROWSER.search(t)),
        "react": bool(RE_REACT.search(t_code)),
        "jsx": p.suffix == ".tsx" and bool(RE_JSX.search(t)),
        "is_hook": bool(RE_HOOKNAME.match(stem)),
        "logic": bool(RE_LOGIC.search(t)),
        "fetch": bool(RE_FETCH.search(t)),
        "is_index": is_index,
    }


def factor(sig: dict) -> tuple[float, str]:
    """Returns (testability_factor, signal label)."""
    if sig["server"]:
        return 0.30, "server-bound"
    if sig["is_index"] and not (sig["logic"] or sig["jsx"]):
        return 0.30, "barrel"
    if sig["jsx"]:
        if sig["logic"] or sig["loc"] >= 60:
            return 0.50, "component-logic"
        return 0.50, "component-presentational"
    if sig["is_hook"] or sig["react"]:
        return 0.85, "hook/react"
    if sig["browser"] or sig["fetch"]:
        return 0.80, "browser/fetch"
    return 1.00, "pure-logic"


def recommend(sig: dict, label: str, done: str | None) -> str:
    if done:
        return f"DONE - {done}"
    if label == "barrel":
        return "放弃（barrel 再导出面，无独立逻辑；覆盖随成员模块）"
    if label == "server-bound":
        return "移交 e2e/集成（server 侧行为，jsdom 单测不适用）"
    if label == "pure-logic":
        return "单测（纯函数/表映射，直接断言）"
    if label == "hook/react":
        return "单测（renderHook：状态机 + 清理语义）"
    if label == "browser/fetch":
        return "单测（jsdom mock 浏览器/fetch 依赖）"
    if label == "component-logic":
        return "渲染测（testing-library：状态与交互分支）"
    # component-presentational
    if sig["loc"] < 30:
        return "放弃（<30 行纯标记组件，单测价值低）"
    return "移交 e2e（纯展示组件，靠页面冒烟覆盖）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-root", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    web = Path(args.web_root).resolve()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    pool = [z for z in summary["zero"] if z["category"] in POOL_CATS]

    # covered-now check: re-apply the scan's path_ref rule over tests at
    # this web root, but split stub refs (vi.mock) from behavioral refs.
    RE_VI_MOCK = re.compile(r"vi\.mock\(\s*[\"']")
    RE_TYPE_IMPORT = re.compile(r"\bimport\s+type\b")
    test_files = []
    tests_dir = web / "tests"
    if tests_dir.is_dir():
        for p in sorted(tests_dir.rglob("*")):
            if not p.is_file() or p.name in META_TESTS:
                continue
            if p.name.endswith((".spec.ts", ".spec.tsx", ".test.ts")):
                test_files.append(
                    (p.relative_to(web).as_posix(), read(p).splitlines())
                )

    def coverage(match_key: str) -> tuple[bool, str]:
        behavioral, stubs = [], []
        for tpath, lines in test_files:
            for ln in lines:
                if match_key not in ln:
                    continue
                if RE_VI_MOCK.search(ln) or RE_TYPE_IMPORT.search(ln):
                    stubs.append(tpath)
                else:
                    behavioral.append(tpath)
                    break
        if behavioral:
            uniq = sorted(set(behavioral))
            shown = ", ".join(uniq[:2]) + ("…" if len(uniq) > 2 else "")
            return True, f"已覆盖（行为引用：{shown}）"
        if stubs:
            uniq = sorted(set(stubs))
            shown = ", ".join(uniq[:2]) + ("…" if len(uniq) > 2 else "")
            return False, f"现有测试仅 vi.mock 桩/类型引用（{shown}）"
        return False, ""

    rows = []
    missing = []
    for z in pool:
        rel = z["path"]
        sig = signals(web, rel)
        if sig is None:
            missing.append(rel)
            continue
        f, label = factor(sig)
        stem_is_index = Path(rel).stem == "index"
        match_key = str(Path(rel).parent) if stem_is_index else str(Path(rel).with_suffix(""))
        covered, cover_note = coverage(match_key)
        done = None
        if rel in CARD_KEYS:
            done = f"已建卡 {CARD_KEYS[rel]}"
            if covered:
                done += "；" + cover_note
        elif covered:
            done = f"origin/main {cover_note}"
        stub_only = cover_note.startswith("现有测试仅 vi.mock")
        rows.append(
            {
                "path": rel,
                "category": z["category"],
                "scan_loc": z["loc"],
                "head_loc": sig["loc"],
                "factor": f,
                "signal": label,
                "score": round(math.log10(sig["loc"] + 10) * f, 3),
                "done": done,
                "stub_only": stub_only,
                "recommendation": recommend(sig, label, done)
                + ("；注意：现有引用均为 vi.mock 桩" if stub_only else ""),
            }
        )

    rows.sort(key=lambda r: (-r["score"], r["path"]))
    head = {k: v for k, v in summary.get("totals", {}).items()}
    out = {
        "scan": "web-zero-triage (AGEN-1181)",
        "input_summary": Path(args.summary).name,
        "web_root_head_files": True,
        "formula": "score = log10(loc+10) * factor; sort (-score, path)",
        "factors": {
            "pure-logic": 1.00,
            "hook/react": 0.85,
            "browser/fetch": 0.80,
            "component-logic (tsx with state/handlers or loc>=60)": 0.50,
            "component-presentational (tsx markup only)": 0.50,
            "barrel (index without own logic)": 0.30,
            "server-bound (node/next-server/use server)": 0.30,
        },
        "pool_counts": {
            c: sum(1 for r in rows if r["category"] == c) + 0 for c in POOL_CATS
        },
        "pool_zero_total_scan": len(pool),
        "missing_at_head": missing,
        "rows": rows,
    }
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    top = rows[: args.limit]
    done_n = sum(1 for r in top if r["done"])
    print(
        f"pool={len(pool)} scored={len(rows)} missing={len(missing)} "
        f"top{args.limit}: done={done_n} new_seeds={args.limit - done_n}"
    )
    for i, r in enumerate(top, 1):
        mark = f" [{r['done']}]" if r["done"] else ""
        print(f"{i:2d}. {r['score']:.3f} {r['path']} ({r['head_loc']}L, {r['signal']}){mark}")


if __name__ == "__main__":
    main()
