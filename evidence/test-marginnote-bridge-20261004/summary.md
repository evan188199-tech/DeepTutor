# test-marginnote-bridge-20261004 — AGEN-442

## 结论

PASS — 新增契约测试 11 passed；回归邻域 60 passed；tests/api 全量 757 passed。产品代码零改动。

## 背景（上游 #1242）

#1242 指出 v0.1.0 旧插件的 `addon.js`（191/222 行）硬编码 `/api/v1/marginnote4/...`，
而服务端 v1.5.16 实际挂载 `/api/marginnote4/*`，客户端与服务端路径漂移导致旧插件永远打不通。
本卡为服务端桥路由补契约测试，锁死挂载前缀、鉴权边界与请求/响应形状。

## 与 #1242 缺陷项的对应

| #1242 缺陷项 | 本测试覆盖 |
|---|---|
| `addon.js:191/222` 硬编码 `/api/v1/marginnote4/...` 与实际挂载 `/api/marginnote4/*` 不一致 | `test_route_surface_is_exactly_the_six_documented_endpoints`、`test_no_bridge_route_is_served_under_api_v1`、`test_drifted_v1_urls_return_404` |
| 旧插件无法以配对凭据直连（headless 同步路径） | `test_device_routes_accept_a_device_token_without_any_session`、`test_device_routes_reject_without_device_credentials` |
| `main.js` MN3 契约、`addon.js:155` 语法错误、manifest MN3 版本基线 | 客户端包缺陷，无服务端测试面，不在本卡范围（docstring 已注明） |

## 覆盖（tests/api/test_marginnote4_bridge_contract.py）

1. 路由面：以 main.py 同款 include（prefix=/api/marginnote4 + tags）挂载后，枚举有效路由
   （兼容 FastAPI 0.141 非扁平表示），断言恰好 6 条、路径与方法一一对应（pair POST、
   devices GET、devices/{id} DELETE、status GET、sync POST、heartbeat POST）。
2. 前缀漂移：结构断言 app 中不存在 `/api/v1/marginnote4` 开头路由；行为断言旧插件会发的
   5 个 `/api/v1/marginnote4/*` 请求全部 404。
3. 鉴权边界：会话端点（pair/devices/devices/{id}/status）在 AUTH_ENABLED=true 且无凭据时
   一律 401 "Not authenticated"；设备端点（sync/heartbeat）不声明 require_auth 依赖，
   仅凭 `Authorization: MarginNote <device_id>:<token>` 通过，缺失/畸形设备凭据得到的是
   设备侧 401（与 会话 401 文案可区分）。
4. 请求/响应形状：pair 响应恰为 {device_id, token, device_name, device_kind}（含默认值）；
   sync 请求接受 SyncObjectIn 全字段、响应恰为 {stored, updated, deleted, new_cursor}；
   devices 列表元素恰为 6 字段；revoke 响应恰为 {status, device_id}、404 分支；
   status 恰为 {status, devices, objects}。

## 不重叠声明

- 与既有 `tests/api/test_marginnote4_router.py`（鉴权行为/磁盘写入防护）互补不重复。
- 与 PR #1243（打包 MN4 add-on 客户端，加载端）无文件交集，未触碰任何客户端包内容。

## 测试命令与数字

```
cd /Users/Shared/DeepTutor-worktrees/agen442-mn4-bridge-contract
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/api/test_marginnote4_bridge_contract.py -v
=> 11 passed
邻域回归：+ tests/api/test_marginnote4_router.py + tests/capabilities/marginnote4/
=> 60 passed
tests/api 全量
=> 757 passed, 5 warnings
```

详见 pytest.txt / pytest-neighborhood.txt / pytest-api-suite.txt。

## 分支

- 基线：origin/main @ ef2d9e5c3（v1.6.12，新 worktree + 新分支）
- 分支：`test/marginnote4-bridge-contract-20261004`
- 变更：仅新增 `tests/api/test_marginnote4_bridge_contract.py` + 本 evidence 目录；未改产品代码。
- 推送：`git push myfork HEAD:refs/heads/test/marginnote4-bridge-contract-20261004`；未向上游开 PR（按储备卡规则）。
