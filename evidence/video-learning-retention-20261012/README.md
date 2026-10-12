# scan: video learning 存储/缓存增长与保留审计（AGEN-1829）

## 范围与输入

- 审计对象：`deeptutor/video_learning/`（8 文件，2,977 行）与 `deeptutor/api/routers/video_learning.py`（571 行）在 `origin/main` @ `6cf793bd8`（release: v1.6.14）上的存储/缓存增长与保留策略。
- 方法：离线静态分析（不启动服务）+ 对本机部署 `/Users/Shared/DeepTutor/data/` 只读观测（仅元数据：文件数、字节数；不读取任何用户数据内容、不读取任何令牌内容）。
- 去重：`scan/learning-journal-retention-20261011`（journal 轴）、`scan/session-sqlite-growth-20261011`（session 轴）、AGEN-1830（LLM 台账）、AGEN-1831（partners）与本卡无范围重叠；`test-video-*` 系列（AGEN-1784/1701/1721/771）为测试轴，与本审计交付物不同。上游无关联 PR（evidence-only 交付，不开上游 PR）。

## 结论（PASS）

video learning 数据全部落盘为用户/owner 私有的 JSON 小文件，无媒体字节落盘，单文件体积有代码级上界（材料 JSON 最坏 ≈9.5MB，观测最大 768,565B ≈ 上界 7.5%）。主要风险按严重度排序：

1. **材料文件与锁文件均无任何删除/GC/TTL 路径**（全仓 grep 无 `timed_media` unlink/rmtree），文件数与 `.locks` 文件数随历史观看视频单调增长，永不回收。
2. **写放大**：进度心跳、mark 增删改、resolve 全部整文件重写材料 JSON（观测最大 ~750KB/次）。
3. **字幕文本三重复制**：`transcript.cues` + `segments` 同文件双份；watching→reading 迁移再把 cues 与笔记复制进 reading store，legacy JSON 保留 → 迁移材料总存储 ×2–3，且两副本独立演化（内容漂移）。
4. **笔记孤儿**：notebook 中 `video_learning` 记录引用 material_id 无外键；材料文件消失后笔记 API 直接 404，记录仍留在 notebook 文件内不可达。
5. 账号/pending 数据保留策略良好（600s 过期 + 惰性清理 + 同实例替换清理；观测 pending 0 个），低风险。

详细矩阵见 `matrix.md`，逐条 path:line 证据与保留建议见 `findings.md`。
