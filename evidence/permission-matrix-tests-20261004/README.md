# 多用户 API 权限矩阵边界补测证据（2026-10-04）

基线：`origin/main` @ `f07029cfc`（release: v1.6.13）
分支：`test/perm-matrix-20261004`（worktree：`/Users/Shared/DeepTutor-worktrees/agen565-perm-matrix`）

## 交付物

- `tests/api/test_permission_matrix.py` — 47 个 pytest 用例（47 个矩阵格，每格恰一个状态码断言），覆盖 learner / teacher / admin（外加匿名与无效 token）对 courses、chat（sessions）、知识库的读写边界与 403/404 语义。
- 本目录 README。

## 矩阵设计

身份三列：

- **learner**：`student` 角色 + `learner` preset（学习策略 allowed_surfaces = chat/reading）
- **teacher**：`teacher` 角色 + standard preset（普通非管理员账号）
- **admin**：`admin` 角色（独立 admin workspace）

路由按 `api/main.py` 的生产方式挂载（`[Depends(require_learning_surface)]`，其内部链 `require_auth` 完成 401 判定与请求 workspace 安装），因此任何一层权限门缺失都会被矩阵格捕获。每个用例使用独立的临时部署（tmp_path 下的用户/系统目录、独立身份库、独立会话库），种子资源（learner 的课程/会话/知识库、teacher 的知识库）经认证作用域真实创建。

### 矩阵（预期值；✓ = 当前实现符合，✗ = 当前实现不符，为红格）

未认证一律拒绝：

| 资源域 | 匿名 / 无效 token | 结果 |
| --- | --- | --- |
| courses 读/写、chat 读/写、知识库 读/写/条目、账号管理读 | 401 | ✓（8 格 + 无效 token 1 格） |

learner（学习账号）：

| 格 | 预期 | 结果 |
| --- | --- | --- |
| courses 列表 / 自建 / 自查 state / 自删 | 200 | ✓ |
| chat 列表 / 改自己会话 | 200 | ✓ |
| chat 改不存在会话 | 404 | ✓ |
| 知识库列表 / 不存在条目 | 200 / 404 | ✓ |
| 知识库创建 / 上传 / 删除 | 403 | ✓ |
| 引擎配置读（rag-providers） | 403 | ✓ |
| 账号管理读（multi-user users） | 403 | ✓ |

teacher（普通非管理员）：

| 格 | 预期 | 结果 |
| --- | --- | --- |
| courses 列表 / 自建 | 200 | ✓ |
| 他人课程 改名 / 改大纲 / 删除 | 404 | ✓ |
| chat 列表 | 200 | ✓ |
| 他人会话改名 | 404 | ✓ |
| 知识库列表 / 自建 / 自查 / 自删 | 200 | ✓ |
| 他人知识库读 | 404 | ✓ |
| 账号管理读 / 他人授权写 | 403 | ✓ |
| 引擎配置写：configs/sync | 403 | ✗ 实际 200 |
| 引擎配置写：active-model | 403 | ✗ 实际 400 |
| 引擎配置写：provider mode | 403 | ✗ 实际 404 |

admin：

| 格 | 预期 | 结果 |
| --- | --- | --- |
| courses 列表 / 自建 | 200 | ✓ |
| 用户域课程改名（admin 作用域与用户域隔离） | 404 | ✓ |
| chat 列表 / 知识库列表 | 200 | ✓ |
| 用户域知识库读 | 404 | ✓ |
| 账号管理读 | 200 | ✓ |

## 红格说明（中性）

三条红格同属一类：知识库**引擎级配置写接口**（`POST /api/knowledge-bases/configs/sync`、`PUT /api/knowledge-bases/rag-pipelines/active-model`、`PUT /api/knowledge-bases/rag-providers/{provider}/mode`）作用于全部署共享状态。同文件内同类接口已有先例——`PUT rag-pipelines/lightrag/config`、weknora / kiwix 的 probe/connect 均带 `Depends(require_admin)`，而上述三条接口目前只挂载级 `_auth`，非管理员请求会越过权限层进入处理逻辑（校验或执行）。预期行为（测试断言）是：非管理员无论请求体如何一律 403，授权先于校验与资源解析。

修复方向（供人工决策，不在本卡范围内）：为三条接口补 `dependencies=[Depends(require_admin)]`，与同文件既有管理员接口对齐；随后三条红格转绿，其余 44 格不受影响。

## 命令与数字

```
python -m pytest -q -p no:cacheprovider tests/api/test_permission_matrix.py
# 3 failed, 44 passed in ~5.3s（3 failed 为上述红格，属本卡预期的失败测试）

# 相邻用例回归抽查（两种顺序各跑一次，均无相互影响）
python -m pytest -q -p no:cacheprovider tests/api/test_auth_contextvar.py tests/api/test_permission_matrix.py tests/api/test_courses_router.py
# 3 failed, 66 passed（failed 均为本卡红格）
python -m pytest -q -p no:cacheprovider tests/api/test_courses_router.py tests/api/test_permission_matrix.py
# 3 failed, 59 passed（同上）

# lint
ruff check tests/api/test_permission_matrix.py   # All checks passed
ruff format --check tests/api/test_permission_matrix.py   # clean
```

## 边界确认

- `git status` 仅新增 `tests/api/test_permission_matrix.py` 与本 evidence 目录；未改任何产品代码。
- 断言只描述预期状态码语义，不含任何绕过步骤或利用细节。
- 测试全部离线：不触网、不启动服务器，服务层副作用隔离在每用例的临时目录内。
