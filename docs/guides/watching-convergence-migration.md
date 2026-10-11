# Watching 收敛与数据迁移导读

面向"补测/修复"场景：解释 `immersive_watching` 并入 Immersive Reading 的现状、
新旧数据结构、迁移触发链路与回退边界。上游决策见 HKUDS/DeepTutor#1378（A→C→B→D 计划），
provider 层（#1379）与媒体舞台（#1380）已合入 main；独立 Watching 能力面已退役
（`deeptutor/capabilities/` 下已无 `watching/` 目录，注册表亦无条目，
回归断言在 `tests/video_learning/test_turn_wiring.py:219`）。
本卡只覆盖**收敛与迁移链路**；Watching 总导读与视频学习导读写另卡。

基线：origin/main `6cf793bd8`（v1.6.14）。所有行号以该基线为准。

## 1. 模块地图

```
旧（保留为 provider 缓存/兼容层）          新（Reading 媒体面）
deeptutor/video_learning/                 deeptutor/reading/
  service.py   TimedMediaStore            ingestion.py   队列+YouTube/B站摄取
  notes.py     "Video Learning" 笔记本     catalog_store.py SQLite 物料目录
  marks.py     时间戳标记（learning.marks） models.py      locator/Annotation 模型
  invidious_*  Invidious 账号/解析          store.py       SQLite 位置/批注存储
                    \                     capabilities/reading/
                     \--> reading_migration.py <---/  capability.py + media_notes.py
                          （只读投影，唯一桥）
web: workspace-mode.ts / ChatWorkspace.tsx 重定向；MediaReadingStage + 播放器；
     AddMaterialsDialog 复用 WatchingBrowser 作为 Invidious 入口
```

关键判断：**TimedMedia 不删**。`reading_migration.py:1-6` 明确"TimedMedia remains
the provider cache for old records"，投影从不改写旧 JSON 或 Notebook。

## 2. 新旧数据结构对照

| 维度 | 旧 Watching（TimedMedia） | 新 Reading（media material） |
|---|---|---|
| 存储 | 每个 material 一个 JSON，落在 `timed_media` 工作区特性目录（`deeptutor/video_learning/service.py:307`，目录注入 `:312`，特性名注册 `deeptutor/services/path_service.py:60`） | SQLite 目录 `ReadingCatalogStore`（`deeptutor/reading/catalog_store.py`，`SourceKind.YOUTUBE/BILIBILI` 见 `deeptutor/reading/catalog_models.py:16-21`）+ ReadingStore SQLite（`deeptutor/reading/store.py:161`） |
| 转写 | `transcript.cues`，旧格式经 `normalize_cues`（`deeptutor/video_learning/service.py:197`） | `TranscriptSegment`，经 `normalize_transcript_segments`（`deeptutor/reading/ingestion.py:736`）+ `build_transcript_segments`（`:769`） |
| 定位 | 秒（`learning.last_position`） | locator：1 起始的段序号（`deeptutor/reading/models.py:3`、`:135`），配 `source_anchor="#t=秒"` |
| 笔记 | Notebook `"Video Learning"`（`deeptutor/video_learning/notes.py:20`；CRUD `:144/:188/:213`） | `Annotation`（`deeptutor/reading/models.py:359`，locator+quote+note），落 `ReadingStore.save_annotation`（`deeptutor/reading/store.py:1326`） |
| 标记 | `learning.marks`（`deeptutor/video_learning/marks.py:123-126`，路由持久化 `deeptutor/api/routers/video_learning.py:343`） | **尚无对应物**（见 §5 空白 1） |
| 进度 | `save_video_progress` 写回 TimedMedia（`deeptutor/api/routers/video_learning.py:243-254`） | `ReadingStore.save_position`（`deeptutor/reading/store.py:1105`，幂等判断 `:1100`） |
| Provider | `_youtube_resolution`（`deeptutor/video_learning/service.py:484`）/ `_invidious_resolution`（`:547`），分发表 `:589-590`，缺省回退 youtube `:610` | Reading 摄取注入 `youtube_loader`（`deeptutor/reading/ingestion.py:158`），默认 `_load_youtube_captions`（`:167`）已走 `resolve_youtube_captions`（`deeptutor/video_learning/service.py:594`）——Provider 层合一；B 站独立 loader（`deeptutor/reading/ingestion.py:820`） |

注意区分：`deeptutor/reading/captions.py:53` 是**图片 captioning**（LLM 配图说明），
与字幕无关，勿混入本链路。

## 3. 迁移链路（数据流）

核心类 `WatchingToReadingMigration`（`deeptutor/video_learning/reading_migration.py:67`）：

1. 读旧记录：`timed_media_store.peek(id)`（`:88`；store 实现 `deeptutor/video_learning/service.py:330`）。
2. 零网络投影：`migrate()` 用 `cached_loader`（`:104-111`）把旧 cues 直接喂给
   `ReadingIngestionService.queue_url/process_url`（`deeptutor/reading/ingestion.py:180/:205`），
   再以 `render_mode="video"` upsert 目录（`:116-128`）。
3. 确定性新 ID（幂等基石）：
   - reading workspace：`"rw_" + sha256("legacy-watching:{timed_media_id}")[:24]`（`:130-132`）；
   - annotation：`"legacy-video-" + sha256(note_id)[:24]`，已存在即跳过（`:184-190`）。
4. 拷贝阅读位置：`_copy_position`（`:160-176`）把 `learning.last_position` 秒映射为段
   locator（`_segment_locator` `:57-64`），并保留 `#t=` 锚点与百分比；仅当
   `has_position` 为假时写（`:148-149`），重迁移不覆盖较新的阅读位置。
5. 拷贝笔记：`_copy_notes`（`:178-207`）经 `video_notes.list_notes`
   （`deeptutor/video_learning/notes.py:107`）逐条投影，quote 取该 locator 的 cue 文本
   （`:200`），保留原 created/updated 时间戳（`:204-205`）。
6. 会话挂接：`catalog.attach_session`（`:151-157`）。

### 三个触发点

| 触发点 | 位置 | 行为 |
|---|---|---|
| 发回合（旧会话继续说话/regenerate） | `deeptutor/services/session/turns/request_preparer.py:236-242`（payload/preferences 的 workspace_mode、capability、session_kind 任一为 `immersive_watching`） | 无 timed_media_id 直接 fail-closed（`:245-248`）；迁移成功后偏好改写为 `chat`+`immersive_reading`（`:262-268`），`timed_media_id` 降级为溯源字段（`:269-271` 注释），viewport 转 `reading_viewport` 并弹出旧字段（`:288-294`） |
| 打开会话（显式迁移端点） | `deeptutor/api/routers/sessions.py:383` `POST /{session_id}/migrate-watching` → `_normalize_legacy_watching_session`（`:132`）；媒体 id 缺失时从消息 request_snapshot 回捞（`:143-149`，snapshot 写入点 `deeptutor/services/session/_turn_runtime_shared.py:956-958`） | 找不到媒体 → 降级为纯 chat 并打 `legacy_watching_unavailable`（`:150-161`，媒体缺失分支 `:171-180`）；迁移异常保留原会话返回 409（`:401-403`）；仅 `persist=True` 时写回偏好 |
| 前端路由 | `web/lib/workspace-mode.ts:30` `immersive_watching → READING`（legacyCapability 同判 `:34-37`）；旧 URL 重定向 `web/features/chat/components/ChatWorkspace.tsx:660-661` + `web/lib/learning-routes.ts:41` | 前端一律落到 Reading 舞台（`web/components/reading/workspace/MediaReadingStage.tsx` + YouTube/Bilibili 播放器） |
回合 schema 仍保留 `timed_media_id/viewport` 字段（`deeptutor/core/turn_request.py:173-174`），
但执行前已被 preparer 弹出——读代码时不要据此认为回合仍消费 TimedMedia。

## 4. 回退与安全边界

- **旧数据零破坏**：投影只读（`reading_migration.py:1-6`、`:5` "never mutates"），
  Notebook/JSON 原样保留；回退 = 停用投影入口即可，旧会话数据完好。
- **幂等可重放**：§3.3 的确定性 ID + 跳过已存在 annotation（`:189-190`）+
  仅空位写 position（`:148-149`），重复触发不产生重复物料/笔记
  （测试 `tests/video_learning/test_reading_migration.py:111`）。
- **失败语义分两级**：回合侧 fail-closed 报错不降级（`request_preparer.py:245-248`、
  `:257-260`）；打开会话侧降级为 chat 保对话（`sessions.py:150-161`、`:171-180`）。
- **不可回退点**：一旦旧会话偏好被重写为 `immersive_reading`（两处都持久化），
  `immersive_watching` 字段即消失，仪表盘 `watching` 桶（`deeptutor/api/routers/dashboard.py:103-113`）
  不再计入——回退到"独立 Watching 面"需要恢复偏好字段，而能力注册已删
  （`tests/video_learning/test_turn_wiring.py:219`），实际上不可单靠数据回退。

## 5. 关键文件表

| 文件 | 角色 | 锚点 |
|---|---|---|
| `deeptutor/video_learning/reading_migration.py` | 迁移投影（唯一桥） | `:67` 类；`:81` migrate；`:130-132` workspace ID；`:160/:178` 位置/笔记拷贝 |
| `deeptutor/services/session/turns/request_preparer.py` | 回合期触发 | `:236-242` 检测；`:251-259` 迁移；`:262-294` 偏好改写 |
| `deeptutor/api/routers/sessions.py` | 打开会话触发 | `:132` 归一化；`:383` migrate 端点 |
| `deeptutor/video_learning/service.py` | TimedMediaStore + provider 解析 | `:307/:330/:367/:407`；`:484/:547/:589-594` |
| `deeptutor/video_learning/notes.py` | 旧笔记（Notebook） | `:20` 笔记本名；`:107` 列表 |
| `deeptutor/video_learning/marks.py` | 旧标记（未迁移） | `:123-126` 存储；`:235-259` CRUD |
| `deeptutor/api/routers/video_learning.py` | 旧 HTTP 面（进度/标记仍活跃） | `:243` 进度；`:322/:342-372` 标记 |
| `deeptutor/reading/ingestion.py` | 新摄取（provider 感知） | `:151/:158/:180/:205/:295/:799/:820` |
| `deeptutor/reading/models.py` | locator/Annotation 模型 | `:3/:135/:359` |
| `deeptutor/reading/store.py` | 位置/批注持久化 | `:1100/:1105/:1208/:1326` |
| `deeptutor/reading/catalog_store.py` | 物料 SQLite 目录 | （与 `catalog_models.py:16-25` 同读） |
| `deeptutor/capabilities/reading/capability.py` | 媒体回合种子 | `:227-240` render_mode 分支；`:394` 当前时间注入 |
| `deeptutor/services/session/_turn_runtime_shared.py` | snapshot 回捞字段 | `:813`；`:956-958` |
| `deeptutor/api/routers/dashboard.py` | 遗留会话计数 | `:103-113`（列表 `:209-210`） |
| `web/lib/workspace-mode.ts` | 前端模式归一化 | `:30-37` |
| `web/components/reading/library/AddMaterialsDialog.tsx` | WatchingBrowser 复用为 Invidious 入口 | `:23/:531` |
| `web/components/watching/WatchingMarksPanel.tsx` | 孤儿组件（无引用） | 全仓仅自引用 |

## 6. 测试现状与空白清单

已有覆盖：迁移投影无 Notebook 副作用 + 重迁移保留新位置
（`tests/video_learning/test_reading_migration.py:18/:111`，仅 2 例）；
回合触发/失败/snapshot（`tests/video_learning/test_turn_wiring.py` 6 例，
`:79/:150/:174/:219`）；打开会话五分支
（`tests/api/test_session_watching_migration.py` 5 例，`:103/:126/:150/:160/:182`）；
旧服务与标记（`tests/video_learning/test_service.py` 23 例、`test_marks.py` 7 例）；
前端模式归一化（`web/tests/watching-session.test.ts`）。

可拆卡条目（按优先级）：

1. **marks 迁移缺口**：`WatchingToReadingMigration._copy_notes` 只搬笔记和位置
   （`reading_migration.py:148-150`），`learning.marks`（`marks.py:123-126`）无投影；
   Reading 侧无 mark 概念，`MediaReadingStage.tsx` 无 marks 集成，面板组件已无人引用。
   拆卡：决定 marks 映射为 `Annotation`（新 kind）或正式废弃，并同步路由面
   （`deeptutor/api/routers/video_learning.py:322-372`）。
2. **迁移边界用例薄弱**：缺"无 cues 旧记录"走
   `TRANSCRIPT_UNAVAILABLE_TEXT` 回退（`reading_migration.py:99`，常量
   `deeptutor/reading/ingestion.py:89`）的直接测试；缺 seconds 超出末段的
   `_segment_locator` 边界（`:57-64`）；缺迁移后目录 `source_kind` 断言（`:121`）。
3. **双写窗口无一致性测试**：迁移后 `timed_media_id` 仅作溯源
   （`request_preparer.py:269-271`），但旧进度/标记端点仍写 TimedMedia
   （`video_learning.py:243-254`）；若 UI 或旧客户端继续调用，读路径已是 Reading
   ——需要一张"迁移后旧端点写密封堵或同步投影"的卡。
4. **仪表盘 watching 桶无测试**：`dashboard.py:103-113` 的遗留计数零覆盖
   （`tests/api/` 下仅 session 迁移测试触及 `watching`）。
5. **`WatchingMarksPanel.tsx` 零测试 + 零引用**：随空白 1 一并处理，或单独删除。
