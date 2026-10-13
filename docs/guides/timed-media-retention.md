# Timed Media 存储保留语义导读（guide-timed-media-retention-2026-10-13）

- 基线：`origin/main @ 6cf793bd8`（release v1.6.14）。所有 `path:line` 均为该基线、相对仓库根目录。
- 范围：`deeptutor/video_learning` 的 TimedMediaStore 单文件结构、字段上界、锁与原子写、用户数据 vs 可重建缓存的划分、watching→reading 迁移的 provenance 约束；供后续 retention 设计与修复卡引用。
- 去重：不重复 guide-video-learning 的子包模块地图/数据流/故障定位，不覆盖 guide-watching 的 UX 轴；邻接的 Invidious 账号/pending 存储仅列保留相关事实。
- 证据：`scan/video-learning-retention-20261012` 分支 `evidence/video-learning-retention-20261012/findings.md`（F1–F7），观测数字（89 文件 / 2.7MB / 77 锁）引自该文件，本导读不重复观测方法。

## 1. 存储布局：一个材料对应哪些文件

| 路径 | 内容 | 产出点 |
| --- | --- | --- |
| `user/workspace/timed_media/{id}.json` | 材料单文件（结构见 §2） | 根目录来自 `get_workspace_feature_dir("timed_media")`（`deeptutor/multi_user/paths.py:164`、`deeptutor/services/path_service.py:243-244`），store 构造即建目录（`deeptutor/video_learning/service.py:310-314`） |
| `user/workspace/timed_media/.locks/{id}.lock` | 每材料一把文件锁，1 字节填充 | `deeptutor/video_learning/service.py:378-388`；全模块无 unlink → 每个被锁过的材料永久 +1 文件 |
| `user/workspace/notebook/{notebook_id}.json` + `notebooks_index.json` | 视频笔记（固定笔记本 "Video Learning"，`deeptutor/video_learning/notes.py:20,161-166`） | `deeptutor/services/path_service.py:290-296` |
| `user/settings/video_learning.json`（admin scope） | 提供方设置，多用户共享一份 | `deeptutor/video_learning/service.py:171-172`、`deeptutor/services/path_service.py:233-236` |
| `user-secrets`/invidious 目录 | `account.json`（每 owner 恒 1 个，`0o600`，`deeptutor/video_learning/invidious_account_storage.py:38,49,72-83`）+ `pending/`（600s 过期，`deeptutor/video_learning/invidious_account.py:28,103`） | 有自身 GC（`purge_expired`，`invidious_account_storage.py:110-115`），保留策略良好，非本卡重点 |

材料 id 是确定性的：`sha256("youtube-resolve-{video_id}")[:32]`（`deeptutor/video_learning/service.py:411-412`），格式校验 `^[0-9a-f]{16,64}$`（`service.py:33`）。同 id 重新 resolve 是**覆盖写**而非新文件。

## 2. 单文件字段表（`{id}.json` 顶层结构）

写入方：`resolve_material` 一次性构建全部字段（`deeptutor/video_learning/service.py:646-683`）；`save()` 追加 `updated_at` 并剥离 `playback`（`service.py:367-372`）。

| 字段 | 类型/内容 | 写入 | 说明 |
| --- | --- | --- | --- |
| `version` / `type` | `1` / `"timed_media"` | service.py:647-648 | 读取时严格校验 `type`，不符按不存在处理（`service.py:326-327`） |
| `material_id` / `created_at` | sha256 前 32 位 / ISO 时间 | service.py:649-650 | `created_at` 重 resolve 时沿用旧值（`service.py:650`） |
| `updated_at` | ISO 时间 | service.py:370 | 每次 save 刷新 |
| `source` | provider/video_id/url/entry_time_seconds | service.py:651-656 | **必须保留的路由数据**：YouTube iframe 需要 video_id（`service.py:813-819`），Invidious live-resolve 从 `source.url` 解析（`service.py:701-702`），refresh 取 `source.video_id`（`service.py:744-747`） |
| `metadata` | title/author/duration_seconds/thumbnail_url | service.py:657-671 | 重 resolve 时逐字段回退旧值（`service.py:633-639,658-668`） |
| `transcript` | status/reason/language/source/cues | service.py:672-678 | cues 上界见 §3；refresh 只替换该字段与 segments（`service.py:775-779`） |
| `segments` | 由 cues 拼接的段（20–90s，含 `locator`） | service.py:679（`build_segments` 于 `service.py:229-253`） | cues 的派生文本，是第二份字幕副本 |
| `learning` | `last_position` + `marks[]` | service.py:680 | marks 结构与上界见 §3/§5；重 resolve 时锁内重读保留（`service.py:684-693`） |
| `provider_cache` | `{"invidious_formats": [...]}` 或空 | service.py:681 | 内部字段，`public_material` 不外发（`service.py:787`）；live-resolve 见 §5 |
| `_caption_text_version` | `1` | service.py:682 | legacy 字幕清洗版本戳；迁移分支依赖它（§6），`public_material` 不外发（`service.py:787`） |

## 3. 上界表（数字与代码常量一一对应）

| 上界 | 常量/规则 | 强制点 |
| --- | --- | --- |
| cues 条数 ≤ 20,000 | `MAX_TRANSCRIPT_CUES`（`deeptutor/video_learning/service.py:27`） | 截断于 `service.py:202` |
| cues UTF-8 总字节 ≤ 2 MiB | `MAX_TRANSCRIPT_BYTES = 2*1024*1024`（`service.py:28`） | 累计超限即停（`service.py:214-216`）；Invidious 拉取侧同限（`service.py:538-541`） |
| 段长 20–90 秒 | `MIN/MAX_SEGMENT_SECONDS`（`service.py:29-30`） | 合并规则：段长 <90s 且间隔 ≤4s 且非「≥20s 且句末」（`service.py:239-243`）；`segments` 条数 ≤ cues 条数 |
| 每材料 marks ≤ 500 | `MAX_MARKS_PER_MATERIAL`（`deeptutor/video_learning/marks.py:16`） | 超限拒绝（`marks.py:238-239`） |
| mark quote ≤ 4,000 字符 | `MAX_QUOTE_CHARS`（`marks.py:17`） | 截断于 `marks.py:217` |
| mark note ≤ 2,000 字符 | `MAX_NOTE_CHARS`（`marks.py:18`） | 截断于 `marks.py:218` |
| mark metadata ≤ 16 字段且序列化 ≤ 4,000B | 硬编码（`marks.py:200-203`） | 超限拒绝 |
| mark 时间戳 0–86,400s | 硬编码（`marks.py:44-45`、路由 `deeptutor/api/routers/video_learning.py:51-52,65-66`） | 超限拒绝 |
| 建议（suggestions）≤ 5 条 | `MAX_SUGGESTIONS`（`marks.py:19`） | `marks.py:381-382` |
| 视频笔记 body ≤ 20,000 字符 | 路由层 Pydantic（`video_learning.py:56,61`） | **notebook 层无记录数上限**：`add_record` 直接 append（`deeptutor/services/notebook/service.py:406-454`） |
| Invidious token ≤ 8,192B | `_MAX_TOKEN_BYTES`（`deeptutor/video_learning/invidious_account.py:38`） | `invidious_account.py:110` |

单文件最坏体量为**推导值**而非代码常量：cues ≤2MiB + segments（cues 文本子集 + 对象开销）≈2.2MB + marks ≤500×≈10.5KB≈5.2MB ≈ **9.5MB**（推导依据见 findings F1）。当前观测约 7.5% 上界（89 文件合计 2.7MB，最大 768,565B，findings F1/F3）。

## 4. 锁与原子写

锁（`TimedMediaStore.lock`，`deeptutor/video_learning/service.py:374-404`）：

- 每材料一把 advisory 文件锁：`.locks/{id}.lock` 以 `a+b` 打开、首次写入 1 字节 `\0`（`service.py:378-388`），Unix `fcntl.flock(LOCK_EX)` / Windows `msvcrt.locking`（`service.py:389-404`）。
- 无 TTL、无持有者记录、锁文件**从不删除**（全模块无对应 unlink）→ 锁文件数单调累积（findings F2：观测 77 个，0–1B）。
- 持锁的写入点：progress PUT（`video_learning.py:246-254`）、mark 增/改/删（`video_learning.py:340-343,356-359,369-372`）、resolve 最终落盘（`service.py:684-693`，锁内重读 `learning` 防丢进度）、transcript refresh（`service.py:775-779`）、`get()` 触发的 legacy 修复写（`service.py:361-365`，每材料仅一次，门在 `service.py:334-353`）。
- **例外**：`material_with_playback` 的 cache 回填写不在锁内（读 `service.py:698`、写 `service.py:736`），与并发 progress 保存之间存在覆盖窗口（事实记录，修复属修复卡范畴）。

原子写（`atomic_write_json`，`deeptutor/services/file_io.py:72-92`）：

- 同目录临时文件 + `json.dump(indent=2)` + flush + fsync + `rename`（`file_io.py:78-89`）；fsync 失败降级为限频 warning，不阻断写入（`file_io.py:25-45`）；Windows rename 遇 `PermissionError` 指数退避重试 5 次（`file_io.py:48-69`）。
- 读者要么看到完整旧文件要么看到完整新文件；**部分写不可见**，但每次保存都要重写整文件（写放大，findings F3：观测最大材料 ~750KB/次心跳）。

## 5. 可丢弃性判定表（用户数据 vs 可重建缓存）

判定依据：该字段丢失后能否通过已存在的代码路径**无信息损失地**重建。

| 字段 | 类别 | 可否 TTL/LRU 丢弃 | 重建路径 / 保留理由 |
| --- | --- | --- | --- |
| `learning`（marks + last_position） | 用户数据 | **不可** | 唯一长期用户内容；重 resolve 时被显式保留（`service.py:640-645,684-693`），marks 上界见 §3 |
| `source` | 路由数据（常量级） | **不可** | material_id 是单向 hash，无法反推 video_id；播放/重建都依赖它（`service.py:701-702,744-747,813-819`） |
| `_caption_text_version` | provenance 标记 | **不可**（1 字节级成本） | 迁移的 cue 归一化分支依赖（§6，`deeptutor/video_learning/reading_migration.py:95-97`）；`get()` 修复门依赖（`service.py:337`） |
| `metadata`（title/author/duration/thumbnail） | 可重建 | 可 | 重 resolve 时 oEmbed/Invidious metadata 覆盖，旧值仅作回退（`service.py:633-639,658-668`） |
| `transcript`（cues 等） | 可重建（有损风险，见注） | 可 | `resolve_material` 重拉（`service.py:613-694`）、`refresh_invidious_transcript`（`service.py:740-780`） |
| `segments` | 可重建（纯派生） | 可 | `build_segments(cues)`（`service.py:229-253,679,734`） |
| `provider_cache.invidious_formats` | 可重建缓存 | 可 | 为空时 `material_with_playback` 已支持 live resolve 并回填（`service.py:700-736`）；**依赖注意**：`refresh_invidious_transcript` 目前要求该缓存存在，否则直接报错（`service.py:748-749`），retention 设计若丢弃缓存需一并改造 refresh 入口 |
| `updated_at` / `version` / `material_id` / `created_at` | 簿记 | — | 常量级，无丢弃收益 |

注（transcript 的有损重建风险）：cues 是**当前可重建**而非**必然可重建**——源站字幕下架、语言策略变化或 provider 切换后，重拉结果可能与现存内容不同甚至为空（`transcript.status` 变 `unavailable`，`service.py:672-677`）。已迁移材料的 cues 已快照进 reading store（§6），未迁移材料的 cues 若按缓存丢弃，存在无法复原的窗口。retention 设计需把「transcript = 快照型缓存」与「segments/provider_cache = 纯派生缓存」区分对待。

## 6. reading 迁移的 provenance 约束

模块契约：`WatchingToReadingMigration` 把 timed_media **只读投影**到 Reading 三库，"It never mutates the legacy JSON or Notebook records"（`deeptutor/video_learning/reading_migration.py:1-6`）。

- 读取用 `peek()`（`reading_migration.py:88`，`service.py:330-332`）——**绕过修复写**，迁移本身不产生材料文件的写放大。
- cue 来源分支依赖 `_caption_text_version`：==1 直接用 `transcript.cues`，否则先过 `normalize_cues` 再构建（`reading_migration.py:92-97`）。**约束**：若 retention 设计原地改写/再清洗 cues 或变更版本戳语义，迁移投影结果随之改变——改 `_caption_text_version` 前必须核对这两个消费方（另一处是修复门 `service.py:337`）。
- 派生副本全部落 reading 侧：segments→TranscriptSegments（`reading_migration.py:92-99`）；position 仅在无既有位置时复制一次（`reading_migration.py:148-149,160-176`）；笔记按 `"legacy-video-" + sha256(note_id)[:24]` 幂等去重（`reading_migration.py:184-190`）。
- 确定性 id：reading workspace = `"rw_" + sha256("legacy-watching:{timed_media_id}")[:24]`（`reading_migration.py:130-132`）→ 重放迁移幂等，timed_media_id 是该等式的输入，删除材料会破坏可重放性。
- 会话归一化：迁移成功后 `timed_media_id` 保留在 preferences 中，注释明确 "Kept as provenance and a provider-cache pointer; it is no longer routing state"（`deeptutor/api/routers/sessions.py:196-199`）；材料缺失时 `TimedMediaNotFound` 降级为纯 chat 会话（`sessions.py:173-183`）→ 材料文件一旦被清理，引用它的历史会话自动失去播放入口，这是清理策略必须显式接受的行为。
- 副本漂移：`refresh_invidious_transcript` 只更新 timed_media 侧 transcript/segments（`service.py:740-780`），reading 侧快照不跟随（现状事实，findings F4）。

## 7. 当前无 GC 的事实面（retention 设计的出发点）

- 材料与锁文件均无删除路径：`deeptutor/video_learning/` 各模块及路由均无针对 `timed_media/{id}.json`、`.locks/` 的 unlink/rmtree（唯一 delete 类代码在 invidious account/pending 存储，`invidious_account_storage.py:115,127,148,163`，见 §1）。
- 材料端点清单中无 DELETE：resolve（`video_learning.py:212`）、get（:226）、transcript refresh（:234）、progress（:242）、notes×5（:260-316）、marks×5（:318-386）、subtitles.vtt（:396）、stream（:526）。
- 增长面：每 resolve 过一个新视频 +1 材料 JSON；每锁过一个材料 +1 锁文件。材料 id 确定性（§1）意味着覆盖写不增加文件数，增长只由「不同视频数」驱动（findings F2：观测约 2.7 文件/天，单用户）。
- 结论性事实：现有设计下材料文件因 `provider_cache`/迁移 provenance 依赖而事实上必须永久保留（§5、§6）；把「用户数据 + 路由数据」与「transcript/segments/provider_cache」拆分后，后者才具备按 LRU/TTL 丢弃的前提——这是后续 retention 卡的设计输入，本导读只立事实不下方案。
