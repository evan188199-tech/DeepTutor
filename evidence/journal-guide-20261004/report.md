# 学习日志域导读与 #1407 面板需求拆解

- 基线: `origin/main` @ `f07029cfc` (release: v1.6.13)，独立 worktree，未改任何代码。
- 输入: 上游 issue #740（状态化学习提案）、#1407（只读总览面板）、PR #1226 公开描述（仅作背景，未检出其分支、未评审）。
- 结论速览: **main 上不存在任何学习日志（learning journal）代码**——存储、工具、注入链、面板、i18n、API 全部缺席；#740 的 mission / handoff / records 三实体目前只活在开放 PR #1226 里，#1407 的面板连 PR 都没有。现状的"可见性"只有上下文预算 popover 里的一行 token 计数。

## 1. 三实体定义（#740 / #1226 / #1407 的公约数）

| 实体 | 含义 | 来源 |
|---|---|---|
| mission（当前使命） | 学习目标 + 约束，tutor 跨会话携带 | #740 "制定具体计划"；#1407 "goal + constraints" |
| last-session handoff（上次交接） | 上次会话的摘要 + 下次接着学的 focus | #740 "每次学习后记录当前状态，方便下次接着学"；#1407 "summary + next focus" |
| records（确认记录） | ADR 风格的已确认学习记录，按新到旧排列 | #1226 描述 "ADR-style learning records"；#1407 "confirmed records (newest first)" |

#1226 的实现口径（背景参考）：每用户 `learning_journal/journal.json` 存储；常驻工具 `learning_status` / `learning_update`（`set_mission` | `note_session` | `add_record`）；turn 开始前快照、作为独立 system block 注入；**records 不随 turn 注入**（只能用 `learning_status` 查），使单 turn 开销不随日志历史增长。

## 2. 现状盘点（main 上真实存在什么）

### 2.1 上下文预算 popover：只有 token 计数

- 数据结构就是纯计数：`ContextBudget` 类型只有 `window / used_tokens / free_tokens / segments[{key, tokens}]` — `web/components/chat/home/ContextBudgetChip.tsx:6-17`。
- popover 渲染 = 环形用量 + 堆叠条 + 每个 segment 的「色块 + 名称 + token 数 + 百分比」三列 — `web/components/chat/home/ContextBudgetChip.tsx:281-311`（SegmentRow: 126-158）。没有任何内容文本、没有实体可看。
- segment 颜色表（`SEGMENT_COLORS`，15 个已知 key）— `web/components/chat/home/ContextBudgetChip.tsx:25-41`；未知 key 用哈希色兜底不崩 — 同文件 :52-62。
- 数据链路：turn 结束的 `result` 事件 metadata 携带 `context_budget`，前端倒序找最近一次测量 — `web/hooks/useContextBudget.ts:27-46`；composer 挂载点 — `web/features/chat/components/ChatWorkspace.tsx:1605` 与 `web/components/chat/home/ChatComposer.tsx:1306`。
- 后端计量：`deeptutor/agents/loop/pipeline.py:1652`（`measure_context_budget`）→ `deeptutor/agents/loop/context_budget.py:151-236`（`build_context_budget`），segment 由 `PromptBlock.name -> segment key` 的映射表 `_BLOCK_SEGMENTS` 决定 — `deeptutor/agents/loop/context_budget.py:33-50`。**表中没有 `learning_journal`**。

### 2.2 prompt 注入链（journal 块应接入的缝）

- 系统提示词由 `LoopPromptAssembler` 按命名块组装；memory 块挂载点 — `deeptutor/agents/loop/prompt_blocks.py:163-164`（`if context.memory_context: blocks.append(PromptBlock("memory", ...))`）。
- 可重放的运行时块名单 `RUNTIME_BLOCK_NAMES`（memory、notebooks 等）— `deeptutor/agents/loop/prompt_blocks.py:26-38`。
- turn 执行器在 turn 开始时读一次 memory 快照：`deeptutor/services/session/turns/executor.py:562-563`（`memory_context = memory_store.read_l3_concat() if memory_references else ""`），随后传入 assembler — 同文件 :903；`UnifiedContext.memory_context` 字段 — `deeptutor/core/context.py:107,139`。这正是 #1226 描述的"turn 开始前快照、整个 turn 字节稳定"所要复制的缝。
- 选区小 tutor 隔离缝：`executor.py:257-263` 提取/解析 `selection_tutor_context`——#1226 测试计划里"选区辅导绝不挂载 journal"的断言点就在这条 guard 上。

### 2.3 常驻聊天工具（learning_status / learning_update 的注册缝）

- 内建工具规格表 — `deeptutor/tools/builtin_specs.py:50-72`（`write_memory` 在 :60）；工具实现 — `deeptutor/tools/builtin/__init__.py:929`；可配置常驻工具名单 `CONFIGURABLE_BUILTIN_TOOL_NAMES` — `deeptutor/tools/builtin/__init__.py:1932-1956`。main 上没有任何 `learning_*` 工具。

### 2.4 每用户存储缝（journal.json 的落点先例）

- 运行时存储布局集中在 `PathService`：单用户 `data/user/`、多用户实例化为 `data/users/<uid>/` — `deeptutor/services/path_service.py:68-69,85-95`；`get_workspace_dir()` — :222。
- memory 域的先例布局（trace/L2/L3 目录 + `ensure_dirs()`）— `deeptutor/services/memory/paths.py:63-97`，journal 域可镜像此模式。

### 2.5 读端点先例（#1407 明确允许"a read endpoint if needed"）

- Memory v3 路由有完整只读读法（`GET /overview` 等）— `deeptutor/api/routers/memory.py:9-28`。journal 面板读端点可照此注册。

### 2.6 Learning Space（面板挂载点）

- 学习空间现有五个 surface：Books / Mastery Path / Practice / Immersive Reading / Immersive Watching — `web/components/learning/surfaces.ts:27-106`。**没有 journal 入口**。
- #1407 提议"alongside notebooks / question bank"，即作为学习空间内的同级只读面板，而非聊天内组件。

### 2.7 i18n

- popover 文案键 `contextBudget.*`（en 从 `web/locales/en/app.json:2637` 起，zh 从 `web/locales/zh/app.json:2646` 起），每个语言包各有 15 个 `contextBudget.segment.*` 键，无 `learning_journal`。仓库共 6 个语言包（de/en/fr/pl/uk/zh）。

### 2.8 同名不同物（避免误读）

main 上三处含 "journal" 的模块与学习日志无关：`deeptutor/multi_user/session_handoff.py:1-6`（私转公会话配对的安全状态）、`deeptutor/learning/storage.py:1-5`（Mastery/Reading 的 SQLite 存储）、`deeptutor/runtime/coordination/journal.py:1-4`（live 事件协调日志）。`handoff` 一词在 #1407 语境下只指学习会话交接，不要与 `session_handoff.py` 混淆。

## 3. 落差清单（实体 → 现状 → 落差 → 面板所需）

统一编号 D1-D7；每条附 path:line 或 issue 引用。

| # | 项 | 现状（main） | 落差 | 引用 |
|---|---|---|---|---|
| D1 | 存储（journal.json） | 不存在。全仓 `learning_journal` 零命中（`grep -ri learning_journal deeptutor` 无结果） | mission/handoff/records 无处落盘；#1226 独占携带 | #1226 描述；`deeptutor/services/path_service.py:68-69`（应有落点先例） |
| D2 | turn 注入链 | turn 开始只快照 memory（executor.py:562-563）；`_BLOCK_SEGMENTS`/`RUNTIME_BLOCK_NAMES` 均无 journal | #1407 要求"面板展示的就是 executor 注入的同一份快照"——注入链缺席则面板无物可镜像 | `deeptutor/agents/loop/context_budget.py:33-50`；`deeptutor/agents/loop/prompt_blocks.py:26-38,163-164`；`deeptutor/services/session/turns/executor.py:562-563,903` |
| D3 | 常驻工具 | 无 `learning_status` / `learning_update`（`grep -rn "learning_status\|learning_update" deeptutor` 零命中） | set_mission/note_session/add_record 三个写入口只存在于 #1226；只读面板的"编辑留在对话内"依赖这两个工具 | `deeptutor/tools/builtin_specs.py:50-72`；`deeptutor/tools/builtin/__init__.py:1932-1956`；#740 |
| D4 | 面板 UI | popover 只有 token 计数（ContextBudgetChip.tsx:281-311）；学习空间 5 个 surface 无 journal（surfaces.ts:27-106）；`web/` 全域 "journal" 零命中 | #1407 的只读面板（三实体渲染 + 空态提示 + records 折叠）整体缺席 | #1407 正文；`web/components/learning/surfaces.ts:27-106` |
| D5 | 读 API | 无 journal 路由；先例见 memory 路由的只读端点 | #1407 允许新增"一个读端点"作为唯一 API 面 | `deeptutor/api/routers/memory.py:9-28`；#1407 "Out of scope" 段 |
| D6 | i18n | 6 语言包均无 journal 文案；popover segment 键 15 个，无 learning_journal | 面板（en/zh 必需）+ popover segment 标签（可选，未知 key 已有哈希色+原文兜底，ContextBudgetChip.tsx:52-62,298-300）需补 | `web/locales/en/app.json:2637` 起；`web/locales/zh/app.json:2646` 起 |
| D7 | 测试 | main 上无任何 journal 测试（#1226 测试计划所列 5 个测试文件均在其分支） | 落地时需按 #1226 测试计划作为验收模板：注入/空态/records 不随行/选区隔离 | #1226 "Test plan" 段 |

依赖顺序：D1 → (D2, D3) → D5 → (D4, D6, D7)。D1-D3 就是 #1226 的领地；#1407 面板只站在 D5/D4/D6 上，但验收（"所见即模型所见"）依赖 D2。

## 4. #1407 面板数据契约建议（读契约）

`GET /api/learning/journal`（每用户作用域，跟随 `PathService` 的 `data/users/<uid>/` 实例化，path_service.py:68-69）：

```jsonc
{
  "mission":  { "goal": "...", "constraints": ["..."], "updated_at": "..." } | null,
  "handoff":  { "summary": "...", "next_focus": "...", "ended_at": "..." } | null,
  "records":  [ { "id": "...", "decision": "...", "confirmed_at": "..." } ],  // 新到旧
  "injected": { "mission_handoff_text": "...", "updated_at": "..." }          // 与 turn 注入同源
}
```

验收要点（全部来自 #1407 正文）：
1. 只读：无任何写端点；编辑只走对话内 `learning_update`（面板不得成为第二条编辑路径，否则与存储态漂移）。
2. 同源：面板展示的 mission+handoff 必须与 turn executor 注入的快照一致（D2 落地后才可验收）；records 折在面板内（点开才看），与注入策略（records 不随 turn）对偶。
3. 空态：显示"tutor 还没为你设定使命——去让它设一个"式提示，而非空白面板。
4. i18n en/zh；每用户作用域；无编辑/评分/门禁（journal 是软状态，偏好归 Memory、评分课程归 Mastery Path）。

## 5. 实现前置条件与可拆卡建议

前置结论：**#1226（后端）未合并前，#1407 面板只能做壳**。建议拆卡如下（每张可独立验收）：

| 卡 | 内容 | 验收要点 | 依赖 |
|---|---|---|---|
| K1 跟踪 | 跟进 #1226 合并进度；不重复实现存储/工具 | 合并后 main 上 `learning_journal` 存在与否 | — |
| K2 注入补测卡 | turn 开始快照 + `learning_journal` PromptBlock + `_BLOCK_SEGMENTS`/`RUNTIME_BLOCK_NAMES` 登记 + 选区隔离 guard | 四条测试：注入挂载为独立块、空日志不注入、records 不随行、selection tutoring 绝不查 store（对齐 #1226 测试计划） | K1 |
| K3 读端点卡 | `GET /api/learning/journal` + 契约测试（空态/三实体/每用户隔离） | 与第 4 节契约一致；无写端点 | K1 |
| K4 面板卡 | Learning Space 内只读面板（三实体 + records 折叠 + 空态提示） | 只读、空态文案、不新增编辑路径 | K3（显示层可先用 K3 契约 mock） |
| K5 i18n 卡 | 6 语言包补 `contextBudget.segment.learning_journal` + 面板文案（en/zh 必做） | popover 里 journal segment 有本地化标签而非原始 key | K2 |
| K6 复核卡 | #1226 合并前不评审其分支（本卡边界）；合并后按其测试计划在 main 复跑 | `timeout 900 python -m pytest -q -p no:cacheprovider tests/services/learning_journal tests/tools/test_learning_journal_tools.py tests/agents/chat/test_learning_journal_injection.py` | K1 |

## 6. 撞车与 PR 状态

- 上游开放 PR 中与 #740 关联的只有 #1226（`feat/learning-journal-mission-records`，后端）；**没有任何 PR 引用 #1407**（面板），无撞车，无需复核。
- 按卡面要求：未检出 #1226 分支、未基于其代码；本文仅引用其公开描述作背景。

## 7. 复核命令

```bash
git -C <worktree> rev-parse HEAD          # f07029cfcf2c8dfccdb671cdfc343db8334f5741
grep -rn "learning_journal\|learning_status\|learning_update" deeptutor --include='*.py'   # 零命中
grep -rn -i "journal" web/components web/features web/hooks web/lib                        # 零命中
```
