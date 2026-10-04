# API 路由鉴权依赖矩阵补测证据（2026-10-04）

卡：AGEN-483（test: API 鉴权依赖矩阵补测）
基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12）
分支：`test/auth-matrix-20261004`（worktree：`/Users/Shared/DeepTutor-worktrees/agen483-auth-matrix`）

## 交付物

- `tests/api/test_auth_matrix.py` — 34 个 pytest 用例，覆盖 settings / knowledge / sessions / partners 四个代表路由的鉴权依赖矩阵（匿名、无效 token、普通用户、管理员）。

## 覆盖范围（对应验收 1）

被测链路：`api/main.py` 的 `_auth = [Depends(require_learning_surface)]` 挂载方式 → `require_auth`（401 判定 + `set_current_user` 安装 ContextVar）→ `require_admin` / 路由内 `_require_settings_admin()`。测试按生产方式挂载路由（同样经 `require_learning_surface`），因此若某路由从 main.py 挂载中丢失鉴权依赖、或路由自身丢失 `Depends(require_admin)` / 内联管理员检查，都会被矩阵行捕获。

抽样路由（每条 × 四类身份 = 32 个矩阵断言）：

| 路由 | 类型 | 匿名 | 无效 token | 普通用户 | 管理员 |
| --- | --- | --- | --- | --- | --- |
| GET /api/settings/llm-options | 开放（登录即可） | 401 | 401 | 200 | 200 |
| GET /api/settings/presets | 仅管理员 | 401 | 401 | 403 | 200 |
| GET /api/knowledge-bases/health | 开放 | 401 | 401 | 200 | 200 |
| GET /api/knowledge-bases/kiwix-catalog | 仅管理员（`Depends(require_admin)`） | 401 | 401 | 403 | 200 |
| GET /api/sessions | 开放 | 401 | 401 | 200 | 200 |
| GET /api/sessions/search | 开放 | 401 | 401 | 200 | 200 |
| GET /api/partners/souls | 开放 | 401 | 401 | 200 | 200 |
| POST /api/partners/souls | 仅管理员（`Depends(require_admin)`） | 401 | 401 | 403 | 200 |

另有 2 个身份安装用例：

1. `test_sessions_requests_run_as_the_token_identity` — sessions 路由自身不引用 `current_user`，作用域收敛在服务层。用记录型假 store 捕获 handler 执行时 `get_current_user().id`，断言普通用户请求以 `matrix-user-1`、管理员请求以 `matrix-admin-1` 身份到达服务层（证明 `require_auth` 真正装入了调用者身份，而非落到 local-admin 兜底）。
2. `test_invalid_token_is_never_installed_as_local_admin` — 无效 token 得到 401，且服务层从未被调用（记录列表为空）。

与既有覆盖的边界：learning API 的鉴权已由 test-learning-records 卡覆盖，本卡未重复；mcp-settings 的管理员门已有 `test_mcp_settings_auth.py`，未重复。

## 测试环境处理

- 断言只依赖状态码与假服务的返回形状，服务层触点（KB manager、soul manager、session store、模型 catalog、KiwixClient.list_archives）全部以 monkeypatch 替身注入，不触网、不写真实数据目录。
- `require_auth` 附带的 workspace 装簿（`install_workspace_scope` / `acquire_activity`）替换为惰性替身——鉴权矩阵不关心该机制。
- worktree 内 `data/user/settings/main.yaml` 为本地最小桩文件（gitignored，不入库），仅为满足 knowledge 路由模块导入时的配置读取。

## 命令与数字（对应验收 2）

```
python -m pytest -q -p no:cacheprovider tests/api/test_auth_matrix.py
# 34 passed in 1.26s
```

相关既有用例回归抽查（未受影响）：

```
python -m pytest -q -p no:cacheprovider tests/api/test_mcp_settings_auth.py tests/api/test_settings_presets.py tests/api/test_sessions_recycle.py
# 12 passed in 0.36s
```

## 边界确认（对应验收 3）

- `git status` 仅有新增 `tests/api/test_auth_matrix.py` 与本 evidence 目录，未改任何产品代码。
- 覆盖路由数：4 个路由文件、8 条抽样路由、34 个用例。
