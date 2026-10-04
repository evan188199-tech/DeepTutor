# LTI 1.3 接入可行性复核备忘（对应上游 issue #567）

- 复核基线：HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13）
- 复核日期：2026-10-04
- 性质：只读评审，不改代码、不引入依赖
- 输入：issue #567（sebPhilippot，pylti1p3next 维护者，征求 LTI 1.3 贡献意向）；pylti1p3next 2.0.2（PyPI）

## 结论摘要

1. **建议：欢迎该贡献（有条件接受）**。上游维护者已在 #567 表态欢迎（要求作为多用户部署的可选项、复用现有数据结构与配置逻辑、并附 AGENTS.md），后端挂点齐全，贡献者是目标库的维护者，长期维护动机强。
2. **依赖评估**：pylti1p3next 2.0.2 为 pylti1p3 的社区 fork（MIT，Python>=3.10，与本项目 requires-python `>=3.11,<3.15` 兼容），目前只有 Django/Flask adapter，**FastAPI adapter 尚不存在**（贡献者计划新增 contrib 模块）。适配成本中等，主要工作在其 cookie/session/launch-cache 体系与本项目的对接，而不是路由本身。
3. 建议以**可选 extra** 形式落地（`lti` extra + `requirements/lti.txt`），核心依赖不变；不改动现有 auth 代码路径。

## 一、后端挂点清单

以下 path:line 均基于基线 commit 实测核对。

### 1. 路由挂点

| 挂点 | 位置 | 说明 |
|---|---|---|
| FastAPI app 实例 | `deeptutor/api/main.py:404-413` | LTI 路由组挂载点；注意 `redirect_slashes=False`，LMS POST 的精确路径不可依赖 307 补斜杠 |
| 公共路由组先例 | `deeptutor/api/main.py:575` | `auth.router` 以 `prefix="/api/auth"` 免token挂载；LTI 的 OIDC login init 与 launch 是 LMS 发起的请求，不带本系统凭证，应仿此作为第二个公共路由组（建议 `/api/lti/*`），其余路由的 `require_learning_surface` 门禁（`main.py:589-595`）不适用 |
| 路由模块组织先例 | `deeptutor/api/routers/auth.py:97` | `router = APIRouter()`；新增 `deeptutor/api/routers/lti.py` 同构 |
| 需要新增的端点 | （新） | ① `GET/POST /api/lti/login`（OIDC third-party initiated login，验 `iss`/`login_hint`/`target_link_uri` 后 302 回平台）；② `POST /api/lti/launch`（接收平台 POST 的 `id_token`，验签后建立会话）；③ `GET /api/lti/jwks`（暴露工具公钥，供平台验工具侧签名，deep linking 阶段才需要） |
| 启动失败重定向先例 | `deeptutor/api/main.py:471-494` | `selective_access_log` 中 video-learning OAuth callback 的 401/403 → 303 重定向特例；LTI launch 失败应重定向回 LMS/错误页而非裸 401 JSON，可复用该位置或独立异常处理 |
| 可选集成启动钩子 | `deeptutor/api/main.py:104-342` | `lifespan`：LTI 的 JWKS 缓存、HTTP client 等资源初始化可在此；若未配置 LTI 则整组路由不注册或返回 404 |

### 2. 身份映射挂点

| 挂点 | 位置 | 说明 |
|---|---|---|
| 用户存储 | `deeptutor/multi_user/identity.py:37-38` | JSON 文件 `users.json`，键为 username（`AUTH_DIR/system/auth`）；LTI JIT provision 的写入落点 |
| 用户 id 生成 | `deeptutor/multi_user/identity.py:44-45` | `u_<uuid hex>`，LTI 建户沿用即可 |
| username 校验 | `deeptutor/api/routers/auth.py:217-231` | 已接受 email 或普通用户名 —— LTI `sub`/email 映射可直接复用；建议映射键为 `lti:<iss>#<sub>` 形式或 email，需在验收标准里固定，避免与本地同名账户冲突 |
| 自助注册是 bootstrap-only | `deeptutor/api/routers/auth.py:1146-1170` | `/register` 仅允许创建第一个用户，之后关闭 —— **LTI JIT 建户必须走新的内部路径**（仅 launch 流程内调用），不得开放公共注册 |
| 角色模型 | `deeptutor/multi_user/models.py:9-16` | `admin/teacher/student/user`，只有 `admin` 提权 —— LTI 角色映射建议：Instructor/TA → `teacher`，Learner → `student`；**任何 launch 都不得产生 admin** |
| learner 账户形态 | `deeptutor/multi_user/models.py:10` + `deeptutor/api/routers/auth.py:689-705` | `AccountPreset="learner"` + `require_learning_surface` 二级默认拒绝门禁 —— LTI 学生角色的权限边界可直接复用该形态，无需新的授权机制 |
| 外部 IdP 并存先例 | `deeptutor/services/auth.py:49-53` | PocketBase 模式开关 —— LTI  provisioning 必须显式处理 `AUTH_ENABLED` 三态（关闭/标准 JWT/PocketBase）：auth 关闭时 LTI 路由应整体禁用（否则产生"绕过单用户模式"的口子） |

### 3. 会话建立挂点

| 挂点 | 位置 | 说明 |
|---|---|---|
| token 签发 | `deeptutor/services/auth.py:260-283` | `create_token`：HS256，claims `sub/role/uid/exp/iat` —— launch 验证通过后直接复用签发，会话与现有登录完全同构 |
| 会话 cookie | `deeptutor/api/routers/auth.py:814-861`（设置于 :852）+ `:129-144` | `dt_token` HttpOnly cookie，`samesite`/`secure` 由 `cookie_secure` 配置驱动（:129-144 `_cookie_attrs`）—— **LTI launch 发生在 LMS iframe 内，要求 `SameSite=None; Secure`，即部署前提为 `cookie_secure=true` + HTTPS**；或采用 302 到顶层窗口的方式绕开三方 cookie |
| 顶层窗口回退先例 | `deeptutor/api/main.py:476-484` | video-learning callback 的 303 顶层重定向 —— iframe cookie 被拒时回退顶层窗口的现成模式 |
| 一次性会话交接 | `deeptutor/multi_user/session_handoff.py`（JWE 票据）+ `web/app/handoff/page.tsx` | 现成的"票据换会话"桥，可作为 iframe→顶层窗口会话传递的备选实现 |
| 凭证双通道 | `deeptutor/api/routers/auth.py:389-390` | `require_auth` 已同时接受 Bearer header 与 dt_token cookie，无需改动 |
| 前端落地 | `web/proxy.ts:35-52` + `web/app/(auth)/login/page.tsx:42-58` | `next` 参数保全目标路径 —— launch 成功后 302 到前端目标页即可进入现有 SPA；`web/lib/auth.ts:49-72` 的 `/api/auth/status` 轮询驱动全局 401 门禁，LTI 会话天然兼容 |

### 4. 配置挂点

| 挂点 | 位置 | 说明 |
|---|---|---|
| runtime settings 模式 | `deeptutor/services/config/runtime_settings.py:81-89`（`DEFAULT_AUTH_SETTINGS`）、`:91-107`（`DEFAULT_INTEGRATIONS_SETTINGS`）、`:1471/:1475`（`load_auth_settings`/`load_integrations_settings`）、`:883-899`（env 覆盖）、`:1311-1320`（normalize） | 新增 `lti.json`（平台注册表：iss、client_id、auth_login_url、key_set_url、deployment_ids、工具公私钥引用）完全套用该模式 —— 维护者在 #567 明确要求"复用现有配置逻辑"，即指此处 |
| 密钥存储先例 | `deeptutor/multi_user/paths.py:217-251` + `deeptutor/services/codex_auth/storage.py` | owner-scoped `data/system/user-secrets` —— LTI 工具私钥（用于签名发往平台的请求）应比照存储，不入 `lti.json` 明文 |
| JWKS 验证先例 | `deeptutor/partners/channels/msteams.py:483-523`（kid 查找 + RS256 验签 + aud/iss 校验）、`:525-560`（openid config + JWKS 拉取缓存） | 仓内已有完整的"验外部平台签名"工程实现，无论是否引库，这是评审 LTI 验签实现的对照基准 |

### 5. 依赖挂点

| 挂点 | 位置 | 说明 |
|---|---|---|
| Python 版本 | `pyproject.toml:16` | `>=3.11,<3.15`；pylti1p3next 要求 `>=3.10`，兼容 |
| JWT 能力现状 | `pyproject.toml:83`（核心 `python-jose[cryptography]`）、`:201`（partners extra 的 `PyJWT[crypto]`） | RS256/JWK 验签能力核心依赖已具备；引库会带来第二套 JWT 实现（PyJWT），有 partners extra 先例、可接受，但应只进 extra |
| 可选 extra 模式 | `pyproject.toml:106-297`（`server` :160-174、`partners` :201 等）+ `requirements/` 镜像文件 | LTI 依赖应落为 `lti` extra + `requirements/lti.txt`，核心 `server.txt` 不动 |

## 二、pylti1p3next 依赖评估

**基本情况**（PyPI，2026-06-02 发布 2.0.2）：pylti1p3（Dmitry Viskov）的社区 fork，MIT，Python>=3.10，4 名维护者中包含 issue #567 作者 sebPhilippot 本人。覆盖 LTI 1.3 核心域：OIDC login、message launch 验证、deep linking、AGS/NRPS/CGS 服务、角色检查、iframe cookie 兼容（`enable_check_cookies`）。

**适配成本：中等。**

1. **必须新写 FastAPI adapter**（库无此 adapter，Django/Flask 实现可作参照）：`Request` adapter、`CookieService`、`SessionService`、`DataStorage` 四个接口；库文档明示这是官方支持的扩展方式。工作量约数百行 + 测试。
2. **session/launch-cache 体系不同构**：库自带 launch 状态缓存（默认框架 session 或 memcache/redis），DeepTutor 会话是无状态 JWT、无服务端 session 存储 —— 需要为其实现一个基于本地存储（或复用现有 runtime 数据目录）的 `DataStorage`，这是最主要的适配面，也是评审时最该盯的实现点。
3. **state/nonce 防重放依赖其 cookie 体系**：iframe 内需要 `SameSite=None; Secure`，其 `enable_check_cookies` 兼容页需要能渲染自托管前端页面 —— 部署前提（HTTPS + `cookie_secure`）必须写进文档。
4. **双 JWT 库并存**：库用 PyJWT，项目核心用 python-jose —— 限定在 extra 内不影响核心，但验收时应检查不把 PyJWT 引入核心 import 链。
5. **fork 选型理由成立但要写明**：上游 pylti1p3 仍在维护；选 fork 的理由是贡献者本人维护 fork 且 FastAPI contrib 只计划进 fork。属于"单一公司/个人主导"型依赖，锁版本 + 订阅其 release 是必要的。

**替代路线（不引依赖）**：参照 `msteams.py:483-560` 用 python-jose 自实现 OIDC login + id_token 验证（核心流程约 300-500 行 + 测试）。核心 launch 验证规范明确，可行；但 deep linking、AGS/NRPS、浏览器 cookie 兼容等外围自己实现工作量大、易踩规范细节。**结论：launch 验证自实现可行但性价比不高，推荐接受 pylti1p3next 并限定在 optional extra。**

## 三、分期建议

- **Phase 0（先决条件，文档级）**：明确部署前提 —— HTTPS、`cookie_secure=true`、反向代理下 `_require_private_frontend`（`deeptutor/api/routers/auth.py:821`）与 `private_login_hosts` 对 LMI 平台回调域名的放行策略；产出 LMS 侧配置指引（Canvas/Moodle 注册步骤）。
- **Phase 1（最小可用 SSO）**：`lti.json` 配置 + `/api/lti/login` + `/api/lti/launch` + JIT 建户（learner 形态，teacher/student 两级）+ 会话建立（iframe 内 SameSite=None cookie，失败回退顶层窗口/handoff）。验收：Canvas 或 Moodle 真机一次成功 launch + 一次失败 launch（错误签名/未注册 deployment）被拒。
- **Phase 2（deep linking）**：工具侧 JWKS 端点 + 把 DeepTutor 知识库/会话以 LTI 资源形态嵌回 LMS 课程。
- **Phase 3（可选，远期）**：AGS 成绩回写与 NRPS 名册同步，与 learning 模块（`deeptutor/learning`）整合。此项涉及成绩数据，建议单独立项评审。

## 四、是否欢迎该贡献：建议与验收标准草案

**建议：欢迎，有条件接受。** 上游维护者已在 #567 给出方向性认可（多用户部署的可选项、复用现有数据结构与配置逻辑、附 AGENTS.md），本仓的 config-gated 可选集成模式（PocketBase/partners/codex_auth 三处先例）说明这类贡献与现有架构同构，风险可控。

**验收标准草案：**

1. **依赖边界**：新依赖只出现在 `pyproject.toml` 的 `[project.optional-dependencies]`（新 `lti` extra）与 `requirements/lti.txt`；核心依赖与 `requirements/server.txt` 无变化；锁定版本下限。
2. **默认关闭等价性**：未启用 auth 或未配置任何 LTI 平台时，`/api/lti/*` 全部 404/禁用，系统行为与现状逐字节等价；现有全部测试保持绿色。
3. **launch 验证完整性**：state/nonce 校验、`iss`/`client_id`/`deployment_id` 白名单、id_token RS256 验签（kid + JWKS）、`iat`/`exp` 容差，缺一不可；拒绝路径（无效 state、坏签名、未注册 deployment、过期 token）有单测覆盖。
4. **身份映射安全边界**：JIT 建户只能产生 `teacher`/`student`（ learner preset 形态），任何 launch 不得产生或提权为 `admin`；建户路径不可从公共 `/register` 触达；与本地同名账户的冲突策略明确（拒绝并提示，而非静默合并）。
5. **会话同构**：launch 后签发的会话与现有 `create_token`/`dt_token` cookie 完全同构；iframe 场景提供顶层窗口回退；不新增独立的会话体系。
6. **配置复用**：平台注册走 `runtime_settings` 模式（新增 `lti.json` + `load_lti_settings` + env 覆盖 + normalize），工具私钥入 owner-scoped secrets 存储，不进明文配置。
7. **测试落位**：路由/流程测试进 `tests/api/`（与 `test_codex_oauth_callback.py` 同层），验证与 provisioning 单测进 `tests/services/lti/`（或 `tests/multi_user/`）；`tests/api/test_canonical_route_surface.py` 需同步更新。
8. **文档**：按维护者要求附 AGENTS.md，说明挂点、配置、部署前提与维护要点；新端点纳入现有 API 文档。
9. **不改现有 auth 行为**：`deeptutor/api/routers/auth.py`、`deeptutor/services/auth.py` 的现有路径零修改（或仅以纯新增方式扩展），diff 可独立 review。

## 附：上游 issue 状态

- #567 状态：OPEN，无关联 PR（截至 2026-10-04 检索，无 LTI 相关开放 PR）
- 维护者 pancacake 三次回复：欢迎 + 定位为多用户可选 + 要求附 AGENTS.md + 提示等 1.4.x 架构稳定后动手（现已表示可以尝试）
- 贡献者已表示接手，尚未提交代码 —— 本备忘可作为 review 其未来 PR 的验收基准
