# LOCAL_FEATURES.md 能力 → 代码映射导读

为 LOCAL_FEATURES.md 声明的每个本地能力给出模块/路由/设置键入口（path:line），标注文档与实现的对应关系，供后续补测卡与修复卡直接定位。

## 基线与文档位置

| 对象 | 位置 | 说明 |
| --- | --- | --- |
| 代码基线（origin/main） | `6cf793bd8` (release: v1.6.14) | 新 worktree 只读核验，行号以此为准 |
| LOCAL_FEATURES.md | `myfork/main` @ `b4dcad917` 根目录 | fork-local 文档；**origin/main 无此文件**（从未加入上游） |
| READING_EXTENSIONS.md | origin/main `docs-for-user/READING_EXTENSIONS.md` | 根目录旧版在 `da856ad67` (v1.6.9) 删除并迁入 docs-for-user/ |
| 本地集成分支（运行态） | `/Users/Shared/DeepTutor` 本地 `main` @ `2a4c4c5f1`（只读参考） | 与 myfork/main 不同线；行号单独注明 |

fork 侧行号除注明外均以 `myfork/main` @ `b4dcad917` 为基线。

## 能力 × 模块 × path:line 映射

### A1. 注册开关 `AUTH_ALLOW_REGISTRATION` + 持久化 `auth.allow_registration`（active，fork-only）

| 项 | 位置 | 说明 |
| --- | --- | --- |
| 设置默认键 | `deeptutor/services/config/runtime_settings.py:88`（myfork） | `"allow_registration": False` |
| 环境变量同步 | `deeptutor/services/config/runtime_settings.py:700`（myfork） | `AUTH_ALLOW_REGISTRATION ↔ auth.allow_registration` |
| 进程内覆盖/读回 | `deeptutor/services/config/runtime_settings.py:852-853,1242`（myfork） | env 覆盖与 bool 归一 |
| 开关常量 | `deeptutor/services/auth.py:48`（myfork） | `AUTH_ALLOW_REGISTRATION` 读自持久化设置 |
| 注册门禁 | `deeptutor/api/routers/auth.py:49,809`（myfork） | 非 first-user 且开关关 → 拒绝 |
| 状态暴露 | `deeptutor/api/routers/auth.py:847`（myfork） | `registration_open` 字段 |
| origin/main 对照 | 无对应键；注册为 bootstrap-only：`deeptutor/api/routers/auth.py:1136-1157`（origin） | 能力为 fork-local |
| 回归测试 | `tests/test_local_feature_contract.py:85`（myfork） | `test_registration_setting_survives_default_save_and_process_override` |

### A2. Partner Feishu/Lark + WeCom 二维码通道 onboarding（active，origin/main 已有实现）

| 项 | 位置（origin/main） | 说明 |
| --- | --- | --- |
| onboarding 服务 | `deeptutor/services/partners/channel_onboarding.py:1,140` | 短时效二维码会话（`ChannelOnboardingManager`） |
| 会话状态/脱敏响应 | `channel_onboarding.py:94,112` | `public_dict` 只回二维码/状态/过期时间，凭证不外泄 |
| 显式 apply | `channel_onboarding.py:200`；`apply` 中脱敏 `:206,270`（`mask_channel_secrets`） | 凭证落盘前打码 |
| 过期清理 | `channel_onboarding.py:308`（`_purge_expired_locked`） | 短时效保证 |
| Feishu / WeCom 分支 | `channel_onboarding.py:336,383`（`_start_feishu` / `_start_wecom`） | 通道名 `Literal["feishu","wecom"]` 见 `deeptutor/api/routers/partners.py:335` |
| 路由（管理员/manageable） | `deeptutor/api/routers/partners.py:1185` start、`:1200` status、`:1215` cancel、`:1224` apply | 前缀 `/api/partners`（`deeptutor/api/main.py:763`） |
| 通道 schema | `deeptutor/api/routers/partners.py:670-673`（`GET /channels/schema`） | |
| 回归测试 | `tests/services/partners/test_channel_onboarding.py`、`tests/api/test_partners_router.py`、`tests/services/partners/test_feishu_domain_initialization.py`（origin/myfork 均有） | |

### A3. Tailscale → Quick Tunnel 会话交接（active，fork-only）

| 项 | 位置 | 说明 |
| --- | --- | --- |
| 状态机单文件 | `deeptutor/services/tunnel_handoff.py:42`（myfork） | `SessionHandoff`；一次性凭证 `create_ticket :202`、配对 `create_pairing :231`、兑换 `exchange_pairing :274`、消费 `consume_ticket :279`；隧道状态 `load_tunnel_state :172` |
| TTL 常量 | `tunnel_handoff.py:17-18`（myfork） | `TICKET_TTL_SECONDS=180`、`PAIRING_TTL_SECONDS=300`（**文档写 120s/60s，见漂移 D1**） |
| 交接路由 | `deeptutor/api/routers/auth.py:851`（POST /handoff）、`:876`（/handoff/pairing）、`:897`（GET /handoff/pairing/{id}）、`:919`（/handoff/consume）（myfork） | |
| 私网 Host 白名单 | `auth.py:315`（`_is_private_login_host`，读 `private_login_hosts` `:330`）、守卫 `:336`，应用于 `/login :623`、`/register :782`（myfork） | 隐式含 localhost/127.0.0.1/::1 |
| 隧道轮换脚本 | `scripts/rotate_deeptutor_tunnel.sh:9,18,23`（myfork） | 写 `data/system/auth/deeptutor_tunnel.json`、kickstart cloudflared、捕获 trycloudflare URL；launchd 定时为宿主机配置（`com.deeptutor.rotate-tunnel.plist`，不入库） |
| Mac 已登录展示页 | `web/app/(auth)/access/page.tsx:6,98`（myfork） | `qrcode.react` 动态二维码 |
| 手机扫码落地页 | `web/app/(auth)/access/device/page.tsx`（myfork） | 免认证白名单见下条 |
| 代理豁免/Host 优先转发 | `web/lib/proxy-policy.ts:105-109`（`isAuthExempt` 含 `/access/device`）、`:38`（`frontendForwardingHost`）；`web/proxy.ts:55-59`（myfork） | |
| 后端只信任本机代理头 | `deeptutor_cli/main.py:214`（`proxy_headers=False`，myfork）；本地集成分支另有 `Dockerfile:293,524`（`--no-proxy-headers`） | **文档提到的 `run_server.py`、`launcher.py` 启动点在两个基线均不存在该文件（漂移 D2）** |
| 契约测试 | `tests/api/test_auth_tunnel_handoff.py`、`tests/test_local_feature_contract.py:17-33`（myfork） | |
| upstream 对照 | origin/main `352897cd4` (#1467) 另有独立实现：`deeptutor/multi_user/session_handoff.py:182,290,403`、`deeptutor/api/routers/auth.py:921,998,1032`（/session-handoff*）、`web/app/handoff/page.tsx`、`web/app/(utility)/session-handoff/page.tsx` | **不同实现体系**（`session_handoff` ≠ `tunnel_handoff`），fork 侧未迁移 |

### A4. YouTube 沉浸 Watching（Invidious 后端）（active，主体在 origin/main，增强在 fork）

origin/main（`6cf793bd8`）：

| 项 | 位置 | 说明 |
| --- | --- | --- |
| Provider 设置键 | `deeptutor/video_learning/service.py:26`（`youtube|invidious`）、`:68`（invidious `api_base_url`/`public_base_url`）、`:149`（normalize）、`:152-158`（校验） | 管理员配置入口 `POST /api/settings/video-learning`（`deeptutor/api/main.py:703`，admin） |
| 字幕 cue / timed_media 段 | `service.py:197`（normalize_cues）、`:229`（build_segments，`locator/start/end/text` `:251-252`）、`:307`（TimedMediaStore） | 存储 `workspace_feature_dir("timed_media")` `:312` |
| Invidious 解析链 | `service.py:494`（metadata）、`:509`（transcript）、`:547`（resolution）、`:594`（resolve_youtube_captions）、`:613`（resolve_material） | no-download 阶段 |
| 路由 | `deeptutor/api/routers/video_learning.py:212`（materials/resolve）、`:226`（get）、`:234`（transcript/refresh）、`:396`（subtitles.vtt） | 前缀 `/api/video-learning`（`deeptutor/api/main.py:744`） |
| HTTP Range 流式播放 | `video_learning.py:518`（stream/{format_id}）、Range 校验与上游转发 `:528-536` | 只存服务端短时效描述符 |
| Invidious 账号绑定 | `video_learning.py:149-204`（authorize/callback/browse/status/disconnect）；`deeptutor/video_learning/invidious_account*.py` | 用户级账号 |
| 范围标记（私有点记） | `deeptutor/video_learning/marks.py:73`（locators_for_range）、`:87`（quote_for_range）、`:138`（normalize_mark）、`:235/245/259`（增改删）、`:296`（启发式建议，仅按需） | 路由 `video_learning.py:318-378`（marks + mark-suggestions） |
| 学习笔记 | `deeptutor/video_learning/notes.py`；路由 `video_learning.py:260-317` | |
| Web 页面 | `web/app/(workspace)/learning/watching/page.tsx`、`web/app/(workspace)/learning/watching/[sessionId]/page.tsx` | |

fork 增强（myfork/main，origin/main 无）：

| 项 | 位置 | 说明 |
| --- | --- | --- |
| youtube-transcript-api 适配器 | `deeptutor/video_learning/service.py:417,435`（myfork） | opt-in 回退 |
| transcript_provider 设置键 | `service.py:67,155-156`（myfork）；请求字段 `deeptutor/api/routers/video_learning.py:103`（myfork） | `youtube_transcript_api|none` |
| host-Chrome 字幕预取 | `deeptutor/video_learning/subtitle_prefetch.py:1,94,132`（myfork） | 单飞、需 owner 授权 |
| Chrome 会话授权（owner consent） | `deeptutor/video_learning/youtube_session.py:1,16`（myfork）；状态/连接/断开路由 `deeptutor/api/routers/video_learning.py:261,276,294`（myfork） | 不存 Cookie/配置文件 |
| yt-dlp cookiesfrombrowser | `service.py:441-500`（myfork，`:453,475,478`） | 显式 opt-in |
| 契约测试 | `tests/video_learning/test_service.py`（origin/myfork 均有）等 | |

契约缺口（文档第 4 步）：audio-only ASR 预处理（只取音频、32 MB 上限、STT 转写、只落 transcript）在 origin/main、myfork/main、本地集成分支均**无代码实现**（漂移 D3）。Bilibili 文档明示 TODO，无代码（与文档一致）。

### A5. 外部渲染器 + 手机遥控（active，fork-only）

| 项 | 位置（myfork/main） | 说明 |
| --- | --- | --- |
| 存储层 | `deeptutor/video_learning/remote.py:144`（`RemoteControlStore`）、bootstrap `:223,267`（一次性设备凭证）、token 校验 `:332`、吊销 `:362`、控制器凭证 `:513,528`、命令队列 `:545` | |
| 路由 | `deeptutor/api/routers/video_remote_control.py:237`（POST /renderers）、`:293`（/renderers/bootstrap）、`:317`（GET /devices）、`:334`（DELETE 设备）、`:341`（POST 命令）、`:355`（GET 命令）、`:365`（player/presence）、`:377`（ack） | 前缀 `/api/video-learning`（myfork `deeptutor/api/main.py:697`） |
| 轮换控制器 Cookie | `video_remote_control.py:450`（issue_controller 签发）、`:479,503`（`dt_video_controller`） | |
| 换片重绑 | `video_remote_control.py:151`（`_ensure_material`，按 video_id 建新 timed material）、`:217`（会话绑定校验） | 不改旧 material 上的标记 |
| 回归测试 | `tests/video_learning/test_renderer_remote.py`（myfork） | |

### U1. MarginNote 4 连接知识库（upstream-v1.5.16，origin/main 已有实现）

| 项 | 位置（origin/main） | 说明 |
| --- | --- | --- |
| KB 类型 | `deeptutor/knowledge/kb_types.py:95`（`MARGINNOTE4_KB_TYPE`）、`:123`（`NON_RETRIEVABLE_KB_TYPES`，排除出通用 RAG 检索——对应 forbidden-regression 第 1 条） | |
| 注册入口 | `deeptutor/knowledge/manager.py:1042`（`register_marginnote4_kb`） | pointer KB |
| 路由（配对/心跳/同步/吊销） | `deeptutor/api/routers/marginnote4.py:149`（pair）、`:177`（devices）、`:194`（吊销）、`:203`（status）、`:217`（sync）、`:267`（heartbeat）；挂载 `/api/marginnote4`（`deeptutor/api/main.py:786`，sync/heartbeat 走设备 token，见 `main.py:784` 注释） | |
| 七个只读工具 | `deeptutor/capabilities/marginnote4/tools.py:103`（marginnote_search）、`:149`（read）、`:180`（list）、`:222`（documents）、`:241`（links）、`:270`（tags）、`:296`（cards） | 注册表 `deeptutor/tools/builtin_specs.py:154-162` |
| store/binding | `deeptutor/capabilities/marginnote4/store.py`、`binding.py`、`capability.py` | |
| 回归测试 | `tests/api/test_marginnote4_router.py`、`tests/capabilities/marginnote4/`、`tests/knowledge/test_marginnote4_kb.py`（origin/myfork 均有） | |
| MN4 add-on 工件 | 不在仓库（文档明示，真实设备联调阻塞点） | |

### READING_EXTENSIONS.md → 代码（origin/main）

| 项 | 位置 | 说明 |
| --- | --- | --- |
| 入口点组 | `pyproject.toml:100-105`（`deeptutor.reading_extensions`：read_aloud/guided_learning/vocabulary/quiz/translation）、`deeptutor/reading/extensions.py:22`（ENTRY_POINT_GROUP） | |
| 路由 | `deeptutor/api/routers/reading_extensions.py:141`（GET /extensions）、`:151`（read-aloud）、`:195`（action 执行）、`:363`（quiz 答案）、`:484`（quiz rewards） | 挂载 `/api/reading`（`deeptutor/api/main.py:648`） |
| 协议/边界实现 | `deeptutor/reading/extensions.py`（manifest/result 校验） | 文档所述 64 KB/60k 字符/30s 超时等约束对应此模块 |
| 测试 | `tests/reading/test_extensions.py`、`web/tests/reading-extensions.test.ts`（origin/myfork 均有） | |

### R（removed）/ P（parked）/ F（forbidden-regression）核对

| 项 | 核对结果 |
| --- | --- |
| Kids 产品面移除（/api/v1/kids、kids-admin、reward providers、dual-track sync） | origin/main 全无（`git ls-tree`/路由均无）；myfork/main 仅保留历史数据迁移模块 `deeptutor/multi_user/legacy_kids_learner_migration.py` + `tests/multi_user/test_legacy_kids_learner_migration.py`，无路由面；契约测试 `tests/test_local_feature_contract.py:35`（myfork）断言其不复出现 |
| parked（MN4 写回、Chrome/MarginNote realtime probe） | 无产品代码（符合文档） |
| forbidden-regression（MN4 走通用 RAG；视频下载器/ASR 入核心依赖） | 前者由 `kb_types.py:123` 结构性保证；后者与 A4 一致（下载/ASR 不在默认路径） |

## 文档 ↔ 代码漂移备忘（本卡仅记录；引用失效漂移归 scan-docs-drift 卡）

- D1：A3 节 TTL 文档写配对 120s / 凭证 60s，代码两基线均为 300s / 180s（`tunnel_handoff.py:17-18`）。
- D2：维护手册提到的启动点 `run_server.py`、`launcher.py` 在 origin/main 与 myfork/main 均不存在；现存启动点为 `deeptutor_cli/main.py:214` 与 Dockerfile。
- D3：视频契约第 4 步 audio-only ASR 预处理（32 MB/STT）无任何实现。
- D4：密码入口 `/activate-learning` 在 myfork/main 与本地集成分支均无对应路由（私网守卫仅覆盖 `/login`、`/register`）。
- D5：`myfork/main` 契约测试固定 `__version__ == "1.6.8"`（`tests/test_local_feature_contract.py:32`），落后于 origin/main v1.6.14——fork 基线待跟进上游。
- D6：`LOCAL_FEATURES.md` "上游 v1.5.16 网关测试集"等表述随版本推进需人工复核；A2/A4/U1 主体已在 origin/main 落地，fork 维护成本集中在 A1/A3/A5。

## 能力覆盖清单（验收 1）

active 5/5（A1–A5）+ upstream-v1.5.16（U1，含配对/同步/七工具/RAG 排除）+ READING_EXTENSIONS（入口点/路由/边界）+ removed/parked/forbidden-regression 核对 —— 全覆盖。

## 复核命令

```bash
git -C /Users/Shared/DeepTutor worktree list   # 本卡 worktree: dt-agen1962-locguide-wt @ guide/local-features-map-20261013
git -C /Users/Shared/dt-agen1962-locguide-wt rev-parse HEAD   # 应为 6cf793bd8…
```
