# weak-top100 ⚠ 模块漂移复核（20261009）

## 输入与边界
- 基线：`/Users/Shared/DeepTutor` fetch 后 origin/main = `6cf793bd868b`（v1.6.14），与 triage 卡（`evidence/weak-triage-20261008/triage.md`）标注的 origin/main 一致，triage 之后上游无新提交
- 漂移区间：`f07029cf`（v1.6.13，coverage-gaps 扫描基线）→ `6cf793bd`（v1.6.14）
- 本卡只读复核：不改产品/测试代码；triage 表内 LOC 为 v1.6.13 快照值，下表「现 LOC」为 origin/main 实测
- 工作分支：`scan/weak-drift-recheck-20261009`（新 worktree `.wt-agen1314-drift-recheck`）

## 结论一览（7/7 仍在原路径，无改名/删除）

| triage# | 模块 | path | LOC 旧→现 | 职责变化 | 拆卡结论 |
|--------:|------|------|----------|----------|----------|
| 20 | `services.rag.visual_assets` | `deeptutor/services/rag/visual_assets.py` | 386→430 | 行为面扩大（manifest 校验翻转＋figure 标注） | 维持，焦点改写 |
| 25 | `services.session.workspace_preferences` | `deeptutor/services/session/workspace_preferences.py` | 55→50 | 缩小（immersive_watching 模式删除） | 维持，用例排除 watching |
| 32 | `services.llm.provider_core.codebuddy_provider` | `deeptutor/services/llm/provider_core/codebuddy_provider.py` | 839→851 | 不变（中断路径日志化） | 维持 |
| 37 | `services.mcp.network` | `deeptutor/services/mcp/network.py` | 121→185 | 显著扩大（trusted origin 私网放行＋新公共函数×2） | 维持，焦点改写 |
| 80 | `api.routers.task_board` | `deeptutor/api/routers/task_board.py` | 28→112 | 重大扩展（3→7 端点，新增 SSE） | 维持，焦点改写 |
| 89 | `services.workspace.session_move` | `deeptutor/services/workspace/session_move.py` | 138→138 | 不变（一行参数） | 维持，微调 |
| 94 | `api.utils.tool_options` | `deeptutor/api/utils/tool_options.py` | 122→133 | 不变（失败路径日志化） | 维持 |

## 逐模块证据

### 20. `services.rag.visual_assets` — 仍在，行为面扩大
- 路径/入口未变：docstring 仍为「Verified, parser-independent source images…」（`visual_assets.py:1`）；`source_key_for` `:78`、`VisualAssetCandidate` `:171`、`collect_visual_assets` `:176`、`VisualAssetStore` `:251` 全部在。
- 漂移（f07029cf..6cf793bd，+55/−11）：
  1. manifest 16MB 上限（`MAX_MANIFEST_BYTES`）删除，读取重写为 `_read_manifest()`（`visual_assets.py:268`）：大/损坏 manifest 由「静默返回 {}」翻转为抛 `OSError`（`#1802` 注释 `:269-270`）；`records()` `:259` 与 `publish()` `:288`（另 `:363`、`:382` 两处 prior 读取）改为经 `_read_manifest()`，错误分支从吞异常改为 log 后返回空表。
  2. `collect_visual_assets` 新增单资产 `OSError` 容忍分支（`:187-192`，读取失败跳过并记录）；记录新增 `figure_labels`（`:226-228`，来自 `services.rag.source_visuals`）与按 img_path 匹配 block 后的 kind/section/group_id/table_html/notes 字段（`:229-244`）。
  3. caption 候选新增 `table_caption`（`:122`）。
- 拆卡结论：**维持**。原焦点四件套不变，需改写补充：manifest 损坏/异常时抛错语义、symlink/逃逸分支、figure_labels 与 block 匹配装配、单资产读失败降级。风险维持「中」（fanin 4、LOC 430≥300）。

### 25. `services.session.workspace_preferences` — 仍在，职责缩小
- 路径未变；`upgrade_workspace_preferences` 仍是唯一公共函数（`workspace_preferences.py:17`）。
- 漂移（+2/−7）：`WORKSPACE_MODE_WATCHING`（`immersive_watching`）删除，`WORKSPACE_MODES` 只剩 reading/mastery（`:12-14`）；watching 分支删除后，`capability="immersive_watching"` 的历史记录不再升级出 `workspace_mode`（`:36-41` 现仅 mastery/reading 两分支）。
- 拆卡结论：**维持**，用例必须排除 watching 模式（原 triage 焦点未提 watching，无需改写焦点本身）；补充一条「watching 遗留值不产生 workspace_mode」断言。

### 32. `services.llm.provider_core.codebuddy_provider` — 仍在，职责不变
- 路径未变；`CodeBuddyProvider`（`:151`）、`fetch_codebuddy_models`（`:795`，含 `__all__` `:850`）均在，docstring 不变。
- 漂移（+16/−4）：仅中断路径错误处理——`_consume_messages`（`:527`）中 `interrupt()` 失败从静默吞掉改为 log 并跳过 drain（`:552-563`）；`_drain_interrupted_response`（`:576`）失败改为 log（`:579-585`）。
- 拆卡结论：**维持**原建议（CodeBuddyProvider/fetch_codebuddy_models 契约＋超时/限流/畸形响应分支），新增两条分支：interrupt 失败后不排空响应、drain 失败仅告警不中断。839→851 行，仍是本卡最大模块。

### 37. `services.mcp.network` — 仍在，职责显著扩大
- 路径未变；docstring 仍为「Network guards for remote MCP servers (SSRF protection)」（`:2-3`），并新增 trusted-origin 放行说明（`:16-18`）。
- 漂移（+71/−7）：
  1. 阻断网表新增 `fd00:ec2::254/128`、`100.100.100.200/32`、`::/128`（`:38-40`）。
  2. `validate_mcp_url`（`:75`）与 `validate_mcp_url_async`（`:129`）新增 `trusted_origin` 参数：URL 属于管理员登记的 origin 时才允许 RFC1918 私网（`:102`、`:116`，`_RFC1918` `:149`）；metadata/loopback 对 self-service 仍阻断。端口解析失败拒绝（`:93-95`）；URL 含内嵌凭证/fragment 拒绝（`:102`）；DNS 无可用地址拒绝（`:125`）。
  3. 新增公共函数 `mcp_origin`（`:154`，origin 规范化：scheme/host 大小写/尾点/默认端口/IPv6 括号）与 `approved_private_origin`（`:172`，查管理员 registry 匹配 sse/streamableHttp 且允许私网的登记项）。
- 拆卡结论：**维持并改写**。原焦点 validate_mcp_url/validate_mcp_url_async 边界仍需覆盖，但必须补：trusted_origin 放行/拒绝矩阵、两个新函数的规范化与匹配契约、端口/凭证/DNS 失败分支。fanin 5、风险「高」不变；本模块为安全防护面，测试按参数组合矩阵写中性断言即可。

### 80. `api.routers.task_board` — 仍在，重大扩展
- 路径未变；docstring 改为「Independent account task board with workspace/conversation associations.」（`:1`）。
- 漂移（+90/−6）：端点从 3 个扩到 7 个——`get_board` `:26`、`create_card` `:62`、`update_card` `:67` 保留；新增 `GET /events` SSE 流 `board_events`（`:31`，revision 轮询＋心跳＋断连退出）、`PUT /colors` `update_colors`（`:82`）、会话关联 `require_session`（`:86`，archived 工作区拒绝/会话不存在 404）、`PUT /sessions/{id}` `link_tasks`（`:101`）、`PATCH /sessions/{id}/status` `link_status`（`:110`）；`update_card` 新增 workspace_id 归属校验（archived 工作区 → 404，`:69-75`）。
- 拆卡结论：**维持并改写**。原焦点 get_board/create_card/update_card 已不完整（覆盖 3/7 端点），补：SSE 事件流与心跳、link 两端点 4xx、workspace 归属校验分支。LOC 28→112 且 bonus=2（用户面路由），优先级应上调。

### 89. `services.workspace.session_move` — 仍在，实质不变
- 路径未变；`move_chat`（`session_move.py:19`）、`migrate_legacy_bindings`（`:53`）均在，docstring 不变。
- 漂移（+1/−1）：仅 `migrate_legacy_bindings` 改传 `assert_no_pending_recovery(reject_unreadable=True)`（`:70`）。
- 拆卡结论：**维持**，补一条「存在不可读恢复挂起时迁移被拒绝」分支。

### 94. `api.utils.tool_options` — 仍在，职责不变
- 路径未变；`build_tool_options`（`tool_options.py:27`）仍是唯一公共入口，docstring 不变。
- 漂移（+12/−1）：deferred tool `get_definition()` 失败从静默 `continue` 改为按 provider/adapter 记录 warning 后跳过（`:96-107`），对外行为不变。
- 拆卡结论：**维持**原建议（build_tool_options 契约＋异常/降级分支）；日志化分支可作为一条「失败工具被跳过且不中断构建」断言顺带覆盖，不单独加分。

## 复核口径备注
- 「仍在/改名」判定：路径存在＋docstring＋公共符号（def/class/@router）逐一比对，7/7 未改名、未删除。
- LOC 复核：`wc -l` 于 origin/main worktree；漂移量：`git diff --stat f07029cf..6cf793bd8 -- <path>`。
- 全部为只读复核，本分支仅新增本 evidence 目录，无产品/测试代码改动。
