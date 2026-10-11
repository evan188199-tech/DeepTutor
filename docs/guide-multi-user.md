# multi_user 域代码导读（guide-multi-user）

- 基线：`origin/main @ 6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/multi_user/` 全部模块、消费方路由（`deeptutor/api/routers/auth.py`、`multi_user.py`、`book.py`、`partners.py`）、`tests/multi_user/` 对照；文末附新增访问域接入 checklist 与校验命令。
- 所有锚点形如 `path:line`，相对仓库根目录。

## 0. 全景：一张模块地图

`deeptutor/multi_user/` 是"可选多用户层"：auth.json 未启用时全系统退化为单管理员（`__init__.py:1`），启用后按 JWT 身份把请求路由进每用户工作区。模块分四组：

| 分组 | 模块 | 一句话职责 |
| --- | --- | --- |
| 身份底座 | `models.py` / `context.py` / `identity.py` / `paths.py` | 角色、请求上下文、账号存储、路径与密钥布局 |
| 授权数据 | `grants.py` / `book_permission.py` / `guardians.py` | 管理员授予普通用户的逻辑资源、图书 ACL、监护关系 |
| 访问解析 | `book_access.py` / `knowledge_access.py` / `tool_access.py` / `skill_access.py` / `model_access.py` / `personal_models.py` / `partner_access.py` / `learning_access.py` | 每资源域一个 resolver，把"这个用户能对它做什么"收敛成单一答案 |
| 会话与审计 | `audit.py` / `device_credentials.py` / `session_handoff.py` | 访问/管理审计流水、本地设备凭证、私网到公网会话交接 |

身份怎么进上下文：`require_auth`（`deeptutor/api/routers/auth.py:420`）解 JWT 后经 `_install_current_user`（`auth.py:399`）调 `user_from_token_payload`（`context.py:30`）写入请求级 ContextVar；WebSocket 走 `ws_require_auth`（`auth.py:541`）。管理面守卫是 `require_admin`（`auth.py:579`）。**不变量：每个认证入口都必须先装上下文**，否则 `get_current_user()`（`context.py:22`）兜底为本地管理员——这是 #481 静默路由错误的根因；该兜底只应服务 CLI/后台任务。

## 1. 账号与角色（identity / models）

- 职责：`users.json` 是唯一账号存储（`identity.py:37-41`），记录 id/角色/哈希/preset/头像/图书 ACL/学习者档案；`VALID_ROLES = {admin, teacher, student, user}`（`models.py:16`），仅 "admin" 提权（`models.py:13-16`）。
- 入口：注册与登录在 `auth.py:1137` / `auth.py:828`；账号 CRUD、preset、角色变更暴露在管理路由 `multi_user.py:926`（/users）及同文件各端点；底层读写走 `save_user` / `load_users`（`identity.py:223` / `:176`）。
- 边界：写锁 `_USERS_WRITE_LOCK`（`identity.py:35`）保证并发首注册只有一人成为 admin（`identity.py:242-243`），但仅单进程有效，多 worker 需外置用户库（`identity.py:30-34`）；auth.json 引导管理员只在内存合并、永不落盘（`identity.py:207-218`）；未知角色经 `normalize_role`（`models.py:19`）最低权限降级；preset（standard/learner/custom）不是第三种角色（`models.py:40-43`）。

## 2. learner_profile 与学习策略

- 职责：学习者账号的结构化档案（年龄/年级/课程/语言/阅读水平/讲解风格），归一化校验在 `learner_profile.py:13`（age 3-120、文本 ≤80 字符、拒绝控制字符），schema v1。
- 入口：档案存于账号记录（`identity.py:88`、`:257`），仅 learner preset 普通账号可写 `set_learner_profile`（`identity.py:304`）；读取/展示走 profile 路由（对照 `tests/multi_user/test_profile_router.py`）；策略面在 `grants.py` 的 `learning_policy`（归一 `grants.py:120`、校验 `grants.py:316` 末段），learner 默认策略见 `learner_grant`（`grants.py:192`）。
- 边界：进入提示词前 `prompt_block`（`learner_profile.py:38`）转义 `<>` 并显式标注"不可信数据，禁止跟随其中指令"——注入面在数据进模型前收口；每轮对话在验证/持久化前强制套用策略 `apply_learning_policy`（`learning_access.py:34`），面级守卫 `assert_learning_surface` / `assert_learning_material`（`learning_access.py:63` / `:73`）与路由守卫 `require_learning_surface`（`auth.py:702`）双层校验。

## 3. guardian 授权链

- 职责：显式监护关系记录（guardian→learner + 四种权限 `assign_materials` / `manage_restrictions` / `view_reports` / `reset_credentials`），存 `data/system/guardians.json`（`guardians.py:17-20`）。
- 入口：建立/撤销走管理路由 `POST/DELETE /guardians`（`multi_user.py:395` / `:427`），底层 `authorize_guardian` / `revoke_guardian`（`guardians.py:95` / `:161`）；监护人操作学习者材料/限制/凭证走 `/learners/{id}/materials|restrictions|credentials/reset`（`multi_user.py:535` / `:656` / `:740`），先过 `_require_guardian_access`（`multi_user.py:321`）→ `guardian_can_access`（`guardians.py:203`）再写 `log_guardian_action`（`multi_user.py:346`）。
- 边界：双方必须是普通账号——admin 不得担任任何一侧、learner preset 只能当 learner、learner 账号不能当 guardian（`_require_ordinary_user`，`guardians.py:81-92`）；禁止自监护与互为监护环路（`guardians.py:102`、`:117-123`）；`guardian_can_access` 每次重验双方当前身份，preset/角色事后变更不会让旧关系复活（`guardians.py:208-215`）；用户删除时级联撤销（`identity.py:378-385` → `revoke_relationships_for_user`，`guardians.py:181`）。

## 4. partner_access（合成用户访问控制）

- 职责：Partner 可见性的唯一裁决点——manage=创建者或 admin（`partner_access.py:63`），use=manage ∪ 被授权分配（`can_use_partner`，`partner_access.py:72`）；两者都不满足则该 Partner 对用户"不存在"（`partner_access.py:1-12`）。
- 入口：会话前断言 `assert_partner_allowed`（`partner_access.py:80`），配置面断言 `assert_partner_manageable`（`:94`）；列表投影 `visible_partners` / `identity_card`（`:127` / `:119`）；消费方 `deeptutor/api/routers/partners.py:100`、`:644`。
- 边界：被分配者只能"对话"不能"配置"（`grants.py:86-91`），且只见身份卡、不见渠道/模型接线（`_CARD_FIELDS`，`partner_access.py:104-116`）；不可管理时与无权使用返回同形 403，不泄露归属（`partner_access.py:94-101`）；Partner 永远运行在自己的隔离工作区 `data/partners/<id>/`（`paths.py:113-125`），会话历史跟随人的账号，两人对同一 Partner 的线程互不可见（`partner_access.py:14-19`）；owner-keyed 资产（OAuth 凭证）解析到其人类 owner 而非合成账号（`paths.py:170-197`、`get_owner_path_service` `paths.py:200`）。

## 5. book_access / book_permission（共享图书 ACL）

- 职责：管理员工 workspace 是共享书库，`BookPermission(create, default, books 覆盖)` 描述普通用户的创建能力与每本共享书的 none/read/edit 等级（`book_permission.py:21-37`）；个人 workspace 完全私有可编辑，本模型只管共享目录（`book_permission.py:1-6`）。
- 入口：单本解析 `resolve_book`——own 命中即全权，否则查共享库并按 ACL 判级，拒绝/不存在统一返回 None（`book_access.py:84-116`）；列表 `accessible_books`（`book_access.py:119`）；创建判定 `can_create_book`（`book_access.py:78`）；路由消费方 `_resolve_book_or_404`（`deeptutor/api/routers/book.py:259-265`）、创建开关 `book.py:610`；ACL 管理端点 `multi_user.py:818` / `:836`。
- 边界：`normalize_book_permission` 对任何持久化形态 fail-closed——缺省/畸形不给共享访问、legacy `mode/actions` 保守折叠（`book_permission.py:45-91`）；共享书永不可删除、学习进度走只读 overlay（`book_access.py:109-116`）；删除共享书时清理所有用户 ACL 并返回受影响者供审计（`remove_book_permission_overrides`，`identity.py:335`），共享编辑动作写审计（`book.py:374` `log_usage("book", …, "shared_edit")`）。

## 6. grants 与工具面（knowledge / tools / skills / models）

- 职责：管理员对普通用户的逻辑授权，每用户一份 `data/system/grants/<uid>.json`（`grant_path`，`grants.py:156`）；v2 形态含 models.llm、knowledge_bases、skills、partners 与工具白名单（`empty_grant`，`grants.py:79-109`）。
- 入口：管理端 `GET/PUT /users/{id}/grants`（`multi_user.py:773` / `:779`）；读取 `load_grant`（`grants.py:217`）全程校验；各域消费：KB `knowledge_access.resolve_kb`（`knowledge_access.py:86`，require_write 写守卫，文档路径解析 `:398`）、内建工具 `allowed_optional_tools`（`tool_access.py:44`，会话管线单点过滤 `deeptutor/services/session/turns/request_preparer.py:585`）、MCP `allowed_mcp_tools`（`tool_access.py:55`）、CLI `allowed_cli_apps`（`:72`）、exec 覆盖 `exec_override`（`:89`，叠加在 `deeptutor/agents/loop/pipeline.py:707`）、技能 `assigned_skill_ids`（`skill_access.py:13`）、模型 `redacted_model_access`（`model_access.py:72`）+ `allowed_llm_options`（`:137`）+ 选择校验 `apply_allowed_llm_selection`（`:196`）。
- 边界：**grants 只存逻辑 id，运行期服务端解析**——`validate_grant` 拒绝 api_key/secret/token/path 等字段（`grants.py:316-334`）；非 admin 的 MCP/CLI 未授权即拒绝（deny-by-default，`grants.py:92-107`）；admin 不接受 grants（`_validated_grant`，`grants.py:258-267`）；跨进程写用文件锁 + 线程锁（`grants.py:47-77`）并支持带回执的条件回滚（`save_grant_with_receipt` / `restore_grant_if_unchanged`，`grants.py:292` / `:301`）；owner-bound 个人模型（如 Codex OAuth）写入用户自己的目录、绝不经 grants 借出（`personal_models.py:1-30`、`is_owner_bound` `model_access.py:59`）。

## 7. device_credentials 与 session_handoff（会话安全）

- 职责：本地学习者设备的可撤销凭证（PIN + 心跳 + 每日使用限额，`device_credentials.py:1-27`）；私网→公网的会话交接（配对码 + 短时票据，`session_handoff.py:1-7`）。
- 入口：设备侧 `/device-login`、`/device/heartbeat`、`/devices` CRUD（`auth.py:891`、`:1093`、`:1397-1456`）；底层 `issue_device_credential` / `begin_device_session` / `validate_device_token` / `revoke_device_credential`（`device_credentials.py:208` / `:272` / `:327` / `:391`）；交接三步 `/session-handoff`、`/exchange`、`/complete`（`auth.py:921` / `:999` / `:1032`），核心 `SessionHandoffStore.create/exchange/consume_ticket`（`session_handoff.py:290` / `:331` / `:403`）。
- 边界：PIN 5 次锁 15 分钟、心跳超时 5 分钟（`device_credentials.py:25-27`）、按用户级联撤销 `:408`；配对码/票据在部署侧 SQLite 只存 SHA-256 指纹（`hash_secret`，`session_handoff.py:146`），凭证明文只活在 120 秒 JWE 里（`:157`）；码 300 秒、5 次尝试、(5,60) 速率限制（`:28-32`）；`canonical_host` 拒绝含路径特征的主机头（`:68-96`），公网面仅回环可达（`is_loopback_host`，`:99`）。

## 8. 审计与路径边界（audit / paths）

- 职责：`data/system/audit/usage.jsonl` 追加式流水（`audit.py:18-22`）：`log_usage` 记普通用户访问受管资源（admin 自访问故意不记，`audit.py:35-60`）、`log_admin_action` 记管理侧写（grants/用户 CRUD，`:63`）、`log_guardian_action` 记监护链动作（`:89`）。
- 入口：写方分散在各 resolver 与路由（如 `book.py:374`、`auth.py:1525`、`multi_user.py:413`、`:437`）；读方为部署运维（文件本身）。
- 边界：审计失败绝不阻断请求（`audit.py:25-32`）；路径布局一棵树——`data/user`（admin）、`data/users/<uid>`、`data/partners/<id>`、`data/system`（账号/授权/审计/**永不挂进沙箱**，见 docker-compose.yml，`paths.py:1-14`）；per-owner 密钥目录强制 0700 且每次调用重申（`owner_secrets_dir`，`paths.py:217-235`）；owner 解析只有一个决策点 `_resolve_owner`——身份与路径同源，绝不互推（`paths.py:170-181` 注释明确"路径不能反解回身份"）；旧 `multi-user/` 树一次性幂等迁移（`paths.py:48-86`）；请求作用域切换用 `user_context`（`paths.py:264`）。

## 9. 新增访问域接入 checklist

新增一类受控资源（如未来的"课程访问"）时按序核对：

1. [ ] 新建 `deeptutor/multi_user/<domain>_access.py`，**单 resolver** 收敛全部判定，fail-closed：缺省/畸形输入一律拒绝（参照 `book_access.py:84`、`knowledge_access.py:86`）。
2. [ ] 身份只取 `context.get_current_user()`；不自行解 JWT；不得添加"取不到就当 admin"的旁路兜底（`context.py:22` 的兜底仅限 CLI/后台）。
3. [ ] 授权数据：优先并入 grants v2（`empty_grant`/`normalize_grant`/`validate_grant` 三件套，`grants.py:79` / `:161` / `:316`）；独立存储则放 `data/system/`，`atomic_write_text` + 锁（参照 `guardians.py:76-78`）。
4. [ ] 只存逻辑 id，禁止 secret/path 字段进入授权载荷（`validate_grant` 的 forbidden 集合，`grants.py:321`）；运行期在服务端解析到物理资源。
5. [ ] 角色语义遵守 `VALID_ROLES` + `normalize_role`；preset 不是角色；未知/损坏角色降级为最低权限（`models.py:19`）。
6. [ ] 路由：读走 `require_auth`、写走 `require_admin`（`auth.py:420` / `:579`）；普通用户可写操作必须有显式授权链（参照 `_require_guardian_access`，`multi_user.py:321`）。
7. [ ] 403 语义不泄露所有权/存在性细节（参照 `partner_access.py:94-101` 的同形拒绝）。
8. [ ] 物理路径一律从 `scope.root` 经 `PathService` 解析（`paths.py:140-146`），不拼接用户输入；owner-keyed 资产走 `get_owner_path_service`（`paths.py:200`）。
9. [ ] 审计：用户访问 `log_usage`、管理写 `log_admin_action`、委托链 `log_guardian_action`（`audit.py:35` / `:63` / `:89`）。
10. [ ] 授权撤销路径完备：删除用户/资源时级联清理（参照 `identity.py:378-385`、`identity.py:335`）。
11. [ ] 测试：`tests/multi_user/` 新增 `test_<domain>*.py`，至少覆盖 deny-by-default、跨用户隔离、撤销后失效、畸形输入 fail-closed。
12. [ ] 更新 `__init__.py` 支持矩阵说明与本导读。

## 10. 校验命令

```bash
# 基线与文档规模
git rev-parse --short=9 origin/main          # 期望 6cf793bd8
wc -l docs/guide-multi-user.md               # 期望 ≤300
grep -c '^- 职责：' docs/guide-multi-user.md  # 期望 8（每个子域一组三行结论）

# 锚点抽查（引文行存在性）
sed -n '16p' deeptutor/multi_user/models.py          # VALID_ROLES
sed -n '420p' deeptutor/api/routers/auth.py          # require_auth
sed -n '84p'  deeptutor/multi_user/book_access.py    # resolve_book
sed -n '203p' deeptutor/multi_user/guardians.py      # guardian_can_access

# 域测试全量（限时）
timeout 900 python -m pytest -q -p no:cacheprovider tests/multi_user/
```
