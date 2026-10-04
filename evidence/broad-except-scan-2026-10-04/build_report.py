#!/usr/bin/env python3
"""Build classification.json and report.md from worklist + handwritten verdicts.

Verdicts are the manual read-only classification of every Appendix-A broad
except (plus 3 scan extras) into: reraise / narrowable / best_effort.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parents[1]

CAT_CN = {
    "reraise": "应上抛",
    "narrowable": "可收窄",
    "best_effort": "尽力而为语义",
}

# idx -> (category, reason, related_pr or None)
V = {
    0: ("best_effort", "错误路径内的进度收尾（写入 ERROR 进度），吞掉以免掩盖原始失败；PR #1706 已加 warning 日志", 1706),
    1: ("narrowable", "仅解析进度时间戳，datetime.fromisoformat 只会抛 ValueError；PR #1706 已收窄并记录", 1706),
    2: ("narrowable", "同上，时间戳解析失败面只有 ValueError；PR #1706 已收窄并记录", 1706),
    3: ("best_effort", "错误帧尽力送达已断开的 WS，失败即放弃；PR #1706 已加 debug 日志", 1706),
    4: ("best_effort", "finally 中关闭 WS 的清理动作；PR #1706 已加 debug 日志", 1706),
    5: ("best_effort", "WS 结束后重置用户上下文，清理尽力而为；PR #1706 已加 warning", 1706),
    6: ("best_effort", "终端回显是辅助通道（前端队列为主通道），吞掉不影响日志投递；建议收窄 (OSError, ValueError) + debug", None),
    7: ("best_effort", "错误消息尽力送达 WS，外层已 logger.exception 记录；建议收窄 WS 相关异常", None),
    8: ("best_effort", "元数据（embedding 签名/索引版本）尽力而为，代码注释明示；PR #1706 已加 error 日志", 1706),
    9: ("best_effort", "逐文件 mtime 记录尽力而为，但失败会破坏增量同步判据；PR #1706 已加 warning", 1706),
    10: ("reraise", "mark_failed 失败被吞则更新任务永久 pending 且无任何痕迹；至少必须记录（PR #1704 已改为记录双错误）", 1704),
    11: ("reraise", "失败恢复路径（标记失败+触发重启）整体静默，自更新失败无诊断线索；PR #1704 已部分覆盖（store.load 失败留痕），外层仍静默", 1704),
    12: ("best_effort", "进度回调是可选通知，失败不应中断嵌入主流程；PR #1703 已加 warning", 1703),
    13: ("best_effort", "同上；PR #1703 已加 warning", 1703),
    14: ("narrowable", "ts 已由 isinstance 限定为 str，fromisoformat 只抛 ValueError，收窄即可", None),
    15: ("best_effort", "注释明示 catalog 不可用时回退 legacy 配置的兜底语义；建议 debug 日志，否则可能静默用错 provider", None),
    16: ("best_effort", "图片进度回调尽力而为，失败不影响文档加载；PR #1703 已加 warning", 1703),
    17: ("narrowable", "清理空父目录只会抛 OSError；宽泛捕获会掩盖循环内逻辑 bug（如路径判断写错）", None),
    18: ("best_effort", "注释明示 tracking 失败不得影响主流程；建议收窄 + debug", None),
    19: ("best_effort", "WS 断开后的用户上下文清理", None),
    20: ("best_effort", "persona 读取失败即回退 admin 源，属回退链语义", None),
    21: ("best_effort", "回退链末端返回空串，由上层转 404", None),
    22: ("best_effort", "同 19，partner 会话收尾清理", None),
    23: ("best_effort", "flush 尽力而为，队列为主通道；建议收窄 (OSError, ValueError)", None),
    24: ("best_effort", "pusher 任务取消清理，CancelledError 已单独处理", None),
    25: ("best_effort", "退出前清空日志队列，尽力而为", None),
    26: ("best_effort", "finally 中关闭 WS 的清理动作", None),
    27: ("best_effort", "生成结束后重置用户上下文", None),
    28: ("best_effort", "日志投递回调尽力而为，失败不影响生成", None),
    29: ("best_effort", "异常路径收尾的用户上下文清理", None),
    30: ("best_effort", "quiz WS 错误路径的 close 清理", None),
    31: ("best_effort", "quiz WS 错误路径的上下文清理", None),
    32: ("best_effort", "quiz WS 缺 question 的 close 清理", None),
    33: ("best_effort", "quiz WS 缺 question 的上下文清理", None),
    34: ("best_effort", "quiz WS 无答案路径的 close 清理", None),
    35: ("best_effort", "quiz WS 无答案路径的上下文清理", None),
    36: ("best_effort", "quiz 流结束的 close 清理", None),
    37: ("best_effort", "quiz 流结束的上下文清理", None),
    38: ("narrowable", "URL 解析失败本就是 ValueError（noqa 注释亦说明）；收窄即可", None),
    39: ("narrowable", "设置文件损坏静默回退默认且无痕，用户配置无痕丢失；应收窄 (OSError, json.JSONDecodeError) 并 warning", None),
    40: ("narrowable", "导览缓存读取，收窄 (OSError, json.JSONDecodeError) + debug 即可", None),
    41: ("best_effort", "延迟加载工具定义失败不应破坏工具列表；建议 debug 记录被跳过的工具名", None),
    42: ("best_effort", "多工作区候选扫描，单个失败跳过；建议 debug 记录，否则断点续读静默失效不可知", None),
    43: ("best_effort", "advisory 对比行读取失败即跳过（noqa 注释明示）", None),
    44: ("best_effort", "advisory 引导提示，失败不阻塞主流程（noqa 明示）", None),
    45: ("best_effort", "首启标记写入尽力而为，失败仅导致下次重复提示", None),
    46: ("best_effort", "样式名仅影响 Markdown 呈现细节，失败返回空串", None),
    47: ("best_effort", "字体/删除线提示失败降级为普通文本", None),
    48: ("best_effort", "解析失败的表格行跳过；PR #1700 改为保留占位行并 warning", 1700),
    49: ("best_effort", "集中配置读取失败回退首个 KB，属回退语义", None),
    50: ("best_effort", "raw 文件计数属展示信息；建议收窄 OSError + debug", None),
    51: ("best_effort", "images 计数同上", None),
    52: ("best_effort", "content_list 计数同上", None),
    53: ("best_effort", "IMAP logout 清理；建议收窄 (OSError, imaplib.IMAP4.error) + debug", None),
    54: ("best_effort", "typing 指示器纯装饰，失败无功能影响", None),
    55: ("best_effort", "停机时 socket 断开清理", None),
    56: ("best_effort", "连接失败后的 disconnect 清理，外层已 logger.error", None),
    57: ("best_effort", "napcat 停机 ws 关闭清理", None),
    58: ("best_effort", "napcat 停机 http 关闭清理", None),
    59: ("best_effort", "QQ 客户端关闭清理", None),
    60: ("best_effort", "打字预览是体验增强，正式发送紧随其后；建议收窄 telegram 异常 + debug", None),
    61: ("best_effort", "zulip 退订清理", None),
    62: ("best_effort", "typing 停止清理", None),
    63: ("best_effort", "单个材料源不可用即跳过（注释明示），属来源枚举语义；建议 debug 计数", None),
    64: ("best_effort", "单个 unit 读取失败跳过该引用", None),
    65: ("best_effort", "单例重置尽力而为；PR #1704 已改为 logger.exception 记录", 1704),
    66: ("best_effort", "同上；PR #1704 已改为 logger.warning 记录", 1704),
    67: ("best_effort", "同上；PR #1704 已改为 logger.warning 记录", 1704),
    68: ("best_effort", "SIGTERM 发送尽力而为，超时后另有 KILL 兜底", None),
    69: ("best_effort", "KILL 发送尽力而为，属终止收尾", None),
    70: ("best_effort", "端口占用清理尽力而为，后有连接探测验证", None),
    71: ("best_effort", "KILL 阶段同上", None),
    72: ("narrowable", "marker 读取失败即全量重拷（安全但浪费）；收窄 (OSError, json.JSONDecodeError) + debug", None),
    73: ("narrowable", "构建指纹 marker 同上", None),
    74: ("narrowable", "dev lock 读取，收窄 (OSError, json.JSONDecodeError) 即可", None),
    75: ("best_effort", "psutil 平台差异异常（noqa 明示），有 /proc 兜底", None),
    76: ("best_effort", "登录流取消清理", None),
    77: ("best_effort", "登出时的流取消清理", None),
    78: ("best_effort", "revoke 失败被吞但本地凭据仍清除；安全相关，应 warning 注明服务器侧 token 或仍有效", None),
    79: ("best_effort", "模型目录失效清理，尽力而为", None),
    80: ("best_effort", "无用户上下文时回退全局实例（CLI 路径），属回退语义", None),
    81: ("best_effort", "健康探测收尾的 close 清理，主体已返回 False", None),
    82: ("best_effort", "缓存清理尽力而为（noqa：stale cache 不致命）；建议 warning", None),
    83: ("best_effort", "finally 中 HTTP client 关闭清理", None),
    84: ("best_effort", "探测失败回退静态 spec 表，属回退语义", None),
    85: ("best_effort", "owner 任务收尾断连，BaseException 有意不掩盖原始异常；建议改为 except Exception 并确认取消语义", None),
    86: ("best_effort", "owner 已通过 future 上报异常，close 处吞掉避免重复报告", None),
    87: ("best_effort", "批量关闭会话，CancelledError 已单独 uncancel 处理", None),
    88: ("best_effort", "interrupt 后排水尽力而为，结果已确定并返回", None),
    89: ("narrowable", "fromtimestamp 失败面为 (ValueError, OSError, OverflowError)，范围明确可收窄", None),
    90: ("best_effort", "索引为派生缓存（注释明示可重建）；建议对跳过文件 warning 计数", None),
    91: ("best_effort", "可选 converter 模块探测，导入失败跳过", None),
    92: ("best_effort", "探测整体失败回退 0.1.7 基线格式集", None),
    93: ("best_effort", "模型目录探测尽力而为，单根失败跳过", None),
    94: ("best_effort", "特意取回异常避免 future 未消费警告，随后 raise，语义正确", None),
    95: ("best_effort", "kb_config 防御性读取（pragma 注释），失败回退默认 mode；建议 debug", None),
    96: ("best_effort", "遥测事件尽力而为，失败不影响检索", None),
    97: ("best_effort", "显式的 best-effort abort 助手（pragma 注释）", None),
    98: ("best_effort", "坏图跳过属提取容错；建议收窄 (RuntimeError, ValueError) 并累计 skipped 计数", None),
    99: ("best_effort", "CLI 单例重置；PR #1704 已改为记录日志", 1704),
    100: ("best_effort", "同上；PR #1704 已改为记录日志", 1704),
    101: ("best_effort", "同上；PR #1704 已改为记录日志", 1704),
    102: ("best_effort", "无浏览器环境（注释明示），URL 已打印到终端", None),
    103: ("best_effort", "同 102", None),
    104: ("best_effort", "控制台编码便利性设置，失败不影响功能", None),
    105: ("best_effort", "畸形 L2 跳过（noqa 明示）避免 500；建议 debug", None),
    106: ("best_effort", "readiness 展示行尽力而为（pragma 明示）", None),
    107: ("best_effort", "可选 RAG 探测，失败即走无 RAG 路径", None),
    108: ("best_effort", "不透明缓存 blob 解码失败跳过（noqa 明示）", None),
    109: ("best_effort", "严格解析失败交 json_repair，注释明示且分级记录", None),
    110: ("best_effort", "L2 文档解析失败跳过，记忆审计容错", None),
    111: ("best_effort", "同上（noqa 明示：不阻塞 L3 迁移）", None),
    112: ("best_effort", "同上", None),
    113: ("best_effort", "引擎未安装即跳过（docstring 明示绝不让路由失败）", None),
    114: ("best_effort", "向量存储文件探测，坏文件跳过；建议收窄 (OSError, json.JSONDecodeError)", None),
    115: ("best_effort", "损坏包被发现机制忽略（注释明示崩溃恢复）；建议 debug", None),
    116: ("best_effort", "测试辅助：坏 YAML bundle 本身会被其它测试暴露", None),
    117: ("best_effort", "import 时兜底接线（pragma），失败仅意味测试保护树为空", None),
    118: ("narrowable", "(json.JSONDecodeError, Exception) 元组冗余；LLM 答案解析失败面为 (ValueError, TypeError, json.JSONDecodeError)，收窄并删冗余", None),
    119: ("best_effort", "fanout 任务收尾，元组冗余可简化为 gather(return_exceptions=True) 惯用法", None),
    120: ("narrowable", "(ImportError, Exception) 元组冗余；广播失败面为 ImportError + RuntimeError（内层已单独处理），收窄/简化即可", None),
}

TOP10 = [
    (11, "自更新失败时 mark_failed 与触发重启均无痕，升级可能停滞且无诊断线索，用户侧表现为\"更新卡住\"。", "复核并补齐 PR #1704：外层 mark_failed/重启失败也写入持久化日志（store.log_path），保留 return 1 语义。"),
    (10, "handoff 失败无法落盘，更新任务永久 pending、无告警，重启后仍在旧版本。", "复核 PR #1704（已记录双错误），确认日志写入 store.log_path 而非 stdout。"),
    (9, "mtime 记录静默失败会破坏增量同步判据，表现为每轮全量重扫或漏检变更。", "复核 PR #1706 的 warning 方案；进一步可收窄 (OSError, ValueError)。"),
    (8, "embedding 签名/索引版本不落库，UI 版本标识与实际索引脱节，排查索引问题失去依据。", "复核 PR #1706 的 error 日志方案即可，语义保持 best-effort。"),
    (0, "ERROR 进度不落盘，前端进度条停在 running，用户误以为仍在重建。", "复核 PR #1706 的 warning 方案；收窄到 (OSError, ValueError)。"),
    (39, "设置文件损坏时静默重置默认，用户自定义 UI 配置无痕丢失且无从发现。", "收窄 (OSError, json.JSONDecodeError)，并 warning 记录损坏路径与原因。"),
    (78, "revoke 失败无痕：服务器侧 token 仍有效而本地已清除，构成安全审计盲区。", "warning 日志注明\"吊销失败，token 可能仍有效\"并附异常摘要；不改变登出语义。"),
    (98, "损坏图片静默跳过，文档图文不完整且无任何计数，用户不知道少了哪些图。", "收窄 (RuntimeError, ValueError)，累计 skipped 计数并在提取结果中返回/记日志。"),
    (15, "catalog 解析失败静默回退 legacy provider，可能用错模型且无日志，问题极难定位。", "加 warning 记录回退原因；尽量收窄到配置/目录类异常，保留兜底语义。"),
    (17, "空目录清理失败或循环内逻辑 bug 均无痕，文件库残留空目录且掩盖代码错误。", "收窄 OSError + debug 日志；让非 OSError（逻辑 bug）自然暴露。"),
]


def main() -> None:
    scan = json.loads((HERE / "py_broad_excepts.json").read_text())
    baseline = json.loads((HERE / "appendix_a_baseline.json").read_text())
    by_loc = {(e["path"], e["line"]): e for e in scan["entries"]}

    work = []
    for i, r in enumerate(baseline["rows"]):
        e = dict(by_loc[(r["file"], r["line"])])
        e["idx"] = i
        e["risk"] = r["risk"]
        e["source"] = "dt22_appendix_a"
        work.append(e)
    seen = {(w["path"], w["line"]) for w in work}
    idx = len(work)
    for e in scan["entries"]:
        if e["silent"] and (e["path"], e["line"]) not in seen:
            e2 = dict(e)
            e2["idx"] = idx
            idx += 1
            e2["risk"] = "MEDIUM"
            e2["source"] = "scan_extra"
            work.append(e2)

    out = []
    top_map = {t[0]: (t[1], t[2]) for t in TOP10}
    for e in work:
        cat, reason, pr = V[e["idx"]]
        row = {
            "idx": e["idx"],
            "risk": e["risk"],
            "path": e["path"],
            "line": e["line"],
            "exc_type": e["exc_type"],
            "function": e["function"],
            "try_body_first_line": e["try_body_first_line"],
            "source": e["source"],
            "category": cat,
            "category_cn": CAT_CN[cat],
            "reason": reason,
        }
        if pr:
            row["related_upstream_pr"] = pr
        if e["idx"] in top_map:
            row["top10"] = True
            row["failure_consequence"] = top_map[e["idx"]][0]
            row["fix_suggestion"] = top_map[e["idx"]][1]
        out.append(row)

    (HERE / "classification.json").write_text(
        json.dumps({"count": len(out), "entries": out}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"classification.json: {len(out)} entries")

    # ── stats ──────────────────────────────────────────────────────────
    n = {"reraise": 0, "narrowable": 0, "best_effort": 0}
    for row in out:
        n[row["category"]] += 1
    prs = {}
    for row in out:
        if row.get("related_upstream_pr"):
            prs.setdefault(row["related_upstream_pr"], []).append(row["idx"])
    total = len(out)
    print(f"reraise={n['reraise']} narrowable={n['narrowable']} best_effort={n['best_effort']}")
    print("PR coverage:", {k: len(v) for k, v in sorted(prs.items())})

    # ── report ─────────────────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = []
    a = lines.append
    a("# 宽泛 except 分型扫描报告（AGEN-370 · 接续 DT-22）")
    a("")
    a(f"- **扫描对象**: `/Users/Shared/DeepTutor` worktree（只读）· `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12，与 DT-22 附录 A 同一提交，行号零偏移）")
    a(f"- **扫描日期**: {today}（UTC）")
    a("- **扫描范围**: `deeptutor` / `deeptutor_cli` / `scripts` / `tests`（与 DT-22 同口径），AST 级识别 `except Exception` / `except BaseException`")
    a("- **产物**: `scan_broad_except.py`（扫描脚本）、`py_broad_excepts.json`（明细）、`appendix_a_baseline.json`（附录 A 基线）、`classification.json`（121 条三型归属）、`extract_appendix_a.py` / `dump_context.py`（复现工具）、`SHA256SUMS`")
    a("- **上游关联 PR**: #1700 / #1703 / #1704 / #1706（均未合并，见 §4）")
    a("")
    a("## 1. 结论（PASS）")
    a("")
    a(f"- 4 个目录共扫描 {scan['stats']['files_scanned']} 个 Python 文件，`except Exception/BaseException` 共 **{scan['stats']['broad_handlers']}** 处（含非静默）；其中\"处理体仅 pass/continue/…\"的静默处理器 **121** 处。")
    a("- 与 DT-22 附录 A 的 **118** 条逐一按 `file:line` 对齐：**118/118 全部命中，零漂移**（DT-22 扫描基于同一提交）。")
    a("- 本扫描新增发现 **3** 条附录 A 漏网条目（元组类型中含 `Exception`，如 `(json.JSONDecodeError, Exception)`，DT-22 的类型名提取未识别），已一并分型，标记 `source=scan_extra`。")
    a("- 每条均有三型归属与理由（`classification.json` 字段 `category` / `reason`）。")
    a("")
    a("## 2. 三型分布")
    a("")
    a("| 分型 | 数量 | 占比 | 说明 |")
    a("| --- | --- | --- | --- |")
    a(f"| 应上抛（reraise） | {n['reraise']} | {n['reraise']/total:.1%} | 吞掉导致状态不可见/不可诊断，至少必须记录后上抛或落盘 |")
    a(f"| 可收窄（narrowable） | {n['narrowable']} | {n['narrowable']/total:.1%} | 异常面明确，收窄到具体类型即可，宽泛捕获会掩盖逻辑 bug |")
    a(f"| 尽力而为语义（best_effort） | {n['best_effort']} | {n['best_effort']/total:.1%} | 清理/通知/回退等有意吞掉；建议补 debug/warning 日志，不改语义 |")
    a("")
    a(f"总体判断：**87.6% 的宽泛捕获是有意的尽力而为语义**，问题不在\"吞\"本身，而在\"吞得无痕\"——全部 121 处中仅 {n['reraise']+n['narrowable']} 处需要改变控制流（上抛或收窄），其余补日志即可。")
    a("")
    a("### 2.1 应上抛（2 处，均已有上游 PR）")
    a("")
    a("| 位置 | 理由 | 关联 PR |")
    a("| --- | --- | --- |")
    for row in out:
        if row["category"] == "reraise":
            a(f"| `{row['path']}:{row['line']}` | {row['reason']} | #{row.get('related_upstream_pr')} |")
    a("")
    a("### 2.2 可收窄（13 处）")
    a("")
    a("| 位置 | 异常类型 | 归属理由 / 收窄建议 |")
    a("| --- | --- | --- |")
    for row in out:
        if row["category"] == "narrowable":
            a(f"| `{row['path']}:{row['line']}` | `{row['exc_type']}` | {row['reason']} |")
    a("")
    a("### 2.3 尽力而为语义（106 处，按主题归组）")
    a("")
    a("| 主题 | 数量 | 代表位置 | 补日志建议 |")
    a("| --- | --- | --- | --- |")
    groups = [
        ("WS 收尾清理（close/reset/错误帧）", [3, 4, 5, 19, 22, 26, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37], "debug 即可，勿用 warning 刷屏"),
        ("进度/遥测回调", [0, 12, 13, 16, 28, 96], "debug/warning；回调属可选通知"),
        ("单例/缓存重置", [65, 66, 67, 82, 99, 100, 101], "warning（写入会落错目录，PR #1704 同款）"),
        ("channel 停机/断连清理", [54, 55, 56, 57, 58, 59, 61, 62, 76, 77, 79, 83], "debug"),
        ("回退链（fallback 语义）", [15, 20, 21, 49, 80, 84, 92, 107, 109, 113], "debug 记录走了哪条回退"),
        ("文件/文档解析容错", [48, 90, 105, 110, 111, 112, 114, 115], "debug + 跳过计数"),
        ("可选模块/工具探测", [41, 91, 93, 106], "debug 记录被跳过对象"),
        ("展示性计数/元数据", [8, 50, 51, 52], "warning（PR #1706 同款）"),
        ("其它单点清理/便利性", [6, 7, 9, 18, 23, 24, 25, 42, 43, 44, 45, 46, 47, 53, 60, 63, 64, 68, 69, 70, 71, 75, 78, 81, 85, 86, 87, 88, 94, 95, 97, 98, 102, 103, 104, 108, 116, 117, 119], "逐条见 classification.json"),
    ]
    grouped = [i for _, idxs, _ in groups for i in idxs]
    b_idx = {row["idx"] for row in out if row["category"] == "best_effort"}
    assert sorted(grouped) == sorted(b_idx), (
        f"group coverage mismatch: missing={sorted(b_idx - set(grouped))} extra={sorted(set(grouped) - b_idx)}"
    )
    for name, idxs, advice in groups:
        rep = f"`{out[idxs[0]]['path']}:{out[idxs[0]]['line']}`"
        a(f"| {name} | {len(idxs)} | {rep} | {advice} |")
    a("")
    a("## 3. Top10（按失败后果排序）")
    a("")
    a("| # | 位置 | 分型 | 一句话失败后果 | 修复建议 | 关联 PR |")
    a("| --- | --- | --- | --- | --- | --- |")
    for rank, (idx, cons, fix) in enumerate(TOP10, 1):
        row = out[idx]
        pr = f"#{row['related_upstream_pr']}" if row.get("related_upstream_pr") else "—"
        a(f"| {rank} | `{row['path']}:{row['line']}` | {CAT_CN[row['category']]} | {cons} | {fix} | {pr} |")
    a("")
    a("## 4. 上游 PR 交叉核对（去重）")
    a("")
    a("开工前已核对上游：四个开放 PR 与本清单的关系如下（本报告不开新 PR，修复卡片应优先复核对应 PR 而非重复实现）：")
    a("")
    a("| PR | 覆盖本清单条目 | 方式 | 审查结论 |")
    a("| --- | --- | --- | --- |")
    a(f"| #1704 runtime/cli 单例与自更新 | {len(prs.get(1704, []))} 处（idx {prs.get(1704, [])}；idx 11 为部分覆盖） | 保留宽泛捕获，补 logger.exception/warning；update_worker 为 store.load 失败新增落盘恢复日志 | 方向正确，与本清单 2 处\"应上抛→至少记录\"结论一致；建议补外层 mark_failed/重启失败的留痕后合并 |")
    a(f"| #1706 knowledge 进度/状态/同步 | {len(prs.get(1706, []))} 处（idx {prs.get(1706, [])}） | 保留宽泛捕获，按级别补日志（close→debug，reset→warning，进度→warning） | 分级得当，与 §2.3 建议一致；未收窄异常类型，可后续跟进 |")
    a(f"| #1703 embedding/图片进度 | {len(prs.get(1703, []))} 处（idx {prs.get(1703, [])}） | 进度回调失败 warning + 测试 | 与本清单 best_effort 定性一致 |")
    a(f"| #1700 DOCX 表格行 | {len(prs.get(1700, []))} 处（idx {prs.get(1700, [])}） | 失败行保留占位并 warning | 比静默跳过更好，已含测试 |")
    a("")
    pr_covered = set()
    for v in prs.values():
        pr_covered.update(v)
    a(f"合计：**{len(pr_covered)} 处已有上游 PR 覆盖**（含 1 处部分覆盖），剩余 {total - len(pr_covered)} 处为潜在新修复卡片的范围；其中优先级最高的是 §2.2 的 13 处收窄项。")
    a("")
    a("## 5. 新增发现（附录 A 之外）")
    a("")
    a("DT-22 的异常类型名提取未识别元组中的 `Exception` 成员，本扫描补齐 3 条（均已分型，见 `classification.json` 尾部）：")
    a("")
    for row in out:
        if row["source"] == "scan_extra":
            a(f"- `{row['path']}:{row['line']}` — `{row['exc_type']}` → {CAT_CN[row['category']]}：{row['reason']}")
    a("")
    a("## 6. 复现")
    a("")
    a("```bash")
    a("cd <DeepTutor worktree @ ef2d9e5c>")
    a("python3 evidence/broad-except-scan-2026-10-04/scan_broad_except.py . --out /tmp/scan.json")
    a("python3 - <<'EOF'")
    a("import json")
    a("s = json.load(open('/tmp/scan.json'))")
    a("c = json.load(open('evidence/broad-except-scan-2026-10-04/appendix_a_baseline.json'))")
    a("keys = {(e['path'], e['line']) for e in s['entries']}")
    a("missing = [r for r in c['rows'] if (r['file'], r['line']) not in keys]")
    a("print('coverage:', len(c['rows']) - len(missing), '/', len(c['rows']))")
    a("EOF")
    a("sha256sum -c evidence/broad-except-scan-2026-10-04/SHA256SUMS")
    a("```")
    a("")
    a("## 7. 验收对照")
    a("")
    a("1. **覆盖附录 A 全部 118 条，每条有三型归属与理由** — ✅ 118/118 命中并分型（另加 3 条 scan_extra，共 121）。")
    a("2. **不修改任何产品代码，产物只进证据目录** — ✅ 仅新增 `evidence/broad-except-scan-2026-10-04/`，未触碰任何源码文件。")
    a("")

    report = "\n".join(lines)
    (HERE / "report.md").write_text(report, encoding="utf-8")
    print(f"report.md written ({len(lines)} lines)")

    # SHA256SUMS
    import subprocess
    files = sorted(p.name for p in HERE.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    digest_lines = []
    for name in files:
        h = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        digest_lines.append(f"{h}  {name}")
    (HERE / "SHA256SUMS").write_text("\n".join(digest_lines) + "\n", encoding="utf-8")
    print(f"SHA256SUMS: {len(files)} files")


if __name__ == "__main__":
    main()
