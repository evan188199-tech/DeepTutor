# 缺失 key 清单（代码使用但 locale 文件缺失）

基线：origin/main @ 6cf793bd8 (release v1.6.14)，只读扫描，未改代码。

定义：web/{app,components,features,hooks,lib,shared} 内 t() 字面量 key 在 locales/<l>/app.json 无对应条目（复数 _suffix 形式视为已覆盖）。

## 计数

- en: 0
- zh: 0
- fr: 59
- de: 0
- uk: 0
- pl: 0

## fr 缺失 used key top10（新漂移，连 myfork/fix/web-locales-parity-20261006 也未覆盖）

- `Add a note for this segment` — components/reading/workspace/MediaReadingStage.tsx:877
- `Add segment note` — components/reading/workspace/MediaReadingStage.tsx:744
- `Approve this MCP origin for private-network connections` — components/mcp/McpServerForm.tsx:292
- `Assisted practice is recorded separately from independent mastery.` — components/space/learning/ObjectiveDetail.tsx:121
- `Assisted` — components/space/learning/ObjectiveDetail.tsx:137
- `Cancel indexing` — components/knowledge/KbIndexingRun.tsx:74
- `Cancellation pending at a safe boundary` — components/knowledge/KbIndexingRun.tsx:74
- `Confirmed learning records` — components/space/LearningJournalPanel.tsx:54
- `Could not read indexing state. Refresh and retry.` — components/knowledge/KbIndexingRun.tsx:65
- `Could not read the learning journal. Its original data is preserved. Try refreshing.` — components/space/LearningJournalPanel.tsx:34

（其余 46 个见 missing-keys.json / dedup.missing_used_new_drift）

## fr 缺失 key 全量（59）按文件分布

- 15  components/knowledge/KbIndexingRun.tsx
- 14  components/space/LearningJournalPanel.tsx
-  8  components/knowledge/KbVisualCoverage.tsx
-  8  components/chat/home/MasteryQuestionCard.tsx
-  6  components/reading/workspace/MediaReadingStage.tsx
-  6  components/space/learning/ObjectiveDetail.tsx
-  3  components/mcp/McpServerForm.tsx
-  2  app/(workspace)/kanban/page.tsx
-  1  components/knowledge/KbTaskLogs.tsx
-  1  components/settings/AddProviderPanel.tsx
-  1  components/space/learning/MasteryStudy.tsx
-  1  features/chat/components/ChatWorkspace.tsx
-  1  features/settings/sections/ImageDescriptionModelSetting.tsx

## 目录级缺口（en 有而 locale 无）

- fr: 529 个 en 目录 key 缺失（fix 分支覆盖 466，新漂移 63）
- zh: 0
- de: 0
- uk: 0
- pl: 0

## 与 fix-web-locales-parity 去重

- 该分支（myfork/fix/web-locales-parity-20261006，未合入 origin/main）覆盖缺失 used key 3 个：['Enter a valid HTTP or HTTPS provider address.', 'General workspace', 'Selected model unavailable']
- 其余 56 个为分支之后的新漂移（LearningJournalPanel / KbVisualCoverage / MasteryQuestionCard / MediaReadingStage / ObjectiveDetail / KbIndexingRun 等 v1.6.14 新界面文案）