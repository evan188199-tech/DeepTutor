# 恢复操作手册（使用者/运维者视角）

基线 `origin/main @ 6cf793bd8`。6 条操作按"先读、再动"排列，全部可照做。
API 前缀约定 `<base>/api`；多用户/工作区部署时 KB 名可用限定形式（路由内部
经 `resolve_kb` 解析，`knowledge.py:4331`）。

## 操作 1：读当前索引状态（任何操作前先做）

```bash
curl -s <base>/api/knowledge-bases/<kb>/indexing-run | python3 -m json.tool
```

- 入口：`GET /knowledge-bases/{kb}/indexing-run`（`knowledge.py:4326-4332`）。
  端点注释即合同："Pure durable diagnostics; reading never recreates a task or
  retries work"——只读投影，随便刷不影响现场。
- 返回体怎么读（字段全部来自 `visible_run`，`indexing_run.py:133-162`）：
  - `state`：`running`（有活人在干）/ `interrupted`（主人已死，进程崩溃或服务重启）/
    `completed` / `partial`（有可用版本但不完整）/ `failed` / `cancelled`；
  - `phase`：preflight → parsing → embedding → verifying（写入点见状态机文档 §4）；
  - `documents`：逐文件 status/reason/detail/parse_reused；`parse_reused: true`
    表示该文件重试时会复用已验证的解析缓存；
  - `cancel_requested`：取消标记是否已挂上；
  - `recovery`：官方恢复提示语（`:161`、`:250`）。
- UI 等价操作：KB 详情页的索引面板（`web/components/knowledge/KbIndexingRun.tsx:67-74`，
  挂载于 `KnowledgeBaseDetail.tsx`），running 态时面板自带 Cancel 按钮。
- 运维直查磁盘（服务不可用时）：`cat data/knowledge_bases/<kb>/.indexing-run.json`。
  文件损坏时服务端会报"Indexing journal is unreadable; original file preserved."
  （`indexing_run.py:92,98`），此时不要删文件，先按操作 6 处置。

## 操作 2：取消正在运行的索引

```bash
TASK=$(curl -s <base>/api/knowledge-bases/<kb>/indexing-run | python3 -c "import sys,json;print(json.load(sys.stdin)['run']['task_id'])")
curl -s -X POST <base>/api/knowledge-bases/<kb>/indexing-run/$TASK/cancel
```

- 入口：`POST /knowledge-bases/{kb}/indexing-run/{task_id}/cancel`
  （`knowledge.py:4335-4345`）。task_id 不匹配或已终态返回 409（`:4340-4341`；
  归属判定 `indexing_run.py:442`）。
- 语义：立即返回 "Cancellation takes effect at the next safe boundary"（`:4344`）。
  worker 在下个 `check()` 边界感知（`indexing_run.py:350-354`），MinerU 子进程
  由看门狗轮询同一标记（`mineru/local.py:236-247`）。已完成的解析成果保留可复用。
- 验证：再跑操作 1，`cancel_requested` 应为 true；结束后 `state=cancelled`。

## 操作 3：恢复失败（error 态）的 KB —— retry

```bash
curl -s -X POST <base>/api/knowledge-bases/<kb>/retry
```

- 入口：`POST /knowledge-bases/{kb}/retry`（`knowledge.py:4291-4323`）。
- 前置条件：KB 的 status 或 progress.stage 必须是 `error`，否则 409
  （`:4303-4310`，提示改用 reindex）。
- LightRAG 例外：返回 409 要求先在 Settings 里复核当前索引配置再重建
  （`:4311-4315`）。
- 内部委托 reindex（`:4316-4318`），因此继承操作 4 的全部防护。
- 恢复收益：`raw/` 源文件原样保留，重试时解析缓存命中即跳过解析
  （`parsing/service.py:184-199`），journal 中已 `completed` 的切片不重复嵌入。

## 操作 4：主动重建索引 —— reindex（覆盖 interrupted/partial/cancelled）

```bash
curl -s -X POST <base>/api/knowledge-bases/<kb>/reindex -F embedding_model=<当前绑定模型>
```

- 入口：`POST /knowledge-bases/{kb}/reindex`（`knowledge.py:4098` 起）。
- 冲突防护：previous run 仍是 `running` 时 409 "An indexing worker still owns
  this knowledge base."（`:4119-4124`）——先等待或先执行操作 2。
- 强制重建规则：previous run 是 `partial/failed/cancelled/interrupted` 任一，
  则强制走完整重建（`:4125-4130`）；换 embedding 模型同样强制（`:4137-4138`）。
- 旧版本不丢：发布走新 version-N 目录，旧 ready 版本在重建期间继续服务；
  新版本未过发布校验（探针 + 源哈希）不会接管（`pipeline.py:467-494`、
  `rag/service.py:116-123`）。

## 操作 5：服务重启后的孤儿任务调和

- 现象：重启前浏览器还挂着任务进度页。重连后服务端发现 task_id 不在本进程
  注册表里（任务 ID 与后台 asyncio 任务都是进程局部的），立即把它固化为
  **可重试的终态错误** `knowledge_task_interrupted`，消息
  "Knowledge-base processing was interrupted by a server restart. Retry the
  operation to continue."（`knowledge.py:4477-4520`，SSE/WebSocket 双通道都会收到）。
- 操作：看到该错误后直接执行操作 3（error 态 → retry）或操作 4。
- 纯轮询替代：`GET /knowledge-bases/{kb}/progress`（`knowledge.py:4379-4396`）
  读持久化进度快照，不依赖长连接。
- journal 侧的对应投影：重启后原属死进程的 run 会被 `visible_run` 判为
  `interrupted`（`indexing_run.py:133-162`），KB 的 `last_indexed_count`/
  `indexing_state` 记账会读取该收据（`initializer.py:110-118`、
  `knowledge.py:1026-1032`）。

## 操作 6：磁盘现场处置（仅服务端救不回来时）

按顺序检查，能不动盘就不动盘：

1. **确认没有活 worker**：`visible_run` 已含 liveness 判定（psutil PID+创建时间，
   退化 flock 探测，`indexing_run.py:113-143`）；`interrupted` 即确认无主。
   `.indexing.lock` 是 flock，进程死亡自动释放，**不需要手删锁文件**。
2. **journal 损坏**：API 报 "Indexing journal is unreadable/invalid; original
   file preserved."（`:92,98`）。处置：把 `.indexing-run.json` 移出 KB 目录归档
   （例如 `journal-broken-<日期>.json`），让 KB 回到"无 journal"状态后再走操作 4
   重建。当前没有管理端点做这件事（缺口记录于 crash-window 报告 S5，此处不展开）。
3. **禁删 `version-N/` 目录**：旧 ready 版本是恢复期间的服务底座；删掉即失去
   `partial` 恢复的落点。清理失败版本目录是管线自己的职责
   （`pipeline.py:459-463`）。
4. **`raw/` 与解析缓存不动**：它们是 retry 能"断点续跑"的本钱
   （`parsing/service.py:180-199`）。

## 状态 → 操作速查

| 读到的 state | 含义 | 动作 |
| --- | --- | --- |
| `running` | 有活 worker | 等待；面板可取消（操作 2）；reindex 会 409 |
| `interrupted` | 上次运行的主人已死 | 直接操作 4（reindex 会强制重建） |
| `partial` | 有可用版本但不完整 | 检索可用；要补全走操作 4（强制重建） |
| `failed` | 终局失败 | 看 `error_code`/`error` 定位；KB error 态走操作 3，否则操作 4 |
| `cancelled` | 已取消 | 需要继续则操作 4（强制重建） |
| `completed` | 全部完成 | 无需动作 |
