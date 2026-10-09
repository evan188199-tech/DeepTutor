# weak242 顺位（top100 之外）tail 补测种子 triage（20261009）

## 输入与边界
- 上游排序：myfork `scan/weak-top100-triage-20261008` `evidence/weak-triage-20261008/triage.py`（AGEN-1154 产物）在本机复算，内建断言 weak242/top100/zero200 与 `scan/coverage-gaps-20261007/summary.json` 全部一致后才取数（根 commit `f07029cf` = v1.6.13）
- 注：该卡说明中提到的 `triage_top60.json` 未提交在其分支上（实际仅有 triage.md/triage.py/SHA256SUMS）；本卡按脚本内建输出 rows.json 复现同一全排序
- 筛选：顺位 >100（top100 之外共 142 个）∩ `fanin≥2`（24 个）∩ 非 weak242 DONE60 → 剔除 `services.github_source.sync_service`（AGEN-1011 in_progress 明确覆盖 client/sync/sync_service）→ **入选 23 个**
- 本卡只读扫描：全部入选文件在 origin/main（`6cf793bd` = v1.6.14）逐一存在并复核 LOC/职责；除 `utils.text_display`（31→39 行，表内标 ⚠）外均无 `f07029cf..origin/main` 漂移

## 去重口径
- weak242 DONE 索引（60 个）：沿用 20261008 triage 的 DONE 映射，tail 区间内 fanin≥2 且 DONE 的仅 `agents.loop.context_budget`（AGEN-1053），已剔除
- 项目全库（backlog/todo/in_progress/in_review/blocked/cancelled/done 共 151 卡，2026-10-09 抓取）：按模块 dotted 名与 path 逐一匹配，23 个入选模块均无建卡命中；松散词命中 3 卡（AGEN-1011 github_source 轴、AGEN-963 base_sync 修复、AGEN-1260 前端 hook）均不指向入选模块
- 建卡时建议沿用 `test/` 前缀与既有去重轴（web_source 同步轴归 test-web-source-sync，导航模块不在其范围）

## 入选清单（23 个，按顺位）
| 顺位 | 模块 | path | fanin | LOC(main) | 风险 | 职责与建议测试焦点 | 去重 |
|-----:|------|------|------:|----------:|------|--------------------|------|
| 101 | `services.parsing.engines.liteparse.formats` | `deeptutor/services/parsing/engines/liteparse/formats.py` | 2 | 58 | 中 | LiteParse 解析引擎的版本下限与支持格式声明；焦点：installed_liteparse_version/liteparse_version_is_current 的版本比较边界与缺失/畸形版本串降级（纯函数、无网络，易测）。 | 未建卡 |
| 109 | `reading.epub_bilingual` | `deeptutor/reading/epub_bilingual.py` | 3 | 248 | 中 | EPUB 双语配对元数据的显式管理与候选推荐（增删查）；焦点：recommend_epub_candidates 匹配排序、create/delete 配对的幂等与删除不存在 material 的容错、list 配对返回排序稳定。 | 未建卡 |
| 119 | `services.singleflight_cache` | `deeptutor/services/singleflight_cache.py` | 3 | 78 | 中 | 进程内 TTL 缓存 + 每 key 单飞 async 生产者；焦点：并发同 key 只创建一次生产任务（coalescing）、TTL 过期后重建、limit/ttl 非法参数拒绝、生产者异常不污染缓存（asyncio 测试）。 | 未建卡 |
| 124 | `knowledge.naming` | `deeptutor/knowledge/naming.py` | 3 | 40 | 中 | 知识库命名校验助手；焦点：validate_knowledge_base_name 合法字符/长度边界与非法输入的错误信息契约。 | 未建卡 |
| 125 | `core.assessment` | `deeptutor/core/assessment.py` | 3 | 15 | 中 | 评估域共享 Literal 值对象（生产者/持久化/HTTP 三方契约源）；焦点：模块级导出契约冒烟，断言 4 个 frozenset 与对应 Literal get_args 一致。 | 未建卡 |
| 162 | `services.session.legacy_migration` | `deeptutor/services/session/legacy_migration.py` | 2 | 291 | 中 | 已移除的 v1 JSON 会话存储的幂等迁移器；焦点：migrate_all_legacy_chat_scopes 重复执行幂等、损坏 JSON 跳过并计入 LegacyMigrationReport、报告计数与实际迁移一致。 | 未建卡 |
| 163 | `utils.bibtex_converter` | `deeptutor/utils/bibtex_converter.py` | 2 | 287 | 中 | BibTeX→Markdown 转换（供检索索引）；焦点：bibtex_to_markdown 字段映射、多 entry 顺序保持、畸形 BibTeX 输入的降级输出不抛异常。 | 未建卡 |
| 164 | `textbook_struct.chapter_rebuild` | `deeptutor/textbook_struct/chapter_rebuild.py` | 2 | 273 | 中 | 从 MinerU layout.json 分层重建章节结构；焦点：rebuild 层级聚合、merge_adjacent 相邻合并规则、assign_page_ranges 页码区间单调且全覆盖、空/畸形 layout 降级。 | 未建卡 |
| 167 | `agents.vision_solver.vision_solver_agent` | `deeptutor/agents/vision_solver/vision_solver_agent.py` | 2 | 205 | 中 | 单次调用图片→GeoGebra 命令生成的 Agent；焦点：mock LLM 返回的解析契约、请求参数校验与透传、失败/超时路径（全 mock 不触网）。 | 未建卡 |
| 168 | `logging.stats.llm_stats` | `deeptutor/logging/stats/llm_stats.py` | 2 | 200 | 中 | LLM 调用统计（token 估算与计费聚合）；焦点：estimate_tokens/get_pricing 表驱动用例、LLMStats 聚合与导出契约、未知模型计费降级。 | 未建卡 |
| 169 | `services.setup.data_volume` | `deeptutor/services/setup/data_volume.py` | 2 | 197 | 中 | 运行数据卷可写性探测与属主诊断；焦点：parse_id/resolve_runtime_ids 边界、describe_path_ownership、format_data_volume_permission_error 文案契约（文件系统相关用例走 tmp_path/mock）。 | 未建卡 |
| 170 | `reading.knowledge_capture` | `deeptutor/reading/knowledge_capture.py` | 2 | 177 | 中 | 阅读标注→Notebook/Mastery 持久来源转换；焦点：organize_workspace_notes 分组去重、mastery_source_records 记录形态、send_workspace_to_notebook 失败分支（mock 存储层）。 | 未建卡 |
| 171 | `services.session.event_preview` | `deeptutor/services/session/event_preview.py` | 2 | 154 | 中 | 会话详情响应使用的有界事件预览；焦点：compact_trace_preview 空/超长截断/unicode 边界与不可序列化事件的降级。 | 未建卡 |
| 173 | `services.partners.runtime_status` | `deeptutor/services/partners/runtime_status.py` | 2 | 132 | 中 | Partner 运行时状态的共享无凭据仓储（sqlite 存储）；焦点：仓储读写幂等、缺表初始化、并发读写一致性（tmp_path sqlite）。 | 未建卡 |
| 174 | `utils.config_manager` | `deeptutor/utils/config_manager.py` | 2 | 129 | 中 | data/user/settings/main.yaml 的极简运行时 YAML 管理器（单例）；焦点：单例语义、mtime 缓存失效再读、缺文件/畸形 YAML 的默认值与降级。 | 未建卡 |
| 175 | `textbook_struct.page_headers` | `deeptutor/textbook_struct/page_headers.py` | 2 | 100 | 中 | 页眉驱动的章节重建 v0.2（与 layout 驱动互为备份）；焦点：normalize_header_chapter 归一化、page_facts 事实提取、rebuild_from_headers 与 chapter_rebuild 基线的一致性。 | 未建卡 |
| 178 | `services.settings.starter_settings` | `deeptutor/services/settings/starter_settings.py` | 2 | 82 | 中 | 起始建议（starter suggestion）设置的读写；焦点：get_starter_settings/save_starter_settings 缺省值、畸形文件降级、保存后回读一致。 | 未建卡 |
| 179 | `agents._shared.json_output` | `deeptutor/agents/_shared/json_output.py` | 2 | 76 | 中 | Agent 结构化模型输出解析的共享助手；焦点：extract_json_object 的噪声前后缀/嵌套围栏输入，及与 utils.json_parser 的契约一致性。 | 未建卡 |
| 181 | `services.web_source.navigation` | `deeptutor/services/web_source/navigation.py` | 2 | 72 | 中 | web 来源 KB 的导航树构建；焦点：flat_to_tree 层级组装（孤儿节点/环输入容错）、build_navigation_manifest 排序与去重契约。 | 未建卡 |
| 182 | `logging.formatters` | `deeptutor/logging/formatters.py` | 2 | 54 | 中 | DeepTutor stdlib logging 管道的格式化器（ContextFilter/JsonlFormatter/ConsoleFormatter）；焦点：record→JSONL 字段契约、缺上下文字段时行为、Console 输出快照回归。 | 未建卡 |
| 186 | `services.partners.workspace_binding` | `deeptutor/services/partners/workspace_binding.py` | 2 | 48 | 中 | Partner 绑定属主已注册内容工作区的校验与内容上下文；焦点：validate_partner_workspace 的拒绝路径（非属主/不存在 workspace）、partner_content_context 组装契约。 | 未建卡 |
| 187 | `services.practice.answers` | `deeptutor/services/practice/answers.py` | 2 | 44 | 中 | 练习客观题保守判分（prose 走 self-assessment）；焦点：check_answer 等值/数值/多选判分边界与无法客观判定时的回退行为。 | 未建卡 |
| 188 | `utils.text_display` | `deeptutor/utils/text_display.py` | 2 | 39⚠ | 中 | 学习者可见文本中密集 \uXXXX 双重转义的显示解码；焦点：decode_escaped_unicode_for_display 密集 run 阈值（3+）、BMP 外 surrogate 对合并、非文本 run 保留原样与幂等性。 | 未建卡 |

## 可测性总览
- 纯函数/值对象（无外部 I/O，易测）：liteparse.formats、knowledge.naming、core.assessment、utils.bibtex_converter、textbook_struct.chapter_rebuild、textbook_struct.page_headers、agents._shared.json_output、services.web_source.navigation、logging.formatters、utils.text_display、services.session.event_preview
- 文件 I/O（tmp_path 即可）：reading.epub_bilingual、services.session.legacy_migration、services.settings.starter_settings、utils.config_manager
- 并发/asyncio（需事件循环用例）：services.singleflight_cache
- sqlite 仓储（tmp_path + 并发用例）：services.partners.runtime_status
- 进程/属主探测（mock os API 为主）：services.setup.data_volume
- 需 mock LLM/服务层：agents.vision_solver.vision_solver_agent、logging.stats.llm_stats（计费表可纯测）、reading.knowledge_capture
- 契约/守卫类：services.partners.workspace_binding、services.practice.answers

## 复现
1. `git archive` 提取 `myfork/scan/coverage-gaps-20261007` 的 evidence 与 `myfork/scan/weak-top100-triage-20261008` 的 triage.py 至临时目录
2. `python3 triage.py <临时目录>`（脚本断言 fanin/weak242/top100/zero200 与 summary.json 一致）→ rows.json 为 242 模块全排序
3. 按 `顺位>100 ∧ fanin≥2 ∧ 未 DONE ∧ 非 AGEN-1011 范围` 过滤得 23 个，再在 origin/main 逐文件复核 LOC 与职责

## 附注
- 全部 23 个风险为「中」（fanin=2-3、非路由/启动面）；top100 之外 fanin≥5 或 bonus=2 的模块不存在，尾部含 fanin=1 的 117 个本卡未纳入
- `utils.text_display` 在 `f07029cf..origin/main` 有改动（+8 行），拆卡前以 origin/main 当前实现为准
