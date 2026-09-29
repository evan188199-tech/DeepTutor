# Fork-local features

Durable ledger of features this deployment maintains on top of upstream
`HKUDS/DeepTutor`. Each section is owned by its port card and must stay
mergeable against `origin/main` (see `DEVELOPMENT_WORKFLOW.md`).

Current baseline: `origin/main@ef2d9e5c3` (tag `v1.6.12`).

## Tailscale & Quick Tunnel Auth Handoff (方案 1 维护规范)

本功能为个人/私有部署专属，用于在 Tailscale 稳定地址上登录后，通过 Mac 屏幕动态二维码或一键跳转，免密安全切换至每日轮换的 Cloudflare Quick Tunnel (`*.trycloudflare.com`) 地址，并自动下发 30 天 HttpOnly 会话 Cookie。

### 架构与核心组件

1. **守护与轮换（0% 代码侵入）**：
   - `scripts/rotate_deeptutor_tunnel.sh`：每日定时触发（本地 launchd `com.deeptutor.rotate-tunnel`，私有配置不入库），HTTP/2 协议启动 `cloudflared`，捕获最新公网 URL 写入 `data/system/auth/deeptutor_tunnel.json`。
   - `~/Library/LaunchAgents/com.deeptutor.cloudflared.plist`：常驻隧道守护进程。
   - `~/Library/LaunchAgents/com.deeptutor.rotate-tunnel.plist`：定时轮换任务。
2. **后端状态机与路由（独立模块）**：
   - `deeptutor/services/tunnel_handoff.py`：单文件状态机，管理 120 秒一次性配对码 (`Pairing`)、60 秒一次性凭证 (`Ticket`)、隧道 Host 绑定校验，以及通用的 `SessionHandoff`（安全站内 redirect 与受限附加 Cookie，禁止注入/覆盖 `dt_token`、禁止重复或冲突 Cookie 名称，严格过滤路径注入与反斜杠跳转）。
   - `deeptutor/api/routers/auth.py`：挂载 `/handoff`、`/handoff/pairing`、`/handoff/pairing/{pairing_id}`、`/handoff/consume` 接口；私网 fail-closed 复用 v1.6.12 的 `_require_private_frontend`（`auth.json` 中的 `private_login_hosts` / `AUTH_PRIVATE_LOGIN_HOSTS` 显式 canonical host 合同，含端口，隐式放行 loopback）；普通账号交接默认清理旧 `dt_video_controller`。
   - 与上游 v1.6.12 自带的 `/session-handoff*`（用户手输公网 origin 的 SQLite+JWE 流程）并存：上游流程不动，本流程绑定运维轮换隧道。
3. **前端页面与代理策略（独立路由）**：
   - `web/app/(auth)/access/page.tsx`：Mac 已登录展示页，生成 120 秒动态二维码（`qrcode.react`）及「在此电脑上打开」直连入口。
   - `web/app/(auth)/access/device/page.tsx`：手机扫码落地页，免认证（`isAuthExempt`）获取一次性 Ticket 并自动 POST 提交至消费端。
   - 公网 Host 转发由上游 v1.6.12 的 `web/lib/backend-forward.ts`（`prepareBackendForwardHeaders` 清洗后设置 `x-deeptutor-frontend-host`）承担。
4. **反向代理身份守卫**：
   - Uvicorn 各启动点（`run_server.py`、`deeptutor_cli/main.py`、`launcher.py`、Dockerfile）统一设置 `--no-proxy-headers` (`proxy_headers=False`)，确保后端仅信任来自本机 Next.js 代理清洗后的 `x-deeptutor-frontend-host`；`tests/runtime/test_uvicorn_launch_flags.py` 锁定所有启动点。

### 视频模块边界

通用 `SessionHandoff` 不含视频字段；feature 模块（后续 AGEN-49/50 卡迁移的 `video_remote_control` 路由）通过声明自己的 `dt_video_controller` Cookie 与 redirect 接入，在通用 replay 之后下发。

### 本地扩展边界

本能力保持“本地薄扩展”，暂不注册为 DeepTutor Tool/Capability 插件。现有插件协议只覆盖 LLM 工具和会话能力，不能声明 FastAPI 认证路由、登录前公共 Next.js 页面、代理豁免规则或跨域 Cookie 策略；强行包装会把认证入口和部署细节混入插件注册表。等官方提供 Web/API/Auth 扩展点后，再把 `SessionHandoff` 与 `/access/device` 迁移到正式插件协议。

### 上游（`origin/main`）更新同步与维护手册

当上游官方仓库更新并需要合并至本地时，按 `DEVELOPMENT_WORKFLOW.md` 的标准流程操作；如遇核心文件冲突：

* **`web/lib/proxy-policy.ts`**：确认 `isAuthExempt` 包含 `pathname.startsWith("/access/device")`。
* **`web/lib/backend-forward.ts`**：确认 `prepareBackendForwardHeaders` 仍以公网 `Host` 设置 `x-deeptutor-frontend-host` 并清洗客户端伪造的转发头。
* **`deeptutor/api/routers/auth.py`**：确认引入 `tunnel_handoff` 相关路由处理函数并保留 `/handoff` 路由定义；上游 `/session-handoff*` 路由保持不动。
* **`run_server.py` / `launcher.py` / `deeptutor_cli/main.py` / `Dockerfile`**：确认 Uvicorn 启动参数包含 `proxy_headers=False` 或 `--no-proxy-headers`。

### 本地回归验证门禁

```bash
.venv/bin/python -m pytest \
  tests/api/test_auth_tunnel_handoff.py \
  tests/runtime/test_uvicorn_launch_flags.py \
  tests/test_local_feature_contract.py
cd web && npm run test:node && npm run lint && npm run build
```
