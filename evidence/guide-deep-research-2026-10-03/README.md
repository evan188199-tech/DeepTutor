# evidence/guide-deep-research-2026-10-03

为 `docs/guides/deep-research.md` 的编写过程与事实核查记录。

## 输入

- 基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），新 worktree `dt-agen290-wt`，分支 `docs/guides/deep-research`。
- 通读文件：
  - `deeptutor/agents/research/pipeline.py`（3239 行；重点：模块 docstring、`__init__`、`run`/`_run_inner`、`_rephrase`/`_decompose`/`_parse_outline`、`_research_block`/`_drive_queue`/`_force_finish_block`、`_summarise_tool_result`、`_write_report` 及 report 子步、`_BlockLoopHost`、`_RephraseLoopHost.dispatch_tools`、模块级 citation/markdown 辅助函数、默认常量区）
  - `deeptutor/agents/research/utils/citation_manager.py`（907 行，全文）
  - `deeptutor/agents/research/data_structures.py`（570 行，全文）
  - `deeptutor/agents/research/utils/json_utils.py`（94 行，全文）
- 佐证材料：分支 `audit/coverage-gaps-20261003` 的 `evidence/coverage-2026-10-02/top15-gaps.md`（第 4 项 citation_manager 264 缺失 / 37.0%；第 7 项 pipeline 408 缺失 / 62.6%）；`capability.py`、`request_config.py`、`mode_strategy.py`、`deeptutor/utils/json_parser.py`、`tests/agents/research/` 目录清单（用于模块边界与延伸阅读）。
- 上游查重：`gh pr list --repo HKUDS/DeepTutor --state all` 检索 "deep research guide docs"，无既有同类文档 PR。

## 导读中关键论断的核查命令与结果

均在 worktree 根目录（基线 ef2d9e5c3）执行：

1. "PLAN- 生成器与 build_ref_number_map 在 pipeline 无调用点（双编号系统，其中一套为遗留）"：
   `grep -rn "generate_plan_citation_id\|build_ref_number_map\|get_ref_number" deeptutor tests --include="*.py" | grep -v "utils/citation_manager.py"` → 零命中。
   PLAN- 在 pipeline.py 仅出现在正则（:2424/:2425）与排序键（:2603）。
2. "报告编号走正文首现顺序，PLAN 优先排序只是无标记时的兜底"：
   `pipeline.py:1398-1407`（`_citation_ids_in_first_appearance` → enumerate 编号 → linkify/reference list）与 `pipeline.py:1432`（`citation_ids is not None` 时不用 `_sorted_citation_ids`）。
3. "DynamicTopicQueue 落盘未被 pipeline 启用"：
   `grep -n "set_state_file\|state_file" deeptutor/agents/research/pipeline.py` → 零命中。
4. "json_utils 是 research 本地工具，pipeline 实际用全局 json_parser"：
   `grep -rn "json_utils\|extract_json_from_text\|..." deeptutor tests --include="*.py"` → 仅 `utils/__init__.py` 再导出与 `tests/agents/research/test_extract_json_adjacent.py`；pipeline/citation_manager/data_structures 均 import `deeptutor.utils.json_parser.parse_json_response`（pipeline.py:102、:2804；citation_manager.py:15；data_structures.py:16）。
5. "tool message 替换在 add_citation 之后无条件执行"：`pipeline.py:2846-2850`（add_citation_async 返回值未检查）。
6. "队列容量两语义"：`data_structures.py:322`（add_block raise）vs `data_structures.py:389`（append_child 返回 None）。

## 产物清单

- `docs/guides/deep-research.md`：模块边界、四阶段编排表、mermaid 数据流图、citation_manager 函数表、产物契约（data_structures/json_utils 表）、吞错/容错点地图、常见坑 6 条、延伸阅读。纯新增文档，未触碰任何产品代码（`git diff --stat` 应仅含 docs/ 与 evidence/ 两个新文件）。
