# scan: web locale key 静态复扫（使用点 × locale 文件对照）— AGEN-1583

基线：`origin/main @ 6cf793bd8`（release v1.6.14），只读扫描，未改任何业务代码。
范围：`web/{app,components,features,hooks,lib,shared}` 的 `.ts/.tsx`；locale 目录 `web/locales/{en,zh,fr,de,uk,pl}/app.json`（i18next 单命名空间，`keySeparator: false`，复数以 `_<form>` 后缀）。

## 三清单计数

| 清单 | 计数 | 说明 |
|---|---|---|
| 缺失 key | **fr 59**（en/zh/de/uk/pl 均为 0） | 代码 t() 使用但 locale 无条目；59 个中 56 个为 fix-web-locales-parity 之后的新漂移，3 个已被该 fix 分支覆盖（去重：只核对） |
| fr 目录级缺口 | **529**（en 有而 fr 无） | fix 分支覆盖 466，新漂移 63 |
| 孤儿 key | en/zh/de **1479 候选**（750 confirmed + 729 guarded）；fr **1910**；uk/pl 与 en 相同 | confirmed = 全源码+tests 无字符串命中；guarded = 有裸命中（可能经动态 map/测试引用，删除前需人工核对）；uk/pl 多出的 16 个为合法复数形式，fr 多出 909 个 fr-only 历史 key |
| 硬编码文案 | **31 处 / 17 文件，疑似真实漂移 0** | 全部为技术占位符/单位/符号/语言名；fix-web-hardcoded-i18n 的 10 个修复文件与本清单零交集 → v1.6.14 后无新增硬编码漂移 |

另：`locales/{en,zh,de,fr}/common.json`（各 37 key）未被 `web/i18n/init.ts` 加载且 key 全部重复存在于 app.json → 4 文件为文件级孤儿（148 key 实例）；动态 t() 调用点 278 处 / 118 文件，抽查同文件与导入的字面量 map 取值均为有效目录 key，非 key 字面量 0 个（明细见 dynamic-keys.json / dynamic-literals.json）。

## 缺失 key top10（fr，新漂移，附使用点证据）

1. `Add a note for this segment` — components/knowledge/KbIndexingRun.tsx
2. `Add segment note` — components/knowledge/KbIndexingRun.tsx
3. `Learning journal` — components/space/LearningJournalPanel.tsx
4. `Current mission` — components/space/LearningJournalPanel.tsx
5. `Independent visual evidence` — components/knowledge/KbVisualCoverage.tsx
6. `Visual practice` — components/reading/workspace/MediaReadingStage.tsx
7. `Review or challenge this assessment` — components/chat/home/MasteryQuestionCard.tsx
8. `Cancel indexing` — components/knowledge/KbIndexingRun.tsx
9. `Use an administrator-approved private MCP origin` — components/mcp/McpServerForm.tsx
10. `Next focus` — components/space/learning/ObjectiveDetail.tsx

（全量 59 个及 file:line 见 missing-keys.json）

## 缺失 key 按文件分布

15 KbIndexingRun.tsx / 14 LearningJournalPanel.tsx / 8 KbVisualCoverage.tsx / 8 MasteryQuestionCard.tsx / 6 MediaReadingStage.tsx / 6 ObjectiveDetail.tsx / 3 McpServerForm.tsx / 2 kanban/page.tsx / 1 ×5 文件（KbTaskLogs、AddProviderPanel、MasteryStudy、ChatWorkspace、ImageDescriptionModelSetting）

## 与已修分支去重（只核对，不重复报）

- `myfork/fix/web-locales-parity-20261006`（df8bbc2e4，**未合入 origin/main**）：覆盖 fr 缺失 used key 3 个（`Enter a valid HTTP or HTTPS provider address.`、`General workspace`、`Selected model unavailable`）、目录缺口 466 个；其余 56 + 63 为该分支之后的新漂移。
- `myfork/fix/web-hardcoded-i18n-20261006`（59d77fa9f，**未合入 origin/main**）：其 10 个源文件在 main 上仍是修复前状态（zh/en 三元文案，审计启发式不覆盖该模式），按任务口径记为已覆盖；与本清单 17 文件零交集。

## 方法与限制

- key 使用点提取与 `web/scripts/i18n_audit.mjs` 同语义（TypeScript AST，仅字面量/三元），孤儿判定叠加全文裸字符串 guard（含 i18n/context/contracts/types/tests）。
- 限制：278 处动态 t()（key 来自变量/map/跨文件 helper）无法静态解析，可能造成孤儿误报（已用 guard 档隔离）与缺失漏报；common.json 未接线、Python 侧不消费 web/locales（已核实 deeptutor/i18n 为独立硬编码字典）。

## 复扫

```bash
bash evidence/scan-web-locale-keys/rescan.sh
```

原始输出快照：`rescan-output.txt`；校验：`sha256sum -c SHA256SUMS`。
