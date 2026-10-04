#!/usr/bin/env python3
"""Apply AGEN-520 classification on top of console_findings.json.

Types:
  reasonable_degrade  合理降级日志 — failure-path logging that accompanies a
                      real fallback, a user-visible error state, or is the
                      designed output of a CLI/test/doc surface.
  debug_leftover      调试残留 — dev-debug console.log/debug payloads,
                      debugger statements, commented-out debug blocks.
  swallow_substitute  吞错替代品 — console.* is the ONLY handling of a
                      failure; the user gets no feedback and the failure is
                      invisible (console substitutes for real error state).

Writes console_classified.json (63 items, authoritative for the report).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = json.loads((HERE / "console_findings.json").read_text())

# key: (file, line) -> (type, severity, reason_zh, suggestion_zh)
CLASSIFIED = {
    # --- web/scripts/*: CLI tool output (console IS the interface) ---
    ("web/scripts/route_budgets.mjs", 162): ("reasonable_degrade", "LOW",
        "CLI 预算报表行输出，脚本的设计输出通道", "保留"),
    ("web/scripts/route_budgets.mjs", 191): ("reasonable_degrade", "LOW",
        "CLI 报表标题输出", "保留"),
    ("web/scripts/route_budgets.mjs", 207): ("reasonable_degrade", "LOW",
        "CLI 顶层错误输出并以 exitCode=1 退出", "保留"),
    ("web/scripts/i18n_audit.mjs", 130): ("reasonable_degrade", "LOW",
        "CLI 校验失败报告 + exitCode=1", "保留"),
    ("web/scripts/i18n_audit.mjs", 143): ("reasonable_degrade", "LOW",
        "CLI 校验失败报告 + exitCode=1", "保留"),
    ("web/scripts/i18n_audit.mjs", 180): ("reasonable_degrade", "LOW",
        "CLI 审计进度输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 182): ("reasonable_degrade", "LOW",
        "CLI 字面量缺失报告 + exitCode=1", "保留"),
    ("web/scripts/i18n_audit.mjs", 186): ("reasonable_degrade", "LOW",
        "CLI 覆盖率报表输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 193): ("reasonable_degrade", "LOW",
        "CLI 覆盖率阈值失败报告 + exitCode=1", "保留"),
    ("web/scripts/i18n_audit.mjs", 199): ("reasonable_degrade", "LOW",
        "CLI --show-missing 明细输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 200): ("reasonable_degrade", "LOW",
        "CLI --show-missing 明细输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 206): ("reasonable_degrade", "LOW",
        "CLI 插值占位符不匹配报告 + exitCode=1", "保留"),
    ("web/scripts/i18n_audit.mjs", 208): ("reasonable_degrade", "LOW",
        "CLI 插值占位符明细输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 233): ("reasonable_degrade", "LOW",
        "CLI 通过结论输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 237): ("reasonable_degrade", "LOW",
        "CLI 发现数汇总输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 240): ("reasonable_degrade", "LOW",
        "CLI 逐文件明细输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 243): ("reasonable_degrade", "LOW",
        "CLI 逐条明细输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 246): ("reasonable_degrade", "LOW",
        "CLI 截断提示输出", "保留"),
    ("web/scripts/i18n_audit.mjs", 249): ("reasonable_degrade", "LOW",
        "CLI 截断提示输出", "保留"),
    ("web/scripts/i18n_parity.mjs", 39): ("reasonable_degrade", "LOW",
        "CLI 目录缺失报告 + exitCode=2", "保留"),
    ("web/scripts/i18n_parity.mjs", 52): ("reasonable_degrade", "LOW",
        "CLI 缺失文件报告", "保留"),
    ("web/scripts/i18n_parity.mjs", 53): ("reasonable_degrade", "LOW",
        "CLI 缺失文件明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 57): ("reasonable_degrade", "LOW",
        "CLI 多余文件报告", "保留"),
    ("web/scripts/i18n_parity.mjs", 58): ("reasonable_degrade", "LOW",
        "CLI 多余文件明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 75): ("reasonable_degrade", "LOW",
        "CLI key 不匹配报告", "保留"),
    ("web/scripts/i18n_parity.mjs", 77): ("reasonable_degrade", "LOW",
        "CLI 缺失 key 明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 78): ("reasonable_degrade", "LOW",
        "CLI 缺失 key 明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 81): ("reasonable_degrade", "LOW",
        "CLI 多余 key 明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 82): ("reasonable_degrade", "LOW",
        "CLI 多余 key 明细", "保留"),
    ("web/scripts/i18n_parity.mjs", 88): ("reasonable_degrade", "LOW",
        "CLI 通过结论输出", "保留"),
    ("web/scripts/generate-contracts.mjs", 78): ("reasonable_degrade", "LOW",
        "生成契约漂移报告（--check 模式）", "保留"),
    ("web/scripts/generate-contracts.mjs", 83): ("reasonable_degrade", "LOW",
        "生成结果确认输出", "保留"),
    ("web/scripts/probe-right-edge.mjs", 21): ("reasonable_degrade", "LOW",
        "开发探针脚本的完成输出（一次性手工工具）", "保留"),
    ("web/scripts/build-brand-icons.mts", 34): ("reasonable_degrade", "LOW",
        "构建脚本 slug 缺失失败报告", "保留"),
    ("web/scripts/build-brand-icons.mts", 100): ("reasonable_degrade", "LOW",
        "构建脚本产物汇总输出", "保留"),
    ("web/scripts/run-node-tests.mjs", 51): ("reasonable_degrade", "LOW",
        "测试 runner 错误输出 + exit 1", "保留"),
    ("web/scripts/build.mjs", 124): ("reasonable_degrade", "LOW",
        "构建脚本错误转发 + exit 1", "保留"),
    ("web/scripts/typecheck.mjs", 49): ("reasonable_degrade", "LOW",
        "typecheck 包装器错误转发 + exit 1", "保留"),
    # --- tests infra ---
    ("web/tests/setup/rendered.ts", 73): ("reasonable_degrade", "LOW",
        "测试基建：保存原 console.error 引用用于 spy/过滤 act 警告，非调用",
        "保留"),
    # --- non-code mentions ---
    ("web/lib/iframe-html.ts", 22, "error"): ("reasonable_degrade", "LOW",
        "沙箱 iframe 内联脚本中的 KaTeX 渲染失败日志（throwOnError:false 降级设计，iframe 内无其他上报通道）",
        "保留；如需采集可在 postMessage 协议中加错误通道"),
    ("web/lib/iframe-html.ts", 22, "warn"): ("reasonable_degrade", "LOW",
        "同上：KaTeX 初始化超时 warn", "保留"),
    ("web/lib/latex-commands.ts", 14): ("reasonable_degrade", "LOW",
        "文档注释中的来源命令示例（说明清单如何生成），非注释掉的调试代码",
        "保留"),
    ("web/lib/brand-slugs.ts", 83): ("reasonable_degrade", "LOW",
        "普通注释文本含 \"debugger\" 字样（指 LLVM 调试器），非调试语句",
        "保留"),
    # --- product code: reasonable ---
    ("web/app/(workspace)/learning/books/BooksRoute.tsx", 184): (
        "reasonable_degrade", "LOW",
        "guard() 统一 catch：已有 error toast 用户可见反馈，console.error 为并发留痕",
        "保留"),
    ("web/app/(workspace)/learning/books/BooksRoute.tsx", 476): (
        "reasonable_degrade", "LOW",
        "深链打开失败：toast + 退回书架，双通道处理，console 仅留痕",
        "保留"),
    ("web/app/(workspace)/learning/books/BooksRoute.tsx", 663): (
        "reasonable_degrade", "LOW",
        "编译失败：toast + 重载书详情，console 仅留痕", "保留"),
    ("web/app/(workspace)/learning/books/BooksRoute.tsx", 785): (
        "reasonable_degrade", "LOW",
        "块再生成失败：toast + finally 重水化，console 仅留痕", "保留"),
    ("web/components/Geogebra.tsx", 173): ("reasonable_degrade", "LOW",
        "逐命令失败收集进 failures 并经 setCommandErrors 呈现，warn 为细粒度诊断",
        "保留"),
    ("web/components/Geogebra.tsx", 177): ("reasonable_degrade", "LOW",
        "同上（异常路径）", "保留"),
    ("web/context/GeogebraTabContext.tsx", 57): ("reasonable_degrade", "LOW",
        "带设计注释的 no-op CTA：用户可重试，warn 合理", "保留"),
    ("web/features/chat/ChatStateAdapter.tsx", 2261): ("reasonable_degrade",
        "LOW",
        "WS 连接重试耗尽：dispatch failed STREAM_END + toast 双通道，console 留痕",
        "保留"),
    ("web/features/chat/ChatStateAdapter.tsx", 2412): ("reasonable_degrade",
        "LOW",
        "消息 trace（开发者诊断视图）加载失败降级，主聊天不受影响，AbortError 已排除",
        "保留"),
    ("web/features/chat/ChatStateAdapter.tsx", 3582): ("reasonable_degrade",
        "LOW",
        "fire-and-forget 持久化分支选择，注释明确本地态为 UI 真相源，warn 留痕",
        "保留"),
    ("web/features/chat/components/ChatWorkspace.tsx", 917): (
        "reasonable_degrade", "LOW",
        "重命名失败：setSessionTitleError + 聚焦输入框，用户可见，console 留痕",
        "保留"),
    ("web/features/settings/store/SettingsStore.tsx", 832): (
        "reasonable_degrade", "LOW",
        "设置加载失败：setSettingsError 进入错误 UI + 解除骨架门，console 留痕",
        "保留"),
    ("web/features/settings/store/SettingsStore.tsx", 845): (
        "reasonable_degrade", "LOW",
        "系统状态加载失败：条件性 setSettingsError（避免掩盖设置本身错误），注释明确",
        "保留"),
    # --- product code: swallow_substitute (console 是唯一处理，用户无感知) ---
    ("web/app/(workspace)/learning/books/BooksRoute.tsx", 244): (
        "swallow_substitute", "MEDIUM",
        "hydratePage 失败仅 console.error：编辑/再生成后 finally 重水化失败时页面停留旧内容，用户误以为已是最新",
        "行内 toast「页面刷新失败，请重试」；保留 console.error"),
    ("web/features/chat/ChatStateAdapter.tsx", 3620): (
        "swallow_substitute", "MEDIUM",
        "显式删除 turn 失败仅 console.error：dispatch 在成功后才执行，删除表现为点了没反应",
        "notify toast「删除失败，请重试」；保留 console.error"),
    ("web/components/quiz/QuizViewer.tsx", 458): ("swallow_substitute",
        "MEDIUM",
        "测验成绩上报失败仅 console.error：signature 复位带来隐式重试但用户不可见，成绩可能未保存",
        "完成区显示「成绩保存失败」轻提示 + 手动重试入口"),
    ("web/components/sidebar/WorkspaceSidebar.tsx", 78): (
        "swallow_substitute", "MEDIUM",
        "会话列表加载失败仅 console.error：骨架消失后侧栏假空，与\"无会话\"不可区分",
        "错误态 + 重试入口；console.error 保留"),
    ("web/components/sidebar/UtilitySidebar.tsx", 65): ("swallow_substitute",
        "MEDIUM",
        "同 WorkspaceSidebar:78（同构代码）", "同 WorkspaceSidebar:78，两处一并修"),
    ("web/components/notebook/useNotebookSelection.ts", 49): (
        "swallow_substitute", "MEDIUM",
        "笔记本列表失败 console.error + setNotebooks([])：选择器假空，引用选择功能静默失效",
        "暴露 loadError 态供选择器渲染重试；console.error 保留"),
    ("web/components/notebook/useNotebookSelection.ts", 79): (
        "swallow_substitute", "LOW",
        "笔记本记录展开失败仅 console.error：loading 复位后内容区空白无提示",
        "行内「加载失败」提示 + 重试"),
}

TYPE_ZH = {
    "reasonable_degrade": "合理降级日志",
    "debug_leftover": "调试残留",
    "swallow_substitute": "吞错替代品",
}


def main():
    items = []
    for f in RAW["findings"]:
        key = (f["file"], f["line"])
        method_key = (f["file"], f["line"], f["method"])
        rule = CLASSIFIED.get(method_key) or CLASSIFIED.get(key)
        entry = dict(f)
        if rule:
            typ, sev, reason, fix = rule
            entry.update({
                "type": typ, "type_zh": TYPE_ZH[typ],
                "severity": sev, "reason": reason, "suggestion": fix,
            })
        else:
            entry.update({
                "type": "unclassified", "type_zh": "未分型",
                "severity": None, "reason": "", "suggestion": "",
            })
        items.append(entry)
    (HERE / "console_classified.json").write_text(
        json.dumps({"total": len(items), "items": items},
                   ensure_ascii=False, indent=2))
    print(f"classified {len(items)} items")


if __name__ == "__main__":
    main()
