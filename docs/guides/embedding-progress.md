# 嵌入与索引进度链路代码导读（Embedding & Index Progress）

面向 #1612（Reliable long-document indexing：truthful progress & safe recovery）中"真实进度"
诉求的定位导读。基线：origin/main `ef2d9e5c3`（v1.6.12），所有 `path:line` 以该提交为准。
吞错清单来源：分支 `agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md`
（下称 DT-22 报告，§3 对应表 + §2/§7 HIGH 表）。本文不改任何代码。

核心结论先行：四个入口（建库 / 上传 / 重建 / 同步）共享同一个 `ProgressTracker` 写入口；
进度有四条出线——`.progress.json`+`kb_config.json` 持久化、WebSocket 广播、SSE 任务日志流、
进程日志。链路内 **11 处 DT-22 HIGH 吞错在 main 上全部未修复**；其中 10 处已被两个 open PR
认领（#1703 嵌入/图片回调侧、#1706 知识库路由/状态侧），1 处（`progress_tracker.py:105`
广播静默）只有本地分支 `myfork/fix/progress-notify-broadcast-warning`（AGEN-155，in_review），
**无上游 PR**。另外有两类 #1612 结构性缺口（阶段不可分辨、LightRAG 进度粒度粗）不是吞错修复
能覆盖的，见 §十。

## 一、链路总览

```
                          ┌─ 持久化: .progress.json（atomic_write_json）
HTTP 入口 ── 背景任务 ──► ProgressTracker.update ──┤  kb_config.json 状态/进度（update_kb_status）
(knowledge.py)            (单一写入口)             ├─ WS 广播: _notify → ports → ProgressBroadcaster
                                                   ├─ SSE 任务流: emit_task_progress → task stream
                                                   └─ 日志: logger.info/error（task_id 前缀）

建库   POST /knowledge-bases → run_initialization_task(:974)  → Initializer.process_documents
上传   POST /upload            → run_upload_processing_task(:1113) → DocumentAdder
重建   POST /reindex           → run_reindex_task(:3682)      → RAGService.initialize
查询   GET  /progress(:4187) / WS /progress(:4220) ← 读 .progress.json → 回退 kb_config

RAGService.initialize(service.py:68) ─ 按绑定 provider 分发 ─► LlamaIndex 管线 / LightRAG 管线 / PageIndex
  LlamaIndex: document_loader.load（图片描述回调）→ _run_with_stall_guard(create_index)（心跳+卡死检测）
              → ContextVar 回调 → CustomEmbedding._aget_text_embeddings → EmbeddingClient.embed（逐批回调）
  LightRAG:   _reconcile 轮询 track_id（按文档终态计数回调）→ before_publish 校验后再发布
  PageIndex:  逐文件回调（pageindex/pipeline.py:205-206）
```

## 二、入口与任务包装

- 三个背景任务都先 `ProgressTracker(...)` 并设置 `task_id`：建库 `knowledge.py:1011-1016`
  （tracker 也可由路由预创建 `knowledge.py:3588`）、上传 `knowledge.py:1179-1180`、
  重建 `knowledge.py:3758-3759`；`task_id` 同时用于日志前缀（`progress_tracker.py:241`）与
  断线重连后的任务归属判定（§五）。
- `run_reindex_task` 有两层重入包装（owner 令牌 `knowledge.py:3699-3713`、workspace 上下文
  `knowledge.py:3715-3732`），真正的任务体从 `knowledge.py:3739 with capture_task_logs` 开始。
- 重建回调 `_on_progress`（`knowledge.py:3791-3798`）把"嵌入批次 n/N"写进 tracker，经
  `rag_service.initialize(progress_callback=_on_progress, ...)` 注入（`knowledge.py:3887-3890`）。
- 建库侧对应 `_on_progress` / `_on_image_progress`（`initializer.py:199-215`），并在 LightRAG
  路径用 `before_publish=_prepare_publication`（`initializer.py:217-244`）先校验再发布。
- 重建终态持久化 `persist_terminal_state`（`knowledge.py:3805-3838`）：写 metadata.json 时间戳/
  计数（`knowledge.py:3810-3825`），随后逐项校验 `.progress.json` 落盘内容与 KB 状态
  （`knowledge.py:3839-3874`），任一不符直接 RuntimeError——这是 #1612 §5"嵌入批完成≠可用"
  的主要防线。

## 三、ProgressTracker：进度的单一写入口

`deeptutor/knowledge/progress_tracker.py`：

- `update()`（:176-281）构造进度 dict：`progress_percent = current/total`（:211），`error`
  会把 stage 强制改为 `error`（:224-226）；`publication_version` 标记"待发布的原生终态"（:232-233）。
- `visible_progress()`（:50-68）：原生（LightRAG）完成记录在发布校验通过前对外伪装成
  `processing_documents / 99% "Finalizing index publication"`——直接回应 #1612 §2
  "阶段 100% 不得暗示整库可用"。
- `_save_progress()`（:114-174）写两处：`manager.update_kb_status`（:140-163，失败仅 warning
  :164-165）与 `.progress.json` 原子写（:169-174，失败仅 warning）。
- `_notify()`（:92-112）：server 模式下经 ports 广播（:97-106，**:105-106 `except (ImportError,
  Exception): pass` 完全静默，DT-22 HIGH，见 §九**）；本地回调失败仅 debug（:111-112）。
- `emit_task_progress`（:273-279）把进度喂给 SSE 任务流，失败仅 debug（:278-279）。
- `verify_terminal()`（:283-322）：重读 `.progress.json` 与 KB 状态逐字段比对，失败抛
  RuntimeError——LightRAG 发布前的最后闸门。
- `get_progress()`（:324-347）：`.progress.json` 优先，缺失时回退 `kb_config.json` 的
  progress 快照；这是页面刷新/重连能恢复"权威状态"的基础（#1612 §2"刷新必须恢复同一状态"）。
- ports 本体：`deeptutor/knowledge/progress_events.py:21-28`（安装）、:31-33（广播）、
  :36-38（任务事件）；服务端装配在 `deeptutor/api/main.py:127-134`（广播→`ProgressBroadcaster.
  broadcast`，任务事件→task stream emit），CLI 侧为 no-op（`main.py:348`）。

## 四、WebSocket 与前端

- 端点 `websocket_progress`（`knowledge.py:4220`）：鉴权（:4225-4227）→ 接入 broadcaster
  （:4231、:4245）→ `get_progress()` 取初始快照（:4246-4247）。
- `task_id` 归属与恢复（:4257-4340）：终态快照直接重放（:4264-4266）；进程内查不到 task
  元数据视为"服务重启中断"，转成可重试 error 终态 `knowledge_task_interrupted`（:4268-4311）——
  #1612 §3"重启后不得留下永久 live"的兜底；任务已终态则合成终态帧（:4313-4340）。
- 快路径：无活跃任务（freshness <120s 判定，:4344-4354）且无 task_id 时发一帧即关（:4356-4381）。
  **:4350-4354 时间戳解析失败被 `except Exception: pass` 吞掉（DT-22 HIGH）**。
- 主循环每秒轮询 `.progress.json`（:4410-4429）；`task_id` 不匹配的进度被跳过（:4418-4423），
  防止旧任务污染新任务（#1612 §2）；:4395-4403 新鲜度判定同样吞时间戳异常（**DT-22 HIGH
  :4402-4403**）；内层 `except Exception: break`（:4473-4474）；错误处理 :4476-4481、
  清理 :4482-4492 中 **send_json(:4480)、close(:4486)、reset_current_user(:4491) 三处吞错**
  （DT-22 HIGH ×3）。
- 广播侧 `ProgressBroadcaster.broadcast`（`deeptutor/api/utils/progress_broadcaster.py:47-69`）：
  发送失败仅 debug 并摘除连接（:56-66）——连接级失败可接受，但 tracker 侧 :105 的静默发生在
  广播**发起**之前，会让所有订阅者一起丢帧。
- 前端 `web/hooks/useKnowledgeProgress.ts`：WS 订阅带 `task_id`（:169-177）；只接受匹配任务的
  进度（:195-201）；终态关流（:235-239）；断线指数退避重连（:246-259）；任务日志走 SSE
  `/api/knowledge-bases/tasks/{id}/stream`（:296-301）；刷新后经 `resumeTask` 恢复（:464-483）。
  前端解析失败被忽略属可接受的显示层降级（:240-242、:359-361）。

## 五、管线侧：回调如何穿越线程与事件循环

- 分发：`RAGService.initialize` 按 KB 绑定选管线（`deeptutor/services/rag/service.py:68-71`）。
- LlamaIndex：`pipeline.initialize` 取出两个回调（`llamaindex/pipeline.py:200-202`），
  图片描述回调传给 loader（:217-222），嵌入回调经 `_run_with_stall_guard`（:232-238）。
  该守卫把同步索引步骤丢进线程池，用 `_heartbeat`（:119-124）喂"最后进度时间"，超过
  stall 超时抛 `IndexingStallError`（:151-157）——#1612 §4"无进展检测≠总时限"的实现。
  守卫通过 `set_progress_callback(_heartbeat)`（:132，绑定 ContextVar 而非共享实例，
  `embedding_adapter.py:239-241`；#1478 修复后超时 worker 不会拾取下一任务的回调，
  `embedding_adapter.py:30-38` 注释）。`finally` 清理回调（`pipeline.py:267`）。
- 批次计数：`CustomEmbedding.__call__` 预估总批数（`embedding_adapter.py:100-121`），
  `_aget_text_embeddings` 用 `_IndexingProgress.completed_batches` 做跨 outer-batch 累计
  偏移（:155-175），最终逐批调 `client.embed(texts, progress_callback=...)`（:167-171）。
- 图片描述：`_describe_one` 每张图完成后回调（`llamaindex/document_loader.py:398-404`，
  **:403 吞错 DT-22 HIGH**）；描述失败/超时仅记日志并跳过该图（:369-391）——部分失败会
  在日志可见但进度照常前进（#1612 §1"不得静默省略"的部分实现）。
- LightRAG：`_reconcile` 轮询 `aget_docs_by_track_id`，仅在文档终态数变化时回调
  （`lightrag/pipeline.py:226-230`），粒度为"完成文档数/总数"，无解析/嵌入阶段细分；
  无进展超时检查 :264-277。发布闸门见 §二 `before_publish`。

## 六、嵌入客户端（EmbeddingClient）

`deeptutor/services/embedding/client.py`：

- `embed()`（:105-215）：按 provider 上限钳制 batch_size（:123-134）；单批失败带完整上下文
  （binding/model/batch 序号/长度）记 error 并**重新抛出**（:161-176）——批次失败不会静默；
  跨批维度一致性校验（:186-196，防止混用模型/维度，对应 #1612 §3"不得仅因维度相同就复用"）。
- 逐批进度回调在 :201-205 与 :276-280（multimodal `embed_contents`），
  **两处 `except Exception: pass`（:204、:279）都是 DT-22 HIGH**——回调抛错会让"卡死检测
  心跳"与进度条同时失真，且无任何日志。
- 连通性预检 `verify_embedding_connectivity`（`embedding_adapter.py:244-263`）：索引前先发
  探针请求，失败给出可行动错误——#1612 §1"昂贵工作前先验证"。
- 配置错误在构造期即报（`client.py:75-99`），未知 binding 同样（:22-35）。

## 七、关键函数表

| 环节 | 函数 | 位置 | 作用 |
| --- | --- | --- | --- |
| 入口 | `run_initialization_task` | `deeptutor/api/routers/knowledge.py:974` | 建库任务，tracker :1011 |
| 入口 | `run_upload_processing_task` | 同 :1113 | 上传任务，tracker :1179 |
| 入口 | `run_reindex_task` | 同 :3682 | 重建任务，tracker :3758 |
| 写入 | `ProgressTracker.update` | `deeptutor/knowledge/progress_tracker.py:176` | 唯一进度写入口 |
| 写入 | `ProgressTracker._save_progress` | 同 :114 | kb_config + .progress.json |
| 写入 | `ProgressTracker._notify` | 同 :92 | WS 广播（:105 吞错） |
| 校验 | `ProgressTracker.verify_terminal` | 同 :283 | 终态落盘校验 |
| 校验 | `visible_progress` | 同 :50 | 发布前 99% 门控 |
| 读取 | `ProgressTracker.get_progress` | 同 :324 | 刷新恢复的状态源 |
| 广播 | `ProgressBroadcaster.broadcast` | `deeptutor/api/utils/progress_broadcaster.py:47` | 按 KB 分发 WS 帧 |
| 端点 | `websocket_progress` | `deeptutor/api/routers/knowledge.py:4220` | 5 处 HIGH 吞错 |
| 端点 | `get_progress` / `clear_progress` | 同 :4187 / :4205 | REST 读/清 |
| 管线 | `_run_with_stall_guard` | `deeptutor/services/rag/pipelines/llamaindex/pipeline.py:89` | 心跳+卡死检测 |
| 管线 | `CustomEmbedding._aget_text_embeddings` | `.../llamaindex/embedding_adapter.py:155` | 批次偏移+回调注入 |
| 管线 | `LightRagPipeline._reconcile` | `.../lightrag/pipeline.py:155` | 按文档终态回调 :226 |
| 嵌入 | `EmbeddingClient.embed` | `deeptutor/services/embedding/client.py:105` | 逐批回调 :203（吞错 :204） |
| 嵌入 | `EmbeddingClient.embed_contents` | 同 :229 | 同上（吞错 :279） |
| 嵌入 | `validate_embedding_batch` | `deeptutor/services/embedding/validation.py` | 计数/维度校验 |
| 前端 | `useKnowledgeProgress` | `web/hooks/useKnowledgeProgress.ts:69` | WS+SSE 双通道消费 |

## 八、失败模式与修复状态（链路内 DT-22 HIGH 全量）

基线 main `ef2d9e5c3` 上**全部未修复**。"认领"= 已有 open PR / 本地修复分支；行号为 main 上的
`except` 位置。

| # | 位置 | 现状与后果 | 认领状态 |
| --- | --- | --- | --- |
| 1 | `embedding/client.py:204`（`embed` 回调） | 回调抛错无日志；进度条停走且卡死检测心跳失效 | PR #1703（open，AGEN-261→合集 AGEN-304） |
| 2 | `embedding/client.py:279`（`embed_contents` 回调） | 同上（图片内容嵌入进度） | PR #1703（open） |
| 3 | `.../llamaindex/document_loader.py:403`（图片回调） | 图片进度失真且无痕迹 | PR #1703（open） |
| 4 | `knowledge.py:3952`（`run_reindex_task` 失败告警） | **失败通知本身被吞**：KB 状态可停留 processing，仅任务流有记录 | PR #1706（open，AGEN-268→合集 AGEN-301） |
| 5 | `knowledge.py:4353`（freshness 时间戳） | 坏时间戳 → 按"无活跃任务"处理 | PR #1706（open） |
| 6 | `knowledge.py:4402`（should_send 时间戳） | 同上，进度帧被跳过 | PR #1706（open） |
| 7 | `knowledge.py:4480`（WS error 帧） | 客户端收不到错误原因 | PR #1706（open） |
| 8 | `knowledge.py:4486`（WS close） | 清理失败无痕迹（低危但属 HIGH 计分项） | PR #1706（open） |
| 9 | `knowledge.py:4491`（reset_current_user） | 多用户上下文残留风险 | PR #1706（open） |
| 10 | `knowledge/manager.py:567`（`update_kb_status` 元数据） | KB 状态/签名/index_versions 失真 → #1612"进度不真实"直接来源 | PR #1706（open） |
| 11 | `knowledge/progress_tracker.py:105`（`_notify` 广播发起） | 广播异常**完全静默**，所有 WS 订阅者丢帧 | **无上游 PR**；本地分支 `myfork/fix/progress-notify-broadcast-warning`（AGEN-155，in_review） |

链路相邻的同类项（非 HIGH 但同链路）：`manager.py:2130`（folder-sync 状态吞错，PR #1706 认领）、
`knowledge.py:1193`（上传 mtime 快照 OSError，MEDIUM，未认领）、`progress_tracker.py:278`
（SSE 事件发射失败仅 debug，未认领）。

## 九、与 #1612 的对应：已覆盖与仍缺口

已由现有机制覆盖（结论附行号）：

- 阶段 100% ≠ 整库可用：`visible_progress` 门控 `progress_tracker.py:50-68`；终态校验
  `verify_terminal` `progress_tracker.py:283-322` 与重建侧 `knowledge.py:3839-3874`。
- 刷新/重连恢复权威状态：`.progress.json` 持久化 `progress_tracker.py:169-174` + WS 重放
  `knowledge.py:4257-4266` + 前端 `resumeTask` `web/hooks/useKnowledgeProgress.ts:464-483`。
- 重启孤儿任务：`knowledge_task_interrupted` 可重试终态 `knowledge.py:4268-4311`。
- 旧任务不污染新任务：WS 按 task_id 过滤 `knowledge.py:4418-4423`；前端同样过滤
  `useKnowledgeProgress.ts:195-201`。
- 卡死检测（区别于总时限）：`llamaindex/pipeline.py:89-161`；LightRAG 侧无进展检查
  `lightrag/pipeline.py:264-277`。
- 嵌入配置变更不复用不兼容索引：批次维度校验 `client.py:186-196`；签名版本目录
  `llamaindex/pipeline.py:211-243`。
- 部分完成可见：跳过文件计数告警 `knowledge.py:3916-3921`；图片描述失败记日志
  `document_loader.py:369-391`。

仍缺口（#1612 相关，吞错修复不覆盖）：

1. **阶段不可分辨**：整条链路只有 `processing_documents/processing_file` 两档
  （`progress_tracker.py:43-47`），模型准备/解析/嵌入/持久化无独立阶段——#1612 §2 明确要求
   区分。LlamaIndex 文档加载阶段（`pipeline.py:217-222`）完全无进度。
2. **LightRAG 粒度粗**：仅"终态文档数/总数"（`lightrag/pipeline.py:226-230`），无百分比、
   无批次语义；单一大文档期间进度完全静止。
3. **进度广播单点静默**：`progress_tracker.py:105` 未被任何 open PR 覆盖（§八 #11）。
4. **心跳语义绑定嵌入回调**：stall 检测依赖回调存活，而回调失败正是 §八 #1-#3 的吞错点——
   两类修复叠加才能保证"卡死可检测"。

## 十、复核命令

```bash
cd /Users/Shared/DeepTutor && git fetch --multiple origin myfork
git show ef2d9e5c3:deeptutor/knowledge/progress_tracker.py | sed -n '92,112p'
git show ef2d9e5c3:deeptutor/services/embedding/client.py | sed -n '198,206p;274,282p'
git show ef2d9e5c3:deeptutor/api/routers/knowledge.py | sed -n '3944,3954p;4348,4356p;4476,4492p'
# DT-22 报告（证据）
git show agent/dt22-todo-scan:evidence/todo-scan-2026-10-03/report.md
# PR 范围核对
gh pr view 1703 --repo HKUDS/DeepTutor --json files --jq '.files[].path'
gh pr view 1706 --repo HKUDS/DeepTutor --json files --jq '.files[].path'
```
