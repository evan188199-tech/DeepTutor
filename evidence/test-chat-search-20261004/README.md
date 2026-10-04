# evidence/test-chat-search-20261004 — 会话历史搜索回归补测（#1678 场景）

分支：`test/chat-history-search-20261004`（基于上游 origin/main `ef2d9e5c3`，release v1.6.12）

## 结论（跑通：PASS）

新增守护测试 `tests/services/session/test_chat_history_search.py`：**10 passed**。

```
python -m pytest tests/services/session/test_chat_history_search.py -v
# 10 passed in 0.39s
```

既有相关套件无回归：

```
python -m pytest tests/services/session/test_history_search.py tests/api/test_session_search.py tests/services/workspace/test_navigation.py
# 13 passed in 1.08s
```

附带说明：同目录全量跑 `tests/services/session/` 时 `test_model_history.py` 有 1 例失败，原因是工作树缺少 gitignore 的运行时配置 `data/user/settings/agents.yaml`（仅存在于主检出），与本卡改动无关。

## 与 #1678 的对应关系

#1678（v1.6.12）报告：聊天历史搜索匹配不到会话中明确存在的文本。关联修复 PR #1683 定位根因在 web 前端：历史页此前只在浏览器本地按标题和最后一条消息过滤，未调用服务端搜索 API；服务端链路（SQLite `INSTR(LOWER(...))` 字面子串匹配标题+全部 user/assistant 消息）在 origin/main 上已支持全文检索。

因此本卡测试在 origin/main 上**全部通过**，属于「守护测试」而非「失败锁定」：一旦未来有人把服务端匹配退化回"仅标题/最后一条消息"（即 #1678 的服务端镜像场景），以下用例会立即失败：

- `test_exact_substring_in_earlier_user_message_is_found`（精确子串命中：较早 user 消息、非标题非最后一条）
- `test_exact_substring_in_assistant_reply_wins_as_latest_visible_match`（assistant 回复命中、取最新可见匹配、排除 system 消息）
- `test_case_differences_do_not_block_matches`（大小写差异不阻断命中）
- `test_outer_whitespace_is_trimmed_and_matching_stays_literal`（首尾空白可忽略；无分词、纯字面匹配——词序颠倒/内部空格不一致不命中）
- `test_empty_or_blank_queries_return_empty_results` + `test_term_without_any_hit_reports_an_empty_page`（空查询/空白查询返回空结果页）
- `test_query_construction_trims_whitespace_and_bounds_length`（查询构造：trim + 200 字符上限）
- `test_match_excerpt_windows_around_the_hit_case_insensitively`（摘录窗口围绕命中、大小写不敏感、≤320 字符）
- `test_search_endpoint_serves_transcript_matches_and_rejects_blank_queries`（REST 检索入口：命中返回、空白 400、无命中空页）
- `test_all_workspaces_entry_finds_message_text_in_other_workspaces`（all_workspaces 入口：跨 workspace 合并检索命中消息文本）

覆盖链路：检索入口（REST `/api/sessions/search`、`session_index` 跨工作区）→ 查询构造（`normalize_search_query`）→ 匹配/分词（SQLite 字面子串、大小写不敏感、可见 transcript 全文、无分词）→ 空结果（store 空页、REST 400/空页）。

## 产品代码改动

无（验收 3）。仅新增测试文件与本证据目录。
