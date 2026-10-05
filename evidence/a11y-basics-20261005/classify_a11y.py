#!/usr/bin/env python3
"""Attach triage decisions and pattern attribution to raw scan findings.

Reads findings.json, writes a11y_classified.json with per-item:
  triage: issue | needs-review | non-issue
  pattern: for A2 items — setting-row | field-label | adjacent-label | bare-control
B1/B3 verified manually on 2026-10-05 (see report.md §5).
"""
import json
import os
import re
import sys

WEB = sys.argv[1] if len(sys.argv) > 1 else "wt/web"
BASE = os.path.dirname(os.path.abspath(__file__))


def file_src(rel):
    return open(os.path.join(WEB, rel), encoding="utf-8").read()


def main():
    raw = json.load(open(os.path.join(BASE, "findings.json")))
    out = []
    for f in raw["findings"]:
        f = dict(f)
        cat = f["category"]
        if cat == "B1-aria-hidden-focusable":
            f["triage"] = "non-issue"
            f["note"] = "隐藏文件输入惯用法：type=file + className hidden + tabIndex=-1 + aria-hidden，控件 display:none 不可聚焦，aria-hidden 合理"
        elif cat == "B3-broken-aria-ref":
            f["triage"] = "non-issue"
            f["note"] = "引用的 id 由模板字符串生成（id={`${item.id}-tab`}），运行时可解析，已人工核对 KnowledgeHome.tsx:280/309/415"
        elif cat == "A3-button-no-text":
            if f["tier"] == "review":
                f["triage"] = "needs-review"
                f["note"] = "内容由调用方变量决定（children/label/prop），运行时是否可访问名取决于用法，需逐处确认"
            else:
                f["triage"] = "issue"
                f["note"] = "纯图标按钮且无 aria-label/aria-labelledby/title，屏幕阅读器无可访问名（WCAG 4.1.2）"
        elif cat == "A2-control-no-name":
            f["triage"] = "issue"
            src = file_src(f["file"])
            if "SettingRow" in src:
                f["pattern"] = "setting-row"
                f["note"] = "SettingRow 的 title 渲染在普通 div 中，与 control 无 htmlFor/id 关联（components/settings/shared.tsx:141-165）"
            elif "FieldLabel" in src:
                f["pattern"] = "field-label"
                f["note"] = "FieldLabel 兄弟组件渲染可见 label，但未与控件建立 htmlFor/id 关联"
            elif re.search(r"<label(?![^>]*htmlFor)[^>]*>", src):
                f["pattern"] = "adjacent-label"
                f["note"] = "存在可见 <label>（无 htmlFor），控件无 id，视觉 label 未程序化关联（WCAG 1.3.1/4.1.2）"
            else:
                f["pattern"] = "bare-control"
                f["note"] = "控件仅有 placeholder/无任何名称来源（WCAG 4.1.2；placeholder 不作为可靠可访问名）"
        elif cat == "A4-heading-skip":
            f["triage"] = "issue"
            f["note"] = "同文件源码顺序标题跳级（h1→h3），区块标题应为 h2（WCAG 章节层级最佳实践，LOW）"
        else:
            f["triage"] = "issue"
        out.append(f)
    with open(os.path.join(BASE, "a11y_classified.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    import collections
    c = collections.Counter((f["category"], f.get("triage")) for f in out)
    for k in sorted(c):
        print(k, c[k])
    p = collections.Counter(f.get("pattern") for f in out if f["category"] == "A2-control-no-name")
    print("A2 patterns:", dict(p))


if __name__ == "__main__":
    main()
