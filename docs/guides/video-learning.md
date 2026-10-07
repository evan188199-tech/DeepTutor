# DeepTutor `video_learning` 子包与 Invidious/YouTube 接入导读

- 基线：origin/main @ `f07029cfc`（v1.6.13），`tests/video_learning` 99 个用例全绿（2.77s）。
- 范围：`deeptutor/video_learning/`（7 个模块）+ 挂载它的 `deeptutor/api/routers/video_learning.py` + 消费它的 `deeptutor/capabilities/watching/`，以及 watching 前端工作区的交界处。
- 所有锚点形如 `path:line`，相对仓库根；本导读不改任何产品代码。
- 去重边界：watching 前端 UX 与操作指引见用户文档 `docs-for-user/watching-workspace.md` 及 guide-watching 卡的 `docs/guides/watching-workspace.md`（UX 轴）；路由契约面被 test-video-learning-router 卡的 `tests/video_learning/test_router_contract.py`（myfork 分支 `test/video-learning-router-contract-20261005`）钉住。本文只讲后端子包本体、账号接入与数据流，在交界处引用它们，不展开。

## 1. 这个子包是什么

`deeptutor/video_learning/` 是"沉浸式 Watching"的领域层：把一条 YouTube（或 Invidious 代理的 YouTube）链接解析成一份带字幕时间轴的 `timed_media` material，为它提供播放描述符、进度、时间戳笔记（notes）、学习标记（marks）和可选的 Invidious 账号接入。三条设计决定：

1. **永不持久化媒体字节或上游流 URL**（`deeptutor/video_learning/service.py:307-308`）——material JSON 里只存 metadata/transcript/segments/learning；播放地址每次请求时向 Invidious 现取（`deeptutor/api/routers/video_learning.py:452`），且 `save` 会剥掉任何 playback 字段（service.py:363-368）。
2. **YouTube 永远是"原生 iframe"回退**——解析产物按 `default_provider` 选择 `youtube_iframe` 或 Invidious html5 代理描述符（service.py:779-816）；Invidious 失败不会静默降级到 YouTube（provider 故障一律 `TimedMediaError` → 400，由用户显式切换）。
3. **凭据只进 owner 私密目录**——Invidious 账号 token 只存 `<owner secrets>/private/video-learning-invidious/account.json`（`deeptutor/video_learning/invidious_account_storage.py:22`），不进会话、不进日志、不进回调 URL。

## 2. 模块地图

```
deeptutor/api/routers/video_learning.py:37    router（/api/video-learning，_auth）+ settings_router（/api/settings/video-learning，_admin）
        │
        ▼
deeptutor/video_learning/service.py           核心：URL 解析、provider 解析、设置、TimedMediaStore、播放描述符
        ├── parse_youtube_url:83              任意 YouTube 形态 → YouTubeRequest(video_id, canonical, entry)
        ├── normalize_video_learning_settings:149   设置校验（provider、字幕源、origin 规则）
        ├── load/save_video_learning_settings:175/186  admin settings/video_learning.json 读写
        ├── normalize_cues:197 / parse_webvtt:256 / build_segments:229   字幕 → cues → 20–90s 学习段
        ├── TimedMediaStore:307               用户隔离的 <workspace>/timed_media/<id>.json 原子存取 + 文件锁:370
        ├── PROVIDER_RESOLVERS:581            {"youtube": _youtube_resolution:480, "invidious": _invidious_resolution:543}
        ├── resolve_material:609              链接 → material（含 provider_cache.invidious_formats）
        ├── material_with_playback:693        取 material + 懒补 Invidious 播放缓存
        ├── refresh_invidious_transcript:736  只刷新字幕不动播放状态
        └── public_material:779               出口脱敏 + 拼 playback 描述符（stream/subtitles URL）
        │
        ├── marks.py                          学习标记：learning.marks 内嵌在 material JSON
        │     create/update/delete_mark:235/245/259, normalize_mark:138, suggest_marks:339（LLM→启发式回退:296）
        ├── notes.py                          时间戳笔记：复用 NotebookManager（"Video Learning" 笔记本，RecordType.VIDEO_LEARNING）
        │     create/list/update/delete_note:144/107/188/213, export_notes:117
        ├── invidious_account.py              账号流程编排：authorize:70 → callback:169 → status:193 → disconnect:215；browse_invidious:250
        ├── invidious_account_client.py       HTTP 边界：request_preferences:21 / revoke_token:43 / request_catalog:67
        └── invidious_account_storage.py      持久化：account.json + pending/（0600 临时文件:69、一次性 rename 认领:134、state 哈希文件名:53）
```

挂在 `deeptutor/api/main.py:694-699`（settings，admin）与 `main.py:734-739`（业务，登录即可）。回调 `/api/video-learning/invidious/account/callback` 上的 401/403 被中间件改写成跳转 `/watching?account=authorization_login_required`，避免过期登录把凭据留在 URL（main.py:471-484）。

## 3. 配置面（键与存储位置逐一核对）

| 键 / 位置 | 值与约束 | 锚点 |
|---|---|---|
| `<admin 数据目录>/settings/video_learning.json` | 唯一持久配置文件；`get_settings_file("video_learning")` | service.py:171-172 → deeptutor/services/path_service.py:233-236 |
| `version` | 恒为 1 | service.py:64,164 |
| `default_provider` | `youtube`（默认）/ `invidious`；其他值 400 | service.py:64,151-153 |
| `youtube.transcript_provider` | `youtube_transcript_api`（默认）/ `none` | service.py:67,155-157 |
| `invidious.api_base_url` | 后端可达 origin；必须纯 HTTP(S)、无凭据/路径/查询/片段；公网必须 HTTPS，私网 HTTP 放行（loopback、私网、link-local、RFC6598 100.64.0/10、`localhost`/`invidious`/`host.docker.internal`/`*.local`/`*.ts.net`）；选 invidious 时必填 | service.py:105-127,130-146,161-162 |
| `invidious.public_base_url` | 浏览器侧可达 origin；同上校验；可空（空则用 api_base_url） | service.py:68,159-160,94 |
| 环境变量 `DEEPTUTOR_PUBLIC_URL` | 后端对外规范 origin，决定 OAuth 回调地址；未设则 `http://localhost:3782`；改后需重启后端 | invidious_account.py:27-30,46-67 |
| material 存储 | `<当前用户数据目录>/workspace/timed_media/<material_id>.json`（+ `.locks/`，fcntl/msvcrt 跨平台锁） | service.py:311-314,370-400 → path_service.py:243-244 |
| 账号凭据 | `<owner secrets>/private/video-learning-invidious/account.json` 与 `pending/<sha256(state)>.json`；目录 0700、临时文件 0600 原子替换 | invidious_account_storage.py:22,33-58,69-83 → deeptutor/multi_user/paths.py:217 |
| material_id | `sha256("youtube-resolve-{video_id}")[:32]`——同一视频跨用户同 id，但目录按用户隔离 | service.py:407-408（隔离测试 tests/video_learning/test_service.py:278） |
| readiness 行 | `video.youtube` / `video.invidious`（/ `video.selected`）配置体检，供设置页就绪面板 | deeptutor/services/config/readiness.py:636-692,998 |
| 前端设置 UI | `web/features/settings/sections/VideoLearningSettingsSection.tsx`（admin）+ `models/VideoSettingsSection.tsx`；API 客户端 `web/lib/video-learning-api.ts:107,394,422-445` | — |

错误面：设置不合法统一 `TimedMediaError` → 400（`_http_error`，routers/video_learning.py:107-112）；读坏/缺文件静默回落默认值（service.py:175-183）——排查"设置不生效"先看这个文件是否 JSON 损坏。

## 4. 数据流：resolve 的函数级调用链（可复现）

`POST /api/video-learning/materials/resolve`（routers/video_learning.py:212 `resolve_video`，body `{url, language?, provider_override?}`）：

1. 校验 `provider_override ∈ {None, youtube, invidious}`（routers/video_learning.py:215-216）。
2. `resolve_material(url, language, provider_override)`（service.py:609）：
   - `parse_youtube_url`（service.py:83）：scheme 必须 http(s)（:86）；host ∈ `youtu.be`（path 首段）或 `YOUTUBE_HOSTS`（`/watch?v=`、`/shorts/`、`/live/`、`/embed/`）；video_id 必须匹配 `^[A-Za-z0-9_-]{11}$`（:32,97）；`t`/`start` 参数过 `parse_timestamp:72`（纯秒或 `1h2m3s`）；规范成 `https://youtu.be/{id}?t={entry}`（:100-102）。
   - `load_video_learning_settings`（:175）读设置；`material_id_for`（:407）算 id；provider = override 或 default。
   - `PROVIDER_RESOLVERS[provider](request, language)`（:581,619）：
     - **youtube** `_youtube_resolution`（:480）：oEmbed 元数据（`_youtube_metadata:445`，8s 超时，失败返回 `{}` → 标题回退 video_id）+ `_youtube_transcript`（:417）：设置 `none` → `(,[],"disabled")`；`youtube_transcript_api` 未安装 → `dependency_missing`（requirements/video-learning.txt 是可选依赖）；线程池里 fetch（新版 `api.fetch` / 旧版 `get_transcript` 双兼容 :431-436）；语言偏好缺省 `zh-CN,zh-Hans,zh,en`（:411-414）。
     - **invidious** `_invidious_resolution`（:543）：未配置 base → `TimedMediaError("Invidious is not configured.")`（:549）；GET `/api/v1/videos/{id}`（`_invidious_metadata:490`，≥400 报 HTTP 码）；字幕选轨 `_caption_choice:460`（语言精确匹配 → 非自动生成优先）后 GET `/api/v1/captions/{id}?label=`（`_invidious_transcript:505`），WebVTT 容错解析（`parse_webvtt:256`，容忍 timing 行后的空行、剥行内标签，实体解码留给 normalize_cues 防二次解码 :286-288）；`formatStreams` 过滤 `video/mp4` 且 itag 纯数字（:556-571），没有 → `TimedMediaError("Invidious returned no compatible MP4 stream.")`。
   - 合并存储：先 `store.get` 取既有 `learning`（:625-628，缺省 `last_position=entry` :636-641）；拼 material（:642-679，`transcript.status = ready|unavailable`，reason 记 transcript_source）；**锁内重读 learning 再落盘**（:680-689，防并发 progress 丢写）。
   - `public_material(material, provider)`（:779）剥 `provider_cache`/`_caption_text_version`（:780-784），拼 playback：youtube → `{kind:"youtube_iframe", video_id, start_seconds}`；invidious → `{kind:"html5", format_id, stream_url, subtitles_url, start_seconds}`，两个 URL 都过 `workspace_url` 补 `dt_workspace` 查询参数（service.py:793-808 → deeptutor/services/workspace/context.py:53-62），subtitles 带 `revision=updated_at` 缓存击穿（:792-797）。

最小复现（不打网络）：

```python
from deeptutor.video_learning import parse_youtube_url
from deeptutor.video_learning.service import build_segments, normalize_cues
r = parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90")
# YouTubeRequest(video_id='dQw4w9WgXcQ', canonical_url='https://youtu.be/dQw4w9WgXcQ?t=90', entry_time_seconds=90)
build_segments(normalize_cues([{"start":0,"duration":25,"text":"a"},{"start":25,"duration":25,"text":"b"}]))
# [{"start":0.0,"end":50.0,"text":"a b","locator":1}] —— 20–90s 合并规则见 service.py:229-253
```

HTTP 层复现：`pytest -q tests/video_learning/test_service.py tests/video_learning/test_router.py`（resolve/进度/字幕/流各分支均有 TestClient 用例）。

## 5. 播放与字幕：流代理链

`GET/HEAD /api/video-learning/materials/{id}/stream/{format_id}`（routers/video_learning.py:518-568）：

1. Range 头只允许单段 `bytes=a-b`/`-n`（:41,529-530，否则 416）；HEAD 只回 200 + `Accept-Ranges`（:532-535）。
2. `_live_stream_url`（:452）：format_id 数字且 ≤6 位；material 的 `provider_cache.invidious_formats` 里必须有该 format_id（:461-464，描述符是 resolve 时快照——**换 Invidious 实例后旧 material 会 400，重新 resolve 即可**）；然后现取 `/api/v1/videos/{id}` 拿新鲜 stream URL（:465-485）。
3. `_allowed_stream_url`（:422-449）：上游 URL 只允许 api_base/public_base 同 origin，或 `*.googlevideo.com` 的 https 443；重定向每一跳都重新过这个闸（`_open_upstream:488-515`，最多 3 跳）。
4. 上游 200/206 透传（Content-Range/ETag 等 4 个头转发 :546-553），其余 ≥400 原样、其他 502（:537-545）；30s 超时（:39）。

字幕：`GET .../subtitles.vtt`（:396-419）从 material.transcript.cues 现拼 WebVTT，`&<>` 转义（:406）；`POST .../transcript/refresh`（:234 → service.py:736）用 `raise_on_failure=True` 重拉字幕，失败不改已存状态（:771-776，tests/video_learning/test_service.py:451）。

## 6. marks 与 notes

- **marks 存在 material JSON 里**（`learning.marks`，marks.py:120-127），写路径 = 路由锁内 `create/update/delete_mark` + `store.save`（routers/video_learning.py:336-375）。约束：kind ∈ key_point/question/review、author ∈ user/assistant、source=immersive、每视频 ≤500 条、quote ≤4000、note ≤2000、metadata ≤16 键且 ≤4000 字节（marks.py:13-20,194-203）；end≥start、按已知时长截断并越界 400（:158-164）。locator/quote 自动从时间段推导（`locators_for_range:73`、`quote_for_range:87`）。
- **suggest 不落盘**（routers/video_learning.py:378-385）：`suggest_marks`（marks.py:339）让 LLM 从当前段±60s 字幕抽 ≤5 条（`deeptutor.services.llm.complete`），解析失败或为空回退启发式（当前段 key_point + 问句 question，:296-336）；返回前剥 id/时间戳。
- **notes 复用笔记本域**：`NOTEBOOK_NAME="Video Learning"`、`RecordType.VIDEO_LEARNING`（notes.py:20 → deeptutor/services/notebook/service.py:39；notebook 路由白名单 deeptutor/api/routers/notebook.py:76）。记录按 `metadata.material_id` 过滤（notes.py:58-63），创建时校验时长上界并快照 segment 文本为 quote（:144-185）；`GET .../notes.md` 导出 Markdown 附件（routers/video_learning.py:268-281）；笔记本损坏 → 409 `notebook_unreadable`（:115-125）。

## 7. Invidious 账号接入（authorize → callback → status/disconnect → browse）

1. **authorize** `POST /invidious/account/authorize`（routers/video_learning.py:149）：必须先配 api_base_url（invidious_account.py:71-74）；生成 `state=token_urlsafe(32)`，回调 = `{DEEPTUTOR_PUBLIC_URL:-http://localhost:3782}{CALLBACK_PATH}?state=…`（:27-30,66-67；Host/X-Forwarded 头不可信，故只用该环境变量，:58-63）；跳 `{public_base or base}/authorize_token?scopes=GET:preferences,POST:tokens/unregister,GET:feed,GET:playlists,GET:playlists/*&callback_url=…`（:31-37,91-95）；写 pending flow（600s TTL :28，同实例旧 flow 作废 storage:118-131）。
2. **callback** `GET /invidious/account/callback?token&state`（routers/video_learning.py:161-176）：`consume_pending_flow` 用同文件系统 rename 做一次性认领（storage:134-151，跨 worker/重启成立）；token 解析最多剥一层 form 编码、字面 JSON 原样保留（invidious_account.py:109-125）；校验 session/signature/scopes 超集/expire（:128-145）；用 token 调 `GET /api/v1/auth/preferences` 验真（client:21-40）后才写 account.json（:169-190）。**任何失败只回稳定码**：`authorization_failure_code`（:342-360）把结果编码进 `/watching?account=<code>` 重定向，token 永不出现在 URL。
3. **status**（:193-212）：token 过期/缺字段 → `{connected:false}`；缺 scopes 或 api_base 与当前设置不一致 → `needs_reauthorization:true`（**改了实例地址后旧连接视为失效是设计行为**）。
4. **disconnect**（:215-235）：先 `POST /api/v1/auth/tokens/unregister` 撤销上游，网络失败保留本地凭据以便重试（client 抛 `InvidiousTransportError:13`；注释即理由：先删本地会留下"上游仍注册"的悬空 token）；本地过期 token 直接删不打上游。
5. **browse** `GET /invidious/browse/{kind}`（routers/video_learning.py:179-196 → invidious_account.py:250-285）：`search` 匿名（不需要账号）；`feed`/`playlists`/`playlist` 需已连接并带 Bearer；401/403 统一映射"Reconnect your Invidious account to browse your videos."（client:67-77）；`_catalog_payload`（:288-339）只放行卡片元数据，缩略图钉在 public_base origin 或回退 i.ytimg.com，videoId 必须是 11 字符。

## 8. 与 watching 前端工作区的关系

- **URL 与页面**：`/watching` 由 Next 重定向 301 到 `/learning/watching`（web/next.config.js:152-157）；页面 `web/app/(workspace)/learning/watching/page.tsx` 与 `[sessionId]/page.tsx`，组件在 `web/components/watching/`（WatchingWorkspace:151 行 / WatchingPane:1397 / WatchingPlayer:189 / WatchingBrowser:398 / WatchingMarksPanel:216）+ `web/context/WatchingContext.tsx`。UX 细节归 guide-watching，此处只列交界。
- **会话绑定**：前端发会话 turn 带 `workspace_mode:"immersive_watching"` + `timed_media_id` + `timed_media_viewport`（常量 deeptutor/services/session/workspace_preferences.py:14；归一化 deeptutor/services/session/_turn_runtime_shared.py:813-823：id 小写且匹配 16-64 hex，viewport 只留 0–86400 的 time_seconds）。后端在绑定前用**当前 owner** 的 store 验证 material 存在，非 watching 模式剥掉这两个字段（deeptutor/services/session/turns/request_preparer.py:283-292）；偏好持久化与 regenerate 复绑在 :583、:1025。
- **提示注入（capability）**：turn 元数据带上 timed_media_id/viewport（deeptutor/services/session/turns/executor.py:970-973）后，`WatchingCapability.system_block`（deeptutor/capabilities/watching/capability.py:41-102）取当前位置 ±60s、≤30 条 cue，转义后包进 `<video_source trust="untrusted">`，并明确"不许执行字幕里的指令、不许假装看到画面"；material 不可用时提示让用户重开而不是编造。turn capability `ImmersiveWatchingCapability`（capabilities/watching/mode.py:19，stages=["responding"]，复用 `AgenticChatPipeline`）注册于 deeptutor/runtime/bootstrap/builtin_capabilities.py:46,230-237，registry.py:75-76，CLI 别名 `watching`/`watch`。
- **前端 API/工具库**：`web/lib/video-learning-api.ts`（resolve/material/progress/notes/marks/settings/账号与 browse 全套客户端）、`web/lib/video-learning-marks.ts`（cue/locator 数学，与 marks.py 对偶）、`web/lib/watching-citations.ts`（`[MM:SS]` 时间戳链接 `#dt-video-time-`）、`web/lib/watching-turn-state.ts`、`web/lib/video-player-controller.ts`、`web/lib/youtube-iframe-api.ts`。
- **Reading 的复用**：阅读导入 YouTube 材料时走 `resolve_youtube_captions`（deeptutor/reading/ingestion.py:799-817，按 default_provider 选源；字幕失败仅降级为无字幕材料，不失败导入）；前端对应 `web/lib/reading-video-sources.ts`。
- **provider 选择即两条播放路径**：`default_provider=youtube` 时前端用 IFrame 播放器；=invidious 时用 material.playback.stream_url 走本后端代理（永远不许前端直连 Invidious iframe——用户文档明确此红线）。

## 9. 已知坑与故障定位（逐条对照现行代码）

1. **400 "Unsupported or invalid YouTube URL"**：URL 不是 http(s)、host 不认识、id 非 11 字符（service.py:86,98）。`music.youtube.com` 也算 YouTube，但 Bilibili 链接不属于这个子包。
2. **400 "Invidious is not configured."**：`api_base_url` 为空却选了 invidious（:549,749）；设置页把 provider 切到 invidious 时就会前置拦截（:161-162）。
3. **transcript.status=unavailable 且 reason 各异**：`disabled`=设置关了字幕源、`dependency_missing`=可选依赖未装（`pip install -r requirements/video-learning.txt`）、`unavailable`=该视频无可用轨（:421-442,540）。依赖缺失是最常见"有视频没字幕"。
4. **400 "Invidious returned no compatible MP4 stream."**：formatStreams 无 mp4 或 itag 异常（:561-571）——实例侧格式策略问题，换实例或重试。
5. **404 "Timed media material was not found."**：id 格式坏、文件缺失/损坏、或**material 属于另一个用户**（store 根按用户隔离，:317-328；tests/video_learning/test_service.py:278）。跨账号看到"视频不存在"先查当前 owner。
6. **流 400 "Stream proxy is available only for an Invidious descriptor."**：material 是 YouTube 时期存的、或换过 Invidious 实例，`provider_cache.invidious_formats` 没有该 format_id（routers/video_learning.py:461-464）。重新 resolve 重建描述符。
7. **流 400 "Invidious returned a stream outside its allowed media hosts."**：实例返回了第三方/非 https googlevideo 地址（:422-449）——通常是实例配了 companion/代理域与 api_base、public_base 都不同源；把该域配成 api_base/public_base 之一，不要放松代码。
8. **流 416**：请求了多段 Range（:529-530）；播放器应发单段 Range 或先 HEAD。
9. **字幕改动不生效**：浏览器缓存——subtitles_url 带 `revision=updated_at`（service.py:792-797），refresh 成功后 revision 变化即击穿；仍不生效查响应 `Cache-Control: no-store`（routers/video_learning.py:416）。
10. **进度回跳/丢失**：progress 落盘锁内且 clamp 到已知时长（routers/video_learning.py:242-257）；resolve 不覆盖已存 learning（service.py:680-689）。若 material metadata 无时长且客户端没传 duration，位置不 clamp——属预期。
11. **账号状态 `needs_reauthorization`**：旧 token 缺 feed/playlists scopes，或连接后改过 `api_base_url`（invidious_account.py:199-204）——重连即可，不是 bug。
12. **回调落 `?account=authorization_*`**：码含义见 `authorization_failure_code`（:342-360）；`authorization_login_required` 来自应用登录过期（main.py:474-484）。回调最终落 `/learning/watching`（301 重写）。
13. **disconnect 报错但连接还在**：上游不可达时故意保留（invidious_account.py:223-232），恢复后重试即可。
14. **feed/playlists 一直空**：先确认 `browse/search` 通（匿名可用），再查账号 scopes 与实例订阅本身；401/403 会被映射成"Reconnect..."（client:72-73）。
15. **设置页 readiness 显示 misconfigured**：`default_provider=invidious` 但 base 空（readiness.py:653-655）；改配置后无需重启后端（每次请求都读盘，service.py:175）。
16. **笔记 409 notebook_unreadable**：Notebook 存储损坏，先修笔记本域再看 video 层（routers/video_learning.py:115-125）。

## 10. 测试覆盖与可拆卡条目

`tests/video_learning/` 6 个文件 99 用例全绿（基线 f07029cfc，2.77s）：service 23（URL 解析、WebVTT、实体修复、预算、用户隔离、provider 切换、锁跨平台）、router 14（挂载权限、进度 clamp、notes/marks CRUD、VTT、Range/重定向闸）、invidious_account 27（state 一次性、跨 owner、过期、scopes、双编码 token、断连保留、browse 隔离、安全回调码）、marks 7、turn_wiring 7、capability 2。契约面另有 test-video-learning-router 卡的 `test_router_contract.py`（551 行，未合入 main）。

按测试名扫描，以下现行代码分支无直接用例（拆卡时先复核）：

| # | 位置 | 缺口 | 建议卡 |
|---|---|---|---|
| 1 | `deeptutor/video_learning/service.py:819-829` + routers:141-146 | `test_invidious_connection` 与 `POST /api/settings/video-learning/test-invidious` 全分支（未配置/HTTP 码/超时）无测试 | 补 settings 路由 test-invidious 契约 |
| 2 | `deeptutor/api/routers/video_learning.py:532-535` | stream 的 HEAD 分支无测试 | 补 HEAD 返回 200+Accept-Ranges |
| 3 | `deeptutor/api/routers/video_learning.py:500-515` | 重定向超 3 跳 → "too many redirects" 无测试 | 补 4 跳用例 |
| 4 | `deeptutor/video_learning/marks.py:268-278` | `_parse_json_array` 剥 ```json 围栏分支无直接断言（现测只走启发式回退） | 补围栏 JSON 解析 |
| 5 | `deeptutor/video_learning/service.py:111-113` | `_validate_origin` 坏端口（`ValueError`）分支无测试 | 补 `:port` 非法 400 |
| 6 | `deeptutor/api/routers/video_learning.py:226-231` | `GET /materials/{id}`（`material_with_playback` 的懒刷新成功路径，service.py:696-732）无路由级/服务级直接用例（服务层只测了 youtube 遗留描述符丢弃，tests/video_learning/test_service.py:243） | 补 invidious 懒刷新成功与失败路径 |

复测命令（限时）：
`timeout 900 python -m pytest -q -p no:cacheprovider tests/video_learning`（本机用 `/Users/Shared/DeepTutor/.venv/bin/python`）。

## 11. 快用参考

```bash
# 解析一条链接（登录态）
curl -X POST "$BASE/api/video-learning/materials/resolve" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEOID?t=90","provider_override":null}'
# 取播放描述符 → stream_url / subtitles_url 都在里面
curl "$BASE/api/video-learning/materials/$MID" -H "Authorization: Bearer $TOKEN"
# 保存进度 / 刷字幕 / 导笔记
curl -X PUT "$BASE/api/video-learning/materials/$MID/progress" -d '{"time_seconds":120,"duration_seconds":600}'
curl -X POST "$BASE/api/video-learning/materials/$MID/transcript/refresh"
curl "$BASE/api/video-learning/materials/$MID/notes.md" -o notes.md
```

排查顺序建议：设置（§3）→ resolve（§4）→ 播放/字幕（§5）→ 账号（§7）→ 会话绑定（§8）。90% 的"视频坏了"落在：可选依赖缺失、Invidious 实例格式策略、换实例后的陈旧 provider_cache、以及跨用户的 404。
