# scan: 纯文本 detail 无机器可读 code 系统性清点（E14）

- 基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 分支：`scan/detail-code-envelope-20261011`（只清点，未改任何源码）
- 证据文件：`detail-inventory.csv` / `detail-inventory.json`（逐点明细）、`clusters.csv`（文案聚类）、`tools/scan_detail.py`（复现脚本）
- 扫描范围：`deeptutor/`、`deeptutor_cli/`、`tests/` 全部 `.py`（AST 解析，非正则）

## 1. 方法与口径

对每个 `detail` 写点用 AST 分类 `detail_kind`：

| detail_kind | 含义 | 机器可读 |
|---|---|---|
| plain_str | 字符串字面量 | 否 |
| fstring | f-string 动态拼文案 | 否 |
| str_call | `str(exc)` / `str(e)` 透传 | 否 |
| i18n_call | `t("api.xxx")` 翻译文案 | 否（key 是翻译键不是错误码） |
| helper_call | 业务 helper 拼文案 | 否 |
| dynamic | 变量/表达式透传 | 否 |
| dict_no_code | dict 结构但无 `code` 键 | 否（半结构化） |
| dict_code | `detail={"code": ..., "message": ...}` | **是（已改造）** |
| none | 未传 detail | — |

`writer` 字段区分 `http_exception`（FastAPI HTTPException）、`payload_dict`（`{"detail": ...}` 负载）、`json_response`。`plaintext=true` 表示无机器可读 code。

## 2. 总量与种子对账

| 口径 | 数量 |
|---|---|
| 写点总数（含 tests） | 906 |
| 生产写点（deeptutor + cli） | 878 |
| 生产纯文本 detail（无 code） | **836** |
| 其中位于路由处理器内 | 622 |
| 已有结构化 code（dict_code） | 13 |
| tests 内写点（不改，仅记录） | 28 |

种子 E14 估算 ~597 处：与"路由处理器内纯文本 detail"口径（622，当前 main）量级一致；本清单按全量口径 836 覆盖（含 helper、service 层、payload 写点），批次建议仍以路由内写点为主。

## 3. 排除标注（子集卡）

- **AGEN-1364**（sessions.py 错误信封，in_review）：`deeptutor/api/routers/sessions.py` 全部 29 处写点在明细 CSV `excluded_subset=AGEN-1364` 标注排除。卡面记 27 处，当前 main 实测 29 处（main 前进所致），改造卡按实际为准。
- **AGEN-880**（web detail.code 共享解析层）：web 前端是 `detail` 的**消费端**（`web/**` 共 244 处 `detail` 引用），不产生后端写点，不在本清单行级范围内；本清单是其后端对端数据源。

## 4. 模块分布（生产纯文本 836）

| 文件 | 纯文本 | 已 code | 测试引用信号 |
|---|---|---|---|
| api/routers/knowledge.py | 173 | 0 | 高 |
| api/routers/partners.py | 77 | 0 | 高 |
| api/routers/auth.py | 64 | 0 | 高 |
| api/routers/book.py | 54 | 3 | 高 |
| api/routers/mastery_path.py | 37 | 0 | 中 |
| api/routers/skills.py | 32 | 0 | 中 |
| api/routers/co_writer.py | 31 | 0 | 中 |
| api/routers/sessions.py | 29 | 0 | 高（**排除 AGEN-1364**） |
| api/routers/multi_user.py | 25 | 0 | 高 |
| api/routers/reading_extensions.py | 25 | 0 | 低 |
| api/routers/memory.py | 23 | 0 | 高 |
| api/routers/file_preview.py | 22 | 0 | 低 |
| api/routers/notebook.py | 22 | 1 | 高 |
| api/routers/partner_groups.py | 22 | 0 | 低 |
| api/routers/question_notebook.py | 18 | 0 | 低 |
| api/routers/settings.py | 18 | 1 | 高 |
| api/routers/reading.py | 17 | 0 | 高 |
| api/routers/courses.py | 15 | 0 | 中 |
| api/routers/plugins.py | 12 | 0 | 中 |
| api/routers/subagents.py | 11 | 0 | 中 |
| api/routers/workspace.py | 11 | 0 | 高 |
| api/routers/system.py | 10 | 0 | 高 |
| 其余 26 个文件（≤9/文件） | 合计 79 | 8 | 混合 |

层次：api_router 849、service 12、multi_user 9、api_internal 4、capabilities 4（生产）；另 payload_dict/json_response 写点 24 处（多为任务进度/审计 detail，非错误契约，见 CSV `writer` 列，不建议纳入改造批次）。

状态码分布（纯文本 HTTPException 写点）：404×250、400×211、500×106、409×94、422×42、403×35、502×21、413×10、503×8、401×7、429×4、动态状态码×11（变量/属性引用）。

## 5. 高频文案聚类（Top，详见 clusters.csv 共 407 簇）

动态透传是最大簇：`str(exc)`×184、`str(e)`×69 —— 无静态文案，需要"默认 code + 原文透传 message"的信封模式（同 str 型 helper）。

高频静态簇（`X not found` 家族为主）：Session/User/Knowledge base/Book/Course/File/Entry/Mastery topic/Progress/Plugin page/Preview source/Page/Block/Document/Notebook not found（各 4–14 处）；i18n 簇 `t('api.partner_not_found')`×9、`t('api.persona_not_found')`×4；模板簇 `Knowledge base '{}' not found`×11、`Source '{}' not found`×5。

## 6. 建议 code 信封分组

沿用既有先例（space_mcp.py:89 `mcp.not_oauth`、book.py:61 `book_paused`、space_cli_apps `cli.not_granted`），统一推荐点分小写 `{domain}.{error_class}`，`message` 保留原文案（向后兼容，AGEN-1364 同款）：

- error_class 按状态码+语义映射：404→`not_found`、400/422→`invalid_request`/`validation_failed`、409→`conflict`、401→`unauthorized`、403→`forbidden`、413→`payload_too_large`、429→`rate_limited`、500→`internal_error`、502/503→`upstream_unavailable`、超时→`timeout`。
- domain 前缀按文件：`kb.`(knowledge)、`partners.`、`auth.`、`book.`、`mastery.`、`skills.`、`cowriter.`、`session.`、`mu.`(multi_user)、`reading.`、`preview.`、`notebook.`、`pgroup.`、`qnb.`、`settings.`、`courses.`、`plugins.`、`subagent.`、`ws.`(workspace)、`system.`、`persona.`、`files.`、`voice.`、`mcp.`、`video.`、`tasks.`、`viz.`。
- `str(exc)`/dynamic 透传类：用该域默认码（如 `kb.internal_error`）+ 原文案进 `message`，不改文本。

## 7. 分批切片建议（12 批，按测试覆盖与域内聚排序；sessions.py 已排除）

| 批 | 范围（文件） | 约数 | 优先级 | 理由 |
|---|---|---|---|---|
| B1 | space_mcp+space_cli_apps+video_learning+notebook+settings 收尾（各文件剩余纯文本，含 2 处 payload 写点） | 53 | P1 | 已有 dict_code 先例，收尾对齐基线 |
| B2 | book.py | 54 | P1 | 先例文件+最高测试覆盖 |
| B3 | auth.py | 64 | P1 | 高覆盖、独立域 |
| B4 | knowledge.py 前半（按行域切分） | ~90 | P2 | 最大文件，拆两批 |
| B5 | knowledge.py 后半 | ~83 | P2 | 同上 |
| B6 | partners.py（+1 payload） | 78 | P2 | 高覆盖 |
| B7 | reading.py+reading_extensions.py+file_preview.py+attachments+outputs+dashboard | ~70 | P2 | reading 域内聚 |
| B8 | mastery_path.py+question_notebook.py+courses.py+courses_state+learning_journal | ~72 | P2 | 学习域内聚 |
| B9 | co_writer.py+skills.py+subagents.py | ~74 | P3 | 生成/技能域 |
| B10 | multi_user.py+partner_groups.py+multi_user 包 3 文件 | ~57 | P3 | 多用户域 |
| B11 | workspace+system+plugins+personas+file_library+voice+mcp_settings+task_board+visualizers+imports+api/main | ~75 | P3 | 平台杂项扫尾 |
| B12 | memory.py+services/capabilities 层 payload 与 helper 写点 | ~40 | P4 | 非路由写点，需单独设计（含审计/进度 detail，仅记录不强制改） |

各批为文件分组，逐点精确数见 §4 与明细 CSV；批次数合计 ≈807（836 减 sessions.py 29，payload 写点就近归并）。每批一张改造卡：契约测试断言 `detail.code/message` 结构且 `message` 文本不变（同 AGEN-1364 验收口径），不改无关路由。

## 8. 复现

```bash
python3 evidence/scan-detail-code-envelope-20261011/tools/scan_detail.py \
  --repo . --out evidence/scan-detail-code-envelope-20261011
```
