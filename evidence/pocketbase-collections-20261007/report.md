# PocketBase 集合/字段字符串引用一致性清点（AGEN-1102 · 2026-10-07）

- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（v1.6.13，2026-10-04），只读静态清点；未改任何产品代码，未连接任何 PocketBase 实例。
- 方法：以 `\.collection("…")` 调用点为主轴（脚本扫描 deeptutor/ + scripts/，含 `for table/name in (…)` 间接引用），对每个集合再回读其全部 `filter` / `fields` / create·update payload 字符串；对照三方定义：
  - **schema 轴**：`scripts/pb_setup.py`（仓库内唯一的集合定义来源，162/186/208/242/268 行定义 sessions、messages、turns、turn_events、knowledge_bases）；
  - **协议轴**：`deeptutor/services/session/protocol.py`（SessionStoreProtocol 返回字典的键契约）；
  - **对照轴**：`deeptutor/services/session/sqlite_store.py`（同协议的 SQLite schema，用于发现单边漂移）。
- 去重：会话域发现标注与 scan-session-schema-drift（会话域三方 schema 对照轴）重叠；行为侧只标注不展开（test-pocketbase-client / test-pocketbase-store 轴）；`sessions.deleted_at` 单点修复已派卡（fix-pb-deleted-at），本卡只补全引用面。

## 一、结论摘要

| 维度 | 计数 | 说明 |
| --- | --- | --- |
| 集合引用点（生产码） | 76 处 / 7 文件 | 全部为内联字符串字面量，无集合名常量模块 |
| 命名不一致 | 6 项（1 高 / 2 中 / 3 低-信息） | 见第三节 |
| 定义缺失 | 3 项（1 高 / 1 中 / 1 低） | 见第四节 |
| 唯一 in-repo schema | 5 集合 | `users` 集合被 3 处引用但仓库零定义 |

生产码引用分布：sessions 21、turns 19、messages 16、turn_events 12、knowledge_bases 5、users 3（含 1 处 docstring 示例 pocketbase_client.py:20、5 处 loop-header 间接引用）。

## 二、集合 × 引用点对照表（path:line，均为 `deeptutor/` 前缀省略写法）

### sessions（21 处）
| path:line | 用法 |
| --- | --- |
| services/pocketbase_client.py:20 | docstring 示例 |
| services/session/pocketbase_store.py:140,200,254,352,395,438,465,484,503,526,548,595,639,788,822,892,1045 | get_full_list / get_list / create / update / delete |
| services/workspace/data_migration.py:197,756 | 导出 / 重绑 |
| services/workspace/session_move.py:92 | 默认工作区收编 |

### turns（19 处）
| path:line | 用法 |
| --- | --- |
| services/session/pocketbase_store.py:1093,1152,1254,1269,1320,1338,1363,1391,1415,1452,1465,1522,1531,1570,1646 | 直接调用 |
| services/session/pocketbase_store.py:459 (loop) | delete_session 级联元组 `("turn_events","turns","messages")` |
| services/workspace/data_migration.py:358,736 (loop) | 活跃 turn 阻塞检查 / 快照 |
| scripts/pb_setup.py:90,105 | 迁移去重清理 |

### messages（16 处）
| path:line | 用法 |
| --- | --- |
| services/session/pocketbase_store.py:417,435,665,687,755,888,912,915,938,1146,1562 | 直接调用 |
| services/session/pocketbase_store.py:459 (loop) | 级联删除 |
| services/workspace/data_migration.py:436 (loop),452 (loop),736 (loop),768 (loop) | 迁移 / 快照 / 重绑（436/452 为 SQLite 侧同型循环，PB 侧为 736/768） |
| services/session/pocketbase_store.py:1065 | usage_records 分页读（变量传参） |

### turn_events（12 处）
| path:line | 用法 |
| --- | --- |
| services/session/pocketbase_store.py:985,1004,1580,1587,1654,1695,1727 | trace 预览 / 续读 / 追加 / 回放 |
| services/session/pocketbase_store.py:1112,459 (loop) | usage_records / 级联删除 |
| services/workspace/data_migration.py:743,768 (loop) | 快照 / 重绑 |

### knowledge_bases（5 处）
| path:line | 用法 |
| --- | --- |
| api/routers/knowledge.py:650,657 | 上传文件（get_full_list + update files=raw_files） |
| knowledge/manager.py:485,497,499 | `_sync_kb_to_pb` 镜像 |

### users（3 处，仓库内无定义，见发现 D2）
| path:line | 用法 |
| --- | --- |
| services/pocketbase_client.py:144 | `auth_refresh()` 令牌校验 |
| services/auth.py:368 | `auth_with_password` 登录 |
| services/auth.py:396 | `create` 注册 |

字段级引用（filter / fields / payload）全部随上表调用点落位：sessions 用 `session_id,user_id,title,compressed_summary,summary_up_to_msg_id,preferences_json,capability,status,session_created_at,session_updated_at` + filter JSON 路径 `preferences_json.workspace_id/.archived/.parent_session_id`；turns 全 14 列（含 `fencing_token/state_version/failure_code/retryable/assistant_message_id`）；turn_events 全 9 列（含 `seq/type/source/stage/metadata_json/event_timestamp`）；messages 全 8 列；knowledge_bases 用 `kb_name,description,rag_provider,needs_reindex,status,kb_created_at,raw_files`。除下文列出者外，payload/filter 字段与 pb_setup.py schema 逐一吻合。

## 三、命名不一致（6 项）

| # | 级别 | 发现 | 证据 |
| --- | --- | --- | --- |
| N1 | 高 | `deleted_at` 软删列三轴命名分裂：SQLite 有列且带迁移（sqlite_store.py:464-465），协议暴露 `is_deleted`/`deleted_at` 双键（pocketbase_store.py:339-340），PB 侧 15 个引用点读写的列在 pb_setup.py sessions schema 中不存在 | 详见 D1；[去重: session-schema-drift, fix-pb-deleted-at] |
| N2 | 中 | `*_created_at` 同名后缀异型：`kb_created_at` 为 text（pb_setup.py:277），而 `session_created_at`(173)、`turn_created_at`(216)、`event_timestamp`(253) 均为 number；manager.py:495 从本地配置写入字符串。text 类型在 PB 侧无法参与数值排序/比较，跨集合时间语义不一致 | 可拆卡（见第六节 C3） |
| N3 | 中 | messages 父消息链接三方三态：SQLite 真列 `parent_message_id INTEGER` + 索引（sqlite_store.py:308,479-505）；PB 存于 metadata_json 键 `_parent_message_id`（pocketbase_store.py:45-47,873,1210）；协议参数名 `parent_message_id`（protocol.py:136,208）。属注释声明的设计取舍，但分支上下文在 PB 明确不可用（pocketbase_store.py:1191-1193） | [去重: session-schema-drift] |
| N4 | 低 | 双时间戳源回退链：PB 逻辑列 `session_created_at/session_updated_at` 优先，回退 PB 系统列 `created/updated`（pocketbase_store.py:205,214-219,312-320,674,692,761），同一集合读路径最多三个时间来源 | [去重: session-schema-drift] |
| N5 | 低 | 协议键 `last_seq` / `active_turn_id` 两后端答案不同：SQLite 计算 MAX(seq)/子查询（sqlite_store.py:1223,1271,1384,1403），PB 恒写死 `0`/`""`（pocketbase_store.py:338,1301,1503） | [去重: session-schema-drift] |
| N6 | 信息 | filter 风格分裂：同集合内字符串引值（`session_id="…"`）与数值裸值（`msg_created_at >= 1.7e9`，pocketbase_store.py:1067）混用；`user_id` 一处 json.dumps 引值（201）一处 f-string 裸引（581） | 纯风格，无功能影响 |

## 四、定义缺失（3 项）

| # | 级别 | 发现 | 引用面 | 影响 |
| --- | --- | --- | --- | --- |
| D1 | 高 | `sessions.deleted_at` 列未定义：pb_setup.py sessions schema（161-181 行）无此列，代码 15 处引用。写路径 484/503（软删/恢复）与 223-225；读路径 150,323,339,340,552,554,616,648；**filter 路径 581/641 `deleted_at = null` 在缺列集合上会 400**，list_sessions/search_sessions 全量失效 | pocketbase_store.py:134,138,150,223,225,323,339,340,484,503,540,552,554,581,616,641,648 | 全新部署跑 pb_setup.py 后软删/列表/搜索即坏；SQLite 轴已有该列证明其为协议必需（sqlite_store.py:464-465）。**[去重: fix-pb-deleted-at 单点修复已派卡，本卡补全 15 处引用点作为其回归范围，不重复开卡]** |
| D2 | 高 | `users` 集合仓库零定义：3 处引用（auth.py:368,396；pocketbase_client.py:144），读写 `username/email/password/passwordConfirm/name/role/id`，但 pb_setup.py 不创建也不扩展 users；PB 内建 users 不保证 `username`（新版默认移除）与 `role`/`name` 字段存在。role 读取静默回退 "user"（auth.py:378、pocketbase_client.py:153），username 缺列时 register_pb 直接失败（auth.py:396-403） | 可拆卡 C2：pb_setup.py 增加幂等 users 同步（复用 `_sync_existing_collection`）或在部署文档固化 users schema 要求 |
| D3 | 低 | 协议字段 PB 无承载列：turns 无 `seq/last_seq` 列，`last_seq` 恒 0（见 N5）；sessions 无 `active_turn_id` 列恒 ""（pocketbase_store.py:338）。协议允许（runtime_checkable 只查方法），但消费方若信任这些键在 PB 模式下得到空值 | [去重: session-schema-drift] |

## 五、字面量散点（类别 1）

- 76 处集合名引用散布 7 个生产文件（分布见第二节），无任何 `COLLECTION_*` 常量、无集中模块；`scripts/pb_setup.py` 与运行时各自独立拼写集合名，改名需手动对齐 7 文件。
- 5 处 loop-header 间接引用（pocketbase_store.py:459；data_migration.py:436,452,736,768）使 `rg '"sessions"'` 类检索漏报级联删除与迁移目标集合。
- 测试侧同型字面量另计（tests/services/session/test_pocketbase_isolation.py:145,209,226,388,394；test_turn_event_flush.py:252,268,280）。**[去重: test-pocketbase-client / test-pocketbase-store 行为测试轴——测试经 FakePB 接受任意字段，故 D1/D2 类 schema 缺列不产生测试失败，该问题归测试卡轴跟进，本卡不展开]**
- 前端（web/ChatStateAdapter.tsx:3320、web/lib/turn-reconcile.ts:10）与 compose.yaml / .env.example / Dockerfile 仅含 "pocketbase" 模式/服务名字符串与配置键，无集合/字段引用，未计入。
- 可拆卡 C1（低优先）：引入 `deeptutor/services/session/pb_collections.py` 之类的常量模块（含字段名），pb_setup.py 与 store 共用；纯重构，不改行为。

## 六、可拆卡条目

| # | 建议卡 | 优先级 | 内容 |
| --- | --- | --- | --- |
| C1 | pb 集合名常量化重构 | 低 | 第五节；一次小 PR，7 文件机械替换 + 5 处 loop 元组改常量 |
| C2 | users 集合同步进 pb_setup.py | 高 | 第四节 D2；幂等补 `username/name/role` 或文档固化，含注册路径回归测试 |
| C3 | kb_created_at 类型统一 | 中 | N2；text→number 需数据迁移说明，或反向把其余 `*_created_at` 语义对齐文档化 |
| C4 | （已派卡，勿重开）sessions.deleted_at 补列 | 高 | D1 = fix-pb-deleted-at；本报告 15 处引用点可作为该卡回归清单 |

## 七、方法与限制

- 纯静态扫描 + 人工回读调用点上下文；`pb.collection(<变量>)` 的 5 处间接点已通过元组字面量归位；正则可能漏掉跨行字符串拼接的 filter（人工复核未发现）。
- 未连接任何 PocketBase 实例，"线上部署集合可能已手工补列"无法证伪——D1 影响表述限定在"全新 pb_setup 部署"场景。
- 本卡不改任何产品代码；evidence/ 目录仅含本报告与校验和。
