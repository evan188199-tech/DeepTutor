# Learner 与账号权限模块导读

面向新维护者的代码导读：覆盖 Learner（学习者）、Guardian（监管人）、课程权限与策略下发的账号模型、权限链路、关键文件与已知坑。基线 v1.6.12（`ef2d9e5c3`），已包含 #1228（PR #1231）与 #1222（PR #1323）的修复。

## 1. 账号模型：role 与 preset 是两层

- `Role` 只有四种合法值（`admin/teacher/student/user`），且**只有 `admin` 提权**；未知/损坏的 role 一律降级为默认值，绝不保留权限。见 `deeptutor/multi_user/models.py:9` 与 `deeptutor/multi_user/models.py:19`。
- `AccountPreset`（`standard/learner/custom`）**不是第三种身份**，只是普通账号的配置形态；管理员永远是管理员，任何 preset 都是普通账号。见 `deeptutor/multi_user/models.py:10`、`deeptutor/multi_user/models.py:40`。
- 账号记录 `UserRecord` 把 `role` 与 `preset` 分开存储：`deeptutor/multi_user/models.py:28`。落盘在 `data/system/auth/users.json`（`deeptutor/multi_user/identity.py:37`）。
- 首个注册账号自动成为 admin；此后新账号固定 `role="user"`，且已配置的 bootstrap admin（`auth.json`）也算"已有账号"，防止 #849 那种首位账号被静默提权。见 `deeptutor/multi_user/identity.py:242`。
- `save_user` 会保留已有 preset（重复保存不会意外翻转），见 `deeptutor/multi_user/identity.py:245`；显式改 preset 走 `set_preset`，支持 `expected_user_id` 乐观校验（`deeptutor/multi_user/identity.py:474`）。
- 存储目录约定：`data/user` 是 admin 工作区，`data/users/<uid>` 是每个非 admin 的独立工作区，`data/system` 放账号/授权/审计，永不挂进沙箱。见 `deeptutor/multi_user/paths.py:6` 与 `deeptutor/multi_user/paths.py:102`。
- PocketBase 模式目前**仅单用户**（users 集合无 role 字段、会话表不按 user_id 过滤），preset 会被显式拒绝。见 `deeptutor/multi_user/__init__.py:13`、`deeptutor/api/routers/auth.py:1537`。

## 2. 权限链路：从请求到数据的一条线

一条 learner 请求要过五道闸，全部服务端强制：

1. **认证**：`require_auth` 解析 JWT（Bearer 头或 `dt_token` cookie），把 `CurrentUser` 写进 ContextVar，并装配请求级工作区。见 `deeptutor/api/routers/auth.py:419` 与 `deeptutor/api/routers/auth.py:398`。
2. **面（surface）默认拒绝**：所有业务路由以 `dependencies=_auth`（即 `require_learning_surface`）挂载（`deeptutor/api/main.py:591`，courses 挂载在 `deeptutor/api/main.py:665`）。`_learning_surface_for_path` 把 URL 前缀映射到 `chat`/`reading` 两面；未映射的一律拒绝。见 `deeptutor/api/routers/auth.py:610` 与守卫入口 `deeptutor/api/routers/auth.py:641`。
   - `/api/courses → reading` 是 #1228 的修复（PR #1231）：此前 learner 打开课程页被 403 风暴。`deeptutor/api/routers/auth.py:617`。
   - `/api/task-board → chat` 是后续补丁 `7dd1f7f04`：`deeptutor/api/routers/auth.py:622`。
   - `/api/mastery-paths → chat` 与 KB 只读白名单（按**路由模板**匹配而非 URL 前缀，防 admin 诊断接口漏进 learner 壳）见 `deeptutor/api/routers/auth.py:626` 与 `deeptutor/api/routers/auth.py:597`。
3. **策略（learning_policy）**：`assert_learning_surface` 对照 grant 里的 `allowed_surfaces` 拒面（`deeptutor/multi_user/learning_access.py:63`）；会话回合前 `apply_learning_policy` 强制 capability 白名单并清空 tools/KB/RAG 等载荷面（`deeptutor/multi_user/learning_access.py:34`，调用点 `deeptutor/services/session/turns/request_preparer.py:277`）。
4. **资料（materials）**：阅读面逐请求校验 `assert_learning_material`（上传开关 + 指派清单，`deeptutor/multi_user/learning_access.py:73`），管理员指派的材料禁止 learner 端删除（`deeptutor/multi_user/learning_access.py:98`）；`deeptutor/api/routers/reading.py` 内十余处调用（如 `deeptutor/api/routers/reading.py:542`、`deeptutor/api/routers/reading.py:783`），撤销的引用会从新鲜与历史会话源里消失（测试 `tests/multi_user/test_learning_reading_turns.py:86`）。
5. **工作区隔离**：课程、会话等每用户数据落在各自 scope 根下，`CourseService` 根取自当前用户工作区（`deeptutor/services/courses.py:254`）；KB 访问经 `resolve_kb` 按指派清单收敛（`deeptutor/multi_user/knowledge_access.py:79`，指派名收集在 `deeptutor/multi_user/knowledge_access.py:64`）。

工具面收敛在 `deeptutor/multi_user/tool_access.py:36`：`enabled_tools/mcp_tools/cli_apps/exec_enabled` 全部源自 grant，MCP/CLI 缺省即拒绝。

## 3. 策略下发：guardian restrictions 与 grant

- Grant 是唯一可执行策略载体（v2 schema），只存逻辑 id、禁止 secret/path 字段。schema 与校验见 `deeptutor/multi_user/grants.py:79`、`deeptutor/multi_user/grants.py:161`、`deeptutor/multi_user/grants.py:316`。
- learner preset 的服务端展开是保守集（tools/MCP/CLI 全空、exec 禁、仅 chat+reading、禁止上传、无材料）：`deeptutor/multi_user/grants.py:192`。
- Guardian 授权是显式关系记录（`assign_materials/manage_restrictions/view_reports/reset_credentials` 四种权限），见 `deeptutor/multi_user/guardians.py:17`；每次访问都**重验双方当前身份**，preset 变更后的旧关系不构成授权路径（`deeptutor/multi_user/guardians.py:203`）。
- 监管端点经 `_require_guardian_access` 双检（admin 直通，guardian 查关系+权限）：`deeptutor/api/routers/multi_user.py:321`。
- **PUT restrictions 是"指派即成为学习账号"的入口**（#1222 修复）：账号还没有 policy 时先以 `learner_grant` 兜底，校验通过后先存 grant，再翻 preset 为 learner；preset 翻转失败会按写回凭据回滚 grant，避免"standard preset + policy"的混合态（那正是当年渲染 admin 壳并 403 风暴的根因）。见 `deeptutor/api/routers/multi_user.py:674`、翻转与回滚 `deeptutor/api/routers/multi_user.py:692`、回滚原语 `deeptutor/multi_user/grants.py:301`。
- 创建 learner 账号同样先建号再落 grant，grant 初始化失败即删号回滚：`deeptutor/api/routers/auth.py:1577`。
- `/api/auth/status` 对外呈现时**以生效策略为准**：存了 policy 的 standard/custom 账号也会按 learner 呈现（ Guardians 可给非 learner 账号挂 policy），见 `deeptutor/api/routers/auth.py:749`；前端 `AuthStatus` 同构该字段（`web/lib/auth.ts:21`），Settings 可见性据此分流（learner-only / guardian-only，`web/features/settings/navigation/settings-access.ts:35`）。
- 本地设备登录（孩子机免密）只对活跃 learner 账号放行：`deeptutor/multi_user/device_credentials.py:154`。

## 4. 关键文件表

| 文件 | 职责 | 关键行 |
| --- | --- | --- |
| `deeptutor/multi_user/models.py` | Role/Preset 定义、UserRecord/CurrentUser | `models.py:9` `models.py:40` |
| `deeptutor/multi_user/identity.py` | 账号存储、注册提权、preset/profile 写入 | `identity.py:223` `identity.py:474` |
| `deeptutor/multi_user/paths.py` | admin/用户/系统目录与 scope 解析 | `paths.py:89` `paths.py:102` |
| `deeptutor/multi_user/grants.py` | grant v2 读写、校验、learner 展开与回滚 | `grants.py:161` `grants.py:192` `grants.py:316` |
| `deeptutor/multi_user/learning_access.py` | 策略解析与会话/面/资料强制 | `learning_access.py:12` `learning_access.py:34` |
| `deeptutor/multi_user/guardians.py` | 监管关系存储与重验 | `guardians.py:95` `guardians.py:203` |
| `deeptutor/multi_user/device_credentials.py` | learner 设备凭证（PIN/租约/心跳） | `device_credentials.py:154` |
| `deeptutor/multi_user/tool_access.py` | 运行期工具白名单收敛 | `tool_access.py:36` |
| `deeptutor/multi_user/knowledge_access.py` | KB 可见性与指派收敛 | `knowledge_access.py:79` |
| `deeptutor/multi_user/book_permission.py` | 共享书目 ACL（none/read/edit） | `book_permission.py:17` |
| `deeptutor/api/routers/auth.py` | 认证、面映射守卫、/status 呈现、账号创建 | `auth.py:610` `auth.py:641` `auth.py:749` |
| `deeptutor/api/routers/multi_user.py` | guardian/管理员管理端点、restrictions | `multi_user.py:321` `multi_user.py:656` |
| `deeptutor/api/main.py` | 路由挂载与守卫依赖注入 | `main.py:591` `main.py:665` |
| `deeptutor/services/courses.py` | 课程容器（每用户工作区） | `courses.py:254` |
| `deeptutor/api/routers/reading.py` | 阅读面资料策略强制 | `reading.py:35` `reading.py:188` |
| `deeptutor/learner_profile.py` 所在层 `deeptutor/multi_user/learner_profile.py` | 学习者画像（年龄/年级等）注入提示词 | `learner_profile.py:13` `learner_profile.py:38` |
| `web/lib/auth.ts` | 前端 AuthStatus（preset+learning_policy） | `auth.ts:10` |
| `web/features/settings/navigation/settings-access.ts` | 设置页 learner/guardian 可见性 | `settings-access.ts:22` |
| `web/components/courses/CoursesShelf.tsx` | 课程架加载失败显式告警（#1228） | `CoursesShelf.tsx:143` |
| `web/lib/courses-api.ts` | 课程 API 错误规范化为 ApiError（#1228） | `courses-api.ts:131` |

## 5. 已知坑

- **新路由必须进面映射**：以 `_auth` 挂载但没进 `_learning_surface_for_path` 的前缀，对 learner 一律 403。#1228（courses）与 `7dd1f7f04`（task-board）都是这么来的。新增 learner 可用的第一方 API 时，先补映射再补 `tests/multi_user/test_learning_surface_map.py` 的参数表。
- **preset 与 policy 双源**：真正的运行时强制以 grant 里的 policy 为准（`learning_access.py:12` 仅在 preset=learner 且无存量 policy 时兜底合成保守集）；对外呈现（/status）又以 policy 反推 learner 标签（`auth.py:749`）。排查"明明是 learner 却看到 admin 壳/或反之"时，先看 `data/system/grants/<uid>.json` 有没有 policy，再看 `users.json` 的 preset 是否翻转成功。
- **WebSocket 不经面守卫**：`require_learning_surface` 需要 Request，WS scope 给不了，所以 WS 路由挂在无 `_auth` 依赖上、靠连接内自检（`deeptutor/api/main.py:627`）。给 WS 加 learner 约束时不能只依赖这层。
- **PocketBase 模式没有多用户**：不要在 PocketBase 部署上验证 learner/guardian 功能，preset 与设备凭证都会被拒（`auth.py:1537`、`device_credentials.py` 的 PocketBase 拒绝分支）。
- **材料指派 ≠ 课程指派**：课程只是容器，attach 的资源指针不改变 reading 面的 material_ids 白名单；learner 能否读某材料仍由 grant 的 `reading.material_ids` 决定（`learning_access.py:73`、`grants.py:148`）。课程删除只摘指针、不删资源（`deeptutor/services/courses.py:1` 模块注释）。
- **grant 写入有跨进程文件锁与回滚凭据**：手工改 `grants/*.json` 绕过 `_grant_write_lock` 可能与在线写入互相覆盖（`grants.py:47`）。
- **guardian 关系重验**是每次访问都做的（`guardians.py:203`），意味着把 learner preset 改走后旧监管立即失效——这是特性不是 bug，但排查"监管突然看不到孩子"时先查双方 preset。

## 6. 现有测试与覆盖空白

### 后端（`tests/multi_user/`，本基线 329 passed）

| 测试文件 | 覆盖点 |
| --- | --- |
| `test_account_presets.py` | preset 生命周期、learner grant 展开/回滚、PocketBase 拒绝、/status 呈现 |
| `test_learning_surface_map.py` | 面映射参数表、KB 只读白名单、restrictions 翻 preset 及全部失败回滚分支 |
| `test_learning_policy.py` / `test_learning_policy_http.py` | grant 校验、回合策略强制、HTTP 层资料/扩展跟随策略 |
| `test_learning_reading_turns.py` | 撤销材料在会话/标签层的消失 |
| `test_guardians.py` | 授权/撤销/报告/材料指派/重验/删除联动 |
| `test_device_credentials.py` | 设备凭证签发、限速、过期、非 admin 放行 |
| `test_task_board.py` | 面映射放行后的读写与账户隔离 |
| `test_learner_profile.py` / `test_grants_and_settings.py` | 画像校验与 grant 注入 settings |

复现命令：`/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/multi_user/ -q`

### 前端

- `web/tests/courses-shelf.spec.tsx`（vitest，1 passed）：课程架错误态。
- `web/tests/course-organization-api.test.ts`、`web/tests/guardian-management.test.ts`、`web/tests/admin-user-presets.test.ts`（node:test，全量 `test:node` 套件 1234 passed / 0 fail）。

复现命令（在 `web/` 下）：`node ./scripts/run-node-tests.mjs`；`./node_modules/.bin/vitest run tests/courses-shelf.spec.tsx`

### 覆盖空白

1. **课程↔材料链路无端到端断言**：课程 attach 资源后，learner 在 reading 面实际能否读到该资源，没有跨 `courses.py` 与 `reading.py` 的集成测试；现有测试各自覆盖一半。
2. **面映射漂移无防护**：没有"枚举全部以 `_auth` 挂载的路由前缀、断言其在映射表内或有意豁免"的守卫测试，新路由漏映射仍只能靠回归发现。
3. **guardian HTTP 层鉴权矩阵不完整**：`test_guardians.py` 覆盖服务层与部分端点，但 `_require_guardian_access` 对非授权 guardian/无关系用户访问各端点的 403 矩阵没有逐端点断言。
4. **`learner_grant` 兜底合成的写入缺口**：policy 只读合成（`learning_access.py:12`）在并发改 grant 时的表现没有测试。
5. **`learner_profile.prompt_block` 注入面**：画像文本转义有单测，但画像进入真实会话提示词的端到端路径未覆盖。
