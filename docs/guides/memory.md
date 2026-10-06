# 记忆子系统代码导读（snapshot / consolidator / 工作台）

> 基于 `origin/main` v1.6.13（`f07029cf`）。所有 `path:line` 均可在该提交直接定位。
> 范围：三层记忆（L1 trace / L2 表面文档 / L3 槽位）+ 工作区快照 + consolidator + 工作台路由。
> 会话历史/持久化/L1 mirror 见 guide-session 卡，本卡不覆盖。

## 1. 模块地图

| 层 | 位置 | 职责 |
|---|---|---|
| 路径与作用域 | `deeptutor/services/memory/paths.py` | `memory_root()` `:63`、Surface/L3Slot 枚举 `:48-60`、`memory_path_service_override` `:39`（partner 运行时代读用户记忆）、`ensure_dirs` `:97`（root 0o700，`deeptutor/utils/secret_files.py:13`） |
| L1 追加日志 | `deeptutor/services/memory/trace.py` | 按表面按天 JSONL：`TraceEvent` `:36`、`append` `:66`（永不抛错 `:73-79`）、`iter_since` `:89`、`count_since` `:131` |
| 文档模型 | `deeptutor/services/memory/document.py` | 脚注引用式 MD 纯解析/序列化：`parse` `:105`、`serialize` `:185`，往返幂等 |
| 存储门面 | `deeptutor/services/memory/store.py` | `MemoryStore` `:69`：`read_l3_concat` `:94`、`write_preference` `:195`（幂等去重 `:223-235`）、`apply_ops_payload` `:166`、v1 迁移 `:331`、tutorbot→partner 迁移 `:360` |
| 原子批量操作 | `deeptutor/services/memory/ops.py` | Add/Edit/Delete `:24-46`，先全量校验后变更 `apply` `:120`，失败不动文档 |
| ID 规范 | `deeptutor/services/memory/ids.py` | ULID：`new_entry_id` `:53`（`m_+26位`）、`new_trace_id` `:57`、引用校验 `:61-80` |
| 快照 | `deeptutor/services/memory/snapshot/` | 见 §3 |
| 合并器 | `deeptutor/services/memory/consolidator/` | 见 §4 |
| 设置 | `deeptutor/services/memory/settings.py` | `load_memory_settings` `:72` / `save_memory_settings` `:82`，单源 `data/user/settings/main.yaml` 的 `memory:` 子树，写入钳制 `:169-184` |
| REST | `deeptutor/api/routers/memory.py` | 26 条路由挂 `/api/memory`（`deeptutor/api/main.py:651`，鉴权仅 `require_learning_surface` `main.py:591`） |
| CLI | `deeptutor_cli/memory.py` | `memory show` `:22` / `memory clear` `:64`（注册 `deeptutor_cli/main.py:42`） |
| Partner 工具 | `deeptutor/tools/partner_memory.py` | `partner_read` `:87` / `partner_memorize` `:127` / `partner_search` `:222`，强制挂载集 `:26-30` |
| Recall | `deeptutor/services/memory/recall.py` | `recent` `:142` / `recent_queries` `:198`，只读快照戳，消费方 `deeptutor/services/suggestions.py:382-383` |

**同名陷阱**：`deeptutor/runtime/coordination/memory.py`（回合租约协调）、`runtime/memory_reclaim.py`（gc 回收 `:17`）、`runtime/memory_probe.py`（RSS 探针 `:311`）与本子系统无关，仅同名。

## 2. 存储布局与写入原子性

根：`memory_root()`（`paths.py:63`）→ `PathService.get_memory_dir()` = `workspace_root/"memory"`（`deeptutor/services/path_service.py:299`）；多用户/伙伴隔离靠请求级 PathService + ContextVar（`paths.py:33-45`）。

```
<memory_root>/
  trace/<surface>/<YYYY-MM-DD>.jsonl      # L1 证据，trace.py:66
  L2/<surface>.md  (+ .meta.json)         # 表面记忆，meta 见 consolidator/meta.py:55
  L3/<slot>.md     (+ .meta.json)         # slot ∈ recent|profile|scope|preferences
  snapshot/<surface>/state.json           # 指纹+last_refresh，snapshot/store.py:31
  snapshot/<surface>/changes.jsonl        # 变更历史，snapshot/store.py:35
  backup/<UTCts>/                         # v1 迁移归档，store.py:347
```

写入原子性分级（由强到弱）：
1. L2/L3 meta 侧车：`mkstemp`+fsync+replace（`consolidator/meta.py:164-178`）。
2. L2/L3 正文：`file_io.atomic_write_text`（fsync + Windows 重试，`deeptutor/services/file_io.py:63-85`）+ MemoryStore 每路径 asyncio 锁（`store.py:319-325`，仅进程内、仅单例共享 `:435`）。
3. 快照 `state.json`：固定名 `state.json.tmp` + `os.replace`，**无 fsync**（`snapshot/store.py:63-70`）。
4. `changes.jsonl`/`trace`：直接 append，进程内锁（trace）或无锁（changes），**均无跨进程保护**。

## 3. 快照：workspace → Entity/Stamp（`services/memory/snapshot/`）

- 数据类：`Entity`/`EntityStamp`/`ChangeEntry`（`snapshot/entity.py:19/:50/:79`）；`ts` 不参与 diff（`entity.py:65-67`）。
- 纯 diff：`diff_snapshots`（`snapshot/diff.py:15`）对指纹表做集合运算，added/removed 按排序输出，一批共享同一 UTC 时间戳 `:27`。
- 适配器（`snapshot/adapters.py`）：7 个表面 reader `_READERS :571-579`（notebook `:64`、cowriter `:127`、book `:158`、partner `:295`、kb `:348`、chat `:408`、quiz `:457`）；仅 chat 有廉价探针 `probe_chat_entities :518`（`_PROBES :585`）。指纹 = SHA-1 截 64 位（`_sha1 :32`）。
- 错误处理约定：数据级问题**静默跳过**（如 partner 空会话 `:271`、quiz 无 question_id 用 `row_<id>` 兜底 `:474`）；DB 级失败记 warning 返回 `[]`（`:451`、`:562`）；顶层 `read_entities` 任何异常→warning+`[]`（`:596-598`）。
- 探针保护：`read_stamps`（`:601`）在探针抛错时回退全量读（`:613-615`），避免坏探针被 diff 误判为"全部删除"；但该保护**只覆盖 chat**。
- 生命周期（`snapshot/__init__.py`）：`refresh_snapshot :74` = 读戳→`pending_changes :45`（纯 diff 不落盘）→`append_changes`（`store.py:73`，空列表 no-op）→`save_state` 刷新 `last_refresh`（`:89`）。`read_changes :94` 分页读取（整文件载入后倒序 `:96-98`）。**没有恢复/回放 API**，`changes.jsonl` 仅展示用；唯一破坏性出口是 `clear_changes :106`。

## 4. Consolidator：L1 证据 → L2/L3 文档（`services/memory/consolidator/`）

四模式，直接函数调用无注册表（`modes/__init__.py:19-22`）：
- **update**：`run_update`（`modes/update.py:80`）。按 meta 已见 ID 集做增量（L2 用快照实体 `:150-157`；L3 用各 L2 文档 entry id `:376-388`），分块调 LLM 抽事实，ref 池校验后以 AddOp 追加；完成后按设置自动接 dedup/merge（`:321-339`、`:551-568`）。`preferences` 槽拒绝 `:373-374`。
- **audit**：`run_audit`（`modes/audit.py:75`）。文档按行渲染 + 每条 bullet 附**全量**原始证据（`references.py:232/:269`），LLM 返回 `{"edits":[...]}` 按行号倒序应用（`line_doc.apply_edits`），每块 checkpoint。
- **dedup**：`run_dedup`（`modes/dedup.py:52`）。最多 `iterations` 轮 replace/delete，0 编辑即收敛 `:140-143`。
- **merge**：`run_merge`（`modes/merge.py:62`）。无 LLM 重序列化：折叠重复脚注、迁移 legacy `m_<ULID>` 引用为表面名（`:157-205`），字节不变即不写（幂等 `:118-132`）。

共享设施：
- `_runtime.py`：prompt 加载 `load_prompt :38`（en/zh YAML 缓存）、`call_llm :88`（流式优先、失败回退非流式）、`write_doc_checkpoint :227`（写前快照旧内容供 undo）。
- `_shims.py`：legacy API `consolidate_l2/l3`（`:51/:71`），preview 模式跑完即回滚（`_rollback_new_entries :110`，非原子写 `:126`）。
- 行文档（`line_doc.py`）：`render_view :129`（行号视图）、`apply_edits :172`（replace/delete/insert，倒序应用 `_sort_reverse :400`）、`parse_edits_payload :335`（容忍围栏/前后杂文，逐 op 容错 `:392-393`）、`_clean_refs :304`（L2 丢弃 `m_` 形引用——幻觉护栏 `:329-330`）。
- 引用池（`references.py`）：`validate_fact_refs :125`（池外引用按 `drop_invalid` 丢弃或拒绝）、L3 引用是**表面名**而非 entry id（`refs_in_span_l3 :98`）。
- 护栏（`guards.py`）：绝对化短语黑名单 `_filter_banned :87`（`BANNED_PHRASES :24`）。
- 进度（`meta.py`）：纯 ID 集 diff（模块头 `:1-30`），meta 损坏视为首轮（`_read_json :154`）；`version:1` `:48`。

运行管理（`runs.py`）：`RunManager.start :157`（每 `(layer,key)` 单活动 run，冲突 `RunBusyError :108`）、`cancel :196`、`undo_last :205`（弹出 checkpoint 恢复/删除文件）、`wait_for_events :239`（SSE 重放，事件环 `_MAX_EVENTS_PER_RUN=2000 :42`，历史 FIFO `_MAX_HISTORY=200 :43`）、`_drive :262`（终态与 `run_ended` 事件）。**纯内存，无持久化也无断点续跑**（模块 docstring `:9-13`）；并发保护是单进程 asyncio.Lock（`:128`）。

## 5. 触发点与数据流

- **无任何定时/回合末钩子**：快照 refresh 与 consolidator 全部由工作台 API 发起（`routers/memory.py:750`、`:308`，legacy 流式 `:529/:544/:559`）。启动时仅跑迁移（`main.py:331-337`）。
- **L1 写入源只有 3 处**：chat `write_memory` 工具（`tools/builtin/__init__.py:984`，surface=chat/kind=preference_stated）、`partner_memorize`（`tools/partner_memory.py:196`）、KB 检索（`services/rag/service.py:172-180`，包在 `except Exception: pass` 里 `:179`）。notebook/quiz/book/cowriter 无 emitter，L1 只能靠快照适配器合成。
- **读路径**：chat 回合注入 `read_l3_concat()`（`services/session/turns/executor.py:563`，开关 `memory_references`）；`read_memory` 工具按 `user_has_memory` 门控自动挂载（`agents/_shared/tool_composition.py:287`）；suggestions 用 `recall.recent`/`recent_queries`（`services/suggestions.py:366/:382`）。
- 主数据流：`工具/KB → trace.jsonl（L1）→ 用户点"刷新快照" → adapters 读 workspace → state.json+changes.jsonl → 用户点"更新" → update 抽事实写 L2（meta 记 seen id）→ update L3 汇总各 L2 → 回合注入/工作台展示`。

## 6. 扩展点

1. **新表面**：`paths.py:48` Surface + `ids.py:36` 短名白名单 + `adapters.py:571` `_READERS`（可选 `_PROBES :585`）+ 前端 `web/components/memory/`。注意 `ensure_dirs`（`paths.py:97`）不会建 `snapshot/`，首次 refresh 才落盘。
2. **新合并模式**：`modes/` 新文件 + `modes/__init__.py` 导出 + `routers/memory.py:240` `_runner_for` 分支 + `RunMode` 字面量（`runs.py:39`）。
3. **参数调优**：`PUT /api/memory/settings`（`routers/memory.py:622`）→ `settings.py:82`，未知键丢弃、数值钳制。
4. **廉价探针模式**：chat 探针（`adapters.py:518`）证明了大表 surfaces 可只读戳做 diff；新表面建议照抄"探针与全量读逐表达式一致"约定（`:520-532` 注释）。
5. **partner 代读用户记忆**：`memory_path_service_override`（`paths.py:39`）+ `partner_read` 的 owner/partner 双 scope 拼接（`partner_memory.py:111-114`）。

## 7. 已知坑（改前必读）

1. **LLM 失败仍记 seen**：`update.py:312`、`:543` 无论是否抽到事实都保存 meta——LLM 挂掉的那批输入被标记已处理，永不重试。
2. **快照刷新无锁非原子**：`snapshot/__init__.py:74-91` 读改写零串行化；`state.json.tmp` 固定名可撞（`store.py:63`）且无 fsync（`:70`）。
3. **坏适配器=整表面清空**：`adapters.py:596-598` 顶层异常返回 `[]`，6 个无探针表面的适配器坏掉时 refresh 会把全部实体记为 removed；探针保护只覆盖 chat（`:613`）。
4. **consolidator 绕过 store 写锁**：runner 直接调 `run_*`（`routers/memory.py:240-305`），不经 `MemoryStore._lock_for`；运行中 `PUT /doc/:151` 手改会与 run 最终写入 last-writer-wins。
5. **trace 尽力而为**：`append` 吞一切异常（`trace.py:73-79`）→ 证据引用可静默悬空；`iter_since :110` 遇坏行抛 TypeError 可使 `GET /trace` 500（`:104/:111` 只捕两类异常）；`:108` ISO 字符串直接比较，混合时区偏移会乱序。
6. **wait_for_events 竞态**：`runs.py:244-252` 先查 `run.active` 再注册 waiter，窗口内 run 结束则调用方永久阻塞。
7. **apply_edits 共享 Entry 对象**：`line_doc.py:187-193` 新文档复用旧 Entry，replace 原地改写，调用方持有的"旧文档"视图会被污染（`:235-236` 注释已承认）。
8. **设置解析死分支**：`settings.py:131` `isinstance(f.type, type)` 在 `from __future__ import annotations` 下恒 False，嵌套 dataclass 识别实际全靠默认实例分支 `:135-138`。
9. **overview/trace 性能**：缺文档时 `count_since(None)` 全量扫描 trace（`store.py:293-297`）；`GET /trace` offset 是 O(n) 跳读（`routers/memory.py:686-688`）；`read_changes` 整文件载入倒序（`snapshot/__init__.py:96-98`）。
10. **迁移写非原子**：`store.py:390-421` 直接 write_text+unlink，中途崩溃可丢 L2。
11. **quiz 行号兜底 ID 漂移**：`adapters.py:474-475` 无 question_id 时用 `row_<id>`，行删除/重排产生幽灵 added/removed。
12. **audit 成本放大**：证据块全文注解不截断（`audit.py:149-157`），长历史线性放大 chunk 数与 LLM 调用。
13. **全程无跨进程锁**：多 uvicorn worker 下 trace append（两段写 `trace.py:84-86`）、consolidator、快照均可竞写，架构假设单 worker。

## 8. 测试空白清单与可拆卡条目

现状：`tests/services/memory/` 12 个文件覆盖纯逻辑主链路；`tests/api/` 仅 1 个 memory 路由测试。已有未合入产物可引用：`myfork/test/memory-modes-20261005`（`_runtime`/shims 372 行）、`agent/dt419-snapshot-iso-tests`（`_iso` 契约）、PR #1770/#1771（web memory-graph、路由契约）。

| 模块 | 已有测试 | 零/弱覆盖 |
|---|---|---|
| `snapshot/store.py` 全模块 | 无 | `load_state :39`/`save_state :54`/`append_changes :73`/`iter_changes :84` 无任何直接测试 |
| `snapshot/__init__.py` 生命周期 | 无 | `refresh_snapshot :74`/`pending_changes :45`/`read_changes :94` 全无（仅被 router 调用） |
| `snapshot/diff.py` | 无 | `diff_snapshots :15` 零覆盖 |
| `adapters.py` | partner 7 个（test_snapshot_adapters.py）、chat 探针 6 个（test_snapshot_probes.py） | notebook/cowriter/book/kb/quiz 5 个 reader 无测试；`read_entities` 顶层兜底 `:596` 无测试 |
| `update.py` | L2 追加/幂等/池外引用（test_modes.py:49/:90/:138） | **`_run_update_l3 :363-586` 全无**；LLM 失败仍存 meta `:312/:543` 无测试 |
| `audit.py` | 1 个（L2 replace，test_modes.py:176） | **`_run_audit_l3 :267-401` 全无**；拒绝编辑路径 `:221-230` 无测试 |
| `dedup.py` | 2 个（test_modes.py:220/:260） | L3 去重、迭代耗尽不收敛 `:114-169` 无测试 |
| `runs.py` | 8 个（test_runs.py） | 阻塞等待路径 `:249-258`（含坑 6 竞态）、eviction `:316-323`、undo 边界无测试 |
| `references.py` | 10 个（test_references.py） | `annotate_l2/l3_line_with_evidence :232/:269` 零覆盖 |
| `trace.py` | 无直接 | `append`/`iter_since`/`iter_by_ids` 仅间接触达 |
| 路由 26 条 | 仅 `resolve_entry`（tests/api/test_memory_resolver.py） | runs 全套（start/405/409/SSE/undo）、doc CRUD、reset、apply、trace、snapshot 路由全无 HTTP 级测试 |
| `partner_memory.py` / CLI | 无 | 两个文件零测试 |

可拆卡条目（建议优先级序）：
1. `test/memory-snapshot-store`：snapshot/store+init+diff 单测（写读往返、坏行跳过、`save_state` tmp 冲突、refresh 幂等）。
2. `test/memory-l3-modes`：补 `_run_update_l3`/`_run_audit_l3`（preferences 拒绝、无新输入早退、auto-dedup/merge 链）。
3. `test/memory-router-contract-v2`：26 条路由契约（现有 PR #1771 只覆盖部分形状；补 405/409/SSE replay/undo）。
4. `test/memory-trace-unit`：trace append 吞错、坏行行为、`iter_since` 时区比较锁定契约。
5. `fix/memory-update-meta-onskip`：坑 1——LLM 空响应时不推进 meta（或记失败事件），防数据静默丢失。
6. `fix/snapshot-refresh-lock`：坑 2/3——refresh 加锁 + `save_state` 改 mkstemp+fsync + `read_entities` 兜底区分"空"与"错"。
7. `test/memory-refs-annotate`：references 注解函数与 `drop_invalid` 边界。

## 9. 与相邻文档的关系

- 会话历史/L1 mirror：guide-session 卡（`docs/guides/session-history` 分支）。
- consolidator 模式测试结论：test-memory-modes / test-memory-snapshot 卡（分支见 §8 首段）。
- 前端工作台（`web/app/(utility)/memory`、`web/components/memory/`）本卡仅列入口，未见详解。
