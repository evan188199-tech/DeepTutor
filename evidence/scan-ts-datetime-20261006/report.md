# web/ TS 侧日期时间处理清点（read-only scan，Python 轴镜像）

- 基线：`origin/main` @ `f07029cfcf2c`（release v1.6.13），新 worktree 只读扫描，未改任何产品代码。
- 范围：`web/` 全部 `.ts`/`.tsx`（1237 个文件；排除 `node_modules`、`.next`、`coverage`、`web/tests`、`web/scripts`、`web/contracts/generated`）。
- 工具：`scripts/scan_ts_datetime.py`（行级规则分类全部 `new Date(...)`/`Date.parse(...)` 调用点与时区敏感构造，输出确定性排序 JSON），辅以人工逐点复核数据源写方（Python 侧写方格式逐一对照源码确认）。
- 口径说明：TS 引擎对 `new Date(string)` 的解析规则——带 `Z`/`±hh:mm` 的 ISO 按瞬时值解析（无缺口）；`YYYY-MM-DD` 日期串按 UTC 午夜；`YYYY-MM-DDTHH:mm[:ss]` **无时区标记**按**浏览器本地**解析。后端 aware-UTC（`+00:00`/`Z`）字符串 TS 均能正确解析，因此本扫描的缺口判定聚焦"后端发出**无时区标记**字符串、TS 按浏览器本地解读"的组合。
- 脚本已知的少数误分类（人工复核修正，见各条目判定依据）：`KbWebSourcesSection.tsx:360`（`next_run_at` 实为 epoch ms 数字）、`KbDocumentList.tsx:596`（`ts` 实为 `unixSeconds*1000` 数字）、`usage-statistics.ts:30`（Date 对象复制）、`locale_display` 有 1 处 `timeZone` 选项在下一行未被行级规则识别（`UsageActivity.tsx:44-46`）。
- 对照：Python 轴镜像 `myfork/scan/datetime-naive-20261005`（evidence/datetime-naive-20261005/report.md）；去重对象：fix-kb-progress-tz（`myfork/fix/kb-progress-tz-aware-utc`，仅 Python 侧）、fix-mochat-ts-naive（`myfork/fix/mochat-ts-aware-20261005`，仅 Python 侧）。两卡均已核对 diff：只改 `deeptutor/` Python 与测试，未触及 `web/`，TS 轴无重叠。

## 总量（118 个命中，53 个文件）

| 桶 | 数量 | 说明 |
|---|---|---|
| `new Date()` 无参 | 9 | 当前时刻，本地语义，无风险 |
| `new Date(<epoch 派生>)` | 10 | `epoch_ms` 1 + `epoch_sec_to_ms`（`*1000`）9，数值语义正确 |
| `new Date(<带时区字面量>)` | 5 | 测试/种子数据的 Z 字面量，正确 |
| `Date.parse(<带时区字面量>)` | 3 | 同上 |
| 组合日期串（无时区标记） | 4 | `` `${date}T00:00:00` `` 风格，见 L2 |
| `new Date(<字符串表达式>)` / `Date.parse(<字符串表达式>)` | 22 | 格式取决于后端写方，人工逐一复核，见 L1/L3 |
| `.toLocale*String()` 展示 | 36 | 28 个文件；35 处浏览器本地、1 处显式 `timeZone:'UTC'`，见 L3 |
| `toISOString().slice(0,10)` 截断 | 2 | 见 L2 |
| `Intl.DateTimeFormat().resolvedOptions().timeZone` 上送 | 2 | 正面模式（usage/practice），见正面参照 |
| `Intl.RelativeTimeFormat` | 3 | locale-aware，正面参照 |
| 中央 helper `parseKnowledgeTimestamp`/`formatKnowledgeTimestamp` 消费点 | 22 | 全部为 KB 时间戳展示，风险集中见 L1#1 |

无 `getTimezoneOffset()`、`dayjs/date-fns/moment/luxon`（grep 证实仅有注释里的英文单词误命中）；日期处理全部原生 `Date` + `Intl`。

## L1 TS↔后端 aware-UTC 衔接缺口（无时区字符串被按浏览器本地解读）

| # | 位置 | 判定依据 | 分级 | 去重 |
|---|---|---|---|---|
| 1 | `web/lib/knowledge-helpers.ts:297-298`（`parseKnowledgeTimestamp`） | KB 元数据 `last_updated` 后端写方为 `strftime("%Y-%m-%d %H:%M:%S")` naive **服务器本地**（`add_documents.py:497/:569`、`initializer.py:105`，见 Python 轴 L1#3/L3#1）；TS 侧 `" "→"T"` 归一后 `new Date()` → 按**浏览器本地**解读。浏览器 TZ ≠ 服务器 TZ 时 KB 卡片"最后更新"偏移整个差值。消费点 22 处（`KnowledgeBaseDetail.tsx:175`、`KbSettingsSection.tsx:89` 等） | MEDIUM（跨时区部署必现，展示层） | 根因在 Python 写方（Python 轴卡④）；TS 读方可加 assume-UTC 防御，两卡联动 |
| 2 | `web/app/(workspace)/partners/page.tsx:264` | `Date.parse(group.updated_at) / 1000`；写方 `partners/sessions.py:413` `datetime.fromtimestamp(st_mtime).isoformat()` naive **服务器本地**；`manager.py:1150` 服务端还直接对该字符串排序（同机自洽）。浏览器端 `Date.parse` 无时区串按本地解读 → partner 列表"最近活动"相对时间/排序偏移 server↔browser TZ 差 | MEDIUM（跨时区展示偏移） | 新发现（Python 轴未列此消费端）；与 fix-mochat-ts 同类：写方根治或读方归一二选一 |
| 3 | `web/components/partners/PartnerArchives.tsx:35` | 归档消息 `timestamp` 无时区标记（mochat 写方 `now(utc).replace(tzinfo=None).isoformat()` 剥 Z，Python 轴 L2#1/卡①）→ `new Date(value)` 浏览器本地解读，非 UTC 宿主 + 非 UTC 浏览器组合下时间显示偏 8 小时 | HIGH 触发条件，但写方修复已备 | **随卡①落地后自动消除**：`myfork/fix/mochat-ts-aware-20261005` 已把写方改回 aware（该卡未并入 main，TS 侧无需单独修） |

## L2 组合日期串 / UTC 截断（语义分型，多为 LOW）

| # | 位置 | 判定依据 | 分级 |
|---|---|---|---|
| 1 | `web/components/chat/MyAgentsPicker.tsx:74`、`web/components/space/ScopePicker.tsx:30` | `` new Date(`${key}T00:00:00`) ``：key 本身是日历日 key，无时区标记按浏览器本地午夜解析，回显同日历日——显示语义尚可，但与 `UsageActivity.tsx:44` 的 `T12:00:00Z` 风格不一致 | LOW（风格统一，建议抽 helper） |
| 2 | `web/components/learning/practice/PracticeInsights.tsx:30` | `` `${date}T12:00:00` `` 本地正午锚（无 Z）：日历日展示语义 OK；同上风格问题 | LOW |
| 3 | `web/lib/chat-export.ts:87` | `toISOString().slice(0,10)` 取 **UTC** 日期作导出文件名：UTC+X 东侧时区在本地日 0-8 点导出会得到前一天日期 | LOW（文件名标签） |
| 4 | `web/lib/usage-statistics.ts:26-34` | `Date.UTC` 迭代 + `toISOString().slice(0,10)` 生成日历格 date key，与后端"按上送 timezone 分箱"的 date key 对齐，代码内有注释说明——**正确**用法 | INFO（正面参照） |

## L3 展示时区（浏览器本地 toLocale*，36 处 / 28 文件）

全部为会话列表、KB 详情、设置页等**本地用户展示**场景，浏览器本地时区是正确默认；已逐点核对数据源写方格式：

- aware-UTC 写方（`new Date` 解析正确，无缺口）：`AboutSettingsSection.tsx:173`（`app_update.py:150` aware）、`DataMigrationSettingsSection.tsx:371`（`data_migration.py:544/:583` aware）、`CliAppsSection.tsx:1019`（`cli_apps/state.py:132` aware）、`SystemWorkspaceSnapshot.tsx:55`（epoch 数值）、`ChannelOnboardingPanel.tsx:136`（`links.py:66` aware UTC）、profile/admin 用户 `created_at`（PocketBase 自动字段 UTC）。
- 唯一显式 `timeZone:'UTC'`：`UsageActivity.tsx:44-46`（配合后端 date key 分箱，正确）。
- epoch 派生（数值，正确）：`HistorySessionPicker.tsx:46`、`PracticeSession.tsx:88`、`PracticePage.tsx:200`、`LearningCard.tsx:41`、`NotebookRecordRow.tsx:223`、`KbDocumentList.tsx:596`、`KbWebSourcesSection.tsx:360`（`next_run_at` epoch ms）、`space/learning/format.ts:68`、`QuestionCard.tsx:544/:549` 等。
- 例外即 L1#1/#2/#3 三处（数据源是无时区字符串）。

INFO：跨时区管理员核对服务器日志时与 UI 显示会有差值，属预期；无固定 `timeZone` 渲染需求。

## 与后端 aware-UTC 时间轴的衔接结论

- knowledge 进度 WS 的 naive `timestamp` 字段（Python 轴 L1#1/#2 HIGH 链）：TS 侧 `useKnowledgeProgress.ts` / `KbTaskLogs.tsx` 只消费 `stage`/`message`，**不解析 timestamp** → 前端无缺口；该风险留在 Python 内部，随 `fix/kb-progress-tz-aware-utc` 根治。
- 后端 aware-UTC（`+00:00`/`Z`）字段在 TS 侧全部正确解析；本扫描未发现 TS 侧自产 naive 比较逻辑（无 `getTimezoneOffset` 依赖、无日期字符串互比命中）。
- 真实缺口集中在"后端无时区字符串 × 浏览器本地解读"三处（L1），根因均可在 Python 写方根治；TS 读方加 assume-UTC 归一是低成本防御。

## 正面参照（修复卡可复用的模式）

- `web/lib/usage-statistics.ts:11` 与 `web/lib/practice-api.ts:83`：把 `Intl.DateTimeFormat().resolvedOptions().timeZone` 显式上送后端，由后端按用户本地日分箱——前后端日界一致的正确做法。
- `web/lib/relative-time.ts:19-37`：会话分组用浏览器本地日界（today/yesterday），输入为真瞬时 epoch——UI 分组的正确选择。

## 与既有工作去重对照

| 来源 | 条目 | 本扫描处置 |
|---|---|---|
| scan-datetime-naive（Python 轴） | `last_updated` strftime naive（L1#3/L3#1） | 补齐 TS 消费端视图：`parseKnowledgeTimestamp` 22 处展示消费点（L1#1），互为印证 |
| fix-kb-progress-tz（`myfork/fix/kb-progress-tz-aware-utc`） | 进度时间戳 aware 化（仅 Python） | 已核对 diff 未触 `web/`；TS 不消费进度 timestamp，无交叠 |
| fix-mochat-ts-naive（`myfork/fix/mochat-ts-aware-20261005`） | mochat 时间戳剥 Z（仅 Python 写方） | 已核对 diff 未触 `web/`；TS 读方 `PartnerArchives.tsx:35` 在该卡并入 main 后自动正确（L1#3），不另开卡 |

上游撞车检查：`gh pr list -R HKUDS/DeepTutor --state open` 全量标题/分支扫描，无 TS datetime/时区相关开放 PR（30 条开放 PR 中仅 Python 侧 tz 测试 #1733）；本卡为纯只读扫描，不开 PR。

## 可拆修复卡条目（建议）

| 卡 | 标题草案 | 范围 | 优先级 |
|---|---|---|---|
| ① | fix: partner 会话 updated_at 改 aware-UTC 并对齐 TS 解析 | `sessions.py:413` 写方 aware 化（与 `manager.py:1150` 字符串排序兼容性确认）+ `partners/page.tsx:264` 读方回归 | MEDIUM |
| ② | fix: KB `last_updated` 写方 ISO 化 + TS helper assume-UTC 防御 | Python 轴卡④（add_documents/initializer）与 `knowledge-helpers.ts:295-305` 归一化联动 | MEDIUM（与 Python 卡④合并最佳） |
| ③ | refactor: web 组合日期串统一 helper（`dateKeyToDate`，显式 UTC 或显式本地） | L2#1/#2 三处风格统一 | LOW（储备） |
| ④ | chore: chat-export 文件名日期改本地日 | `chat-export.ts:87` | LOW（储备） |

## 复跑与自证

```bash
python3 evidence/scan-ts-datetime-20261006/scripts/scan_ts_datetime.py \
  --root . --out /tmp/rerun && diff -r /tmp/rerun/data evidence/scan-ts-datetime-20261006/data
```

基线 f07029cfcf2c 上重跑输出与提交内容逐字节一致（提交前已验证）；`SHA256SUMS` 覆盖 report/data/scripts 全部交付文件。
