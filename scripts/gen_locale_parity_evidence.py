#!/usr/bin/env python3
"""Verify web locale key parity for the v1.6.13..v1.6.14 window (AGEN-1807).

Read-only analysis: compares web/locales/{de,en,fr,pl,uk,zh}/app.json
between tag v1.6.13 and HEAD (v1.6.14), then emits an evidence bundle.
"""
import csv
import hashlib
import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path("/tmp/multica-task-3411011787/opencode/dt-agen1807-parity-wt")
BASE = "v1.6.13"
HEAD = "HEAD"
LANGS = ["de", "en", "fr", "pl", "uk", "zh"]
OUT = REPO / "evidence" / "verify-web-locale-parity-20261011"


def load(ref: str, lang: str) -> OrderedDict:
    raw = subprocess.run(
        ["git", "show", f"{ref}:web/locales/{lang}/app.json"],
        capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout
    return json.loads(raw, object_pairs_hook=OrderedDict)


def flat(d, prefix=""):
    out = OrderedDict()
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flat(v, p))
        else:
            out[p] = v
    return out


def main():
    cur, prev = {}, {}
    for lang in LANGS:
        cur[lang] = flat(load(HEAD, lang))
        prev[lang] = flat(load(BASE, lang))

    en_c, en_p = cur["en"], prev["en"]

    # Window key set: added or value-changed in en (source of truth)
    added_en = [k for k in en_c if k not in en_p]
    removed_en = [k for k in en_p if k not in en_c]
    changed_en = [k for k in en_c if k in en_p and en_p[k] != en_c[k]]
    window_keys = sorted(set(added_en) | set(changed_en))

    # Per-language window diff (context: which langs moved in the window)
    per_lang_diff = {}
    for lang in LANGS:
        c, p = cur[lang], prev[lang]
        per_lang_diff[lang] = {
            "added": sorted(k for k in c if k not in p),
            "removed": sorted(k for k in p if k not in c),
            "changed": sorted(k for k in c if k in p and p[k] != c[k]),
        }

    # Matrix rows: window key × language × status
    rows = []
    for key in window_keys:
        en_val = en_c[key]
        for lang in LANGS:
            c, p = cur[lang], prev[lang]
            present = key in c
            if not present:
                status = "missing"
            elif lang != "en" and str(c[key]).strip() == "":
                status = "placeholder_empty"
            elif lang != "en" and c[key] == en_val:
                status = "placeholder_same_as_en"
            elif key not in p:
                status = "added_in_window"
            elif p[key] != c[key]:
                status = "changed_in_window"
            else:
                status = "carried_over"
            rows.append({
                "key": key,
                "lang": lang,
                "status": status,
                "value_preview": (str(c[key])[:120] if present else ""),
            })

    # Full-file parity at HEAD (context beyond the window)
    snapshot = {}
    for lang in LANGS:
        c = cur[lang]
        snapshot[lang] = {
            "total_keys": len(c),
            "missing_vs_en": sorted(k for k in en_c if k not in c),
            "extra_vs_en": sorted(k for k in c if k not in en_c),
            "same_value_as_en_non_en": sorted(
                k for k in c if lang != "en" and k in en_c and c[k] == en_c[k]
            ),
            "empty_value": sorted(k for k in c if str(c[k]).strip() == ""),
        }

    OUT.mkdir(parents=True, exist_ok=True)

    # --- key-matrix.csv ---
    with open(OUT / "key-matrix.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["key", "lang", "status", "value_preview"])
        w.writeheader()
        w.writerows(rows)

    # --- key-matrix.md ---
    lines = [
        "# v1.6.13 → v1.6.14 window locale key matrix",
        "",
        f"- window: {BASE}..{HEAD} ({'origin/main'} = 6cf793bd8 'release: v1.6.14')",
        f"- window key set (added or value-changed in en): {len(window_keys)} keys",
        f"- en keys added: {len(added_en)}, changed: {len(changed_en)}, removed: {len(removed_en)}",
        "",
        "| key | en action | " + " | ".join(f"{l}" for l in LANGS) + " |",
        "|---|---|" + "---|" * len(LANGS),
    ]

    def cell(key, lang):
        r = next(x for x in rows if x["key"] == key and x["lang"] == lang)
        return r["status"]

    for key in window_keys:
        action = "added" if key in set(added_en) else "changed"
        lines.append(
            f"| `{key}` | {action} | " + " | ".join(cell(key, l) for l in LANGS) + " |"
        )
    lines.append("")
    (OUT / "key-matrix.md").write_text("\n".join(lines), encoding="utf-8")

    # --- missing-keys-by-language.md / .json ---
    gap = OrderedDict()
    for lang in LANGS:
        miss_window = sorted(
            r["key"] for r in rows if r["lang"] == lang and r["status"] == "missing"
        )
        ph_empty = sorted(
            r["key"] for r in rows if r["lang"] == lang and r["status"] == "placeholder_empty"
        )
        ph_same = sorted(
            r["key"] for r in rows if r["lang"] == lang and r["status"] == "placeholder_same_as_en"
        )
        gap[lang] = {
            "missing_in_window_keys": miss_window,
            "placeholder_empty_in_window_keys": ph_empty,
            "placeholder_same_as_en_in_window_keys": ph_same,
            "missing_vs_en_full_file": snapshot[lang]["missing_vs_en"],
            "extra_vs_en_full_file": snapshot[lang]["extra_vs_en"],
            "empty_value_full_file": snapshot[lang]["empty_value"],
        }
    with open(OUT / "missing-keys-by-language.json", "w", encoding="utf-8") as f:
        json.dump(gap, f, ensure_ascii=False, indent=2)

    ml = ["# 缺失/占位键补齐清单（按语言）", ""]
    for lang in LANGS:
        g = gap[lang]
        ml.append(f"## {lang}")
        ml.append(f"- 窗口键缺失: {len(g['missing_in_window_keys'])}")
        ml.append(f"- 窗口键占位(空值): {len(g['placeholder_empty_in_window_keys'])}")
        ml.append(f"- 窗口键占位(与 en 相同): {len(g['placeholder_same_as_en_in_window_keys'])}")
        ml.append(f"- 全文件 vs en 缺失: {len(g['missing_vs_en_full_file'])}")
        ml.append(f"- 全文件 vs en 多余(孤儿键): {len(g['extra_vs_en_full_file'])}")
        ml.append(f"- 全文件空值: {len(g['empty_value_full_file'])}")
        for title, keys in (
            ("missing (window)", g["missing_in_window_keys"]),
            ("placeholder-empty (window)", g["placeholder_empty_in_window_keys"]),
            ("placeholder-same-as-en (window)", g["placeholder_same_as_en_in_window_keys"]),
        ):
            if keys:
                ml.append(f"\n### {title}")
                ml.extend(f"- `{k}`" for k in keys)
        ml.append("")
    (OUT / "missing-keys-by-language.md").write_text("\n".join(ml), encoding="utf-8")

    # --- full-parity-snapshot.md ---
    sl = [
        "# v1.6.14 全量奇偶快照（窗口外上下文）",
        "",
        "| lang | total | missing vs en | extra vs en | same-as-en | empty |",
        "|---|---|---|---|---|---|",
    ]
    for lang in LANGS:
        s = snapshot[lang]
        sl.append(
            f"| {lang} | {s['total_keys']} | {len(s['missing_vs_en'])} "
            f"| {len(s['extra_vs_en'])} | {len(s['same_value_as_en_non_en']) if lang != 'en' else 'n/a'} "
            f"| {len(s['empty_value'])} |"
        )
    (OUT / "full-parity-snapshot.md").write_text("\n".join(sl), encoding="utf-8")

    # --- per-lang window diff summary (context) ---
    dl = ["# 各语言窗口内增/删/改（上下文）", ""]
    for lang in LANGS:
        d = per_lang_diff[lang]
        dl.append(f"- {lang}: added={len(d['added'])} removed={len(d['removed'])} changed={len(d['changed'])}")
    (OUT / "per-lang-window-diff.md").write_text("\n".join(dl), encoding="utf-8")

    # --- README.md ---
    n_missing = sum(len(gap[l]["missing_in_window_keys"]) for l in LANGS if l != "en")
    n_ph = sum(
        len(gap[l]["placeholder_empty_in_window_keys"]) + len(gap[l]["placeholder_same_as_en_in_window_keys"])
        for l in LANGS if l != "en"
    )
    readme = f"""# verify: v1.6.14 窗口 web locale 键六语言奇偶复核 (AGEN-1807)

- 仓库基线: HKUDS/DeepTutor origin/main = 6cf793bd8 (`release: v1.6.14`)，窗口 v1.6.13..v1.6.14（96 commits）
- 锚点合并: 849ab2871 (#1310 reading workspace panels), 64bc0d8e7 (#1407 workspace journal overview) 均在窗口内
- 只读复核，不改源码

## 结论
- en 窗口新增键 {len(added_en)}，变更值键 {len(changed_en)}，删除键 {len(removed_en)}；窗口键集合共 {len(window_keys)}
- 6 语言窗口键缺失合计（不含 en）：{n_missing}
- 窗口键占位翻译（空值或与 en 完全相同，不含 en）：{n_ph}
- 全文件级孤儿键（语言有、en 无）：fr={len(snapshot['fr']['extra_vs_en'])} pl={len(snapshot['pl']['extra_vs_en'])} de={len(snapshot['de']['extra_vs_en'])} uk={len(snapshot['uk']['extra_vs_en'])} zh={len(snapshot['zh']['extra_vs_en'])}

## 文件
- key-matrix.md / key-matrix.csv — 窗口键 × 语言 × 状态矩阵
- missing-keys-by-language.md / .json — 可直接补齐的键名清单（含全文件级缺失/多余/空值）
- full-parity-snapshot.md — v1.6.14 全量奇偶快照
- per-lang-window-diff.md — 各语言窗口内增删改计数

复跑命令: `python3 scripts/gen_locale_parity_evidence.py`（在本 worktree 内）

## 详细结论
1. **fr 是唯一有窗口键缺失的语言**：63 个窗口键缺失（全部在 zh/de 已有翻译，属 fr 滞后，非新特性只写了 en）。
   - 其中含 visualCoverage.* 7 键、reading/learning journal、索引恢复、private MCP origins 等窗口新特性文案。
   - 全文件级 fr vs en：缺失 529、多余 909（多为旧版英文文案键的历史漂移，含 8 个 `_few/_many` 复数键）；窗口外差异属既有欠账，修复卡 fix-web-locales-parity / fix-web-locales-fr-dir-gap 未合入 main，故 main 仍存在缺口。
2. **窗口键占位翻译（低优先级）**：
   - fr `settings.providerServices.filter.imagegen` = `"Images"`（与 en 相同）
   - de `settings.providerServices.filter.videogen` = `"Video"`（与 en 相同）
   - 两者为 Images/Video 这类可保留原文的词，是否补译由人决定。
3. **pl/uk 的 16 个"多余键"为合法复数形式**（`_few`/`_many`，对应 en 的 `_one`/`_other`），非孤儿键，无需处理。
4. **zh 遗留空值键** `"s"` = `""`：v1.6.13 之前就存在（100ae2710 引入），非窗口键，属历史遗留。
5. **kanban.footer（窗口内唯一 en 变更值键）**：6 语言均已同步新译，无欠账。

## 补齐清单优先级
- P1：fr 补 63 个窗口缺失键（见 missing-keys-by-language.md 的 fr 段落）
- P2（可选）：fr/de 各 1 个占位键复核是否补译
- 无需处理：pl/uk 复数键、zh 遗留 `"s"` 键
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(f"window keys: {len(window_keys)} (en added={len(added_en)} changed={len(changed_en)} removed={len(removed_en)})")
    print(f"missing (window, non-en): {n_missing}")
    print(f"placeholder (window, non-en): {n_ph}")
    for lang in LANGS:
        g = gap[lang]
        print(f"  {lang}: miss_window={len(g['missing_in_window_keys'])} ph_empty={len(g['placeholder_empty_in_window_keys'])} ph_same={len(g['placeholder_same_as_en_in_window_keys'])} miss_full={len(g['missing_vs_en_full_file'])} extra_full={len(g['extra_vs_en_full_file'])} empty_full={len(g['empty_value_full_file'])}")


if __name__ == "__main__":
    sys.exit(main())
