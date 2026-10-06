# DeepTutor MarginNote 桥接契约导读

- 基线：origin/main @ `f07029cfc`（v1.6.13）。锚点形如 `path:line`，相对仓库根，行号已在该 commit 核对。
- 背景：上游 #1242 指出桥贡献者发布的 add-on v0.1.0 是 MN3 契约包，MN4 无法加载。本文梳理服务端桥的契约面，供评估 #1242 后续方向；开放 PR #1243（Closes #1242）自带 MN4 原生 add-on，要点见 §7。

## 1. 集成面总览

MarginNote 4 知识库是一种"指针型"KB：`type: marginnote4`（`deeptutor/knowledge/kb_types.py:95`），不参与 RAG 检索（`kb_types.py:123`）。库内没有文档——数据全部由 MN4 add-on 经 HTTP 桥推送：

- 注册库：`deeptutor/knowledge/manager.py:1033` `register_marginnote4_kb` 只写配置指针，`db_path` 可省略；同库冲突拒绝在 `manager.py:1086`。
- 存储层：`deeptutor/capabilities/marginnote4/store.py:39` 四张表——`mn4_objects`（主键 `(object_id, device_id)`）、`mn4_devices`（只存 token 哈希）、`mn4_cursors`、`mn4_tombstones`。库文件在 `<data>/marginnote4/<kb>.db`（`store.py:96`）。
- 库与 store 的唯一解析点：`store.py:112` `resolve_db_path`（KB 可钉 `db_path`，否则按名派生）。pairing 与 sync 必须解析到同一 store，否则令牌永远 403。
- AI 侧消费：capability `marginnote4`（`deeptutor/capabilities/marginnote4/capability.py:31`）经 `binding.py:19` 绑定会话选中的 MN4 库，暴露 7 个只读工具（`tools.py:25`）：search/read/list/documents/links/tags/cards。

## 2. 服务端桥路由（挂载 `/api/marginnote4`，`deeptutor/api/main.py:777`）

| 方法+路径 | 鉴权 | 请求 → 响应 | 失败路径 |
|---|---|---|---|
| POST `/pair` | 会话 | `PairRequest` → `PairResponse` | 501 工作区不一致 `routers/marginnote4.py:156` |
| GET `/devices` | 会话 | → `DeviceInfo[]` | — |
| DELETE `/devices/{id}` | 会话 | → `{status, device_id}` | 404 未知设备 `routers/marginnote4.py:199` |
| GET `/status` | 会话 | → `{status, devices, objects}` | — |
| POST `/sync` | 设备令牌 | `SyncRequest` → `SyncResponse` | 401/403/422 见 §4 |
| POST `/heartbeat` | 设备令牌 | → `{status, device_id, object_count}` | 401/403 |

两层鉴权（`routers/marginnote4.py:6`）：会话层走 JWT（Bearer 头或 dt_token cookie，`routers/auth.py:419`）；设备层格式 `Authorization: MarginNote <device_id>:<token>`（`routers/marginnote4.py:68`）。选库用 `X-MN4-KB` 头（缺省 `default`，`routers/marginnote4.py:40`）——它只是选择器，凭据仍是设备令牌。Web 端参考实现：`web/lib/marginnote4-api.ts:18`（BASE）、`:43`（选库头）。

## 3. add-on 期望的请求/响应形状

配对（`routers/marginnote4.py:149`）：请求 `{device_name ≤128, device_kind}` → 响应 `{device_id, token, device_name, device_kind}`。`token` 只在下发时可见，服务端只存 SHA-256（`store.py:92`、`:232`）；Web UI 同样只展示一次（`web/components/knowledge/KbMarginNoteDevicesSection.tsx:182`）。add-on 持久化 `device_id:token`，之后每个 sync/heartbeat 都带上。

增量同步（`routers/marginnote4.py:217`）：

- `SyncRequest`（`:121`）：`cursor ≤256`（不透明记账值，服务端不据此过滤）、`objects ≤2000`、`deleted_ids ≤2000`（上限 `MAX_SYNC_BATCH` `:37`，超限 pydantic 422）。
- `SyncObjectIn`（`:104`）：`object_id`/`object_type` 必填，其余可省；`raw` 透传原始 MN4 JSON（`models.py:14`，前向兼容扩展点）。
- `object_type`：note/excerpt/card/mindmap_node/document/comment（`models.py:29`）；未知类型跳过不报错（`store.py:297`）。
- `SyncResponse`（`:130`）：`{stored, updated, deleted, new_cursor}`。upsert 冲突键 `(object_id, device_id)`（`store.py:311`）；删除写墓碑后物理删除（`store.py:346`）；游标每批推进为当前 UTC 时间（`store.py:358`）。分页语义：add-on 自行把积压切成 ≤2000 的批，服务端每批一个事务（`store.py:295`）。

## 4. 失败路径（add-on 需要处理）

| HTTP | 触发 | 锚点 |
|---|---|---|
| 401 | 无/malformed Authorization；会话令牌缺失或过期 | `routers/marginnote4.py:76`；`routers/auth.py:453`、`:461` |
| 403 | 令牌不匹配、设备已吊销、库尚未配对（无 db 文件） | `routers/marginnote4.py:82`；`store.py:160` |
| 404 | revoke 未知设备 | `routers/marginnote4.py:199` |
| 422 | cursor >256 或批 >2000 | `routers/marginnote4.py:121` |
| 501 | pairing 与 sync 解析到不同工作区（防发死凭据） | `routers/marginnote4.py:156` |

无 db 文件时 `open_existing` 返回 None 而不是建库（`store.py:160`）：未认证请求不能靠编造 `X-MN4-KB` 在磁盘生成目录与库。重试语义：401/403 应引导重新配对；422 是 add-on 批切分 bug；其余失败可幂等重放（upsert + 游标推进）。

## 5. 版本探测

服务端无版本协商：桥上没有任何 version 字段或 `/api/v1` 本地路由（`deeptutor/api/` 全目录 grep 仅命中出站调用，如 `deeptutor/api/routers/video_learning.py:466`），兼容性完全由 §3 线格式 + `raw` 透传承载。MN 版本差异在客户端消化——PR #1243 的 add-on 对 MN4 4.1.x（NSData 包装）与 4.4.x（已解析对象）两种回调形状做 shape-agnostic 解析。服务端唯一的"版本面"是 KB 类型 `marginnote4` 本身：MN3 从未被服务端支持。

## 6. MN3/MN4 契约差异与 #1242 的代码层对应

#1242 对 v0.1.0 包（外部仓库）的四点指控，逐一对照本仓库：

| #1242 指控（v0.1.0 包） | 服务端代码层对应点 |
|---|---|
| MN3 装载契约：`JSB.require` 装模块 + `JSB.newAddon(__dirname)` 挂载（main.js:23），MN4 无法加载 | 服务端只定义线契约，不涉装载层；MN4 原生入口是 `JSB.newAddon` 工厂（见 PR #1243 描述）。此差异纯在客户端，服务端无从兜底 |
| addon.js:155 多一个 `}`，文件无法通过语法解析 | 纯客户端缺陷；对应服务端事实是该包从未成功打过任何端点——本地不存在 `/api/v1/marginnote4` 路由可命中 |
| addon.js:191/222 硬编码 `/api/v1/marginnote4/...` | 服务端实际挂载 `/api/marginnote4`（`main.py:777`）；web 参考客户端同前缀（`marginnote4-api.ts:18`）→ 即使语法通过也全部 404 |
| manifest `marginnote_version_min: 3.7.11`（MN3 基线） | 声明仅在包内 manifest；服务端 KB 类型 `marginnote4`（`kb_types.py:95`）即隐含 MN4-only |

结论：#1242 是**单侧客户端契约漂移**——装载方式、语法、路径前缀、版本基线四个独立缺陷叠加；服务端契约自 v1.5.16 起自洽稳定，修复不需要动服务端。

## 7. 后续方向评估输入

- PR #1243（open，Closes #1242）：树内打包 MN4 原生 add-on（`packaging/marginnote4-addon/`，7 文件 +649），build 产物不进树；入口为 `JSB.newAddon` 工厂，批次 500（≤2000 上限），字段与 `SyncObjectIn` 一一对应。
- 已知局限（详见完成评论审查结论）：全量重扫非增量（cursor 恒为空串）、`deleted_ids` 恒空（删除不传播）、`tags` 恒空、外部仓库最新 1.1.3 与 PR 内 1.1.2 有版本差。
- Phase 2/3 未实现：MN4 写回 propose/apply/verify（`routers/marginnote4.py:14`）；学习事件仅建模无端点（`models.py:136`）。
- 测试锚点：`tests/api/test_marginnote4_router.py:50`（未认证不写盘）、`:95`（配对-同步往返）、`:151`（批量上限）；`web/tests/marginnote4-api.test.ts:32`（选库头契约）。
- 桥烟雾测试由独立的 test-marginnote-bridge 卡承载，本文未执行。
