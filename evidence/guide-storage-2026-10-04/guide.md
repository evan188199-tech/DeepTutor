# deeptutor/services/storage/file_library 模块导读（本地文件库：增删查 / 路径 / 落盘与清理）

> 基线：origin/main @ `ef2d9e5c3`（v1.6.12，2026-10-04 fetch）。所有 `path:line` 锚点对应该提交。
> 本导读只读代码，不修改任何产品代码（验收 3）。行号格式：`文件:行号`，未注明的相对路径均自仓库根起。

## 1. 模块地图

本地文件库（Persistent File Library，源自上游 issue #1437 / PR #1446）= SQLite 元数据 + 平铺磁盘文件。
整个存储层只有两个同构模块：`file_library`（跨会话可复用文件库）和 `attachment_store`（聊天附件，session 维度）。

```
deeptutor/services/storage/
├── __init__.py            仅再导出 attachment_store 的符号（__init__.py:1-17）
├── file_library.py        本导读主角：FileLibraryStore + 单例工厂（480 行）
└── attachment_store.py    聊天附件存储，与 file_library 平级、互不调用（260 行）

deeptutor/api/routers/file_library.py   HTTP 面：/files/library 全部端点（169 行）
deeptutor/services/path_service.py      根路径解析（get_user_root）
deeptutor/multi_user/paths.py           每用户 scope → PathService
deeptutor/services/workspace/context.py scoped_path_service（contextvar 装配）
deeptutor/services/workspace/data_migration.py  工作区迁移时清 store 缓存

tests/services/storage/test_file_library.py     store 层单测 26 用例
tests/api/test_file_library_router.py           路由层测试 21 用例
```

关键入口速查：

| 入口 | 位置 | 作用 |
|---|---|---|
| 存储类 | `deeptutor/services/storage/file_library.py:83` | `FileLibraryStore`：SQLite + 磁盘 |
| 单例工厂 | `deeptutor/services/storage/file_library.py:457` | `get_file_library_store()`，按用户根缓存 |
| 上传端点 | `deeptutor/api/routers/file_library.py:64` | `POST /files/library/` |
| 下载端点 | `deeptutor/api/routers/file_library.py:106` | `GET /files/library/{id}/download` |
| 路由挂载 | `deeptutor/api/main.py:621-626` | 前缀 `/files/library`，整体挂 `_auth` |
| 磁盘写入 | `deeptutor/services/storage/file_library.py:175` | `_write_file`：tmp + `os.replace` 原子落盘 |
| 磁盘删除 | `deeptutor/services/storage/file_library.py:191` | `_delete_file`：unlink + 空父目录回收 |

前端（`deeptutor_web/`）当前无任何 `/files/library` 调用——该库目前是纯 API 面（本运行全仓检索确认）。

## 2. 路径与数据布局（路径处理）

### 2.1 用户作用域解析链

`get_file_library_store()`（file_library.py:457-475）每次调用都重新解析用户根：

1. `get_path_service()`（path_service.py:509-513）→ 委托 `multi_user.paths.get_current_path_service()`（multi_user/paths.py:164-168）→ `workspace.context.scoped_path_service(account)`（workspace/context.py:146-160）按 contextvar 中的 scope 返回 `WorkspacePathService`；
2. `get_user_root()` 返回 `<scope 工作区根>/user`（path_service.py:90、118-119）；
3. 文件目录 = user_root + `("workspace", "library", "files")`（file_library.py:42、473）；DB = user_root + `("workspace", "library") / "library.db"`（file_library.py:43、470-472）。

单例缓存键就是 `str(user_root)`（file_library.py:467-468）。注释明确说明：若用常量键，第一个请求会把所有用户钉死在同一实例上（file_library.py:460-465）——这是多用户隔离的关键点。

### 2.2 库内相对路径：为什么天然防穿越

上传时 `library_path = f"{file_id}{ext}"`，`file_id` 是 `uuid4()`，`ext = Path(filename).suffix`（file_library.py:247-249）。`Path.suffix` 永远不含路径分隔符，因此相对路径只能是 `<uuid>.<ext>`，用户无法注入 `../`。绝对路径在 `_file_path` 中 `resolve()`（file_library.py:168-170）。

对比：`attachment_store` 直接用用户文件名落盘，所以必须做 `_coerce_filename` + `_safe_join`（attachment_store.py:50-60、127-139）解析后校验 `relative_to(root)`。file_library 不需要这套防护，因为"相对路径不含用户输入"——两者路径安全模型不同，读代码时不要互相套用。

## 3. 数据流（上传落盘 / 查询 / 删除清理）

### 3.1 上传落盘链路

`POST /files/library/`（multipart，`filename` + 可选 `mime_type` + 原始字节 `file`，router:64-82）
→ `_get_store()` 取单例（router:41-43，延迟到调用时取，便于测试 monkey-patch）
→ `store.add_file()` 经 `asyncio.to_thread` 下放线程（file_library.py:212-225）
→ `_add_file_sync`（file_library.py:227-291）五步：

1. 算 `sha256`（file_library.py:234，`_sha256` 定义在 :46-47）；
2. 持 `self._add_lock` + 打开连接，查活跃同哈希行（file_library.py:237-244）——命中即**直接返回已有条目，不写盘**（这就是库内去重）；
3. 生成 uuid 相对路径，`_ensure_root` 建根目录，`_write_file` 落盘：写 `<uuid>.<ext>.tmp` → `os.replace` 原子改名（file_library.py:175-189、251-253）；
4. INSERT 元数据行并 commit（file_library.py:255-265）；
5. 若 INSERT 撞部分唯一索引（`sqlite3.IntegrityError`，跨进程竞态落败），**删掉刚写的文件**、回读胜出行返回（file_library.py:266-278）。

返回条目由 `_row_to_entry` 统一整形（file_library.py:433-447）。

### 3.2 查询/读取链路

- 列表/搜索都过滤 `is_deleted = 0`，按 `created_at DESC, id DESC` 排序（file_library.py:379-409）；搜索是文件名大小写不敏感 LIKE 子串（:392-409，pattern 在 :399 拼 `%...%`）。
- `get_file` **不过滤**软删（:297-305）——路由下载端点自行检查 `is_deleted` 后才给文件（router:113-115、140-142）；`GET /{id}` 返回含软删条目是文档化行为（router:94-103）。
- `resolve_path` 只认活跃行且要求磁盘文件真实存在，否则 None（file_library.py:415-427）——DB 与磁盘不一致时收敛为"读不到"，不抛错。
- 下载直接 `FileResponse` 流式返回，`Cache-Control: immutable` 一年（router:106-130）：成立前提是同一 `file_id` 内容永不改变——去重语义（同内容复用旧 id）恰好保证了这一点。

### 3.3 删除与清理链路

- 软删：`UPDATE ... SET is_deleted=1`，磁盘文件**不动**（可恢复）；幂等：已删再删返回 True，不存在返回 False（file_library.py:307-323）。
- 恢复：反向 UPDATE，幂等（file_library.py:349-365）。HTTP 面只有软删与恢复（router:148-169）。
- **硬删是唯一物理清理入口，且没有 HTTP 端点**：`hard_delete_file` 要求条目已软删，先删 DB 行、commit，再在连接外删磁盘文件（file_library.py:325-347，顺序注释见 :345）。磁盘删除 `_delete_file`（:191-206）：unlink 失败仅 warning（:196-197）；随后自底向上回收空父目录，`is_relative_to(root)` 兜底防越界，到 root 停（:199-204），整段异常全吞（:205-206）。
- 工作区数据迁移完成后 `_clear_store_caches()` 会 `reset_file_library_store()` 清空单例缓存（data_migration.py:974-978；`reset` 定义 file_library.py:478-480），否则迁移后旧实例仍指向旧根目录。

## 4. 失败模式清单（读代码要盯的点）

| # | 场景 | 锚点 | 后果 |
|---|---|---|---|
| 1 | 写盘成功但 INSERT 因非完整性错误失败（如 DB 锁超时 30s、磁盘满） | file_library.py:253→255-265 | 磁盘留下无 DB 行的孤儿文件；无 GC 任务回收 |
| 2 | 进程在 `_write_file` 与 `commit` 之间崩溃 | file_library.py:253、265 | 同上，孤儿文件 |
| 3 | 硬删时 unlink 失败（权限/占用） | file_library.py:342-346、196-197 | DB 行已删、文件留存 → 永久孤儿，无再发现路径 |
| 4 | 父目录回收静默失败 | file_library.py:205-206 | 空目录残留（无功能影响）；AGEN-432/457 用测试锁定现状，非缺陷 |
| 5 | 老库存在重复活跃行时唯一索引建不起来 | file_library.py:148-158 | 降级：跨进程去重失效，仅剩进程内 `_add_lock` 兜底 |
| 6 | 搜索词含 `%`/`_` | file_library.py:399 | LIKE 通配符未转义，`100%` 匹配面意外放大（良性怪癖） |
| 7 | 软删后重新上传同内容 | file_library.py:239-244（只查活跃行） | 生成第二条目+第二份磁盘文件；去重范围 = 活跃条目，非全表 |
| 8 | SQLite 未开 WAL，每调用新建连接 | file_library.py:113-122、116 | 靠短事务 + 30s busy timeout 抗并发；高频写场景会放大锁等待 |
| 9 | 迁移/换根后未清缓存（若绕过 `_clear_store_caches`） | file_library.py:454、467-468 | 旧实例继续写旧根 |

## 5. 与 #1138（内容寻址去重）现状衔接

### 5.1 file_library 现状：三层防重（进程内/DB 层/竞态回收）

1. 进程内：`threading.Lock` 串行化"查-写-插"序列（file_library.py:103-106、237）——注释明确它只保护单进程；
2. DB 层：`CREATE UNIQUE INDEX ... WHERE is_deleted = 0` 部分唯一索引兜底跨进程（file_library.py:143-152）；初始化时先 DROP 旧的普通索引再建唯一索引（:147）；
3. 竞态回收：撞索引后丢弃自己写的文件、复用胜者（file_library.py:266-278）。

注意：这是**每用户范围内**的去重（DB 与文件树都在 user_root 下），且只覆盖 library 自身；与聊天附件、阅读、知识库之间互不去重——这正是 #1138 要解决的问题。

### 5.2 上游在途实现：PR #1218（OPEN，覆盖 #1138 第一阶段）

> 按储备卡规则先查上游：#1138 已有关联 PR **#1218** `feat(storage): content-addressed dedup for chat attachments`（2 commits，OPEN）。本导读第 7 节给出审查结论；本卡不做实现，无在途冲突。

PR #1218 的落点全部在 `attachment_store` 侧，**不改 file_library**：

- 新增 `deeptutor/services/storage/blob_store.py`：`ContentAddressedBlobStore`，SHA-256 对象库 + 按 label 引用计数，布局 `{blob_root}/objects/<ab>/<sha256>` + `refs/<ab>/<sha256>.json`，per-digest 锁；
- `LocalDiskAttachmentStore.put` 改为先 `blobs.put()` 再 `link_or_copy()` 硬链接/拷贝回 session 路径，URL 形状不变；session 文件旁落 `.cas.json` sidecar 记 `sha256/label/materialize`；
- 删除链路改为读 sidecar → `blobs.release(label)` 减引用计数，计数归零才删对象；
- blob 根可配 `chat_attachment_blob_dir`，默认取附件目录同级 `attachment_blobs`。

### 5.3 file_library 侧的去重改造落点（若后续接入 #1138 体系）

按影响面从小到大：

1. **写路径替换**：`_add_file_sync` 中 `_write_file(library_path, data)`（file_library.py:253）改为向共享 blob catalog `put()` + `link_or_copy()`；`library_path` 字段语义不变，磁盘上变成硬链接即可，`resolve_path`（:415-427）与下载端点零改动；
2. **删除语义升级**：`_delete_file`（:191-206）的"直接 unlink + 回收空父目录"要换成 sidecar 引用计数 release——因为硬链接下 unlink 本文件不影响其他引用者，但 `hard_delete` 的"先删行后删文件"顺序（:342-346）在引用计数模型下要改成"先 release 再删行"，否则计数虚高；
3. **孤儿治理**：第 4 节 #1/#2/#3 的孤儿文件在 CAS 模型下可被 blob catalog 的 GC（扫描 objects 对比 refs）统一回收，这是接入后的附带收益；
4. **根布局**：仿 PR #1218 的 `_blob_root`，在 `workspace/library/` 下放 `blob_root`，或与 attachments 共用一个 catalog 实现跨子系统去重（#1138 的终极目标）；
5. **约束提醒**：`_add_lock`（:106）与部分唯一索引（:149-152）保护的是 `library_files` 表的行唯一性，blob 化后仍需保留（行 → blob 引用的映射依然要求每用户每内容至多一个活跃行）。

## 6. 与 test-file-library 卡的分工边界（验收 2）

- **本卡（AGEN-449，导读）**：只读产出文档；覆盖全模块——数据流、路径处理、失败模式、#1138 衔接；不改任何代码，不新增测试。
- **test-file-library 卡（AGEN-432 原卡 + AGEN-457 返工，已 in_review）**：行为测试侧，锁定 `delete_file`/`hard_delete_file` 的**物理磁盘清理与失败路径**（对应本文第 4 节 #3/#4，锚点 file_library.py:196-197、203-206；6 用例并入 `tests/services/storage/test_file_library.py`，覆盖率 84%→87%）。
- 边界：本卡的失败模式清单是**读代码得出的静态结论**，不落测试；AGEN-432/457 只对其中删除/清理分支做测试固化。若后续要为第 4 节 #1/#2（孤儿文件）补测试，属新卡范围，两卡都不含。

## 7. PR #1218 审查结论（中文，按储备卡"已有 PR 改复核"要求）

**总体**：方向正确、实现自洽，可作为 #1138 第一阶段合入；与 file_library 无冲突（diff 未触及 `file_library.py`，仅 `attachment_store.py`、新增 `blob_store.py`、`__init__.py` 及新测试文件）。

**优点**：URL 与 session 路径形状不变（对前端零感知）；引用计数 + sidecar 让删除语义干净；blob 根跟随自定义附件目录（sibling 策略）；per-digest 锁 + JSON refs 的无数据库实现与现有 storage 层风格一致。

**关注点（供人决定合入时参考）**：
1. 引用计数 refcount JSON 非原子多进程并发写场景下的正确性依赖 per-digest 锁（进程内）——与 file_library `_add_lock` 同样的单进程边界，多 worker 部署时同内容并发 release 存在丢更新窗口（与 #1138 目标相比是可接受的第一阶段取舍，但值得在 PR 里注明）；
2. `.cas.json` sidecar 与旧数据兼容：存量附件无 sidecar，删除路径 `_release_file` 读不到就跳过 release——旧文件照旧整删，行为兼容，无迁移负担（审查确认）；
3. 硬链接失败自动降级拷贝（`materialize` 字段记录），跨设备场景已覆盖；
4. 后续阶段（reading / knowledge-base 接入同一 catalog）在 blob_store docstring 中已预留契约（"Reading / knowledge-base stores can adopt the same catalog later"）——届时可按本文第 5.3 节落点改造 file_library。

## 8. PR 标题与正文草稿（本卡为纯文档，不向上游开 PR；草稿供人决定是否提交）

- **标题**: `docs(storage): add Chinese reading guide for FileLibraryStore (upload/dedup/cleanup paths)`
- **目标分支**: `dev`
- **正文要点**: 基于 origin/main v1.6.12 的 `deeptutor/services/storage/file_library.py` 模块导读，覆盖增删查数据流、路径安全模型（uuid 相对路径 vs attachment_store 的 safe_join）、失败模式清单、#1138/PR #1218 衔接与后续去重改造落点；纯文档，无产品代码改动。
