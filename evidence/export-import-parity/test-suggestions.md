# 补测建议（不实现，仅建议；映射去重轴）

现有测试面（本卡只读确认）：
- `web/tests/partner-group-export.test.ts`（chat-export 轴）
- `web/tests/chat-import-chatgpt.spec.ts`、`web/tests/chat-import-codex.spec.ts`、
  `web/tests/imports-api.spec.ts`
- `tests/api/test_imports.py`、`tests/services/session/test_import_session.py`
- claude-code 适配器暂无 web 端 spec（对应独立卡 test-web-chat-import-claude-code）。

## 轴 1：test-chat-export（web/lib/chat-export.ts）
1. 空内容消息导出为"仅标题"区块（chat-export.ts:62-63）——当前无断言。
2. capability 后缀 ` _(cap)_` 与 speaker 单行净化（:28-31,60）。
3. 未知角色（如 `tool`）标题回退 `"System"`（:21-25）（G14）。
4. 文件名净化：全非法字符输入 → `"chat"`（:69-75）。
5. 建议新增（矩阵驱动，G8/G13）：`buildChatMarkdown` 接受可选 `createdAt`/`metadata`
   的接口演进预留测试位——先固化"当前不导出"的契约，防止无意识变更。

## 轴 2：test-web-chat-import-claude-code（claude-code.ts，尚无 spec）
1. `ai-title` 位于 64KB 头部之外：scan 预读标题 ≠ parse 标题（G11，
   claude-code.ts:24,94-107 vs :151-152,167）。
2. 图片 turn：`metadata:{had_images:true}` 断言（:53-57,73）。
3. `isSidechain`/`isMeta` 行与 tool/thinking block 丢弃（:55,62）。
4. 目录名有损还原 `-`→`/` 仅在无 cwd 记录时生效（:36-40,97-99）（G6）。
5. 空内容行丢弃、`<system-reminder>` 剥离（shared.ts:14-18）。

## 轴 3：test-imports-router（imports.py + test_imports.py）
1. >10000 messages 截断：建议断言结果中可观察（G5，imports.py:36-37,99-100）——
   若产品决定保持静默，至少固化为契约测试。
2. `metadata` 透传入库（imports.py:44,120 ↔ sqlite_store.py:2181）。
3. 消息 `created_at` 0/缺省回退会话时间（sqlite_store.py:2182）（G13）。
4. title >100 二次截断（sqlite_store.py:2157）（G4，需构造 101–256 字符标题）。
5. agent_id/agent_name 空串不入 `import` 元数据（imports.py:108-111）。
6. GET /chat-history limit/offset 边界（imports.py:139-146）。

## 跨轴（新增建议）：奇偶契约测试
1. schema 镜像测试：断言 `NormalizedMessage`/`NormalizedSession`（types.ts:68-85）字段集
   ⊆ 后端 `ImportedMessage`/`ImportedSession`（imports.py:40-53）字段集——当前手工对齐，
   无测试守门。
2. 三源 golden fixture 往返快照：每个源一个最小 `.jsonl`/`conversations.json` 夹具 →
   parse → `NormalizedSession` 快照，覆盖矩阵 B 每格；图片、分支、空行各一行。
3. codex 分层选择：同文件含 `event_msg` 与 `response_item` 时的取舍（G7，
   codex.ts:126-130,237）固化为行为测试。

## 运行命令参考（限时）
```
timeout 900 python -m pytest -q -p no:cacheprovider tests/api/test_imports.py tests/services/session/test_import_session.py
timeout 900 npx vitest run web/tests/partner-group-export.test.ts web/tests/chat-import-chatgpt.spec.ts web/tests/chat-import-codex.spec.ts web/tests/imports-api.spec.ts
```
（本卡未运行测试：只产证据，无代码变更；命令供后续补测卡复用。）
