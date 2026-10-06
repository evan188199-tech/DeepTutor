# 任务板（Task Board / Kanban）导读

> 面向后续修复与补测卡的模块导读。行号基于 `origin/main` @ `2eb2f2de9` 之后（v1.6.13，`f07029cfc`）。
> 注意：服务实现位于 `deeptutor/services/task_board.py`（非顶层 `services/`），任务卡中的 `services/task_board.py` 指此文件。

## 模块地图

```
web/app/(workspace)/kanban/page.tsx        看板 UI（单页客户端组件）
        │  fetch(POST/PATCH) → 全量快照
web/lib/task-board-api.ts                  前端 API 封装（3 个函数）
        │  apiFetch + scopedUrl（自动带 dt_workspace / cookie）
deeptutor/api/main.py:638-640              挂载 /api/task-board，dependencies=_auth
deeptutor/api/routers/task_board.py        路由层：GET / POST /cards / PATCH /cards/{id}
        │  get_task_board_store()
deeptutor/services/task_board.py           服务层：Pydantic 模型 + SQLite 存储
        │  get_path_service().get_workspace_dir()
deeptutor/services/path_service.py:222     路径解析 → <用户数据>/workspace/task-board/cards.sqlite
```

一次请求的完整链路：UI → `apiFetch`（注入 `credentials: include` 与 `dt_workspace`，`web/shared/api/client.ts:36`）→ `require_learning_surface`（`deeptutor/api/main.py:591`，`_auth` 依赖）→ 路由 → `TaskBoardStore` → 工作区私有 SQLite 文件。

## 数据模型

### SQLite 表（DDL 内嵌于代码，无迁移文件）

`deeptutor/services/task_board.py:74-84`，`_connect()` 每次连接执行 `CREATE TABLE IF NOT EXISTS`：

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | TEXT | PRIMARY KEY，`uuid4().hex`（生成于 :105） |
| `title` | TEXT | NOT NULL |
| `note` | TEXT | NOT NULL DEFAULT '' |
| `status` | TEXT | NOT NULL `CHECK(status IN ('todo','doing','done'))` |
| `archived` | INTEGER | NOT NULL DEFAULT 0 `CHECK(archived IN (0,1))` |
| `created_at` / `updated_at` | TEXT | ISO-8601 UTC（含时区，:101、:130） |

CHECK 约束是落盘层的最后防线；API 层由 Pydantic 先行拦截，正常路径到不了 CHECK。

### Pydantic 模型（API 边界校验）

- `TaskStatus = Literal["todo","doing","done"]`（:17）
- `TaskTitle`：strip 空白后 1–160 字符（:18）
- `TaskNote`：≤2000 字符（:19）
- `CreateCard`：`extra="forbid"`，title/note（:22-27）；id、时间戳由服务端生成
- `UpdateCard`：全部可选 + `extra="forbid"`；`reject_null` 校验器（:39-45）——**省略字段=不改，显式传 null=422**
- `TaskCard`：持久化完整形态（:48-55）；`TaskBoard = {cards: [...]}` 全量快照（:58-61）

### 存储位置与隔离

`get_task_board_store()`（:137-139）→ `get_workspace_dir()/task-board/cards.sqlite`。
`get_workspace_dir()` = `<user_data>/workspace`（`deeptutor/services/path_service.py:222-223`）。
实际打开哪个目录由请求时安装的 workspace 上下文决定（见"多用户与权限"）。**没有卡片级 ACL——隔离完全靠目录路径**，每个 用户×内容工作区 一个独立 sqlite 文件。

## 状态机（文字版）

- `status ∈ {todo, doing, done}`，**无服务端转移规则**：PATCH 可从任意状态跳到任意状态（含回退）；前端按钮只是视觉上的左右箭头（`web/app/(workspace)/kanban/page.tsx:277-308`），拖拽同理。
- 新卡固定落 `todo`、`archived=0`（`deeptutor/services/task_board.py:104`），POST 无 status 入参。
- `archived` 是与 status 正交的布尔开关：归档不改 status；恢复（`archived:false`）保留原 status。前端"已归档"视图与活跃视图互斥显示（page.tsx:83）。
- 无删除：卡片只能归档，不能物理删除（无 DELETE 端点）。

## 并发与事务

- 每操作短连接，不缓存连接（:65 注释、:70-85）；`timeout=10` 等锁（:72）。
- `update()` 用 `BEGIN IMMEDIATE` 把读-改-写序列化到进程间（:116-117）；字段级合并：`model_dump(exclude_unset=True)` 只覆盖显式传入的字段（:113、:121），两个并发 PATCH 改不同字段可共存（测试 `tests/multi_user/test_task_board.py:220-231`）。
- 所有写操作（含 create/update）在事务内返回**全量快照**（:107、:134），前端直接以响应整体替换本地 state（page.tsx:66），服务端是唯一事实源。
- `update()` 对不存在的 id 抛 `KeyError` → 路由转 404（`deeptutor/api/routers/task_board.py:25-28`）；事务随之回滚。
- 排序 `ORDER BY created_at, id`（:89）：created_at 是 ISO 字符串可字典序排序，同秒创建的卡按随机 uuid 排，顺序不稳定（低风险）。

## 前后端接口对照

| 前端（`web/lib/task-board-api.ts`） | 后端（`deeptutor/api/routers/task_board.py`） | 成功 | 失败 |
|---|---|---|---|
| `getTaskBoard(signal)` GET `/api/task-board`（:27-29） | `get_board`（:10-13） | 200 `{cards}` | 401/403/404（workspace 错误） |
| `createTaskCard(title)` POST `/api/task-board/cards`，body 仅 `{title}`（:31-37） | `create_card`（:16-19） | 201 `{cards}` | 422（校验） |
| `updateTaskCard(id, changes)` PATCH `/api/task-board/cards/{id}`，body 部分字段（:39-48） | `update_card`（:22-28） | 200 `{cards}` | 404（无此卡）/ 422（校验） |

- 三个端点统一返回全量 `TaskBoard` 快照，前端无增量协议。
- 前端错误处理粗糙：`request()` 把一切非 2xx 折叠成 `Error('Task board request failed')`（task-board-api.ts:23），页面只显示 `kanban.loadError` / `kanban.saveError` 两类文案（page.tsx:55、:69），不区分 404/422/500。
- 前端在输入层用 `maxLength={160}` / `{2000}` 复制了后端上限（page.tsx:133、:239），与 `deeptutor/services/task_board.py:18-19` 无共享来源。
- `createTaskCard` 只传 title；后端 `CreateCard` 其实接受 note，前端创建时无备注入口（创建后再编辑才能加）。

## 认证与多用户权限

1. **认证**：路由挂载带 `dependencies=_auth`（`deeptutor/api/main.py:638-640`），`_auth = [Depends(require_learning_surface)]`（:591）；`require_learning_surface` 内部先 `require_auth`（`deeptutor/api/routers/auth.py:689-704`），未登录/无效 token → 401。
2. **学习面策略（learner 专属门槛）**：`/api/task-board` 被映射到 `chat` surface（`deeptutor/api/routers/auth.py:648-649`）；learner 账号的 `learning_policy.allowed_surfaces` 不含 `chat` 时全部 403（测试 :61-98）。
3. **工作区选择**：请求级上下文由 `_install_request_workspace` 安装（auth.py:474-526），来源为 `dt_workspace` query 或 `x-deeptutor-workspace` header，两者冲突 → 400；归档工作区上的写操作 → `WorkspaceError` → 404（auth.py:516、:524-526）；访问他人工作区 → `WorkspaceError`（`deeptutor/services/workspace/context.py:153`）→ 404。
4. **数据隔离**：卡片存于请求工作区目录，跨账号 PATCH 他人的卡等价于"换了一个空库"→ `KeyError` → 404（测试 :151-160、:163-204）。任务卡对 learner 是"当前内容工作区"的私有数据。

## 关键文件表

| 文件 | 行 | 职责 |
|---|---|---|
| `deeptutor/services/task_board.py` | :17-19 | 状态/长度常量（唯一权威） |
| 同上 | :22-61 | CreateCard/UpdateCard/TaskCard/TaskBoard 模型 |
| 同上 | :64-134 | TaskBoardStore：DDL、read/create/update、事务 |
| 同上 | :137-139 | get_task_board_store：工作区路径解析 |
| `deeptutor/api/routers/task_board.py` | :10-28 | 3 个端点，KeyError→404 |
| `deeptutor/api/main.py` | :591, :638-640 | `_auth` 定义与路由挂载 |
| `deeptutor/api/routers/auth.py` | :648-649, :689-704 | surface 映射与守卫 |
| 同上 | :474-526 | workspace 上下文安装、归档写保护 |
| `deeptutor/services/workspace/context.py` | :65-81, :153 | resolve_workspace_scope、跨账号保护 |
| `deeptutor/services/path_service.py` | :222-223 | get_workspace_dir |
| `web/lib/task-board-api.ts` | :3-17, :19-48 | TS 类型镜像 + 3 个请求函数 |
| `web/app/(workspace)/kanban/page.tsx` | :27-31 | 三列定义 |
| 同上 | :44-74 | pending 互斥 + 全量替换 state |
| 同上 | :82-84 | 活跃/归档视图过滤 |
| `web/shared/api/client.ts` | :17-19, :36 | apiUrl→scopedUrl、credentials:include |
| `web/locales/*/app.json` | zh :5210 起 | `kanban.*` 扁平键（6 个语言齐全） |
| `tests/multi_user/test_task_board.py` | 全文 | 后端契约测试（8 个用例） |
| `web/tests/task-board.spec.tsx` | 全文 | 前端交互测试（4 个用例） |

## 测试覆盖与空白

已有（`tests/multi_user/test_task_board.py`）：401 门槛（:50）、chat surface 403（:61）、CRUD+归档+重载（:101）、非法创建 422（:130）、非法 PATCH 422 不改库（:139）、跨账号 404（:151）、工作区选择与归档写保护（:163）、多线程并发字段合并（:207）。
前端（`web/tests/task-board.spec.tsx`）：scoped fetch 断言（dt_workspace、credentials，:24-25）、拖拽+重挂载（:89）、保存失败保留草稿（:109）、加载失败重试（:123）。

空白清单（可拆补测卡）：

1. 后端无 `note` 上限边界（恰好 2000）与 title 恰好 160 的等价类正例。
2. 无"并发 PATCH 同一字段"的用例（现有并发用例只改不同字段，:223-225）。
3. 无 sqlite 文件损坏/`DatabaseError` 时的 API 行为测试（当前会 500）。
4. 前端测试未覆盖 404（陈旧卡片）与 422（超长）分支的 UI 表现。
5. 无看板数据量增长后的快照体积/性能测试（全量返回无分页）。
6. `createTaskCard` 未传 note 的契约（后端接受 note 但前端不发）无对齐测试。

## 契约风险点与可拆卡条目

风险点：

- **R1 双份常量无共享源**：`TaskStatus` 与 160/2000 上限在 TS（task-board-api.ts:3、page.tsx:133/:239）与 Python（task_board.py:17-19）各写一份，漂移只会表现为 422。
- **R2 全量快照协议**：每次增改都返回整个看板，`act()` 整体替换 state（page.tsx:66）。单浏览器内安全，但两个标签页并发时后写者会覆盖前写者界面上的他人改动（服务端字段合并只防"单次 PATCH 内"的互踩，不防界面级丢失更新）。
- **R3 错误粒度**：前端把 401 跳登录（client.ts:39-44）之外的一切失败折叠成一句文案，404（卡被别处归档/工作区切换陈旧）与 422（超长）不可区分，排障困难。
- **R4 无清理路径**：卡片只增不删，归档视图仍随 GET 全量返回；长期使用后快照线性膨胀。
- **R5 DDL 无迁移机制**：表结构演进（如加列、改 status 枚举）只能靠 `CREATE TABLE IF NOT EXISTS` 之后的 `ALTER`，目前代码里没有任何 schema 版本管理。

可拆卡条目（供排期）：

- 拆卡 A：补并发同字段 PATCH 用例 + note 2000/title 160 边界正例（对应空白 1/2）。
- 拆卡 B：前端错误分类（404/422 各自文案）+ 陈旧卡片重载（对应 R3、空白 4）。
- 拆卡 C：契约常量共享（codegenn 或 OpenAPI schema 校验）防 R1 漂移。
- 拆卡 D：卡片删除/清理策略与快照分页（对应 R4）。
- 拆卡 E：task_board schema 版本化迁移（对应 R5）。
