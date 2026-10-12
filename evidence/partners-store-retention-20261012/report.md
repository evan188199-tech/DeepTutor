# partners 存储增长与孤儿审计（manager / sessions / links / 索引）

- 基线：`origin/main` @ `6cf793bd8`（v1.6.14），只读 worktree（新分支 `evidence/partners-store-retention-20261012`），未改任何源码。
- 范围：`deeptutor/services/partners/`（17 文件 6438 行）及其落盘点（`deeptutor/partners/config/paths.py`、`deeptutor/partners/channels/base.py`、`deeptutor/api/routers/partners.py`、`deeptutor/multi_user/identity.py`）。离线静态分析，未启动任何服务。
- 去重边界：
  - `scan-session-store-retention`（会话轴）管统一会话后端（sqlite/pb）的保留；本卡只管 partners 树自身的 sessions/links/索引/运行态。
  - `fix-partners-index-atomic-rebuild` 分支（`myfork/fix/partners-index-atomic-rebuild` @ `5fc9264f7`）已核对：diff 只改 `deeptutor/services/partners/workspace.py`（notebook 索引 `notebooks_index.json` 原子化），**不覆盖**本卡 §4.1 的 sessions `_index.json` 非原子写发现。
  - `test-partner-*` 测试卡不产证据。
- 所有路径相对仓库根；行号以基线 `6cf793bd8` 为准。

## 0. 树根与目录不变式

- 树根固定为 admin workspace 下的 `partners/`，与请求者 scope 无关（防递归布局）：`deeptutor/partners/config/paths.py:11-22`（`_base_dir` = `get_admin_path_service().workspace_root / "partners"`）。
- partner 发现只认"目录存在且含 `config.yaml`"（`deeptutor/services/partners/manager.py:1042-1047`），保留名 `{workspace, media, sessions, _souls}`（`manager.py:121`）与 `.`/`_` 前缀目录（`manager.py:1043`）被排除——`media/`、`_runtime/`、`_souls.yaml` 不会被误认成 partner。

## 1. 落盘位置清单（位置 × 写入方式）

| # | 位置 | 内容 | 写入方式 | 证据 |
|---|------|------|----------|------|
| 1 | `data/partners/{id}/config.yaml`（含 `.tmp` 瞬态） | 配置 + `auto_start` | tmp+replace 原子 | `manager.py:612-658`（写点 `:656-658`） |
| 2 | `data/partners/{id}/workspace/**` | SOUL.md、knowledge_bases/、skills/、notebook/ | copytree + 非原子 `write_text` | `workspace.py:70-72`；SOUL 写点 `workspace.py:112-115`；KB `workspace.py:214-221`；notebook 索引非原子 `workspace.py:310-323`（写点 `:323`） |
| 3 | `data/partners/{id}/sessions/*.jsonl` | 共享/未归因会话（admin + 未链接渠道） | 追加写 | `sessions.py:161-204`（写点 `:201-204`） |
| 4 | `data/partners/{id}/sessions/_index.json` | 归档软标志 sidecar | **非原子** `write_text` | `sessions.py:72-91`（写点 `:86-91`） |
| 5 | `data/partners/{id}/sessions/*.turn.lock` | web 回合跨进程锁（1 字节 `\0`） | open("a+b")+flock | `manager.py:79-104`；路径派生 `manager.py:1328-1329` |
| 6 | `data/partners/{id}/users/{uid}/sessions/*.jsonl` | 个人会话（链接账号后） | 同 #3 | `interaction.py:76-101`（分流 `:83-86`） |
| 7 | `data/partners/{id}/users/{uid}/web_continuity.json`（含 `.lock`） | 跨浏览器活动会话指针 | 临时文件+replace 原子；锁文件 `.{name}.lock` 常驻 | `web_continuity.py:69-97`（写 `:91-97`；锁 `:26-52`） |
| 8 | `data/partners/{id}/users/{uid}/workspace/memory/` | 关系记忆（chat 格式 PathService） | mkdir+工具写入 | `interaction.py:151-160` |
| 9 | `data/partners/{id}/channel_links.json` | 渠道账号→DeepTutor 账号绑定 + 兑换码 | `atomic_write_json` 原子整写 | `links.py:53-54`（路径）、`:104-111`（`_update`） |
| 10 | `data/partners/{id}/channels/{channel}/` | 渠道运行态（token、poll cursor、E2EE device store） | 各渠道自写 | `paths.py:57-63`；`channels/base.py:109-122` |
| 11 | `data/partners/{id}/media/{channel}/` | 渠道媒体下载 + web 附件（`{uuid12}_{filename}`） | 直接落盘，无回收 | `paths.py:52-54`；web 附件 `api/routers/partners.py:1596-1630`（命名 `:1627`）；渠道 `channels/base.py:99-107` |
| 12 | `data/partners/media/{channel}/` | **旧共享**媒体目录（仅无 partner_id 的独立渠道） | 同 #11 | `paths.py:29-32`；`channels/base.py:107` |
| 13 | `data/partners/_souls.yaml` | 灵魂模板库（整文件重写） | 非原子 `write_text` | `manager.py:1549-1573`（写点 `:1570`） |
| 14 | `data/partners/_runtime/status.sqlite3`（+`-wal`/`-shm`） | 跨 worker 运行态投影，每 partner 1 行 UPSERT | WAL SQLite | `runtime_status.py:17-41`（路径 `:18`；建表 `:20-34`；UPSERT `:70-93`） |
| 15 | `{用户工作区}/partner_drafts/{32hex}.json` | Partner 草稿 —— **在 partners 树之外** | tmp+replace 原子 | `drafts.py:58-62`（root）、`:117-121`（路径校验）、`:99-109`（原子写） |
| 16 | `data/tutorbot/`（遗留） | TutorBot 迁移源树，**原地保留** | 只读残留 | `manager.py:1488-1545`（非破坏性注释 `:1493-1494`） |
| 17 | `data/partners/{weixin,mochat,msteams,matrix-store}`（遗留共享渠道态） | 一次性 rehome 的**拷贝源**，原地保留 | 只读残留 | `channel_state_migration.py:20-22, 37-42, 94-127` |

## 2. 增长轴矩阵

| 对象 | 增长模式 | 上限/回收 | 证据 |
|------|----------|-----------|------|
| 会话 JSONL（#3/#6） | 每回合追加 2 条记录（user+assistant）；assistant 记录内嵌**完整 events 轨迹**与附件元数据 | 无写入上限；读侧仅 40 条 / 24,000 字符窗口（对落盘无影响） | 追加点 `runtime.py:342-375`（`:342` user、`:359` assistant、`:373-374` events/attachments）；events 字段 `sessions.py:199-200`；读窗口 `sessions.py:24-25`；"IM 不读回 events 但成本在存储"注释 `sessions.py:196-198` |
| 归档副本 `_archived_*.jsonl` | IM 每次 `/new` 把当前文件 rename 为 `_archived_<stamp>_<key>.jsonl`；同名冲突加序号 | 无 GC | `sessions.py:213-243`（rename `:241`）；前缀 `:26` |
| branch 副本 | `/branch` 把源会话**全量复制**到新键再归档源 | 无 GC，字节翻倍 | `sessions.py:141-157`（复制 `:152-155`） |
| `users/{uid}/sessions` | 每 (partner, 链接用户) 一套独立 JSONL 树 | 无 GC | `interaction.py:76-101` |
| 媒体（#11/#12） | web 附件每文件独立落盘；渠道媒体下载同目录 | **全仓 0 处清理代码**（grep clean/prune/retention/purge/ttl 于 partners/channels 无命中） | `routers/partners.py:1627` |
| `*.turn.lock`（#5） | 每会话键 1 个文件，释放只 close 不删除 | 单调增长（每文件 1 字节 + 目录项） | `manager.py:106-118` |
| `.web_continuity.json.lock`（#7） | 每 (partner,uid) 1 个 | 常驻 | `web_continuity.py:30` |
| `_runtime/status.sqlite3`（#14） | 每 partner 1 行，UPSERT 覆盖；WAL 常规伸缩 | **有界** | `runtime_status.py:70-93` |
| `_souls.yaml`（#13） | 整文件重写 | 有界 | `manager.py:1568-1573` |
| `channel_links.json`（#9） | codes 15 分钟 TTL 过期清理；links 无淘汰（绑定数单调增） | codes 有界、links 无界 | TTL `links.py:36`；清理 `links.py:87-94`（仅作用于 codes） |
| `partner_drafts`（#15） | 每 draft 一 JSON；`status=created` 永存 | 数量无上限 | `drafts.py:64-84`、`:111-115`；soul 上限 20,000 字符 `drafts.py:70` |
| 内存有界项 | activity feed 每账号 32 条（`manager.py:364`，逐出 `:376-381`）；`live_turns` 每键覆盖（`manager.py:1316`） | 有界 | 同左 |

读放大（非落盘但随增长恶化）：`merged_messages` / `list_sessions` 每次 stat 并**全量读取**所有 `*.jsonl` 后排序再截断（`sessions.py:383-396`、`:453-459`）；`messages_page` 从文件头逐行读到游标（`sessions.py:316-338`）；`get_recent_active_partners` 遍历全部 partner 的全部会话文件（`manager.py:1139-1161`）。

## 3. 孤儿与残留矩阵

| 对象 | 产生条件 | 残留影响 | 证据 |
|------|----------|----------|------|
| `users/{uid}/` 整棵（会话+记忆+continuity） | 账号被删除（`delete_user` 只删 users 记录 + guardian 关系，**无任何 partners 清理钩子**） | 无主个人数据永存于 partner 目录内 | `multi_user/identity.py:367-386`；`get_partner_user_dir` 全仓仅 `web_continuity.py:70` 与 `interaction.py` 引用 |
| `channel_links.json` 中已删账号的 link | 同上；`remove_link` 仅限本人调用，账号删除不触发 | 悬空绑定：`actor_for_account` 返回 None 回退共享池，但记录永存 | `links.py:181-191`；回退 `interaction.py:35-60`（`:46-48`） |
| `*.turn.lock` | `delete_session` 只删 `.jsonl` 与索引条目；`clear` 只删 `.jsonl` | 锁文件永存 | `sessions.py:130-139`、`:206-211`；无任何 unlink |
| 媒体文件（#11） | `delete_session` / `clear` 不回收 `attachments` 引用的媒体 | 孤儿 blob 永存 | `routers/partners.py:1596-1630` 无反向清理；`sessions.py:130-139` |
| `_index.json` 陈旧条目 | 手工删除会话文件后条目残留（无对账路径） | `is_archived` 对不存在文件误报标志 | `sessions.py:106-111` |
| `partner_drafts` 悬空 `created_partner_id` | `destroy_partner` 后草稿仍在（树外） | 读取端降级为 stopped 占位，草稿永存 | `drafts.py:111-115`；读取降级 `routers/partners.py:866-870` |
| cron 任务 | `remove_owner_jobs` 失败仅 warning | 孤儿定时任务继续触发 | `manager.py:1450-1455` |
| 遗留 `data/tutorbot/`、遗留共享渠道态目录（#16/#17） | 迁移设计为"拷贝不移动" | 永久双份存储（含渠道凭据副本） | `manager.py:1493-1494`；`channel_state_migration.py:20-22` |
| runtime status 行 | 仅当 partner 目录被**外部手段**删除（正常 destroy 先删行后删树，`manager.py:1449`→`:1459`） | 孤儿行；`list_partners` 对未知 id 跳过（`manager.py:1083-1085`），但行不清理 | `runtime_status.py:112-116` |
| 会话键折叠碰撞 | `safe_filename` 有损折叠（`:`/`/`→`_`）使不同键同文件 | 数据混写；代码注释声明由调用方键构成保证实际不可达 | `sessions.py:92-104`；`partners/helpers.py:36-39` |

## 4. 重建路径

| 存储 | 损坏表现 | 重建行为 | 后果 | 证据 |
|------|----------|----------|------|------|
| `sessions/_index.json` | JSONDecodeError → 返回 `{}` | 会话列表以磁盘 glob 为源，**列表自愈**；但归档软标志**无重建来源**，下次 `set_archived`/`delete_session` 以单条状态整写 | 所有归档标志静默丢失（归档会话重新显示为未归档）；写本身非原子，崩溃窗口可触发损坏→重置链 | 读回退 `sessions.py:76-84`（`:83-84`）；列表源 `sessions.py:453-459`；非原子写 `sessions.py:86-91` |
| `channel_links.json` | JSONDecodeError → 读空 | 下次 `_update` 整文件重写 | 既有 links 全丢（codes 本就 TTL 短，损失可控）；写为原子，损坏窗口极小 | 读回退 `links.py:70-84`；原子写 `links.py:104-111` |
| `_runtime/status.sqlite3` | 文件删除/损坏 | `CREATE TABLE IF NOT EXISTS` 重建空表 | 仅运行态显示重置，数据无损 | `runtime_status.py:20-34` |
| `config.yaml` | YAML 解析失败 | `load_config` 返回 None 并记日志；无自动重建 | 发现仍要求文件存在（`:1045`），列表降级 `name=pid`；会话数据不受影响 | `manager.py:584-610`（`:608-610`）、`:1045`、`:1060-1062` |
| `kb_config.json` / `notebooks_index.json` | 解析失败 → `{}` / 最小条目重建 | notebook 索引原子化+重建在 `fix-partners-index-atomic-rebuild` 分支（未进 main） | 指针 KB 条目丢失可由重新 provision 恢复 | `workspace.py:161-172`、`:297-323`；fix 分支 diff 仅 `workspace.py`+测试（已核对 `5fc9264f7`） |
| `sessions/*.jsonl` 单坏行 | JSONDecodeError | 逐行跳过 | 不中断读取，该条消息丢失 | `sessions.py:258-261`、`:322-326` |

## 5. `destroy_partner` 删除残留核对

顺序（`manager.py:1445-1461`）：stop（`:1446`）→ forget 会话 store 缓存（`:1447`，`interaction.py:104-108`）→ forget link 锁（`:1448`，`links.py:194-197`）→ 删 status 行（`:1449`）→ 删 cron 任务，尽力而为（`:1450-1455`）→ `shutil.rmtree(partner_dir)`（`:1456-1459`）。

- 一并清除：sessions、`users/`、`channels/`、`media/`、`channel_links.json`、`config.yaml`、`workspace/`、`*.turn.lock`（均在 partner 目录内）。
- 幸存项：`partner_drafts/*.json`（树外，悬空引用）；`_souls.yaml`（共享库，预期保留）；遗留 `data/tutorbot/`；遗留共享渠道态目录；共享 `data/partners/media/`（#12，destroy 不触及）；status sqlite 的 `-wal`/`-shm`（SQLite 自管理）。
- 失败模式：rmtree 中途失败 → 目录半删且无重试/标记；行已删（先删行后删树），列表显示 partner 消失但磁盘有残骸。

## 6. 保留建议（按收益排序）

1. **`.turn.lock` 生命周期**：释放时删除文件（`_release_web_turn_lock`，`manager.py:106-118`）；`delete_session`/`clear` 一并清理；启动时清扫无主锁文件。收益：消除唯一的纯垃圾单调增长项。
2. **`_index.json` 原子写 + 启动对账**：改用 `atomic_write_json`（与 `links.py:110` 同模式）；启动时以 glob stem 集合对账清理陈旧条目。归档软标志损坏后不可恢复属已知取舍，应写入文档。
3. **归档/分支副本 GC**：`_archived_*` 与 branch 副本按条数/字节/年龄设上限；assistant `events` 轨迹按渠道或大小截断（IM 不读回，`sessions.py:196-198`）。
4. **媒体回收**：会话删除时按记录 `attachments[].id` 反查回收媒体；或媒体目录按 mtime TTL 清扫；web 附件 `{uuid12}_` 命名（`routers/partners.py:1627`）已具备对账条件。
5. **账号删除钩子**：`delete_user`（`identity.py:367-386`）补 partners 清理——遍历 partners 删 `users/{uid}/` 与 `channel_links.json` 中该 user_id 的记录。
6. **草稿清理**：destroy partner 时 prune `created_partner_id` 失配的 `status=created` 草稿（读取端已有降级 `routers/partners.py:866-870`，可前移为删除）。
7. **runtime status 开机对账**：启动时 `DELETE FROM partner_runtime_status WHERE partner_id NOT IN (discovered ids)`（配合 `manager.py:1037-1047`）。
8. **遗留树退役**：`data/tutorbot/` 与共享渠道态目录在迁移验证期后提供一次性清理命令（当前永久双份，且 #16/#17 含渠道凭据副本）。

## 附录：数字与方法

- 审计对象规模：`deeptutor/services/partners/` 17 文件 6438 行（manager 1847 / runtime 1178 / sessions 462 / workspace 448 / links 197 / interaction 189 / web_continuity 175 / drafts 145 / runtime_status 132 / channel_state_migration 127 / 其余 <500）。
- 关键常量：读窗口 40 条 / 24,000 字符（`sessions.py:24-25`）；activity feed 32 条（`manager.py:364`）；兑换码 6 位、TTL 15 分钟（`links.py:35-36`）；草稿 soul 上限 20,000 字符（`drafts.py:70`）；分页单页上限 200（`sessions.py:314`）。
- 落盘点合计 17 处（§1）；原子写 6 处（#1/#7/#9/#14/#15 + continuity tmp），非原子 3 处（#2 SOUL、#4 `_index.json`、#13 `_souls.yaml` + notebook 索引 `workspace.py:323`，后者已有修复分支）。
- 媒体/锁文件/归档副本清理代码命中数：0（grep `clean|prune|retention|purge|ttl|max_age` 于 `deeptutor/services/partners` 与 `deeptutor/partners`）。
- 方法：仅静态阅读与 grep/git 取证；未运行服务、未执行仓库代码、未修改任何源文件。
