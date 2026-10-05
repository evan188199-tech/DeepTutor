# 会话存储 schema 漂移清点（sqlite_store / protocol / pocketbase_store）

基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
日期：2026-10-05 · 性质：只读对照，未改任何代码 · 范围：`deeptutor/services/session/` + PB 集合定义 `scripts/pb_setup.py`
方法：逐实体对照三方——SQLite 建表/迁移语句（`sqlite_store.py`）、协议与数据模型（`protocol.py`、`TurnRecord`）、PocketBase 集合字段（`pocketbase_store.py` 读写负载 + `scripts/pb_setup.py` 引导 schema）。所有引用为仓库相对 `path:line`。

---

## 1. 结论先行

三方覆盖同一组会话实体（sessions / messages / turns / turn_events），字段命名与载体差异大多是刻意设计（PB 走逻辑键 + user_id 隔离，SQLite 走物理外键），但存在 **1 个高危 schema 缺列、3 类高危读写不对称、7 项中危契约/保真度漂移**。最大的新发现：**PB 引导脚本从未创建 `sessions.deleted_at` 字段，而 PB store 的回收站全链路（软删/恢复/硬删/回收站列表/归档提升迁移）都依赖它**（D1）。

与既有卡去重：存储面全景（无版本表、PB 无升级机制、无事务、get_full_list 全扫、星星寄居聊天库、turn_events 无 TTL）已在 scan-persistence 卡覆盖，本报告不重复展开，仅在条目上标注【去重】；SQLite 初始化 DDL 的测试面已由 test-sqlite-store 卡覆盖。

---

## 2. 字段对照表

### 2.1 sessions

| 语义字段 | SQLite 列 | PocketBase 集合字段 | protocol/读侧契约 | 备注 |
| --- | --- | --- | --- | --- |
| 主键 | `id TEXT PRIMARY KEY` `sqlite_store.py:285` | `session_id`(text,required) + 系统 `id` `pb_setup.py:165`；**无 session_id 唯一索引** | `id`/`session_id` 双键 `sqlite_store.py:1146-1148`；PB `_session_record_to_dict` `pocketbase_store.py:308` | PB 并发 create 可产生重复 session_id（D11） |
| 租户隔离 | 每用户独立 DB 文件（隐式） | `user_id`(text) `pb_setup.py:166`，全查询过滤 `pocketbase_store.py:104-152` | 协议不含租户字段 | 设计差异 |
| title | `TEXT NOT NULL DEFAULT 'New conversation'` `sqlite_store.py:286`；截断 100 `:1129,1143` | `title`(text) `pb_setup.py:167`；截断 100 `pocketbase_store.py:259,355` | 默认 `'New conversation'` 两端一致 | 一致 |
| created_at / updated_at | `created_at`/`updated_at REAL NOT NULL` `sqlite_store.py:287-288` | `session_created_at`/`session_updated_at`(number) `pb_setup.py:173-174`；读侧回退系统 `created`/`updated` `pocketbase_store.py:310-321` | `created_at`/`updated_at` float | 命名不同，读侧已归一 |
| 压缩摘要 | `compressed_summary TEXT DEFAULT ''` `sqlite_store.py:289`；`summary_up_to_msg_id INTEGER DEFAULT 0` `:290` | 同名 number/text `pb_setup.py:168-169` | `update_summary` 两端一致（SQLite 保持 `updated_at` 不变 `sqlite_store.py:2913`；PB 不写 `session_updated_at` `pocketbase_store.py:788-794`） | 一致 |
| preferences | `preferences_json TEXT DEFAULT '{}'` `sqlite_store.py:291`（CREATE 内）+ ALTER 守卫 `:462-463` | `preferences_json`(json) `pb_setup.py:170`；读时 `upgrade_workspace_preferences` 归一 `pocketbase_store.py:332-335`【去重：scan-persistence §2.2"读时归一化"】 | `preferences` dict | 一致（载体 text vs json） |
| 回收站 | `deleted_at REAL DEFAULT NULL`——仅 ALTER 补列 `sqlite_store.py:464-465`，**不在 CREATE TABLE 内** | **无此字段** `pb_setup.py:161-181`；但 store 写 `pocketbase_store.py:484,503,225`、读/过滤 `:150,339-340,581,616,641` | `soft/restore/hard/list_deleted` 协议方法 `protocol.py:65-73` | **D1 高危** |
| status / capability | 无列，读时派生自 turns `sqlite_store.py:1203-1233,2647-2662` | `status`/`capability`(text) 落列 `pb_setup.py:171-172`，仅 create 写一次 `pocketbase_store.py:263-264,407-408`，turn 状态迁移从不回写 | `get_session` 返回 `status`/`active_turn_id`/`capability` `sqlite_store.py:1242`；PB 恒返回落列值 + `active_turn_id:""` `pocketbase_store.py:336-338` | **D2**；`get_session_summaries` 部分重算 `:736-738` |

### 2.2 messages

| 语义字段 | SQLite 列 | PocketBase 集合字段 | protocol/读侧契约 | 备注 |
| --- | --- | --- | --- | --- |
| 主键 | `id INTEGER PK AUTOINCREMENT` `sqlite_store.py:295` | 系统 record id（string）`pb_setup.py`（隐含）；返回 `str(record.id)` `pocketbase_store.py:904` | `int \| str` `protocol.py:137` | 一致（union） |
| 会话外键 | `session_id TEXT NOT NULL REFERENCES sessions ON DELETE CASCADE` `sqlite_store.py:296`；索引 `:311-312` | `session_id`(text,required) `pb_setup.py:189`，**无索引**；级联靠手工删 `pocketbase_store.py:458-465`【去重：scan-persistence §2.2 无事务】 | — | D11 |
| role | `TEXT NOT NULL` `sqlite_store.py:297` | `role`(text,required) `pb_setup.py:190` | `role: str` | 一致 |
| content | `TEXT NOT NULL DEFAULT ''` `sqlite_store.py:298` | `content`(text) `pb_setup.py:191` | `content` | 默认值声明差异（低） |
| capability | `TEXT DEFAULT ''` `sqlite_store.py:299` | `capability` `pb_setup.py:192` | `capability: str = ""` | 一致 |
| events / attachments | `events_json`/`attachments_json TEXT DEFAULT ''/''` `sqlite_store.py:300-301` | json 型 `pb_setup.py:193-194` | `events`/`attachments` list | 载体差异，读侧归一 |
| metadata | `metadata_json TEXT DEFAULT '{}'`（ALTER 补 `sqlite_store.py:477-478`） | `metadata_json`(json) `pb_setup.py:195` | `metadata` dict | SQLite 内部默认值不一致：messages `'{}'` vs turn_events `''`（D13） |
| created_at | `created_at REAL NOT NULL` `sqlite_store.py:303` | `msg_created_at`(number) `pb_setup.py:196` | `created_at` float | 一致 |
| 父子链 | `parent_message_id INTEGER`（ALTER+回填 `sqlite_store.py:479-499`；索引 `:503-506`）；写：显式/自动成链 `:1909-1924` | **无列**；藏 metadata `_parent_message_id`（str）`pocketbase_store.py:45-47,872-873,1210-1223` | 协议默认 `None` `protocol.py:136`；SQLite 具体默认 `_PARENT_AUTO`（自动成链）`sqlite_store.py:1970,1910-1917`；PB 默认 `None`（不自动成链）`pocketbase_store.py:867` | **D3** |
| 排序 | `ORDER BY m.id ASC` `sqlite_store.py:2446`；`ORDER BY created_at,id` `:2825` | `sort: "msg_created_at"`（无 tiebreak）`pocketbase_store.py:1149`；其余查询 `"-msg_created_at,-created"` `:674,692,761` | — | **D10** |
| 分支上下文 | `get_message_path`/`get_messages_for_context(leaf)` `sqlite_store.py:2471-2504,2560` | `get_messages_for_context` 显式忽略 leaf `pocketbase_store.py:1188-1193`；`source_inventory._load_lineage` 刻意绕开 sqlite-only 方法 `source_inventory.py:663-694` | 协议方法 `protocol.py:219-221` | D3 的一部分 |

### 2.3 turns

| 语义字段 | SQLite 列 | PocketBase 集合字段 | protocol/读侧契约 | 备注 |
| --- | --- | --- | --- | --- |
| 主键 | `id TEXT PRIMARY KEY` `sqlite_store.py:322` | `turn_id`(text,required) + 唯一索引 `pb_setup.py:211,227` | `id`/`turn_id` 双键 `sqlite_store.py:159-161` | 一致 |
| 会话外键 | `session_id REFERENCES sessions ON DELETE CASCADE` `sqlite_store.py:323` | `session_id`(text,required) `pb_setup.py:212` | — | 一致 |
| capability/status | `capability DEFAULT ''`、`status NOT NULL DEFAULT 'running'` `sqlite_store.py:324-325` | 同名字段（无默认）`pb_setup.py:213-214`；写入 `'running'` `pocketbase_store.py:1275` | 状态机 `protocol.py:100-110` | 一致 |
| error/failure_code/retryable | `error DEFAULT ''`、`failure_code DEFAULT ''`、`retryable INTEGER NOT NULL DEFAULT 0` `sqlite_store.py:326,333-334` | `error`/`failure_code`/`retryable`(bool) `pb_setup.py:215,222-223` | `transition_turn` 参数 `protocol.py:107-109` | 一致（int vs bool 载体） |
| 时间戳 | `created_at`/`updated_at`/`finished_at` `sqlite_store.py:327-329` | `turn_created_at`/`turn_updated_at`/`finished_at` `pb_setup.py:216-218` | `created_at`/`updated_at`/`finished_at` | 命名差异，读侧归一 |
| 并发 v2 列 | `owner_id`/`fencing_token`/`state_version` 建表即有 `sqlite_store.py:330-332`，legacy 由 ALTER 补+回填 `:571-583` | 同名字段 `pb_setup.py:219-221`；PB 侧重复 running 收敛在 bootstrap `pb_setup.py:88-115`，与 SQLite 迁移收敛 `sqlite_store.py:610-639` 是**两处实现** | `begin_turn(owner_id, fencing_token)` `protocol.py:80-88` | D15 |
| assistant_message_id | `INTEGER`（ALTER+从 events 回填 `sqlite_store.py:582-601`）；部分唯一索引 `:602-608` | text 型 `pb_setup.py:224`；全量唯一索引 `pb_setup.py:230`（NULL 可重复，语义等价） | `link_turn_message` `protocol.py:175` | 类型差异（设计使然） |
| last_seq | 读时派生 `MAX(seq)` `sqlite_store.py:1384,1403,1425` | **硬编码 0** `pocketbase_store.py:1503` | `TurnRecord.last_seq` `sqlite_store.py:150,169` | **D6** |
| 单活跃 turn 约束 | 部分唯一索引 `sqlite_store.py:640-646`；begin 捕获 IntegrityError→`ActiveTurnConflict` `:1294-1338` | 同款部分唯一索引 `pb_setup.py:228-229`；begin 先读后写，**不翻译唯一索引冲突** `pocketbase_store.py:1252-1290` | `ActiveTurnConflict` `protocol.py:13-29` | **D7** |

### 2.4 turn_events

| 语义字段 | SQLite 列 | PocketBase 集合字段 | protocol/读侧契约 | 备注 |
| --- | --- | --- | --- | --- |
| 主键/序 | `id INTEGER PK`；`seq` + `UNIQUE(turn_id, seq)` `sqlite_store.py:345-355`；索引 `:358-359` | `seq`(number,required) + 唯一索引 `pb_setup.py:247,256` | `get_events(turn_id, after_seq)` `protocol.py:120` | 一致 |
| turn_id | `TEXT NOT NULL REFERENCES turns ON DELETE CASCADE` `sqlite_store.py:346` | `turn_id`(text,required) `pb_setup.py:245` | — | 一致 |
| session_id | **无列**，读时 join turns `sqlite_store.py:1684-1685` | 冗余列 `pb_setup.py:246`，写入 `payload.get("session_id","")` `pocketbase_store.py:1698`，读回 `:1740` | payload 携带 `session_id` `sqlite_store.py:1564` | D12 |
| type/source/stage/content | `type NOT NULL`、`source/stage/content DEFAULT ''` `sqlite_store.py:348-351`；写入不截断 `:1637` | 同名字段 `pb_setup.py:248-251`；写入/幂等比较均截断 10000 `pocketbase_store.py:1683,1703` | 幂等冲突比较 SQLite 全文 `:1547-1554` | **D5** |
| metadata | `metadata_json TEXT DEFAULT ''` `sqlite_store.py:352` | `metadata_json`(json) `pb_setup.py:252` | `metadata` dict | D13 |
| 时间戳 | `timestamp REAL NOT NULL` + `created_at REAL NOT NULL` `sqlite_store.py:353-354` | `event_timestamp`(number) `pb_setup.py:253` + 系统 `created`(ISO) | payload `timestamp` `sqlite_store.py:1567` | D12 |
| 预览过滤 | SQL json_extract 服务端过滤 `sqlite_store.py:2351-2362` | 客户端 `compact_trace_preview`（PB 直接取尾部 seq）`pocketbase_store.py:985-994` | 预览契约 `event_preview.py` | 保真度差异小，未列级 |

### 2.5 SQLite-only 实体（PB 无任何覆盖）

- `notebook_entries`（`sqlite_store.py:361-405`，UNIQUE 四元组 `:398`）及 `notebook_categories`/`notebook_entry_categories`（`:448-458`）
- `assessment_attempts`（`:407-429`）
- `reading_quiz_pending`/`reading_quiz_rewards`（`:431-446`，星星奖励）
- practice 题库表由 `deeptutor/services/practice/storage.py` 注入（`sqlite_store.py:516-518`）
- 上述读写在 PB 模式下仍钉住本地 SQLite：`learning/assessment.py:433,515`、`api/routers/reading_extensions.py:360,379,494`、`api/routers/reading.py:462`、`api/routers/practice.py:94,127,161,218`、`tools/question_bank.py:134`、`capabilities/mastery/tools.py:333`、`agents/question/history.py:56`、`book/inputs.py:106,241`、`learning/topic_materials.py:276`、`agents/_shared/tool_composition.py:351`
- 会话自身的分支端点也钉 SQLite：`api/routers/sessions.py:541`（update_branch_selection）、`:555`（delete_turn_by_message）、`:576` → **D4**

---

## 3. 漂移清单（分级）

| 编号 | 级别 | 漂移 | 证据 | 去重标注 |
| --- | --- | --- | --- | --- |
| D1 | 高 | PB sessions 集合缺 `deleted_at` 字段：bootstrap 未创建 `pb_setup.py:161-181`，而 soft_delete 写 `pocketbase_store.py:484`、restore `:503`、migrate_workspace_preferences 归档提升 `:223-226`、读/过滤 `:150,339-340,581,616,641` 全依赖。新 PB 部署：软删"成功"但列不存在（PB 忽略未知字段）→ 回收站/恢复/硬删/归档迁移静默失效 | `pb_setup.py:161-181` vs `pocketbase_store.py:484,503,223-226` | **新发现**（scan-persistence §2.2 只记"无 schema 升级机制"，未定位到该缺列） |
| D2 | 高 | 会话派生字段语义漂移：PB `sessions.status/capability` 落列但 turn 迁移从不回写，`active_turn_id` 恒 `""`（`pocketbase_store.py:336-338`）；SQLite 全部读时派生（`sqlite_store.py:1203-1233,2647-2662`）。PB 上 `get_session`/`get_session_with_messages` 返回过期 idle 状态；仅 `get_session_summaries` 重算（`:736-738`） | `pocketbase_store.py:336-338` vs `sqlite_store.py:1203-1233` | 新发现（scan-persistence 未列） |
| D3 | 高 | 消息父子链不对称：SQLite 建列+回填+自动成链+分支读（`sqlite_store.py:479-506,1909-1924,2471-2504`）；PB 无列、metadata 藏键、无自动链、import 不回填、`get_messages_for_context` 忽略 leaf（`pocketbase_store.py:45-47,867,414-430,1188-1193`）。协议默认值也不一致：protocol `None`（`protocol.py:136`）vs SQLite `_PARENT_AUTO`（`sqlite_store.py:1970`）vs PB `None` | `pocketbase_store.py:45-47,867,1188-1193` | 【去重：scan-persistence §2.2 已记"父链藏 metadata"】本卡新增：默认链路不对称 + import 不回填 + 协议默认漂移 |
| D4 | 高 | SQLite-pinned 读写面在 PB 模式下分裂：notebook/assessment/星星/练习/题库/分支端点全部 `get_sqlite_session_store()` 直连本地库（见 §2.5 引用清单，含 `api/routers/sessions.py:541,555,576`）；PB 部署下会话在 PB、星星/练习/分支数据在本地文件，双库无一致性 | `api/routers/sessions.py:541,555,576` 等清单 | 【去重：scan-persistence §2.4 记"星星存聊天库"（存储位置维度）】本卡新增：PB 部署形态下的双库分裂与被钉死的 API 面 |
| D5 | 中 | `turn_events.content` PB 截断 10000 字符（写入 `pocketbase_store.py:1703`、幂等比较 `:1683`），SQLite 不截断（`sqlite_store.py:1637,1547-1554`）→ 同一事件流两后端保真度与冲突判定不同 | `pocketbase_store.py:1683,1703` vs `sqlite_store.py:1637` | 新发现 |
| D6 | 中 | `turn.last_seq` 读侧不对称：SQLite 派生 MAX(seq)（`sqlite_store.py:1384`），PB 硬编码 0（`pocketbase_store.py:1503`）→ 同一契约字段在 PB 上恒失真 | `pocketbase_store.py:1503` vs `sqlite_store.py:1384` | 新发现 |
| D7 | 中 | begin_turn 竞态契约漂移：SQLite 捕获 IntegrityError→`ActiveTurnConflict`（`sqlite_store.py:1335-1338`）；PB 有同款部分唯一索引（`pb_setup.py:228-229`）但不翻译冲突，竞态时抛原始客户端异常（`pocketbase_store.py:1252-1290`） | `pocketbase_store.py:1252-1290` vs `sqlite_store.py:1335-1338` | 新发现（PB 唯一索引本身存在，缺的是异常翻译） |
| D8 | 中 | 错误契约不对称：PB `add_message` 吞异常返回 0（`pocketbase_store.py:905-907`）、`delete_message`/`get_messages`/`get_last_message` 吞异常返回 False/[]/None（`:918-922,1181-1185,952-954`）；SQLite 对缺失会话抛 `ValueError`（`sqlite_store.py:1906-1907`）→ PB 上调用方无法区分"写入失败" | `pocketbase_store.py:905-907,918-922` | 新发现 |
| D9 | 中 | `import_legacy_session` 契约漂移：返回体 PB 缺 `updated` 键（`pocketbase_store.py:440-444` vs `sqlite_store.py:2044-2049`）；capability 落值不一致（PB 硬编码 `"chat"` `:407,423`，SQLite `''` `:2068`）；重导入语义不同（SQLite 回填 import attribution `:2031-2049`，PB 直接跳过 `:388-389`） | `pocketbase_store.py:388-389,407,440-444` | 新发现 |
| D10 | 中 | `get_messages` 排序键不对称：SQLite `ORDER BY id`（`sqlite_store.py:2446`），PB `sort: msg_created_at` 无 tiebreak（`pocketbase_store.py:1149`）→ 同毫秒/时钟回拨时两后端消息顺序可不同（分支/上下文错位） | `pocketbase_store.py:1149` vs `sqlite_store.py:2446` | 新发现 |
| D11 | 中 | PB 集合索引覆盖不对称：`sessions` 无 `session_id` 唯一索引（并发 create/import 可重复）且无 updated_at/user_id 索引；`messages` 无 `session_id` 索引（`pb_setup.py:161-203` vs SQLite `sqlite_store.py:285,311-319`） | `pb_setup.py:161-203` | 【去重：scan-persistence §2.2 记 get_full_list 全扫（性能维度）】本卡新增：唯一性约束缺口（正确性维度） |
| D12 | 低 | `turn_events` 结构不对称：PB 冗余 `session_id` 列（`pb_setup.py:246`，写入可落空串 `pocketbase_store.py:1698`），SQLite 靠 join（`sqlite_store.py:1684-1685`）；SQLite 双时间戳（`:353-354`），PB 单 `event_timestamp`+系统 `created` | `pb_setup.py:246` | 新发现 |
| D13 | 低 | 默认值声明漂移：SQLite 内部 `messages.metadata_json DEFAULT '{}'` vs `turn_events.metadata_json DEFAULT ''`（`sqlite_store.py:302` vs `:352`）；title/content 的 NOT NULL DEFAULT 仅 SQLite 有，PB 靠代码补默认（`pocketbase_store.py:248,881`） | `sqlite_store.py:302,352` | 新发现 |
| D14 | 低 | 建表与迁移叙述不一致：`sessions.deleted_at` 不在 CREATE TABLE（`sqlite_store.py:284-292`）仅 ALTER 补（`:464-465`）；`preferences_json` 同时出现在 CREATE（`:291`）与 ALTER 守卫（`:462-463`）。幂等无害，但"完整 schema"需读两处 | `sqlite_store.py:284-292,462-465` | 与 test-sqlite-store 互补：其测试断言升级补列与 kind 残留，未断言 deleted_at 缺席建表 |
| D15 | 低 | turns v2 回填双实现：SQLite 迁移回填 assistant_message_id + 重复 running 收敛（`sqlite_store.py:582-639`）；PB 侧重复收敛独立实现在 bootstrap（`pb_setup.py:88-115`）。同一逻辑迁移两处维护 | `pb_setup.py:88-115` vs `sqlite_store.py:582-639` | 【去重：scan-persistence §4 中危"三种 schema 版本习惯并存"】本卡新增：同一迁移的具体双实现 |

---

## 4. 可拆卡条目

1. **fix: pb_setup sessions 集合补 deleted_at + 存量回填**（对应 D1）
   - `scripts/pb_setup.py` sessions schema 增 `deleted_at`(number)；`_sync_existing_collection` 幂等补列后，对"已 archived=true"的存量做一次 deleted_at 回填（或按 preferences_json.archived 提升回来的行重刷）。
   - 验收：重跑 pb_setup 幂等；真 PB 上 soft→list_deleted→restore→hard 全链路通；回归测试模拟缺列集合的升级。
2. **fix: PB turn 契约对齐**（对应 D5/D6/D7）
   - `last_seq` 按尾部事件派生；begin_turn 捕获唯一索引冲突翻译为 `ActiveTurnConflict`；content 截断策略与 SQLite 对齐（抬上限或两端同截）。
   - 验收：同一事件流在两后端 `get_turn`/`get_turn_events` 输出一致；并发 begin_turn 在 PB 上抛 `ActiveTurnConflict`。
3. **fix: PB add_message/import 错误与返回契约**（对应 D8/D9）
   - add_message 不吞异常或契约化返回；import 返回补 `updated`；capability 落值与 SQLite 对齐；重导入走同一 attribution 回填。
4. **fix: PB 消息父链落列或协议收窄**（对应 D3/D10）
   - 方案 A：messages 集合增 `parent_message_id`(text) 列，bootstrap 迁移从 metadata 提升，`get_messages` 排序加 `-created,-id` 类 tiebreak，`get_messages_for_context` 支持 leaf。
   - 方案 B：明确"PB 不支持编辑分叉"，在协议层与前端禁用分支入口（现 `pocketbase_store.py:1188-1193` 的静默降级改为显式声明）。
5. **fix/docs: SQLite-pinned API 面治理**（对应 D4）
   - sessions.py 分支端点改 `get_session_store()` 或 PB 模式显式 501；星星/练习维持本地并在部署文档声明"PB 模式下学习数据仍在本地 SQLite"。

---

## 5. 验收对照

1. 对照表覆盖全部会话实体，每项附 path:line —— §2.1–2.5（sessions / messages / turns / turn_events / SQLite-only 实体）。
2. 与 scan-persistence 结论去重标注 —— §3 表格逐条标注【去重】/【新发现】；对照基线 `evidence/persistence-scan-20261004/report.md`（commit `b130ee082`）。test-sqlite-store（commit `8ddd1fd39`）为测试面，D14 处注明互补关系。
3. 不改任何代码 —— 本分支仅新增 `evidence/session-schema-drift-20261005/` 下报告与校验文件，`git diff origin/main --stat` 可验证。
