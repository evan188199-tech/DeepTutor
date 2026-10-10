# 剩余可领取种子清单（claimable 2026-10-10）

口径：三态中「仍可建卡」的种子，按轴与报告内优先序排列；领卡前按 seed-ledger.md 同行复核当日看板（本台账匹配基于 2026-10-10 抓取的 1370 张卡）。

总计 131 条可领取。轴分布：E=3，D=9，C=12，F=107

## E 轴：错误消息 Top15 残留（3）

| ID | # | 内容 | 备注 |
|---|---|---|---|
| E13 | #13 | LANG-MIX：后端 routers 不走 t()、web 硬编码文案绕过 locale | 残留主项：后端 routers t() 收敛无卡；已建卡子项 AGEN-905（web 9 文件）/AGEN-904（fr/pl/uk 键）/AGEN-1366（co_writer 中文 detail） |
| E14 | #14 | NO-CODE：~597 处纯文本 detail 无机器可读 code | 残留主项：系统性 code 信封无卡；子集 AGEN-1364（sessions.py 27 处）、web 侧 AGEN-880 |
| E15 | #15 | INCONSISTENT：not_found 15+ 种写法、网络失败/限流话术分裂 | 残留主项：后端 not_found 模板统一无卡；web 侧 AGEN-910、跨文件话术 AGEN-1361 |

## D 轴：通道契约修复卡（9）

| ID | 卡 | 优先 | 内容 | 备注 |
|---|---|---|---|---|
| D1 | A | P0 | feishu send 抛错语义：feishu.py:2322-2323 send 吞一切，manager 重试失效 | AGEN-262 为卡片正文/视频域，非 send 契约 |
| D2 | B | P0 | mochat send 抛错语义：mochat.py:409-410 吞一切；需同步改 test_send_failure_does_not_raise | AGEN-690/694 为解析/生命周期测试卡，不含 send 契约修复 |
| D3 | C | P0+P1 | dingtalk 投递与资源：send 失败 raise + client 超时 + stop 关闭 SDK StreamClient | AGEN-735 为解析/签名测试卡，不含本修复 |
| D7 | G | P1 | stop 清理补全：feishu lark Client/流缓冲、slack web client、telegram/mochat/dingtalk/discord/zulip 取消 await | AGEN-493 仅吞错收口（且未落 main），本卡范围为其遗留 |
| D9 | I | P1 | 事件循环阻塞治理：zulip 鉴权/deregister+join、msteams shutdown/join、weixin 媒体加密移出循环 | AGEN-998 为全仓 async 阻塞扫描轴、AGEN-861 为 zulip 测试侧，均非本修复 |
| D10 | J | P2 | 入站幂等补齐：msteams/discord/slack/dingtalk 入站去重缺口 | AGEN-493 是 stop 幂等，非入站幂等 |
| D11 | K | P1 | qq/wecom 易失状态：qq 路由缓存未命中兜底发错 API；wecom frame 缺失静默丢 | AGEN-736/1051 为解析/收发测试卡，不含本修复 |
| D12 | L | P2 | 发送超时归一：slack/wecom/qq/whatsapp/feishu/dingtalk 发送路径补超时 | AGEN-578 为 HTTP 客户端超时扫描轴 |
| D13 | M | P2 | not-running 契约文档化：base.py 注明未运行时 send 预期行为并统一 16 通道 | - |

## C 轴：weak100 未建卡（12，triage 分序）

| ID | rank | 模块 | LOC | fanin | 风险 | 建议测试焦点 |
|---|---|---|---:|---:|---|---|
| C19 | 19 | `runtime.agentic.labels` | 173 | 3 | 高 | 「Protocol-label parsing for streaming LLM」覆盖 strip_label_probe_prefix/classify_label/recover_finished_label/find_inline_labels 契约与边界＋启动/装配失败路径 |
| C25 | 25 | `services.session.workspace_preferences` | 55 | 6 | 高 | 「Canonical workspace ownership stored on」覆盖 upgrade_workspace_preferences 契约与边界＋异常/降级分支 |
| C41 | 41 | `services.llm.provider_core.codebuddy_http_provider` | 258 | 3 | 中 | 「CodeBuddy provider that talks to the cloud」覆盖 normalize_api_key/CodeBuddyHTTPProvider/codebuddy_http_available/sdk_installed 契约与边界＋超时/限流/畸形响应分支 |
| C44 | 44 | `services.parsing.engines.tika.formats` | 217 | 3 | 中 | 「Apache Tika 4 input-format routing hints.」覆盖 tika_version_is_current 契约与边界＋异常/降级分支 |
| C46 | 46 | `learning.event_hub` | 140 | 3 | 中 | 「Low-latency wake-up channel for durable」覆盖 TopicSignal/TopicSubscription/MasteryTopicEventHub/publish_topic_signal 契约与边界＋异常/降级分支 |
| C47 | 47 | `services.parsing.engines.markitdown.formats` | 102 | 3 | 中 | 「MarkItDown version and built-in」覆盖 markitdown_supported_formats/installed_markitdown_version/markitdown_version_is_current 契约与边界＋异常/降级分支 |
| C49 | 49 | `services.workspace.navigation` | 81 | 3 | 中 | 「Account navigation across content stores」覆盖 read_workspace_indexes/session_index 契约与边界＋异常/降级分支 |
| C62 | 62 | `services.memory.consolidator.runs` | 405 | 2 | 中 | 「Persistent, cancellable consolidator runs.」覆盖 RunEvent/UndoCheckpoint/Run/RunBusyError 契约与边界＋异常/降级分支 |
| C78 | 78 | `services.rag.pipelines.llamaindex.vector_store` | 288 | 2 | 中 | 「Vector-store backend selection for the」覆盖 faiss_available/faiss_write_index/faiss_read_index/new_faiss_storage_context 契约与边界＋异常/降级分支 |
| C80 | 80 | `api.routers.task_board` | 28 | 1 | 高 | 「Authenticated task board endpoints using」覆盖 get_board/create_card/update_card 契约与边界＋失败/4xx 分支 |
| C82 | 82 | `services.rag.linked_kb` | 237 | 2 | 中 | 「Probe an external folder before mounting it」覆盖 EmbeddingCompat/ProbeResult/provider_is_linkable/allowed_link_roots 契约与边界＋异常/降级分支 |
| C89 | 89 | `services.workspace.session_move` | 138 | 2 | 中 | 「Move conversations with the same verified」覆盖 move_chat/migrate_legacy_bindings 契约与边界＋异常/降级分支 |

## F 轴：zero96 未建卡（31，LOC 降序=基线序）

| ID | 模块 | LOC | fanin | 备注 |
|---|---|---:|---:|---|
| FZ14 | `services.memory.consolidator.modes._runtime` | 319 | 4 | - |
| FZ20 | `partners.channels.qq` | 203 | 0 | - |
| FZ27 | `book.blocks._rag_helpers` | 142 | 2 | - |
| FZ28 | `services.search.providers.zhipu` | 142 | 0 | - |
| FZ30 | `services.search.providers.firecrawl` | 136 | 0 | - |
| FZ33 | `book.blocks.animation` | 133 | 2 | - |
| FZ41 | `book.blocks.interactive` | 113 | 2 | - |
| FZ45 | `services.search.providers.searxng` | 104 | 1 | - |
| FZ49 | `agents.math_animator.agents.visual_review_agent` | 100 | 1 | - |
| FZ51 | `capabilities.reading._tool_base` | 86 | 2 | - |
| FZ53 | `agents.visualize.agents.review_agent` | 75 | 1 | - |
| FZ54 | `book.blocks.flash_cards` | 74 | 2 | - |
| FZ56 | `book.blocks.deep_dive` | 70 | 2 | - |
| FZ59 | `services.practice.analytics` | 67 | 1 | - |
| FZ60 | `book.blocks.timeline` | 66 | 2 | - |
| FZ64 | `services.search.providers.duckduckgo` | 65 | 0 | - |
| FZ65 | `book.blocks.callout` | 64 | 2 | - |
| FZ70 | `services.mcp.session_state` | 59 | 2 | - |
| FZ72 | `services.rag.pipelines.llamaindex.errors` | 59 | 1 | - |
| FZ73 | `runtime.worker_tasks` | 56 | 0 | - |
| FZ77 | `knowledge.progress_events` | 45 | 2 | - |
| FZ84 | `services.parsing.engines.formats` | 29 | 1 | - |
| FZ85 | `core.response_languages` | 28 | 2 | - |
| FZ86 | `book.blocks.user_note` | 26 | 2 | - |
| FZ88 | `services.session.turns.context_assembler` | 20 | 1 | - |
| FZ91 | `agents.notebook._text` | 14 | 2 | - |
| FZ92 | `__version__` | 11 | 2 | - |
| FZ93 | `response_languages` | 8 | 2 | - |
| FZ94 | `book.errors` | 8 | 2 | - |
| FZ95 | `__main__` | 6 | 0 | - |
| FZ96 | `services.llm.provider_registry` | 3 | 0 | 仅相关卡（guide/docs/scan/review，不构成领取去重）：AGEN-1265 |

## F 轴：weak tail 有焦点种子（16，AGEN-1315 已给焦点）

| ID | rank | 模块 | LOC | fanin | 焦点来源 | 焦点 |
|---|---|---|---:|---:|---|---|
| FT1 | 101 | `services.parsing.engines.liteparse.formats` | 58 | 2 | ★AGEN-1315 | LiteParse 解析引擎的版本下限与支持格式声明；焦点：installed_liteparse_version/liteparse_version_is_current 的版本比较边界与缺失/畸形版本串降级（纯函数、无网络，易测）。 |
| FT24 | 124 | `knowledge.naming` | 40 | 3 | ★AGEN-1315 | 知识库命名校验助手；焦点：validate_knowledge_base_name 合法字符/长度边界与非法输入的错误信息契约。 |
| FT64 | 164 | `textbook_struct.chapter_rebuild` | 273 | 2 | ★AGEN-1315 | 从 MinerU layout.json 分层重建章节结构；焦点：rebuild 层级聚合、merge_adjacent 相邻合并规则、assign_page_ranges 页码区间单调且全覆盖、空/畸形 layout 降级。 |
| FT67 | 167 | `agents.vision_solver.vision_solver_agent` | 205 | 2 | ★AGEN-1315 | 单次调用图片→GeoGebra 命令生成的 Agent；焦点：mock LLM 返回的解析契约、请求参数校验与透传、失败/超时路径（全 mock 不触网）。 |
| FT69 | 169 | `services.setup.data_volume` | 197 | 2 | ★AGEN-1315 | 运行数据卷可写性探测与属主诊断；焦点：parse_id/resolve_runtime_ids 边界、describe_path_ownership、format_data_volume_permission_error 文案契约（文件系统相关用例走 tmp_path/mock）。 |
| FT70 | 170 | `reading.knowledge_capture` | 177 | 2 | ★AGEN-1315 | 阅读标注→Notebook/Mastery 持久来源转换；焦点：organize_workspace_notes 分组去重、mastery_source_records 记录形态、send_workspace_to_notebook 失败分支（mock 存储层）。 |
| FT71 | 171 | `services.session.event_preview` | 154 | 2 | ★AGEN-1315 | 会话详情响应使用的有界事件预览；焦点：compact_trace_preview 空/超长截断/unicode 边界与不可序列化事件的降级。 |
| FT73 | 173 | `services.partners.runtime_status` | 132 | 2 | ★AGEN-1315 | Partner 运行时状态的共享无凭据仓储（sqlite 存储）；焦点：仓储读写幂等、缺表初始化、并发读写一致性（tmp_path sqlite）。 |
| FT75 | 175 | `textbook_struct.page_headers` | 100 | 2 | ★AGEN-1315 | 页眉驱动的章节重建 v0.2（与 layout 驱动互为备份）；焦点：normalize_header_chapter 归一化、page_facts 事实提取、rebuild_from_headers 与 chapter_rebuild 基线的一致性。 |
| FT78 | 178 | `services.settings.starter_settings` | 82 | 2 | ★AGEN-1315 | 起始建议（starter suggestion）设置的读写；焦点：get_starter_settings/save_starter_settings 缺省值、畸形文件降级、保存后回读一致。 |
| FT79 | 179 | `agents._shared.json_output` | 76 | 2 | ★AGEN-1315 | Agent 结构化模型输出解析的共享助手；焦点：extract_json_object 的噪声前后缀/嵌套围栏输入，及与 utils.json_parser 的契约一致性。 |
| FT81 | 181 | `services.web_source.navigation` | 72 | 2 | ★AGEN-1315 | web 来源 KB 的导航树构建；焦点：flat_to_tree 层级组装（孤儿节点/环输入容错）、build_navigation_manifest 排序与去重契约。 |
| FT82 | 182 | `logging.formatters` | 54 | 2 | ★AGEN-1315 | DeepTutor stdlib logging 管道的格式化器（ContextFilter/JsonlFormatter/ConsoleFormatter）；焦点：record→JSONL 字段契约、缺上下文字段时行为、Console 输出快照回归。 |
| FT86 | 186 | `services.partners.workspace_binding` | 48 | 2 | ★AGEN-1315 | Partner 绑定属主已注册内容工作区的校验与内容上下文；焦点：validate_partner_workspace 的拒绝路径（非属主/不存在 workspace）、partner_content_context 组装契约。 |
| FT87 | 187 | `services.practice.answers` | 44 | 2 | ★AGEN-1315 | 练习客观题保守判分（prose 走 self-assessment）；焦点：check_answer 等值/数值/多选判分边界与无法客观判定时的回退行为。 |
| FT88 | 188 | `utils.text_display` | 31 | 2 | ★AGEN-1315 | 学习者可见文本中密集 \uXXXX 双重转义的显示解码；焦点：decode_escaped_unicode_for_display 密集 run 阈值（3+）、BMP 外 surrogate 对合并、非文本 run 保留原样与幂等性。 |

## F 轴：weak tail 无焦点种子（60，拆卡前需自审职责）

| ID | rank | 模块 | LOC | fanin | 焦点 | 备注 |
|---|---|---|---:|---:|---|---|
| FT13 | 113 | `services.rag.pipelines.llamaindex.exercise_lookup` | 373 | 1 | 无焦点 | - |
| FT20 | 120 | `capabilities.setup.jobs` | 280 | 1 | 无焦点 | - |
| FT33 | 133 | `services.subagent.openclaw` | 197 | 1 | 无焦点 | - |
| FT34 | 134 | `capabilities.reading.figure_view` | 180 | 1 | 无焦点 | - |
| FT35 | 135 | `video_learning.invidious_account_storage` | 177 | 1 | 无焦点 | - |
| FT37 | 137 | `tools.cron_tool` | 142 | 1 | 无焦点 | - |
| FT39 | 139 | `services.rag.pipelines.lightrag.cache_reuse` | 137 | 1 | 无焦点 | - |
| FT40 | 140 | `tools.zotero_search` | 136 | 1 | 无焦点 | - |
| FT41 | 141 | `services.llm.image_caption_batch` | 135 | 1 | 无焦点 | - |
| FT42 | 142 | `services.rag.pipelines.llamaindex.rerank` | 130 | 1 | 无焦点 | - |
| FT44 | 144 | `services.subagent.partner_group` | 118 | 1 | 无焦点 | - |
| FT46 | 146 | `book.overview_copy` | 104 | 1 | 无焦点 | - |
| FT50 | 150 | `services.imagegen.adapters.openai_compat` | 98 | 1 | 无焦点 | - |
| FT51 | 151 | `services.parsing.engines.mineru.checkpoints` | 98 | 1 | 无焦点 | - |
| FT52 | 152 | `services.voice.adapters.minimax` | 91 | 1 | 无焦点 | - |
| FT53 | 153 | `video_learning.invidious_account_client` | 85 | 1 | 无焦点 | - |
| FT54 | 154 | `services.rag.smart_retriever` | 81 | 1 | 无焦点 | - |
| FT56 | 156 | `services.llm.request_cache` | 73 | 1 | 无焦点 | - |
| FT57 | 157 | `services.rag.pipelines.graphrag.pandas_compat` | 68 | 1 | 无焦点 | - |
| FT65 | 165 | `services.llm.usage_estimation` | 45 | 1 | 无焦点 | - |
| FT91 | 191 | `services.search.providers.serply` | 174 | 0 | 无焦点 | - |
| FT92 | 192 | `services.search.providers.aliyun_iqs` | 163 | 0 | 无焦点 | - |
| FT93 | 193 | `services.search.providers.tavily` | 162 | 0 | 无焦点 | - |
| FT94 | 194 | `services.search.providers.perplexity` | 157 | 0 | 无焦点 | - |
| FT95 | 195 | `services.search.providers.qianfan` | 149 | 0 | 无焦点 | - |
| FT96 | 196 | `services.search.providers.bocha` | 132 | 0 | 无焦点 | - |
| FT99 | 199 | `services.rag.pipelines.lightrag.parser` | 99 | 0 | 无焦点 | - |
| FT100 | 200 | `services.search.providers.brave` | 77 | 0 | 无焦点 | - |
| FT101 | 201 | `agents.loop.dsml_tool_calls` | 292 | 1 | 无焦点 | - |
| FT104 | 204 | `agents.math_animator.agents.code_generator_agent` | 261 | 1 | 无焦点 | - |
| FT105 | 205 | `services.llm.telemetry` | 46 | 0 | 无焦点 | - |
| FT107 | 207 | `services.settings.registry_edit` | 224 | 1 | 无焦点 | - |
| FT108 | 208 | `services.practice.importing` | 212 | 1 | 无焦点 | - |
| FT110 | 210 | `services.cron.executor` | 198 | 1 | 无焦点 | - |
| FT112 | 212 | `agents.loop.ask_user_drafts` | 193 | 1 | 无焦点 | - |
| FT113 | 213 | `services.videogen.adapters.async_task` | 182 | 1 | 无焦点 | - |
| FT114 | 214 | `agents.math_animator.retry_manager` | 160 | 1 | 无焦点 | - |
| FT115 | 215 | `services.session.attachment_parsing` | 158 | 1 | 无焦点 | - |
| FT116 | 216 | `services.config.settings_presets` | 135 | 1 | 无焦点 | - |
| FT117 | 217 | `services.partners.channel_state_migration` | 127 | 1 | 无焦点 | - |
| FT118 | 218 | `agents.notebook.summarize_agent` | 120 | 1 | 无焦点 | - |
| FT119 | 219 | `agents.question.agents.followup_agent` | 118 | 1 | 无焦点 | - |
| FT120 | 220 | `agents.visualize.agents.code_generator_agent` | 117 | 1 | 无焦点 | - |
| FT121 | 221 | `agents.math_animator.agents.concept_analysis_agent` | 97 | 1 | 无焦点 | - |
| FT122 | 222 | `agents.research.utils.json_utils` | 94 | 1 | 无焦点 | - |
| FT123 | 223 | `logging.configure` | 81 | 1 | 无焦点 | - |
| FT124 | 224 | `agents.math_animator.agents.summary_agent` | 78 | 1 | 无焦点 | - |
| FT125 | 225 | `services.sandbox.quota` | 78 | 1 | 无焦点 | - |
| FT126 | 226 | `agents.question.request_config` | 77 | 1 | 无焦点 | - |
| FT127 | 227 | `agents.math_animator.agents.concept_design_agent` | 76 | 1 | 无焦点 | - |
| FT128 | 228 | `services.settings.provider_edit` | 60 | 1 | 无焦点 | - |
| FT129 | 229 | `services.codex_auth.client_version` | 55 | 1 | 无焦点 | - |
| FT131 | 231 | `agents.math_animator.duration_utils` | 36 | 1 | 无焦点 | - |
| FT132 | 232 | `logging.loguru_bridge` | 28 | 1 | 无焦点 | - |
| FT133 | 233 | `services.session.turns.resource_reuse` | 18 | 1 | 无焦点 | - |
| FT135 | 235 | `agents.question.coordinator` | 242 | 0 | 无焦点 | - |
| FT138 | 238 | `reading.vocabulary` | 131 | 0 | 无焦点 | - |
| FT139 | 239 | `reading.study_guidance` | 103 | 0 | 无焦点 | - |
| FT140 | 240 | `utils.network.circuit_breaker` | 88 | 0 | 无焦点 | - |
| FT141 | 241 | `core.errors` | 57 | 0 | 无焦点 | - |

## 附：部分已建卡、残留子项可续卡

- E6（供应商响应体透传）：主体已建卡 AGEN-779/1277；残留 `generation_http.py:80` resp.text 拼接在 main 且无修复卡，可续卡
- D7（stop 清理补全）：AGEN-493 已覆盖 6 通道吞错收口（未落 main）；feishu/slack/telegram 等资源关闭与取消 await 仍无卡
- E13/E14/E15 按残留主项已列入上方可领取清单，其已建卡子项见 seed-ledger.md 轴 E 备注

