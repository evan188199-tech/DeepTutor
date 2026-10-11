# guarded 档人工核对清单（AGEN-1729）

来源：myfork `scan/web-locale-keys-20261011`（66919d8bc）`evidence/scan-web-locale-keys/orphan-keys.json`；
判定沿用该报告定义：孤儿候选中存在裸字符串命中（web/{app,components,features,hooks,lib,shared,i18n,context,contracts,types} 或 tests 任一文件含该 key 子串）→ guarded，删除前需人工核对。

本次清理（chore/web-locale-orphan-cleanup-20261011）未删除任何 guarded key；confirmed 档中 132（en/zh/de）/60（fr）个动态拼接/直通误报 key 已恢复（见 restored-dynamic-keys.json），实际删除 618/1340。逐 key 命中证据见 `guarded-keys.json`（每 key 最多 3 条 file:line）。

## 计数对账

| 档 | en | zh | de | fr |
|---|---|---|---|---|
| confirmed（报告口径） | 750 | 750 | 750 | 1400 |
| 恢复（动态拼接/直通误报） | 132 | 132 | 132 | 60 |
| 实际删除（本卡） | 618 | 618 | 618 | 1340 |
| guarded（本清单，零改动） | 729 | 729 | 729 | 510 |
| 合计（=扫描候选） | 1479 | 1479 | 1479 | 1910 |

fr 与任务描述口径差异说明：任务卡写 "guarded 档 fr 1910"，扫描报告 fr confirmed=1407 / guarded=503。复核发现报告的 fr 计数对 909 个 fr-only key 未执行其自身定义的裸字符串 guard（fr guarded 503 恰等于与 en 共享部分的 guarded 数）。按报告定义复算：fr confirmed=1400、guarded=510（503 共享 + 7 fr-only）。本卡按定义执行：删除 1400，其余 510 全部进本清单。7 个由报告 confirmed 移入 guarded 的 fr-only key 见下节。

## 7 个 fr-only key（报告计为 confirmed，按定义有裸命中 → 移入本清单）

| key | 命中证据（file:line） |
|---|---|
| `Assigned knowledge bases are read-only` | components/knowledge/KbLinkedFoldersSection.tsx:219; components/knowledge/KbLinkedFoldersSection.tsx:371 |
| `Change line width` | components/reading/ReaderDisplayControls.tsx:95; tests/reading-display-preferences.test.ts:115; tests/reading-display-preferences.test.ts:134 |
| `Choose model` | components/settings/SettingsOverview.tsx:143 |
| `Larger text` | components/reading/ReaderDisplayControls.tsx:81; tests/reading-display-preferences.test.ts:111 |
| `Learning` | app/(admin)/admin/users/page.tsx:673; app/(auth)/login/page.tsx:166; app/(auth)/register/page.tsx:187 |
| `Smaller text` | components/reading/ReaderDisplayControls.tsx:73; tests/reading-display-preferences.test.ts:110; tests/reading-display-preferences.test.ts:133 |
| `{{count}} paths` | components/learning/surfaces.ts:55 |

人工初判（供复核参考，非结论）：
- `Assigned knowledge bases are read-only` 是 `Assigned knowledge bases are read-only.`（带句号，另一 key）的子串 → 伪命中
- `Change line width` 是 `Change line width ({{width}} characters)` 的子串 → 伪命中
- `Choose model` 是 `Choose models for automatic tasks …` 的子串 → 伪命中
- `Larger text` / `Smaller text` 是对应 `({{percent}}%)` key 的子串 → 伪命中
- `Learning` 是 `LearningBoard`/`fetchLearningBoard` 等标识符的子串 → 伪命中
- `{{count}} paths`：`components/learning/surfaces.ts:55` 存在精确裸命中（`unit: '{{count}} paths'`），可能经动态拼接消费 → **保留，需人工确认消费路径后再决定**

## en/zh/de 共享 guarded（729 key，三语言同集）

完整列表 + 命中证据存于 `guarded-keys.json`（`en_guarded` 字段；`evidence` 字段含命中 file:line）。以下为按字典序前 80 条预览：

```
(optional)
AI judge connection closed unexpectedly.
Active model
Adaptive
Afternoon — what's on your mind?
Again
Age
Agent conversations
Amber
Animator settings
Answer preferences
Answer:
Answers name the place in the text they came from
Anthropic Messages
Apply a behavior persona for this turn.
Approximate graph search for large knowledge bases. Faster at scale with a small recall trade-off.
Arxiv Search
Ask AI
Ask Questions
Ask anything about this question
Ask me a few things first, then propose an outline
Assessment Type
Assets
Attach
Attach image
Audio
Audit memory
Authorization was cancelled. You can connect again whenever you are ready.
Auto (recommended)
Auto-play replies in this conversation?
Auto-validated question generation
Available
BM25 keyword + vector semantic retrieval, fused and re-ranked. More robust recall.
Backend Port
Behavior presets you can apply per chat turn.
Bilibili
Blockquote
Blue
Bold
Book Reference
Bot
Brainstorm
Brief
Bring in PDFs, EPUBs, web pages, video or audio and read them here. Select any passage to ask about it.
Bring questions from every learning activity together, import your own, and build lasting recall through daily practice.
Built-in plain text extraction for PDF/Office/text files. No optional parser package, no model download, no layout structure.
Built-in tools the chat agent can invoke.
Bullet List
Burning the midnight oil?
Callout
Capability
Capability playbooks the model reads on demand.
Categories
Chapter
Chat Completions
Chat Completions for most endpoints; Responses for OpenAI reasoning models, with fallback.
Chat Session
Chat history
Chat model
Chat with imported Claude Code and Codex agents.
Chats
Chinese
Choose a model
Co-Writer drafts
Co-Writer tooltip
Code
Code Block
Code Sandbox
Coding
Collaborating agent
Color:
Combines local and global retrieval — a solid general default.
Coming soon
Comparison
Compilation
Complete
Completed
Composer hint
Comprehensive multi-agent research
Concept Check
… 其余 649 条见 guarded-keys.json
```

## 核对方法建议

1. 打开 `guarded-keys.json` 中该 key 的命中 file:line，判断命中是否为完整 key 的动态引用（map/对象取值/测试夹具）→ 保留 key；仅是更长字符串的子串或标识符片段 → 可安全删除。
2. 判定可删后，按 confirmed 档同流程在四个 locale 同步删除（en/zh/de 同集；fr 另含 7 个 fr-only）。
3. 删除后运行 `node evidence/web-locale-orphan-cleanup-20261011/orphan-guard.mjs`（应保持 OK）与 `cd web && npm run i18n:check`。
