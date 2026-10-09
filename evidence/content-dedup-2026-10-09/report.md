# 内容寻址去重机会清点（上游 #1138 只读对照）

- 基线：origin/main @ `6cf793bd8`（v1.6.14），只读 worktree，未改任何产品代码。
- 对照：上游 issue #1138（open，跨 reading/KB/chat 附件的内容寻址去重提案）；其开放 PR #1218（`feat/attachment-content-addressed-dedup` → `dev`，diff 为 `services/storage/__init__.py`、`attachment_store.py`、新增 `blob_store.py` +210、新增 `tests/services/storage/test_attachment_blob_dedup.py` +124）。本卡不复核 PR。
- 关联内部卡：scan-persistence（持久化面与 pg 评估）、guide-storage（存储层导读）——重叠处只引用，不重复展开。

## 一、三个存储面现状

### 1. Chat 附件
- 布局：`{root}/{session_id}/{attachment_id}_{filename}`（`deeptutor/services/storage/attachment_store.py:21-26`），纯路径键，无内容键。
- 写入：`LocalDiskAttachmentStore.put`（`attachment_store.py:147-174`）整份字节落盘，原子写（:176-191）。全部写入点都汇聚到 `put`：chat 轮次上传 `deeptutor/services/session/turns/executor.py:345`、提取出的内嵌图片 `executor.py:450`、错题本答案图 `deeptutor/api/routers/question_notebook.py:250`。
- 删除：`delete_session`/`delete_attachment`（`attachment_store.py:193-231`）直接删文件，无引用计数。
- 去重现状：无。同一文件在两个会话上传 = 两份完整拷贝；同会话重复上传（不同 attachment_id）同样两份。
- **已有路线：PR #1218 覆盖本面**（blob store + attachment_store 改造 + 回归测试）。本卡不展开。

### 2. Immersive Reading
- 内容身份已存在：`content_hash()` = `sha256(raw)[:_ID_LENGTH]`（`deeptutor/reading/store.py:157-158`）。
- ingest 幂等：`material_id = content_hash(source_data)`（`store.py:283`），同内容已完整存在则直接返回既有 manifest（`store.py:286-298`）。
- raw 落盘：按 content-id 目录写 `raw/`（`store.py:336-344`）；EPUB 修复归档另存 `render/`（`store.py:341-344`，设计上独立浏览器视图，非冗余）。媒体/网页走 `ingest_units`，raw_data 落 `raw/`、assets 落 `assets/`（`store.py:658-675`）。
- 目录内共享：catalog 允许多条目挂同一 content_id，字节只存一份（`deeptutor/api/routers/reading.py:1090-1106`，注释明言 "the bytes are stored once"）。
- 硬链接先例：`_carry_dir` 优先 `os.link`、跨文件系统回退 copy（`store.py:1518-1536`）。
- 去重现状：reading 面内已去重；跨面（与附件、KB）无共享。

### 3. Knowledge Base
- 布局：每 KB 独立 `raw/` 目录，路径键（`_raw_hash_key` = 相对路径，`deeptutor/knowledge/add_documents.py:111-120`；目录上传保留层级 :300-307）。
- 写入：staging 一律 `shutil.copy2` 拷入（`add_documents.py:350-352`）。
- 面内去重：索引成功的文件按内容 hash 记账，重复导入跳过（`add_documents.py:321-324`，记账 :391 `asyncio.to_thread(self._record_successful_hash, ...)`）——但字节在跳过前已拷贝或已在 raw/ 内，省的是索引不算字节。
- 跨 KB：零共享。同一 PDF 入两个 KB = 两份完整拷贝。
- 删除：`delete_knowledge_base` rmtree 整个 KB 目录含 raw/（`deeptutor/knowledge/manager.py:1780-1860`）；单文件删除 `remove_raw_document`（`add_documents.py:141-155`）。

### 参考面（非本次主目标）
- File Library：入库即按 SHA-256 去重（`deeptutor/services/storage/file_library.py:10-13`），但盘上布局是 UUID 键 `{file_id}{ext}`（:249），软删除保留文件（:15-18）。库内已去重，跨面无共享。
- Parse cache：已是内容寻址 `parse_cache/<hash[:2]>/<source_hash>/<signature>/`（`deeptutor/services/parsing/cache.py:8,38-49`，sha256[:16]），仓库内内容寻址布局的现成范本。非去重目标。
- 图片 caption 缓存：已按 `image_sha256` 寻址（`deeptutor/services/llm/image_caption_cache.py:59-69`）。无需动作。

## 二、仓库内已有先例（可复用，不需新造）

| 先例 | 位置 | 形态 |
| --- | --- | --- |
| 内容寻址分片布局 | `deeptutor/services/parsing/cache.py:8,48-49` | `<hash[:2]>/<hash>/<signature>/` |
| 截断 sha256 内容 ID | `deeptutor/reading/store.py:157-158` | `sha256[:_ID_LENGTH]`，幂等 ingest |
| 硬链接+copy 回退 | `deeptutor/reading/store.py:1518-1536` | `os.link` → `shutil.copy2` |
| 原子写 | `deeptutor/services/storage/attachment_store.py:176-191` | tmp + `os.replace` |
| 库内 hash 去重 | `deeptutor/services/storage/file_library.py:10-13` | sha256 查重后跳过写入 |

## 三、Top5 机会点

判定口径：每条附 path:line 与去重键选择依据；与 #1218 重叠处标「已有路线」。

### Op-1 Chat 附件跨会话去重 —— 已有路线（PR #1218）
- 接入点：`LocalDiskAttachmentStore.put`（`deeptutor/services/storage/attachment_store.py:147-174`）。三个写入点（`executor.py:345`、`executor.py:450`、`question_notebook.py:250`）全部经由此单点，改一处即覆盖全面。
- 去重键：`sha256(raw)` 全量 hex。理由：写入点手里已是完整 bytes（base64 解码后），单遍可算；文件名/类型属展示层，放 label；截断键（如 [:16]）在这里无收益，全量避免任何碰撞讨论。
- 状态：#1218 已给出 blob_store + store 改造 + 测试。**不展开**。

### Op-2 跨面共享 blob 目录（attachments ↔ reading ↔ KB）—— 部分已有路线
- 对应 #1138 提案 1。#1218 的 diff 只落 attachments 一面（storage/__init__ + attachment_store + blob_store），跨面 catalog 不在其内 → 部分已有路线。
- 接入点：reading 侧在 `ReadingStore.ingest` 取得 raw 后改查共享 catalog（`deeptutor/reading/store.py:283-298` 已有 content-id 幂等，改为先查 blob）；KB 侧在 staging 拷贝点（`add_documents.py:350-352`）改为 link/引用。
- 去重键：`sha256(raw)` 全量，label 层挂 `reading:<content_id>` / `kb:<name>:<relpath>` / `attachment:<sid>:<aid>`。理由：三面各自的现有身份都由同一原始字节派生（reading 的 content_hash、KB 的 index hash、#1218 的 blob 键），全量 sha256 是三面都可接受的最大公约数；label 保留各面现有语义（KB 相对路径承载目录上传，`add_documents.py:300-307`）。
- 分档：L。依赖 Op-1 blob store 先落地（复用其 catalog 形态）。

### Op-3 KB raw/ staging 内容寻址（面内字节去重 + 跨 KB 前置）
- 现状缺口：面内 hash 查重只挡「重复索引」，不挡「重复字节」（`add_documents.py:321-324` 与 :350-352 两个路径各写各的）；跨 KB 完全重复。
- 接入点：`KnowledgeBaseManager.add_documents` 的拷贝点（`add_documents.py:350-352`）与 `_non_colliding` 冲突分支（:346-348）；记账复用现有 `_record_successful_hash`（:391）。
- 去重键：staging 层 `sha256(raw)`，label 层保留相对路径（目录上传语义不可破坏，`add_documents.py:111-120,300-307`）。理由：KB 的 folder 结构是用户可见语义，必须留在 label；字节层换内容键即可同 KB、跨 KB（配合 Op-2）复用。
- 风险：`remove_raw_document`（:141-155）与 KB 整删（`manager.py:1860`）现按路径删，换内容键后需 refcount（归入 Op-5）。
- 分档：M（单 KB 内）；并入 Op-2 后为跨 KB 完整形态。

### Op-4 Chat 附件 → Reading 导入单拷贝路径
- 现状：前端从 `/files/attachments/...` 把字节 fetch 回浏览器再重传 `POST /materials`（`web/components/chat/preview/FilePreviewDrawer.tsx:175-184` → `web/lib/reading-api.ts:247-254` → `deeptutor/api/routers/reading.py:1037-1088`）。同一文件字节在盘上存两份（chat/attachments 一份 + reading/raw 一份），还多一次往返。
- 机会：新增服务端导入端点，收附件指针（sid/aid/name），经 `resolve_path`（`attachment_store.py:233-242`）直接以已存字节喂 `ReadingStore.ingest`（`store.py:254`），reading 现有 content-id 幂等自动收敛拷贝。
- 去重键：沿用 reading 现有 `content_hash`（`store.py:157-158`）；若 Op-1 blob 已存全量 sha256，导入时直接复用该摘要，免二次读盘计算。
- 不在 #1218 范围（其 diff 无 reading/api 路由）。
- 分档：S。

### Op-5 去重前置：删除语义与引用计数对账
- 现状三个删除口都无引用概念：附件 `delete_session`/`delete_attachment` 直删（`attachment_store.py:193-231`）；reading catalog `delete_material` 只删 DB 行，底层 content 目录由共享它的其他 catalog 条目继续引用（`deeptutor/reading/catalog_store.py:562-567`）；KB 整删 rmtree（`manager.py:1860`）。
- 任何共享 blob（Op-2/Op-3）落地前必须先有：refcount 记账 + 孤儿对账命令 + 每面用量统计（对应 #1138 提案 3-4 的 retention/observability）。
- 去重键：对账以 blob 键（全量 sha256）为主键，label 表记录引用方。
- 不在 #1218 范围。
- 分档：M。

### 次级项
- File Library 接入共享 blob（`file_library.py:10-13,249`）：库内已 hash 去重，仅盘上布局改内容键即可并入 Op-2 catalog。分档 S，依赖 Op-2。
- parse cache / caption cache：已内容寻址（`cache.py:8`、`image_caption_cache.py:59-69`），无动作。

## 四、风险清单

1. **引用计数缺失**：三面删除口均为直删/只删行（见 Op-5），共享字节后一次删除可能打断另一面的预览。任何去重落地前先补 refcount + 对账。
2. **多工作区隔离**：附件根按活动工作区解析（`attachment_store.py:296-316`），KB base_dir 独立（`manager.py:328`）。全局单一 blob 库会跨工作区共享字节，改变多用户隔离姿态；共享范围须按工作区划定或 label 带工作区维度。
3. **硬链接可移植性**：APFS/btrfs/NTFS 支持、跨文件系统必须回退 copy（先例 `store.py:1528-1536`）；#1138 报告人环境为 Windows。硬链接字节一旦被原位重写会污染所有引用——现有写入全部「stage 后原子替换」（`attachment_store.py:176-191`、reading staging+backup `store.py:307-308`），硬链接安全性依赖此纪律持续成立。
4. **截断 ID 与全量键的映射**：reading 用 `sha256[:_ID_LENGTH]`（`store.py:157-158`）、parse cache 用 `sha256[:16]`（`cache.py:45`），共享 catalog 若取全量 sha256 需要显式映射层，不能默认截断键等价于全量键。
5. **legacy 根迁移**：附件存储保留 legacy 根与 materialize 流程（`attachment_store.py:46-47,244-276`），blob catalog 需处理已物化的旧拷贝，否则对账双计。

## 五、分档计数

| 分档 | 数量 | 条目 |
| --- | --- | --- |
| S（≤1 天） | 2 | Op-4；次级-File Library 接入（依赖 Op-2） |
| M（2-3 天） | 2 | Op-3（单 KB 内）；Op-5 |
| L（≥1 周） | 1 | Op-2（跨面 catalog，依赖 Op-1 blob store） |
| 已有路线 | 1 | Op-1（PR #1218） |

拆卡建议顺序：Op-5（对账/refcount 前置）→ Op-4（独立小卡，立即可做）→ Op-3 → Op-2（待 #1218 落地后复用其 blob store 形态）。

## 六、验证

- 本卡纯只读：`git diff` 为空（evidence/ 之外无改动），未 checkout/reset/clean 主工作区，未改 `/Users/Shared/DeepTutor` 的未提交内容。
- 清点基于 origin/main @ 6cf793bd8；所有 path:line 在该提交下核对。
