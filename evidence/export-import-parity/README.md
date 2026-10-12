# scan: 会话导出↔导入往返奇偶矩阵

- 基线：origin/main @ `6cf793bd8`（release v1.6.14，2026-10-08）
- 分支：`scan/export-import-parity-20261012`（只产证据，不改源码）
- 范围：`web/lib/chat-export.ts`、`web/lib/chat-import/*`、`deeptutor/api/routers/imports.py`，
  以及往返两端的持久化/读回层（`deeptutor/services/session/sqlite_store.py`）与上传封装
  （`web/lib/imports-api.ts`）——这些仅作只读引用以闭环字段流向。
- 去重轴（单点测试卡）：test-chat-export、test-web-chat-import-claude-code、test-imports-router。
  本卡不写测试、不改源码，只给矩阵 + 缺口 + 补测建议。
- 上游撞车检查：HKUDS/DeepTutor 开放 PR 中无涉及 chat-export / chat-import / imports 路由的
  PR（2026-10-12 检查，open PR #1899/#1268/#1218/#492 均为其他区域）。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| matrix.md | 格式 × 方向 × 字段矩阵（含 path:line 证据） |
| gaps.md | 缺口清单（逐条 path:line） |
| test-suggestions.md | 补测建议（映射到现有/缺失测试轴） |
| SHA256SUMS | 本目录所有文件的校验和 |

## 数据流总览

```
导出（仅 Markdown，单向）:
  MessageItem ──buildChatMarkdown──> .md 下载（浏览器本地）
  web/lib/chat-export.ts:50-91；调用点 ChatWorkspace.tsx:2362-2365、
  ReadingCompanion.tsx:284-290、partners/[partnerId]/page.tsx:325-329、
  partners/groups/[groupId]/page.tsx:61-64

导入（三源，外部→应用）:
  ~/.claude (dir)  ──claude-code.ts──┐
  ~/.codex  (dir)  ──codex.ts───────┼─> NormalizedSession[] ──imports-api.ts:22-46──>
  conversations.json ──chatgpt.ts───┘      POST /api/imports/chat-history (imports.py:74-136)
                                           ──> sqlite_store.import_session (sqlite_store.py:2191-2208)
                                           ──> 读回 _serialize_message (sqlite_store.py:2469-2490)
```
