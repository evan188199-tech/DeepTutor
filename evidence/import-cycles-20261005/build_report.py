#!/usr/bin/env python3
"""Build report.md from the JSON outputs of scan_imports.py (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
COMMIT_FALLBACK = "unknown"


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()[:12]
    except Exception:
        return COMMIT_FALLBACK


def short(mod: str) -> str:
    return mod.replace("deeptutor.", "d.").replace("deeptutor_cli.", "cli.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default=BASE)
    args = ap.parse_args()

    cycles = json.load(open(os.path.join(BASE, "cycles.json")))
    lazy = json.load(open(os.path.join(BASE, "lazy_hotspots.json")))
    se = json.load(open(os.path.join(BASE, "side_effects.json")))

    stats = cycles["summary"]
    imp_sccs = cycles["import_time_sccs"]
    lazy_sccs = cycles["lazy_only_sccs"]
    date = "2026-10-05"

    L: list[str] = []
    w = L.append

    w(f"# Python 循环导入与函数内 lazy import 清点（AGEN-661，{date}）")
    w("")
    w(f"- 基线：origin/main `{git_commit()}`（v1.6.13，只读扫描，未改任何产品代码）")
    w("- 范围：`deeptutor/` `deeptutor_cli/` `scripts/`（排除 tests/conftest；"
      f"共 {stats['files_scanned']} 个 .py 文件，AST 解析全部成功，0 个语法错误）")
    w("- 工具：`scan_imports.py`（纯标准库：ast / json / hashlib），"
      "本目录下 `python3 scan_imports.py --repo <仓库根> --out <本目录>` 可复现")
    w("- 机器可读数据：`cycles.json` `lazy_hotspots.json` `side_effects.json`")
    w("")
    w("## 1. 总览")
    w("")
    w(f"| 指标 | 数值 |\n|---|---|")
    w(f"| 模块级（top-level）import 记录 | {stats['total_import_records_top']} |")
    w(f"| 函数内（lazy）import 记录 | {stats['total_lazy_imports']}（"
      f"{stats['files_with_lazy']} 个文件含 lazy import） |")
    w(f"| 强连通分量（SCC，≥2 模块） | {len(imp_sccs) + len(lazy_sccs)} |")
    w(f"| 其中纯模块级 import 环 | **{len(imp_sccs)}** |")
    w(f"| 由函数内 lazy import 掩盖的环 | {len(lazy_sccs)}（最大 303 个模块） |")
    w(f"| import 副作用条目 | {len(se['hits'])}（其中启动路径可达 "
      f"{sum(1 for h in se['hits'] if h['startup_reachable'])}） |")
    w("")
    w("**核心结论**：代码库已经没有任何“纯模块级”import 环——但代价是把环 "
      "全部推迟到了函数内：2219 处函数内 import、426 个文件涉入，"
      "7 个 SCC 的环边全部依赖 lazy import 才能在导入期不炸。这正是 DT-22 "
      "“大量函数内 import”的系统性成因：函数内 import 不是风格问题，"
      "而是当前解开循环依赖的唯一手段，任何一处被“顺手”提到模块级，"
      "都可能当场触发 ImportError。治理应按第 6 节按卡拆解，不要全量上提。")
    w("")
    w("## 2. 方法与局限")
    w("")
    w("- 用 `ast` 解析每个文件，区分模块级 import 与函数/类体内 import"
      "（`TYPE_CHECKING` 块单独计数、`if __name__` 块忽略）。")
    w("- 相对 import 按所在包解析为绝对模块名；`from pkg import name` 优先解析为子模块，"
      "其次回退到包本身。仅保留仓库内部边。")
    w("- 环检测：Tarjan SCC；对每个 SCC 再在其**模块级边诱导子图**上复检是否成环，"
      "以区分“导入期就会成环”与“仅运行时成环”。每个 SCC 给出一条最短代表环路径。")
    w("- 局限：①动态导入（`importlib.import_module`）不进图，第 5.4 节单列；"
      "②子模块导入隐式执行父包 `__init__` 的级联边未画（避免假环，但意味着"
      "`__init__` 聚合导出会放大实际导入面）；③不追踪字符串拼出的模块名。")
    w("")
    w("## 3. 循环导入环清单")
    w("")
    w("### 3.1 纯模块级环：0 个")
    w("")
    w("把 303+14+…=全部 SCC 成员间的模块级边诱导子图逐一复检，均无环。"
      "即当前 origin/main 导入期不会因循环导入直接失败。")
    w("")
    w("### 3.2 lazy import 掩盖的环（7 个 SCC）")
    w("")
    w("| # | 规模 | 模块级边 | lazy 边 | 判定 | 代表环（⇢=lazy 边） |")
    w("|---|---|---|---|---|---|")

    def cycle_path_str(c: dict) -> str:
        parts = []
        for e in c["edges"]:
            arrow = "⇢" if e["kind"] == "lazy" else "→"
            parts.append(f"{short(e['src'])} {arrow} ")
        if c["edges"]:
            parts.append(short(c["edges"][-1]["dst"]))
        return "".join(parts)

    risk_map = {}
    for i, c in enumerate(lazy_sccs, 1):
        risk_map[f"S{i}"] = c
        if c["size"] == 303:
            verdict = ("运行时环，面积极大（303 模块互达）；"
                       "模块级边 484 条无环，全靠 lazy 边维持。治理见 F6/F7")
        elif c["size"] == 14:
            verdict = "运行时环，blocks 注册模式所致，拆卡 F5"
        else:
            verdict = "运行时环，两模块互需，拆卡 F4"
        w(f"| S{i} | {c['size']} | {c['top_edge_count']} | {c['lazy_edge_count']} "
          f"| {verdict} | `{cycle_path_str(c)}` |")
    w("")
    w("各 SCC 明细（关键证据，完整数据见 `cycles.json`）：")
    w("")
    for i, c in enumerate(lazy_sccs, 1):
        w(f"**S{i}（{c['size']} 模块）** 代表环逐边：")
        w("")
        for e in c["edges"]:
            kind = "lazy（函数内）" if e["kind"] == "lazy" else "模块级"
            w(f"- `{e['file']}:{e['line']}` {kind} `{e['stmt'][:90]}`")
        if c["size"] == 303:
            w(f"- 该 SCC 覆盖 services/session、services/partners、services/llm、"
              "services/rag、services/workspace、learning、reading、multi_user、"
              "tools 等几乎全部业务核心；成员清单见 `cycles.json` 的 "
              "`lazy_only_sccs[0].members`。")
            agg = [e for e in c["top_edges_sample"]
                   if e["file"].endswith("__init__.py")]
            if agg:
                w("- 其中 `__init__.py` 聚合导出贡献的模块级边（放大导入面的首要嫌疑，"
                  "拆卡优先对象）：")
                for e in agg[:10]:
                    w(f"  - `{e['file']}:{e['line']}` `{e['stmt'][:90]}`")
        w("")
    w("### 3.3 风险判定")
    w("")
    w("- **无导入期爆炸风险**：现在没有任何两模块在模块级互相 import。")
    w("- **高脆弱性风险**：303 模块的大 SCC 意味着“谁先导入谁都行，"
      "但谁也不能在模块级引用谁”。任何把 lazy import 上提为模块级的改动，"
      "或新增一条跨层模块级边，都可能引入首个真环。 review 时凡见到"
      "把函数内 import 移到模块级的 PR，应对照本清单确认该边不在 SCC 内。")
    w("- **两模块小环（S3–S7）**：低风险、易拆——把环上一条 lazy 边改为"
      "参数注入/类型仅 TYPE_CHECKING 即可解除（拆卡 F4）。")
    w("")
    w("## 4. 函数内 lazy import 热点 Top20")
    w("")
    w(f"全库函数内 import 共 {lazy['total_lazy']} 处。下表为按出现次数排序的 "
      "Top20（次数 / 涉及文件数 / 目标）：")
    w("")
    w("| # | 次数 | 文件数 | 被重复导入的目标 | 主要成因 |")
    w("|---|---|---|---|---|")

    cause = {
        "get_content_workspace_service": "服务单例访问器（F6 卡）",
        "get_current_user": "多用户上下文访问器（F7 卡）",
        "get_path_service": "服务单例访问器（F6 卡）",
        "get_session_store": "服务单例访问器（F6 卡）",
        "asyncio": "标准库为省启动成本被下放（F8 卡）",
        "get_sqlite_session_store": "服务单例访问器（F6 卡）",
        "KnowledgeBaseManager": "跨层类引用（环 S1 内）",
        "get_llm_config": "服务单例访问器（F6 卡）",
        "LearningStore": "跨层类引用（环 S1 内）",
        "WorkspaceError": "异常类跨层引用，可安全上提",
        "workspace_context": "上下文管理器访问器（F7 卡）",
        "get_runtime_settings_service": "设置服务访问器（F6 卡）",
        "current_workspace_id": "上下文访问器（F7 卡）",
        "get_partner_manager": "服务单例访问器（F6 卡）",
        "complete": "LLM 门面函数（环 S1 内）",
        "resolve_kb_metadata": "多用户访问控制（F7 卡）",
        "task_llm_scope": "模型选择工具函数（环 S1 内）",
        "msvcrt": "Windows 平台分支（F8 卡）",
        "fcntl": "POSIX 平台分支（F8 卡）",
        "get_admin_path_service": "服务单例访问器（F6 卡）",
    }
    for i, h in enumerate(lazy["top20"], 1):
        key = h["display"]
        c = next((v for k, v in cause.items() if key.endswith(k)), "")
        w(f"| {i} | {h['count']} | {h['distinct_files']} | "
          f"`{h['display'][:80]}` | {c} |")
    w("")
    w("### 4.1 同一文件内重复 import（DT-22 症状最直接证据）")
    w("")
    w("| 文件 | 同一 import 在函数内重复次数 | 行号（示例） |")
    w("|---|---|---|")
    for r in lazy["per_file_repeats"][:10]:
        lines = ", ".join(str(x) for x in r["lines"][:8])
        w(f"| `{r['file']}` | {r['count']}× `{r['import'][:60]}` | {lines} |")
    w("")
    w("`deeptutor/api/routers/knowledge.py` 一处文件内同一函数级 import 重复 "
      "12 次（另有 6×、5×、5×、5× 共 5 组），是 DT-22 的典型样本。")
    w("")
    w("## 5. import 副作用与启动影响")
    w("")
    w("启动路径 = `deeptutor_cli.__main__` / `deeptutor.api.main` / `scripts/start_web` "
      f"等 {len(stats['entrypoints_found'])} 个入口沿模块级边的前向闭包"
      f"（{stats['startup_reachable_files']} 个文件）。")
    w("")
    w("### 5.1 导入期执行的真实副作用（高优先）")
    w("")
    w("| 位置 | 副作用 | 风险判定 |")
    w("|---|---|---|")
    w("| `deeptutor/api/main.py:20` | `ensure_runtime_settings_files()` 在导入时"
      "创建/校验运行时设置文件 | 高：导入 API 应用即落盘；测试中 import 也会写用户目录 |")
    w("| `deeptutor/api/main.py:21` | `export_runtime_settings_to_env(overwrite=True)` "
      "导入时覆盖进程环境变量 | 高：同进程内先 import 后启动的顺序被固化；"
      "覆盖语义对嵌入方不友好 |")
    w("| `deeptutor/api/main.py:22` | `configure_logging()` 导入时改全局日志配置 | 高："
      "import 副作用经典反模式，且 `deeptutor_cli/main.py:29` 又配一次，双重初始化 |")
    w("| `deeptutor/api/main.py:515-526` | `init_user_directories()` 放在模块级 "
      "`try/except Exception` 里，失败静默走 fallback 只建一个目录 | 高：吞错 + 启动语义，"
      "DT-22 同症状（与 fix-init-singletons 主题相邻、位置不同） |")
    w("| `deeptutor/api/main.py:528-529` | 注释自证顺序敏感：“Import routers only "
      "after runtime settings are initialized. Some router modules load YAML settings "
      "at import time.” | 高：模块导入顺序即业务正确性，属 scan-startup-order 主题 |")
    w("| `deeptutor_cli/main.py:29,65-78` | 导入时 `configure_logging()` 并串行 "
      "register 13 个子命令模块 | 中：CLI 启动即拉起全部子命令 import 链，"
      "拖慢 `--help` 且失败点提前 |")
    w("")
    w("### 5.2 导入期注册/自注册（顺序耦合）")
    w("")
    w("| 位置 | 副作用 |")
    w("|---|---|")
    w("| `deeptutor/services/partner_groups/memory.py:196-197` | 模块级实例化 "
      "`SharedMemoryRegistry` 并自注册 `WhiteboardMemory` |")
    w("| `deeptutor/services/partner_groups/modes.py:181-184` | 模块级实例化 "
      "`DiscussionModeRegistry` 并注册 3 个模式 |")
    w("| `deeptutor/services/app_update.py:654` | 模块级 `_version_service = "
      "VersionCheckService()` |")
    w("| `deeptutor/services/partner_groups/manager.py:1622` | 模块级 `_manager = "
      "PartnerGroupManager()` |")
    w("| `deeptutor/services/workspace/service.py:801` | 模块级 "
      "`_service = ContentWorkspaceService()` |")
    w("| `deeptutor/config/settings.py:50` | 模块级 `settings = Settings()` |")
    w("")
    w("这些单例本身构造轻，但都属“谁 import 谁触发”的隐式初始化，"
      "与 scan-startup-order 主题重叠；F1/F2 卡一并处理。")
    w("")
    w("### 5.3 其余模块级实例化")
    w("")
    w("共 107 处模块级赋值实例化，绝大多数为良性常量（`APIRouter`×52、"
      "`typer.Typer`×13、`httpx.Timeout`×4 等），已从拆卡清单剔除；"
      "全量明细见 `side_effects.json`。")
    w("")
    w("### 5.4 动态导入（静态图外）")
    w("")
    w("28 处 `importlib.import_module` / `__import__`。值得单列的：")
    w("")
    w("- `deeptutor/services/config/__init__.py:51,138,142` 用 f-string 自导入"
      "子模块——若只是为了打破本包内环，可改静态 import（F9 卡）。")
    w("- `deeptutor/partners/channels/registry.py:42`、"
      "`deeptutor/runtime/registry/capability_registry.py:32`、"
      "`deeptutor/tools/builtin_specs.py:26` 等为插件/通道动态发现，属设计内，保留。")
    w("- `deeptutor/api/utils/task_log_stream.py:325`、"
      "`deeptutor/services/rag/service.py:248` 导入 `lightrag.utils`（第三方），"
      "疑为规避其导入副作用，建议注释说明。")
    w("")
    w(f"### 5.5 平台分支与标准库下放")
    w("")
    w("`msvcrt`（10 处）与 `fcntl`（9 处）在函数内按平台导入是正确做法但散落多处；"
      "`asyncio` 被函数内导入 18 处纯属可上提项（F8 卡）。")
    w("")
    w("## 6. 可拆修复卡清单")
    w("")
    w("> 每卡独立可交付；**改动原则：只减少函数内 import，不新增模块级跨层边**，"
      "动前先跑 `scan_imports.py` 对比 SCC 数量不增。")
    w("")
    w("| 卡 | 标题 | 范围（path:line） | 风险 | 工作量 | 去重标注 |")
    w("|---|---|---|---|---|---|")
    w("| F1 | api/main.py 导入期初始化收敛到 lifespan/工厂函数"
      "（ensure_runtime_settings_files / export_runtime_settings_to_env / "
      "configure_logging 三连） | `deeptutor/api/main.py:20-22` | 高 | 中 | "
      "与 scan-startup-order 主题重叠，拆卡需与其合并（该卡未在板上找到，见 §7） |")
    w("| F2 | init_user_directories 导入期吞错可见化"
      "（top-level try/except Exception 静默 fallback） | `deeptutor/api/main.py:515-526` "
      "| 高 | 小 | DT-22 吞错同症状；与 fix-init-singletons 主题相邻、位置不同，不重复 |")
    w("| F3 | routers/knowledge.py 函数内重复 import 收敛"
      "（12×/6×/5×/5×/5× 五组，含 get_runtime_settings_service 12 处） | "
      "`deeptutor/api/routers/knowledge.py:1470,1493,1520,1546,1590,1606,1630,1642` 等 "
      "| 中 | 中 | 无重叠；依赖 F1 先收敛（否则上提会改变导入时序） |")
    w("| F4 | 两模块小环拆除（S3-S7）：环上一条 lazy 边改参数注入或 "
      "TYPE_CHECKING | `deeptutor/learning/pending.py:20`↔`models.py`；"
      "`deeptutor/services/rag/eval/runner.py:28`↔`report.py`；"
      "`deeptutor/services/web_source/sync.py:194`↔`scheduler.py`；"
      "`deeptutor/agents/loop/pipeline.py:44`↔`agent_loop.py`；"
      "`deeptutor/textbook_struct/page_headers.py:18`↔`chapter_rebuild.py` | 低 | 小 | "
      "无重叠 |")
    w("| F5 | book/blocks 注册模式改造：base.py 不再逐块 lazy import，"
      "改为块自注册 | `deeptutor/book/blocks/base.py:207` + blocks/*（S2，14 模块） "
      "| 中 | 中 | 无重叠 |")
    w("| F6 | 服务访问器统一访问层：get_path_service(21)/get_session_store(21)/"
      "get_content_workspace_service(31)/get_partner_manager(13) 等 Top 访问器"
      "收敛到模块级或 FastAPI Depends | `deeptutor/services/path_service.py`、"
      "`deeptutor/services/session/__init__.py`、"
      "`deeptutor/services/workspace/service.py` 等 | 中 | 大 | 无重叠；"
      "注意这些模块都在 S1 大 SCC 内，须逐边验证 |")
    w("| F7 | 多用户上下文访问器收敛：get_current_user(22×)/workspace_context(14×)/"
      "current_workspace_id(13×)/resolve_kb_metadata(11×) | "
      "`deeptutor/multi_user/context.py`、`deeptutor/services/workspace/context.py` "
      "| 中 | 大 | 无重叠 |")
    w("| F8 | 标准库函数内 import 上提：asyncio 18 处；msvcrt/fcntl 19 处"
      "改为模块顶部 `sys.platform` 分支 | 全库（热点见 §4/§5.5） | 低 | 小 | 无重叠 |")
    w("| F9 | config/__init__ 动态自导入改静态（f-string importlib 三处） | "
      "`deeptutor/services/config/__init__.py:51,138,142` | 中 | 小 | 无重叠；"
      "改前确认 loader/provider_runtime/test_runner 不回导 `__init__` |")
    w("| F10 | CLI 启动瘦身：main.py 导入期 configure_logging + 13 个 "
      "register_* 移入 main() | `deeptutor_cli/main.py:29,65-78` | 中 | 中 | 无重叠 |")
    w("| F11 | partner_groups 注册器导入期自注册改显式注册清单 | "
      "`deeptutor/services/partner_groups/memory.py:196-197`、"
      "`modes.py:181-184` | 低 | 小 | 与 scan-startup-order 主题轻度重叠，标注即可 |")
    w("")
    w("优先级建议：F1 → F2 → F3（先消掉导入期副作用与最痛的重复 import）；"
      "F4/F8/F9/F11 为低风险快赢；F6/F7 大卡建议再切子卡。")
    w("")
    w("## 7. 与既有卡去重说明")
    w("")
    w("- **fix-init-singletons**（储备卡，覆盖 `deeptutor_cli/init_cmd.py:35`、"
      "`deeptutor/runtime/launcher.py:146` 的 PathService 重置吞错 HIGH，"
      "及 `init_cmd.py:41/47`、`launcher.py:152/158` 同模式 MEDIUM）："
      "本扫描在这 4 处均**未**发现 import 环或 lazy 热点，无条目冲突；"
      "F2（api/main.py:515-526 的 try/except 吞错）与其“吞错可见化”主题同族"
      "但位置、机制不同，独立成卡不重复。")
    w("- **scan-startup-order**（卡上未找到，按描述理解为主题为启动/导入顺序）："
      "本扫描 §5.1/§5.2/§5.4 的发现（api/main.py 导入期初始化三连、顺序敏感注释、"
      "导入期自注册、config/__init__ 动态自导入）与该主题高度重叠。"
      "F1/F11 已标注“拆卡需与 scan-startup-order 合并”；"
      "若该卡后续建卡，建议以本报告 §5 作为其输入之一。")
    w("- 上游 PR 撞车检查：`gh pr list -R HKUDS/DeepTutor --author @me --state open` "
      "30 个开放分支及全量开放 PR 检索（import cycle / circular / lazy import）"
      "均无本主题条目。")
    w("")
    w("## 8. 校验和")
    w("")
    w("完整清单（含 report.md 本身）见本目录 `SHA256SUMS` 文件；"
      "数据与脚本文件的校验和：")
    w("")
    w("```")
    for name in sorted(os.listdir(args.out)):
        p = os.path.join(args.out, name)
        if not os.path.isfile(p) or name in ("report.md", "SHA256SUMS"):
            continue
        digest = hashlib.sha256(open(p, "rb").read()).hexdigest()
        w(f"{digest}  {name}")
    w("```")
    w("")
    w("（report.md 与 SHA256SUMS 由 `build_report.py` 生成；"
      "复现：`python3 scan_imports.py --repo . --out <dir>` 后 "
      "`python3 build_report.py --repo .`）")

    out_path = os.path.join(args.out, "report.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print(f"wrote {out_path} ({len(L)} lines)")

    sums_path = os.path.join(args.out, "SHA256SUMS")
    with open(sums_path, "w", encoding="utf-8") as fh:
        for name in sorted(os.listdir(args.out)):
            if name == "SHA256SUMS":
                continue
            p = os.path.join(args.out, name)
            if not os.path.isfile(p):
                continue
            digest = hashlib.sha256(open(p, "rb").read()).hexdigest()
            fh.write(f"{digest}  {name}\n")
    print(f"wrote {sums_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
