# 会话历史与内存代码导读（Session History & Memory）

面向 #1410（会话内聊天记录丢失 / L1 镜像看不到完整历史）与 #1614（长会话只渲染前 ~7 轮）
类问题的定位导读。基线：origin/main `ef2d9e5c3`（v1.6.12）。所有行号以该提交为准。

核心结论先行：**压缩（rolling summary）从不删除消息**，SQLite 里的消息是全量的（
`deeptutor/services/session/context_builder.py:162-166` 明确 budget 只是规划目标，非破坏性截断；
`GET /api/sessions/{id}` 返回全部消息，`deeptutor/api/routers/sessions.py:287-298`）。
因此"历史丢失"类 bug 几乎都在**前端可见路径选择**或**内存侧读取边界**，而不是数据被删。

## 一、模块总览

```
写路径  FE 发送 turn(parent_message_id) → executor → add_message(SQLite/PocketBase)
        → ContextBuilder.build（滚动摘要压缩）→ LLM → assistant 消息落库
读路径  FE GET /api/sessions/{id}（全量消息）→ buildVisiblePath 选单条可见路径 → 渲染
内存    chat 轮次 →(工具调用)→ L1 trace JSONL → consolidator → L2/<surface>.md → L3
镜像    L1 workspace mirror：snapshot 适配器直读 chat SQLite → diff → changes.jsonl
```

三层内存布局：`deeptutor/services/memory/paths.py:5-8`（L1 trace JSONL / L2 每表面 MD /
L3 跨表面综合）；表面枚举 chat/notebook/quiz/kb/book/partner/cowriter 见 `paths.py:48-56`。

## 二、入口

后端 API（会话）— `deeptutor/api/routers/sessions.py`：

| 端点 | 位置 | 说明 |
|---|---|---|
| `GET /api/sessions` | sessions.py:112-129 | 列表，limit≤200 分页 |
| `GET /api/sessions/search` | sessions.py:132-152 | 标题+消息全文搜索 |
| `GET /api/sessions/{id}` | sessions.py:287-298 | 会话详情 + **全量**消息 |
| `GET .../messages/{id}/events` | sessions.py:301-312 | 单消息 trace，after_seq+limit≤1000 |
| `PUT .../branch-selection` | sessions.py:531-542 | 持久化分支选择到 preferences_json |
| `DELETE .../messages/{id}` | sessions.py:545 | 按 message 删 turn（会动树结构） |

后端 API（内存）— `deeptutor/api/routers/memory.py`：
`GET /overview`(memory.py:84)、文档读写(memory.py:140-170)、runs 编排(memory.py:308-457)、
`GET /trace/{surface}` L1 事件分页(memory.py:680)、
snapshot 镜像三件套 `GET /snapshot/{surface}`(memory.py:728) /
`POST .../refresh`(memory.py:750) / `GET .../changes`(memory.py:765)。

前端入口：
- 会话 API 封装 `web/lib/session-api.ts`：listSessions(:199)、getSession(:267)、
  getMessageTrace(:336，after_seq 翻页 limit=500)、updateBranchSelection(:417)。
- 可见路径计算 `web/features/chat/messages/ChatMessageList.tsx:1956-1960` 调 `buildVisiblePath`。
- 内存工作台页面 `web/app/(utility)/memory`；L1 镜像面板
  `web/components/memory/MemoryL1Workbench.tsx:85` 拉 `/api/memory/snapshot/{key}`。

turn 管线：`deeptutor/services/session/turns/executor.py` 是每轮的入口，
context 组装在 executor.py:541-555（经 `turns/context_assembler.py:17-20` 构造 ContextBuilder）。

存储后端选择：`deeptutor/services/session/__init__.py:15-38` — 配了
`integrations.pocketbase_url` 走 `PocketBaseSessionStore`，否则本地
`SQLiteSessionStore`（默认）。**排查前先确认实际后端**。

## 三、数据流

### 写路径（一轮对话怎么落库）

1. FE 在 payload 里显式带 `parent_message_id`（可为 null）：出现该 key 即"编辑分支"
   语义，新 user 消息挂到指定父节点，成为已有子节点的兄弟分支；key 缺失则线性追加
   （`deeptutor/services/session/turns/executor.py:268-288`）。
2. 消息表结构：`messages.parent_message_id`（`deeptutor/services/session/sqlite_store.py:286-301`），
   同父即兄弟分支；索引 `idx_messages_parent`(sqlite_store.py:489)。
   写入走 `add_message`(sqlite_store.py:1931)。
3. 上下文构建（见下节）→ LLM → assistant 消息落库并 `link_turn_message`
   (sqlite_store.py:1695)；branch 元数据写入见 executor.py:845-852、:1088。

### 读路径（会话页怎么渲染）

`GET /api/sessions/{id}` 一次性返回全部消息（sessions.py:287-298，后端**不分页**，
`get_session_with_messages` 在 sqlite_store.py:2927）。前端用
`buildVisiblePath(allMessages, selectedBranches)`（`web/lib/message-branches.ts:101-159`）
从平铺列表选出**一条**根→叶路径：每个分叉点优先用已持久化的 `selected_branches`，
否则**取最新创建的兄弟**（:136-140）；乐观（负数 client id）永远排最前（:32-43）。
#1614 的直接病灶就在 :136-140 这个"未选择→最新兄弟"回退（见第七节）。

### 上下文压缩（rolling summary）

`ContextBuilder.build`（`deeptutor/services/session/context_builder.py:469-621`）：

1. 取消息（编辑轮只取 leaf 祖先链，sqlite_store.py:2563-2598；:482-484）。
2. 读 watermark：`sessions.compressed_summary` + `summary_up_to_msg_id`
   （列定义 sqlite_store.py:281-282；读取 context_builder.py:492-493）。
3. **分支守卫**：watermark 不在当前祖先链上就丢弃 summary 从本分支重建
   （context_builder.py:494-502；测试 tests/services/session/test_context_builder.py:676）。
4. 预算：history=窗口×0.35、summary=40%、recent=60%（context_builder.py:171-176,
   :185-209；上限常量 :29,:37-39）。
5. 未超预算直接返回（:517-527）；超了则 `_select_recent_messages` 从尾往前按组保留
   （:245-269），前缀重新摘要：原始前缀还能放下就从原文重建（防摘要漂移，
   :537-543,:600），否则折叠加旧摘要（:547-552）。
6. **watermark 只在摘要成功后前移**（:589-596）；失败则本轮降级、下轮重试
   （:598-608）。持久化 `update_summary`（sqlite_store.py:2880-2893）。

### 内存（Memory L1/L2/L3）

- L1 trace 追加：`MemoryStore.emit` → `trace.append`
  （`deeptutor/services/memory/store.py:77-78`；JSONL 落盘 `trace.py:66-86`）。
  chat 表面的事件主要来自 read/write_memory 工具（`deeptutor/tools/builtin/__init__.py:911,:982-989`）
  与 RAG（`deeptutor/services/rag/service.py:172`）——**普通聊天轮次本身不写 L1 trace**。
- 挂载判定：L3 任一槽非空才自动挂 read_memory
  （`deeptutor/agents/_shared/tool_composition.py:296-304`）。
- 每轮把 L3 拼进上下文：executor.py:556-557（`read_l3_concat` store.py:94）。
- consolidator 做 L1→L2、L2→L3（`deeptutor/services/memory/__init__.py:3-9`；
  runs 编排 memory.py:240-457）。

### L1 Workspace 镜像（snapshot）

- 适配器直读工作区/数据库：chat 表面 `read_chat_entities` 一个会话一个 Entity，
  content 内联全部消息（`deeptutor/services/memory/snapshot/adapters.py:408-454`）。
- diff 与变更日志：`snapshot/__init__.py:36-107`（refresh 只存 fingerprint+label，
  :74-91；changes 分页 :94-99）。
- API 出口 memory.py:725-783；前端 MemoryL1Workbench.tsx:85。

## 四、关键文件表

| 文件 | 职责 | 关键行 |
|---|---|---|
| deeptutor/services/session/sqlite_store.py | 会话/消息持久化（SQLite） | schema :276-301；add_message :1931；上下文取数 :2533-2604；分支路径 :2444；update_summary :2880 |
| deeptutor/services/session/pocketbase_store.py | PocketBase 后端同协议实现 | 类定义 :169 |
| deeptutor/services/session/context_builder.py | 滚动摘要/预算/分支守卫 | build :469-621 |
| deeptutor/services/session/model_history.py | model turn 重放（工具轮折叠） | replay_history :157 |
| deeptutor/services/session/turns/executor.py | 每轮编排（分支 tip、上下文、落库） | :268-288, :541-557 |
| deeptutor/api/routers/sessions.py | 会话 REST API | :112,:132,:287,:531 |
| web/lib/message-branches.ts | 前端可见路径选择 | buildVisiblePath :101-159 |
| web/lib/session-api.ts | 前端会话 API 封装 | getSession :267 |
| web/features/chat/messages/ChatMessageList.tsx | 渲染可见路径 | :1956-1960 |
| deeptutor/services/memory/paths.py | 内存目录/表面定义 | :5-8, :48-60 |
| deeptutor/services/memory/store.py | 内存 facade（emit/读写文档） | :77, :94 |
| deeptutor/services/memory/trace.py | L1 JSONL 追加/遍历 | append :66; iter_since :89 |
| deeptutor/services/memory/snapshot/adapters.py | 镜像实体适配器 | read_chat_entities :408-454 |
| deeptutor/services/memory/snapshot/__init__.py | 镜像 diff/变更日志 | :36-107 |
| deeptutor/api/routers/memory.py | 内存 workbench API | :680, :725-783 |
| deeptutor/services/session/legacy_migration.py | v1→v2 会话迁移 | 全文件 |

## 五、截断与分页逻辑一览

| 位置 | 机制 | 上限/默认 |
|---|---|---|
| context_builder.py:37-39,:185-209 | 上下文预算（规划值，非删除） | history 131072 tokens 上限；ratio 0.35/0.40 |
| context_builder.py:29,:454-456 | 摘要截断守卫 | TRUNCATION_GUARD_RATIO=0.95 |
| sessions.py:160-162,:244 | 返回给 UI 的事件负载截断 | 单事件 1MB，tool_result/observation 才截 |
| sessions.py:114-115 | 会话列表分页 | limit≤200, offset |
| sessions.py:135-136 | 搜索分页 | limit≤100 |
| sqlite_store.py:2648 | 列表 SQL LIMIT/OFFSET | 同上 |
| sessions.py:287-298 | 会话详情消息 | **不分页，全量返回** |
| sessions.py:305-306 | 单消息事件翻页 | after_seq 游标，limit≤1000（FE 用 500，session-api.ts:344） |
| memory.py:680-681 | L1 trace 分页 | limit=200, offset |
| snapshot/__init__.py:94-95 | 镜像 changes 分页 | limit∈[1,1000]，默认 200 |
| message-branches.ts:124 | 前端路径游走防环 | safety=10000（后端同款 sqlite_store.py:2567） |

## 六、已知坑

1. **消息树双实现**：后端 `_get_message_path_sync`（sqlite_store.py:2444-2476）与前端
   `buildVisiblePath`（message-branches.ts:101-159）是两套可见路径逻辑，选择规则不同
   （后端编辑轮只看祖先链，前端按 selected_branches+最新兄弟）。修任何一侧都要对照另一侧。
2. **乐观 id 参与排序**：client 负数 id 排在所有持久化消息之前
   （message-branches.ts:32-43）；持久化选择必须先过 `persistedBranchSelections`
   （:162-170）滤掉负数 id，否则刷新后指向不存在的分支。
3. **孤儿树起点**：根消息缺失（如先硬删父消息）时 `walkStartKey` 从最老孤儿挂靠点开走
   （message-branches.ts:53-80）——能兜底渲染，但起点之前的"更早历史"依旧不可见。
   #1410"只剩最近几条"与此形态吻合，应优先核对 DB 里 parent 链是否断裂。
4. **watermark 跨分支**：`summary_up_to_msg_id` 不在当前祖先链上时 summary 直接作废重建
   （context_builder.py:494-502），表现为分支切换后首轮上下文变"短/薄"，非数据丢失。
5. **L1 镜像 ≠ 全量历史 UI**：snapshot 的 changes 是 fingerprint 级 diff 日志
   （snapshot/__init__.py:74-91），trace 默认只吐 200 条/页（memory.py:680）；
   想看完整会话内容必须直读 chat SQLite（adapters.py:408 路径），Memory 工作台没有
   逐消息翻页入口。#1410"有 L1 镜像仍看不到完整历史"属此边界，不是镜像坏了。
6. **镜像不过滤回收站**：`read_chat_entities` 查 sessions 时没有 `deleted_at IS NULL`
   过滤（adapters.py:418-419，对照列表侧 sqlite_store.py:2662-2663），软删会话仍会进镜像。
7. **摘要预算 ≠ 生成上限**：`_recent_budget` 刻意与 summarizer 输出上限解耦
   （context_builder.py:199-203），调 max_tokens 不会等比改变逐字尾窗大小。
8. **后端可切换**：同一 API 背后可能是 SQLite 或 PocketBase
   （session/__init__.py:15-38），两边行为差异要先排除再定位 bug。

## 七、与 #1410 / #1614 的对应位置

- **#1614（长会话只渲染前 ~7 轮）**
  - 病灶：message-branches.ts:136-140 —— 无持久化选择时回退"最新兄弟"，早节点上
    一条新短分支会遮住长主链；后端全量返回无损（sessions.py:287-298），纯前端问题。
  - 修复现状：上游 **PR #1619 已开（OPEN，base=dev）**，改 longest-continuation 默认
    并新增 `web/tests/message-branches.test.ts`。复核要点：与乐观 id 排序（:32-43）、
    孤儿起点（:53-80）、`latestChildId` 编辑后自动选新兄弟（:195-211）的交互是否互斥。
  - 测试空白（main 上）：`buildVisiblePath` 无"多兄弟长链"用例；现有仅孤儿树
    （web/tests/orphaned-tree.test.ts:9-36）与乐观 id（web/tests/optimistic-id.test.ts:135,:170,:219）。
- **#1410（会话内只剩最近几条 / L1 镜像看不全）**
  - 排查序：① 前端可见路径（message-branches.ts:53-80 孤儿起点、:136-140 回退）；
    ② DB parent 链完整性（DELETE .../messages/{id} 会重挂子孙，executor 侧
    `_delete_turn_by_message_sync` sqlite_store.py:2111）；③ L1 边界（坑 5/6）。
  - 测试空白：`read_chat_entities` 无任何测试（tests/services/memory/test_snapshot_adapters.py
    只测 partner 表面 :48-158）；软删会话进镜像无回归用例；
    `get_session_with_messages`（sqlite_store.py:2927）无分支形态下顺序断言。
  - 压缩链路本身已有较好覆盖：tests/services/session/test_context_builder.py:598-691
    （重建/折加/失败降级/分支守卫）、test_sqlite_store.py、test_model_history.py 可作回归基线。

## 八、修这类问题的操作提示

- 复现 #1614 形态：构造会话 A(长链)+早节点 B(短新分支)，断言 `buildVisiblePath` 输出。
- 判断"数据还在不在"：直接查 `messages` 表按 `parent_message_id` 走链
  （sqlite_store.py:2565-2598 同款 SQL），先于任何前端改动。
- 前后端规则改动需同步评估 `selected_branches` 持久化（sessions.py:531-542）与
  `tipMessageId`（message-branches.ts:221-227）后续发送挂点。
