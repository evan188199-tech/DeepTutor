# 测试覆盖空白 Top 15（按风险排序）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），2026-10-02。
后端总计 **75.69%**（128,732 语句 / 缺失 31,295）；前端总计 **28.11% statements / 29.24% lines**（47,855 语句，397 个文件 0% 覆盖，共 19,814 条语句从未被触碰）。

排序依据：风险 = 缺口规模 × 关键度（判分/引用等正确性 > 数据完整性入口 > 用户主路径 > IM 通道 > 纯函数）。每项含：现状数字 → 空白原因与风险 → 建议测试（可直接拆成一张 ≤25 行补测卡，实施时以实际 API 形状为准）。

---

## 1. `deeptutor/api/routers/knowledge.py`（后端）— 758 缺失 / 68.0%
- 原因：KB 上传/索引/删除是数据完整性主入口，仅 Happy-path 被碰过；`_writable_kb`、`_build_unique_task_id`、链接文件夹同步等分支全空。
- 建议卡：`tests/api/routers/test_knowledge_upload_guards.py` — ① 不支持类型/超限文件 → 4xx 且无半成品索引；② 重复任务 ID 幂等；③ 删除文档后列表与磁盘一致。

## 2. `web/features/chat/components/ChatWorkspace.tsx`（前端）— 1074 缺失 / 0%
- 原因：聊天主 UI 从未被任何 vitest 文件 import；流式状态切换、错误横幅全部无回归保护。
- 建议卡：`web/tests/chat/ChatWorkspace.smoke.test.tsx` — ① 空会话渲染冒烟；② mock `ChatStateAdapter` 注入流式事件，断言状态迁移与错误态展示。

## 3. `deeptutor/api/routers/quiz_judge.py`（后端）— 192 缺失 / 9.4%
- 原因：判分正确性风险最高（9.4% 覆盖）；`_build_judge_user_prompt`、`_guess_image_mime`、WS 判分循环几乎全空。
- 建议卡：`tests/api/routers/test_quiz_judge_unit.py` — ① 判分 prompt 组装含题目+答案+图片 mime；② 正确/错误/多答案三种判定；③ WS 断连时资源清理。

## 4. `deeptutor/agents/research/utils/citation_manager.py`（后端）— 264 缺失 / 37.0%
- 原因：引用编号与来源映射直接决定报告可信度（幻觉风险面），payload 容错分支缺失。
- 建议卡：`tests/agents/research/test_citation_manager_payloads.py` — ① `_rag_source_payload` 对空/残缺 answer_data 容错；② 编号连续且不重复；③ 来源缺失时降级不抛错。

## 5. `web/features/knowledge/api/client.ts`（前端）— 304 缺失 / 13.9%
- 原因：前端 KB 数据层，纯 fetch+缓存逻辑易测；`invalidateKnowledgeCaches` 失效链路未验证。
- 建议卡：`web/tests/knowledge/client.test.ts` — ① `listKnowledgeBases`/`getEmbeddingUsage` 请求形状与 4xx 处理；② `invalidateKnowledgeCaches` 后强制回源。

## 6. `deeptutor/book/engine.py`（后端）— 506 缺失 / 46.5%
- 原因：书籍生成引擎是最长多阶段流程，失败重试/断点续跑分支未测，出错代价高（长任务报废）。
- 建议卡：`tests/book/test_engine_stage_transitions.py` — ① 阶段顺序推进；② 单阶段失败→重试不重复产出；③ 取消后状态可恢复。

## 7. `deeptutor/agents/research/pipeline.py`（后端）— 408 缺失 / 62.6%
- 原因：deep_research 的 rephrase→decompose→research→report 编排只有局部覆盖，阶段间契约松散。
- 建议卡：`tests/agents/research/test_pipeline_stage_contract.py` — ① 四阶段顺序与产物字段；② 检索为空时短路到报告；③ 单元 mock LLM。

## 8. `deeptutor/knowledge/manager.py`（后端）— 329 缺失 / 73.7%
- 原因：KB 管理核心（增删查、元数据），被 knowledge 路由与 CLI 共用，缺口影响面广。
- 建议卡：`tests/knowledge/test_manager_crud_edges.py` — ① 文档增删后列表/计数一致；② 名称冲突与空 KB 边界；③ 并发写同一 KB 的锁语义（如实现有）。

## 9. `deeptutor/partners/channels/feishu.py`（后端）— 495 缺失 / 55.5%
- 原因：IM 通道里缺口最大的在用通道；消息解析/媒体下载/回复路由错误即用户可见故障。
- 建议卡：`tests/services/partners/test_feishu_message_parsing.py` — ① 文本/富文本/媒体消息解析；② 回复目标路由（私聊 vs 群聊）；③ 回调签名/错误码分支（mock SDK）。

## 10. `web/lib/memory-graph.ts`（前端）— 314 缺失 / 0%
- 原因：纯函数库零依赖，补测成本最低；`parseDoc`/`splitRef`/`buildGraph` 是记忆图谱正确性根基。
- 建议卡：`web/tests/lib/memory-graph.test.ts` — ① `parseDoc` 空/畸形输入；② `splitRef` 非法 ref；③ `buildGraph` 空 slots 与跨 surface 引用。

## 11. `deeptutor/api/routers/reading.py`（后端）— 279 缺失 / 66.9%
- 原因：沉浸阅读进度/选区 API 主路径过半未覆盖，进度丢失类 bug 难被现有测试捕获。
- 建议卡：`tests/api/routers/test_reading_progress.py` — ① 进度保存→取回一致；② 重复保存幂等；③ 非法 payload 4xx。

## 12. `web/features/settings/store/SettingsStore.tsx`（前端）— 354 缺失 / 52.2%
- 原因：全局设置状态与持久化归一化，`persistUiSettingsPatch`/`syncLoadedCodeBlockSettingsToAppShell` 回归直接改坏所有用户偏好。
- 建议卡：`web/tests/settings/settings-store.test.tsx` — ① patch 后本地存储与 store 同步；② 非法值归一化不抛错；③ 目录/TOUR_STEPS 常量完整性。

## 13. `deeptutor/services/session/pocketbase_store.py`（后端）— 225 缺失 / 72.6%
- 原因：会话持久化层，错误分支（网络失败、字段缺失回退）未测，存在静默丢数据风险。
- 建议卡：`tests/services/session/test_pocketbase_store_fallbacks.py` — ① upsert 失败重试/降级；② 读取字段缺失时的默认值；③ 列表分页边界。

## 14. `web/lib/markdown-display.ts`（前端）— 206 缺失 / 40.3%
- 原因：Markdown 渲染与 HTML 转义是 XSS 防护面，`escapeUnknownHtmlTagsForDisplay`/`safeDecodeURIComponent`/强调修复函数分支复杂。
- 建议卡：`web/tests/lib/markdown-display-security.test.ts` — ① 未知标签转义（script/iframe 样本）；② 编码 URI 二次解码安全；③ 畸形 `**` 修复不变式：修复前后纯文本一致。

## 15. `deeptutor/agents/question/pipeline.py`（后端）— 283 缺失 / 65.6%
- 原因：deep_question 的 ideation→generation 链路产物契约未锁定，改 prompt 易静默破坏下游。
- 建议卡：`tests/agents/question/test_pipeline_output_contract.py` — ① 两阶段产物字段契约（mock LLM）；② 空知识点输入边界；③ 生成失败时的错误事件。

---

### 备选（第 16-20 位，按需扩卡）
- `web/components/quiz/QuizViewer.tsx` — 366 缺失 / 0%
- `deeptutor/partners/channels/telegram.py` — 418 缺失 / 30.2%
- `deeptutor/runtime/launcher.py` — 295 缺失 / 66.7%
- `web/features/chat/ChatStateAdapter.tsx` — 352 缺失 / 64.9%
- `deeptutor/api/routers/co_writer.py` — 246 缺失 / 40.0%

### 已知测试失败（origin/main 既有，与本清单无关）
- `tests/agents/chat/test_runtime_context.py` 3 例：日期断言跨本地时区（UTC-7）差一天（期望 2026-08-17，实际 2026-08-16）。
- `tests/services/sandbox/test_sandbox.py::test_runner_server_executes_and_truncates_output`：沙箱内 runner exit 127（命令缺失），环境性失败。
