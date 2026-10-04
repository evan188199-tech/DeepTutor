# Skills / MCP 工具层代码导读

基线：origin/main @ `ef2d9e5c3`（v1.6.12），2026-10-03。所有路径相对仓库根，行号以该提交为准。
范围：技能定义（SKILL.md 体系）、工具注册、MCP 客户端与 SSRF/私网校验、分发路径——上游 #1629（研究工具绑定）与 #1028（ACP）均落在这一层。

## 0. 两个文件名的澄清（先读这个）

- 仓库根 `SKILL.md` **不是**产品技能运行时，而是一个面向外部 AI agent 的 CLI 技能包（`name: deeptutor-cli`，SKILL.md:2），教外部 agent 用 `deeptutor` CLI 操作 DeepTutor（SKILL.md:91-101 是技能管理命令，SKILL.md:62 列出可切换工具）。
- 产品内技能是 `deeptutor/skills/builtin/<name>/SKILL.md`（builtin 五件套：docx/pdf/pptx/skill-creator/xlsx）+ 用户层 `data/.../skills/<name>/SKILL.md`，由 `SkillService` 管理。
- `REASONING_SAFETY_CHECKLIST.md` 在根目录已于 v1.6.9（da856ad67）删除，现位于 `docs-for-user/REASONING_SAFETY_CHECKLIST.md`；README.md:638 的链接指向新位置。**旧根路径引用已失效**。

## 1. 模块地图

| 层 | 位置 | 职责 |
|---|---|---|
| 技能存储/解析 | `deeptutor/services/skill/service.py` | SKILL.md CRUD、frontmatter、manifest、hub 导入 |
| 技能解析顺序 | `deeptutor/services/skill/runtime.py` | workspace→account→admin 授权→builtin 的唯一解析序 |
| 技能/工具 API | `deeptutor/api/routers/skills.py`、`space_mcp.py` | 技能 CRUD/hub 安装；用户 MCP 服务器/OAuth/catalog |
| 工具注册 | `deeptutor/runtime/registry/tool_registry.py` | 进程级 registry：builtin 懒加载 + 别名 + 分发 |
| 逐回合工具组合 | `deeptutor/agents/_shared/tool_composition.py` | 用户开关 + 上下文旗标 → 本回合 enabled 列表 |
| 外部 provider 组装 | `deeptutor/runtime/providers/view.py` | MCP/CLI app/overlay → allowlist → scoped registry + manifest |
| 延迟加载 | `deeptutor/runtime/registry/deferred_tools.py` | `load_tools` 渐进披露 |
| 工具分发 | `deeptutor/runtime/agentic/tool_dispatch.py` | 并行执行、子 trace、超时/重试/pause |
| MCP 客户端 | `deeptutor/services/mcp/manager.py`（1031 行，核心） | 连接生命周期、owner 作用域、适配器 |
| MCP 配置/安全 | `deeptutor/services/mcp/config.py`、`user_config.py`、`network.py`、`secrets.py` | 部署级/用户级配置、SSRF 防护、`${secret:}` 引用 |
| MCP catalog | `deeptutor/services/mcp/catalog/` | 45 个 curated 模板条目（vendor/curated.json） |
| 子代理后端 | `deeptutor/services/subagent/` | 外部 agent CLI（codex/claude_code/…） consult，#1028 落点 |
| CLI app 工具 | `deeptutor/services/cli_apps/` | 安装的 CLI harness 以 `cli_<app>` 工具暴露 |

## 2. 技能定义层

**存储与格式**。一个技能 = 一个目录：`<root>/<name>/SKILL.md` + 可选 `references/`（service.py:22-26）。frontmatter 字段 `name/description/tags/always/requires(bins/env/sandbox)`（service.py:27-38）；`requires` 门槛检查在 service.py:371-394（bins 查 PATH、env 查环境变量、sandbox 走 `exec_capability_available`，service.py:205-216）。名称强制 `^[a-z0-9][a-z0-9-]{0,63}$`（service.py:64,236-240）。

**两层 + 阴影**。builtin 层只读（`BUILTIN_SKILLS_ROOT` service.py:72），用户层 `data/.../workspace/skills/`（service.py:227）；`_resolve_skill_dir` 先用户后 builtin（service.py:248-258），写操作拒绝改 builtin（`_assert_writable` service.py:547-553）。

**运行时解析顺序（多用户关键）**。`skill_sources()` 固定为：workspace 绑定 → 本账号 → admin 授予（非 admin 且有 `assigned_skill_ids` 时）→ builtin 最后（runtime.py:24-44，注释明确"包括 admin 技能阴影 builtin"）。`runtime_skills()` 用 `setdefault` 保证同名先到先得（runtime.py:47-61），并按本回合 `turn_resource_selection` 选中的 skills 过滤（runtime.py:53-59；选中作用域在 `services/session/turns/executor.py:216-233` 用 ContextVar 进入，保证同进程并发会话互不影响）。

**System prompt 注入是"一行 manifest + 按需读取"**。`skill_manifest()` 把 `always:true` 且可用的技能全文注入，其余渲染成一行条目（runtime.py:64-75；渲染函数 service.py:997-1023，明示"call `read_skill` … BEFORE attempting the task"）。manifest 作为 `skills` PromptBlock 拼进 system prompt（`agents/loop/prompt_blocks.py:172-173`），由 turn 执行器产出（executor.py:590-592,900）。

**read_skill 工具**。`ReadSkillTool`（`tools/builtin/__init__.py:1637-1728`）执行时经 `runtime_skills()` 解析（__init__.py:1689），所以多用户可见性与 manifest 严格一致。`SkillService.read_skill_file` 做路径防护：拒绝绝对路径与 `..`、resolve 后必须在技能目录内、超 10 万字符截断（service.py:452-476，cap 常量 service.py:76）。文件不存在时回列可用文件并标注截断（__init__.py:1700-1710），止住模型重试循环。

**Hub 导入（不可信来源边界）**。ClawHub/eduhub 两个源（`services/skill/hub.py:70-71`），引用格式 `<hub>:<slug>[@version]`（hub.py:164）。`install_tree` 是导入唯一入口（service.py:631-712）：SKILL.md 超 1MB 拒收（service.py:663-664）；**`always:` 一律剥离**——下载包不得强制注入每个 system prompt（service.py:727-741，注释点名 injection vector）；附属文件白名单后缀 + 数量/总量上限（service.py:86-102,766-804）；**符号链接直接中止导入**（service.py:782-783）；拷贝走 `copyfile` 不保留 exec 位（service.py:772-773,803）；staging 原子换名（service.py:690-699）。来源记录在 `.hub-lock.json`（service.py:81,834-851）。

**API 面**。`api/routers/skills.py`：tags 85-130、list 132、hub catalog/detail 153-199、create/install 224-278、update/delete 280-305。CLI 侧 `deeptutor_cli/skill.py` 走同一 `SkillService`。

## 3. 工具注册与一次调用的生命周期

1. **进程启动**：`ToolRegistry` 单例（`runtime/registry/tool_registry.py:170-176`）只登记"import 便宜的" `BuiltinToolSpec`（名称→类路径，`tools/builtin_specs.py:19-43`），首次 `get` 才实例化（tool_registry.py:59-73）；spec 的 `create()` 校验类名/`tool.name` 漂移（builtin_specs.py:23-33）。21 个内置工具 + exec + workspace 四件注册于 builtin_specs.py:41-80。
2. **回合组合**：`compose_enabled_tools`（`agents/_shared/tool_composition.py:170-265`）按序合并：用户开关（经 `optional_whitelist` 过滤，:253-257）→ 条件自动挂载 `_CONDITIONAL_MOUNT_FLAGS`（rag 有 KB 才挂、read_skill 有技能才挂、load_tools 有 deferred 才挂等，:47-64）→ capability 自有工具（:261）→ 常开五件 `write_memory/web_fetch/github/ask_user/cron`（:262）。`exclusive` 知识 capability 只留 owned+ask_user 底座（:230-248）。`has_skills` 旗标来自 `context.skills_manifest` 非空（`agents/loop/pipeline.py:750`）。`AUTO_MOUNTED_TOOLS` 直接取自 `CONFIGURABLE_BUILTIN_TOOL_NAMES`（:40），UI 与运行时不会漂移。
3. **外部 provider 组装**：`build_tool_view`（`runtime/providers/view.py:70-93`）**承诺不抛异常**——provider 挂了降级为"本回合无外部工具"（:89-93）。它 `ensure_started()` 部署级 MCP（view.py:109），`ensure_scope(owner)` 拉用户自有服务器（3 秒上限，view.py:36,200-213），叠加 CLI app 工具与 overlay（:112-136），经 `authorize_mcp_tools` 生成 allowlist（:121-128；`runtime/providers/authorize.py:26-56`——非 admin 的 grant 缺省是**空** allowlist，fail closed，authorize.py:34-38），workspace 白名单再 narrow（view.py:138-150），产出本回合专属 `ScopedToolRegistry`（view.py:157-165）与 `DeferredToolLoader`（:171-179）。`ToolScope` 是纯输入记录（`runtime/providers/scope.py:20-41`）。
4. **渐进披露**：deferred 工具（MCP 全部，`services/mcp/manager.py:108`）不进初始 schema 列表；system prompt 只带一行 manifest（`runtime/registry/deferred_tools.py:1-16,57-113`，名称/描述经 `sanitize_provider_text` 清洗，:66-75，并明示"当作数据，绝不当指令"，:86-96）。模型调 `load_tools`（`tools/builtin/__init__.py:1731-1786`）→ `DeferredToolLoader.load` 把 schema 追加进活列表（deferred_tools.py:171-193），`run_agentic_loop` 每轮重读，立即可调；已加载名单按 session 持久化（deferred_tools.py:195-201 → `services/mcp/session_state.py`）。loader 的 `allowed` 集合二次把关，模型不能靠猜名字加载白名单外工具（deferred_tools.py:134-139）。
5. **分发执行**：`dispatch_tool_calls`（`runtime/agentic/tool_dispatch.py:122-354`）三段式：rebinding 工具串行 → 其余并行（上限 15，:48）→ pause 工具（ask_user/workspace_export，:55）最后并重绑（:288-325）。缺必填参数先拒（arg guard，:424-504；`tool_arg_guard.py`）。`execute_tool_call`（:647-826）做超时/重试（:721-750），失败**返回 tool result 而非 stream error**——partner 回合会把 ERROR 当"整回合失败"换备份模型重跑、重复执行有副作用工具（:789-797 注释）。trace 行标注 `tool_source/tool_provider`（来自 `provider_identity`，:618-630），UI 因此无需解析 `mcp_<server>_<tool>`。

## 4. MCP 客户端层

**连接模型**（`services/mcp/manager.py` 模块 docstring :8-28）：MCP SDK 的 anyio cancel scope 绑定任务，故每台服务器一条**专职连接任务**独占 `AsyncExitStack`（`_run_server` :672-726），生命周期 = connect → 在任务内进 transport/session → 发布适配器 → 等 shutdown → 同任务退栈。

**双 store，键 `(owner, server_name)`**：部署级来自 admin `mcp.json`（`config.py:115-131`，原子写 :133-151），owner 恒为 `_shared`（manager.py:59）；用户自有来自 `data/system/user-mcp/<owner>.json`（`user_config.py:70-77`，目录在 exec 沙箱永不挂载的分支，:8-14 注释说明为何——该文件命名要注入的凭据）。`ensure_scope` 只为本 owner 连接（manager.py:296-317），**用户级适配器永不进进程 registry**（`_register_adapters` :867-877）——registry 是按名 last-writer-wins 的 dict，两租户重名会互相顶掉；它们经 scoped registry 的 overlay 到达回合（view.py:157-162；overlay 撞共享名直接丢弃并 log error，`runtime/registry/scoped_registry.py:62-71`）。空闲作用域 15 分钟 TTL、上限 64 个（manager.py:75-76,338-365）。写入口已双保险：保留前缀 `mcp_`/`cli_` 禁用（user_config.py:49,172-176）、与部署服务器重名拒绝（`assert_name_available` user_config.py:149-161）。

**传输**：stdio/sse/streamableHttp 自动识别（`config.py:72-79`）。`_open_transport`（manager.py:748-846）：**stdio 仅管理员**（user_config.py:178-183 拒绝写入；manager.py:772-774 运行时再拒）；用户级 URL 在**连接时**重跑 strict 校验（:784-791——保存时校验挡不住 DNS 事后变更，network.py:20-22）；用户级禁用重定向（:792，防"已批准的公网 URL 302 跳元数据地址"）；`tool_timeout` 1-600s（config.py:48）；连接超时 15s（manager.py:52,642），失败指数退避 30s→300s 重试（:68-69,664-670,367-388）。

**SSRF/私网校验**（`services/mcp/network.py`）：两档姿态（:1-23）。基础档（部署级，管理员本就有主机权限）只拦"意外危险目标"：`0.0.0.0/8`、`169.254.0.0/16`（云元数据 169.254.169.254）、`fe80::/10`（:31-35）。strict 档（用户自配）加禁 loopback、三个私网段、CGNAT/Tailscale `100.64.0.0/10`、IPv6 `::1` 与 `fc00::/7`（:39-47）。校验流程：仅 http/https（:82-83）、`getaddrinfo` 解析**全部**地址逐个比对（:88-104），IPv6-mapped IPv4 先归一化（:50-56）。DNS 解析是阻塞调用，async 侧一律走 `validate_mcp_url_async`（to_thread，:108-118），否则一个慢 resolver 拖住整个事件循环的每个请求。

**凭据**：配置里存 `${secret:<server>/<field>}` 引用而非明文（`secrets.py:43-45`），密文件落 owner 级目录 chmod 700（:48-55），连接前 `_materialize` 内存解析、resolve 结果绝不持久化/入日志（manager.py:728-746）。reload 的变更指纹混入**解析后**配置的 sha256，否则换钥匙后 diff 认为没变、会话一直用旧 key（manager.py:570-602）。错误字符串里的 URL 做去凭据化（userinfo/query 打码，`_redact_urls` manager.py:958-986）——该字符串会进设置页**和**返回给模型。

**OAuth**：`auth: "oauth"` 显式声明（config.py:59）；连接任务内非交互、只刷新已存 token，需要人工授权时置 `needs_auth` 状态而非阻塞（manager.py:656-661,799-808）；交互流在 `api/routers/space_mcp.py:169-253`（authorize + callback）。

**Catalog**：模板库不是第二配置库（`catalog/models.py` docstring :1-30）：条目 + 凭据字段（env/header/url_param/arg 四种去向），`build_server_config` 折成 `MCPServerConfig`，**secret 值永不进生成的配置**。`vendor/curated.json` 现有 45 条（airtable、amap、apify…），安装入口 `space_mcp.py:319`。

**测试**：`tests/services/mcp/`（scopes/call_failures/progress/missing_dependency/catalog/config）、`tests/runtime/registry/`（scoped/deferred）、`tests/runtime/providers/test_view.py`、`tests/services/skill/`（service_v2/hub/read_skill 错误消息）、`tests/tools/builtin/test_read_skill_tool.py`、`tests/multi_user/test_skill_resolution_scoped.py`。

## 5. 扩展点（改哪里）

1. **加内置工具**：类放 `tools/builtin/__init__.py`（实现 `BaseTool.get_definition/execute`），在 `tools/builtin_specs.py:41-53` 登记名称与类路径；用户可开关的加进 `USER_TOGGLEABLE_TOOL_NAMES`（`tools/builtin/__init__.py:1907`，CONFIGURABLE 在 :1932），上下文条件挂载的加进 `_CONDITIONAL_MOUNT_FLAGS`（tool_composition.py:47-64）。
2. **加研究/外部能力工具**（#1629 方向）：轻量做 builtin wrapper（参照 `PaperSearchToolWrapper` tools/builtin/__init__.py:484-560 → `tools/paper_search_tool.py` 的 ArxivSearchTool）；重协议做 MCP server + catalog 条目（`catalog/models.py` + `vendor/curated.json` + `space_mcp.py:319` 安装路径），工具会自动走 deferred 披露，无需改 pipeline。
3. **加外部 provider kind**：在 `runtime/providers/authorize.py` 增一个按自身键授权的函数（现有注释明确 MCP 按 tool name、CLI app 按 app id，两政策不能合并，:1-15），`view.py:_build` 中拼进 pool 并 widen（view.py:133-136 为 CLI app 的先例）；manifest 分组在 `deferred_tools.py:46-54` 的 `_group_key`。
4. **加外部 agent 后端**（#1028 方向）：继承 `SubagentBackend`（`services/subagent/base.py:22`，`detect`/`consult` 两个方法，:35,39），参照 `codex.py`（JSONL 事件流映射到 `SubagentEvent` 类型，codex.py:1-27,60+）；注册进 `services/subagent/registry.py`。

## 6. 已知坑

- **根 SKILL.md ≠ 技能运行时**（见 §0）；`REASONING_SAFETY_CHECKLIST.md` 根路径已死，勿再引用。
- `mcp` 包是可选依赖，manager 内全部懒导入（manager.py:61-64,672-682 是 issue #792 的修复——顶层导入会让 connect 干等 15s 超时而非立刻报错）。
- 工具名即全局键：改 `wrapped_tool_name`（manager.py:100-102）会破坏已存 allowlist/白名单（里面存的是名字字符串）。
- reload 指纹若不混入解析后密钥，轮换凭据对运行中进程不可见（manager.py:570-586 整段注释讲这个洞）。
- pause 工具豁免墙钟超时（tool_dispatch.py:233-238）——给 ask_user 加超时会杀掉等待用户。
- 连接任务死亡时适配器必须下线（manager.py:715-724），否则烧 prompt token 换一堆"not connected"。
- exclusive capability 回合 suppression of manifest（view.py:180-184）+ allowlist 置空（authorize.py:44-45），知识能力回合外部工具整体让位。
- `always` 技能只认"可用"的（service.py:540-543）；`requires` 不满足的技能在 manifest 里标 `(unavailable: …)`（service.py:1010-1014）。

## 7. 上游落点

### #1629 研究原语（Feynman / arXiv 工作流）

现状：研究工具只有 `paper_search`（仅 arXiv，tools/builtin/__init__.py:484-560 + `tools/paper_search_tool.py:24`）与 `zotero_search`；deep_research capability 声明的工具面是 `rag/web_search/paper_search/exec`（`agents/research/capability.py:42`）；仓库内**无** alphaXiv/社区标注/文献递归review相关代码。落点二选一（可并行）：
- **builtin 路线**：新 wrapper 进 `tools/builtin/__init__.py` + `builtin_specs.py` 登记；math-vs-code 审计类需要 exec/sandbox 通道（`tools/exec_tool.py`，经 `requires.sandbox` 门槛服务技能侧同理 service.py:389-393）。
- **MCP 绑定路线**（上游原文"first-class MCP tool bindings"）：为 alphaXiv 等做 catalog 条目（`catalog/models.py` + `vendor/curated.json`），走现成 deferred 披露 + allowlist，零 pipeline 改动；deep_research 的工具面在 capability.py:42 追加即可。
前置条件：上游 API 的凭据字段设计（`CredentialTarget` 四去向，catalog/models.py:11-12）；限流策略（arXiv 现有 rate-limit 兜底文案 tools/builtin/__init__.py:524-529 是样板）。

### #1028 Agent Client Protocol（ACP）

现状：**无任何 ACP 代码**（全仓 rg 无匹配）。但已有两条"驱动外部 agent"的成熟先例可复用：
- `services/subagent/` 已有 12+ 个 CLI agent 后端（codex/claude_code/opencode/grok/kimi/openclaw/antigravity/deepseek_harness/hermes…，见目录），统一 `SubagentBackend.detect/consult` 契约（base.py:22-39），事件经 `process.py` 的流式读取映射为 `SubagentEvent`。
- `services/cli_apps/` 把整个 agent harness 安装成 `cli_<app>` 工具，argv-only + 沙箱执行（runner.py:1-14），guide 文件从安装包内读取并清洗（provider.py:48-56,66-75）。

落点：新增 `services/subagent/acp.py`——ACP 客户端（JSON-RPC over stdio，按 agentclientprotocol.com 的 session/update 通知模型）实现 `SubagentBackend`，detect 阶段探测 ACP 兼容 agent；`registry.py` 注册后即接入 consult_subagent 链路。若目标是"用 ACP agent 当对话模型"而非 consult，则落点在 `runtime/providers/`（新增 provider kind，见 §5.3），工作量大得多。
前置条件：ACP 权限模型到 DeepTutor 审批/沙箱的映射（codex.py 的 sandbox bypass 白名单 codex.py:31-33 是参照）；`SubagentEvent` 类型对 ACP session/update 流的覆盖检查（`services/subagent/types.py`）；长会话 resume（codex 用 `exec resume <session_id>`，codex.py:8，ACP 对应 session id 机制）。

## 8. 验证

只读导读，未改任何代码。已用下列命令复核（工作树任意 checkout 需自带 venv；timeout 用 Bash 侧限时替代，macOS 无 timeout 命令）：

```bash
/Users/Shared/DeepTutor/.venv/bin/python -m pytest \
  tests/services/mcp tests/runtime/registry tests/runtime/providers \
  tests/services/skill tests/tools/builtin/test_read_skill_tool.py -q
# 实测 @ ef2d9e5c3 + 本证据文件：302 passed in 3.15s
```

行号抽查示例：`sed -n '31,47p' deeptutor/services/mcp/network.py`（SSRF 两档网段表）。
