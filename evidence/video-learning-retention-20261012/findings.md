# 逐条证据与保留建议（path:line + 数字）

基线 commit：`6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）。
所有行号以该 commit 为准。观测命令均为只读（`ls` / `du` / `stat` / `wc`）。

## F1 材料 JSON：单文件体积上界 ≈9.5MB，当前观测 ≈7.5% 上界

- cues 上界：`deeptutor/video_learning/service.py:27-28`（`MAX_TRANSCRIPT_CUES = 20_000`、`MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024`）；`normalize_cues` 在 `service.py:215-216` 按 UTF-8 字节累计截断（`if total_bytes + len(encoded) > MAX_TRANSCRIPT_BYTES: break`），条数截断在 `service.py:202`（`list(rows)[:MAX_TRANSCRIPT_CUES]`）。
- 字幕文本同文件双份：`resolve_material` 同时写入 `transcript.cues`（service.py:672-678）与 `segments`（service.py:679，`build_segments` 于 service.py:229-253 由 cues 拼接，文本为 cues 子集）。
- marks 上界：每材料 ≤500 条（marks.py:16 `MAX_MARKS_PER_MATERIAL = 500`，超限拒绝 marks.py:238-239）；单条 quote ≤4,000、note ≤2,000 字符（marks.py:17-18，截断于 marks.py:217-218）；metadata ≤16 字段且 JSON 序列化 ≤4,000B（marks.py:200-203）。单条最坏 ≈(4000+2000+4000+~500 开销) ≈10.5KB → 500 条 ≈5.2MB。
- 结论：单文件最坏 ≈ 2MB(cues) + ~2.2MB(segments 文本+对象开销) + ~5.2MB(marks) ≈ **9.5MB**；含 provider_cache（invidious_formats，常数级 service.py:681）。
- 观测（`/Users/Shared/DeepTutor/data/user/workspace/timed_media/`）：**89 个 .json，合计 2.7MB，最大 768,565B、次大 563,622B** → 现状约为最坏上界 7.5%，尚未逼近上界。

## F2 无删除/GC/TTL：材料文件与锁文件单调累积（最高优先级）

- 全仓检索 `timed_media` 落盘方（`deeptutor/video_learning/`、`deeptutor/api/routers/video_learning.py` 及 `services/workspace/dependencies.py:14,57` 等消费方）均无 unlink/rmtree。
- `TimedMediaStore`（service.py:307-408）只有 `_load/peek/get/save/lock`，无 delete。
- 路由层核对（routers/video_learning.py:212-568）：材料相关端点为 resolve/get/progress/notes×5/marks×5/mark-suggestions/subtitles.vtt/transcript-refresh/stream，**无材料 DELETE**；材料 id 是确定性 sha256（service.py:411-412），无法通过"重新 resolve"清空。
- 保留动因：迁移后的会话把 `timed_media_id` 保留为 "provenance and a provider-cache pointer"（routers/sessions.py 归一化分支），`material_with_playback` 依赖 `provider_cache.invidious_formats`（service.py:700）；`refresh_invidious_transcript` 要求该缓存存在（service.py:748-749）→ 现有设计下材料文件事实上必须永久保留。
- 锁文件：`lock()` 每次创建 `.locks/{material_id}.lock`（service.py:378-383），全模块无对应 unlink → 每个被锁过的材料永久 +1 文件（0–1B）。观测 **77 个锁文件 vs 89 个材料文件**。
- 数字：文件数增长率 = 用户 resolve 过的不同视频数；当前部署 89 文件 / mtime 跨度 2026-08-26 至 2026-09-28（约 4.7 周）≈ **2.7 文件/天**（单用户，含回看旧视频的覆盖写，非净增速上限）。

## F3 写放大：每次进度/mark 操作整文件重写（观测最大 ~750KB/次）

- progress PUT：routers/video_learning.py:242-257 在锁内 `store.get` → 改 `learning.last_position` → `store.save`。
- mark 增/改/删：routers/video_learning.py:336-375 同模式。
- `save()` 全量 `atomic_write_json`（service.py:367-372；file_io.py:72-92：临时文件 + fsync + rename）。
- 观测：最大材料文件 768,565B → 播放器每次进度心跳重写 ~750KB 并 fsync；多并发观看时 I/O 与该值成正比。
- 读取也可触发一次性写：legacy 字幕修复 `get()` 在 `_caption_text_version` 缺失时重写文件（service.py:355-365；修复门 service.py:334-353，每材料仅一次）。
- resolve 重写：`resolve_material` 每次网络解析成功后整文件覆盖 transcript/segments/metadata，仅保留 `learning`（service.py:629-694，锁内重读 learning 防丢进度于 service.py:684-693）。

## F4 字幕三重复制与副本漂移（迁移材料 ×2–3 存储）

- 第一/二份：F1 所述 cues + segments。
- 第三份：watching→reading 迁移把 cues 转为 TranscriptSegments 写入 reading store，并把视频笔记复制为 annotations；模块头明确 "TimedMedia remains the provider cache for old records…It never mutates the legacy JSON"（reading_migration.py:1-6, 92-99, 148-207）→ legacy 材料 JSON 原样保留。
- 漂移：`refresh_invidious_transcript` 只更新 timed_media 副本（service.py:740-780），reading 副本的段文本不跟随更新。

## F5 视频笔记：notebook 记录无数量上限 + 材料缺失即不可达

- 落盘：`user/workspace/notebook/{id}.json`（path_service.py:290-294），固定笔记本 "Video Learning"（notes.py:20,161-166），记录 type=`video_learning`（notebook/service.py:39）。
- 无 cap：`add_record` 直接 append（notebook/service.py:452）；note body 上限 20,000 字符仅在路由层（routers/video_learning.py:56,61），notebook 层不设限。
- 全量重写：每次 add/update/remove 重写整个 notebook 文件（notebook/service.py:230-231, 452-454, 524-525）。
- 匹配成本：每次笔记 list/update/delete 遍历**所有** notebook 的**所有**记录（notes.py:66-88），单 notebook 记录数无界 → 随笔记积累线性变慢。
- 孤儿：`list_notes`/`export_notes` 先 `get_timed_media_store().get(material_id)`（notes.py:108,118-119），材料缺失抛 `TimedMediaNotFound` → API 404，notebook 记录仍留盘不可达；材料存在但 notebook 损坏时记录被跳过（notes.py:69-81, NotebookCorruptedError continue）→ 笔记"消失"。
- 观测：Video Learning 笔记本已存在、0 条记录（247B）→ 增长路径尚未启动。

## F6 Invidious 账号 / pending：保留策略良好（低风险）

- account.json 每 owner 恒 1 个、0600 权限、原子覆盖写（invidious_account_storage.py:69-83,158-159）；token ≤8,192B（invidious_account.py:38,110）。
- 删除：仅 disconnect（storage.py:162-163）；上游撤销失败时保留以便重试（invidious_account.py:223-234）；令牌过期只使状态显示 needs_reconnected，不清理文件（invidious_account.py:193-212）→ 过期令牌长期留盘但 <8KB。
- pending：FLOW_TIMEOUT_S=600（invidious_account.py:28）；`purge_expired` 在每次 begin/complete 触发（invidious_account.py:90,172）且顺带清理损坏文件（storage.py:110-115）；同 owner+实例新流自动替换旧流（storage.py:118-127）；consume 走一次性 rename claim（storage.py:134-151）。
- 观测：2 个 owner 目录 pending 均为 **0 文件**；account.json 1 个 **625B**。

## F7 设置文件：admin scope 全局单份

- `video_learning_settings_path()` 恒用 `get_admin_path_service()`（service.py:171-172）→ 多用户部署下所有用户共享同一 `user/settings/video_learning.json`（path_service.py:233-236）；单文件 ~245B（观测），无增长，非保留问题（记录为多用户行为事实）。

## 保留建议（按投入产出排序）

1. **拆分"用户数据"与"可重建缓存"**：材料 JSON 内仅 `learning`（marks+last_position，≤5.2MB 上界）与 `metadata` 有长期价值；`transcript`/`segments`/`provider_cache` 均可重新 resolve 重建。拆为 `{id}.json`（用户数据）+ 可选缓存文件后，缓存可按 LRU/TTL 丢弃，用户数据量级降至 KB 级。改动点集中在 service.py:646-683（写入结构）与 307-408（store）。
2. **材料 TTL/LRU**：对"无 learning 活动 > N 天且无活动会话引用"的材料清理缓存部分；provider_cache 依赖（service.py:700,748）可改为 `material_with_playback` 已具备的按需重建路径（service.py:697-737 已支持无缓存时 live resolve）。
3. **`.locks` GC**：材料确认不存在时顺带删除同名锁文件；或在 save() 中对超期（mtime > N 天）且无并发持有者的锁做惰性回收。观测 77 个 0–1B 文件，量小但机制上无界。
4. **笔记孤儿治理**：`list_notes` 对缺失材料改为返回已有笔记 + 附 `material_missing: true`（或提供按材料清理端点），避免 404 掩盖留盘孤儿（notes.py:107-114）。
5. **notebook 记录 cap**：对 `video_learning` 类型 notebook 设记录数上限（如 1,000）并在触及后提示导出，控制 `list_notes` 的 O(全部记录) 扫描（notes.py:66-88）与整文件重写成本（notebook/service.py:230-231）。
6. **doctor 指标**：`timed_media` 目录文件数/字节数、`.locks` 文件数可直接 stat 得到，建议纳入诊断输出以便观测 F2 增长。

## 观测方法与数字汇总

- 统计命令：`ls | wc -l`、`du -sh`、`ls -laS`、`stat -f "%z"`、`find … | wc -l`（全部只读，2026-10-12）。
- timed_media：89 个 .json / 2.7MB / 最大 768,565B / 锁 77 个（0–1B）。
- notebook：Video Learning 笔记本 1 个，0 条记录，247B；索引 316B。
- settings/video_learning.json：245B。
- user-secrets：video-learning-invidious 目录 2 个 owner；account.json 1 个 625B；pending 0 个。
- 未读取任何用户数据内容与任何令牌内容（仅元数据）。
