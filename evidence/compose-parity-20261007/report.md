# Docker/compose 配置与代码默认值一致性清点（compose parity scan）

- 日期：2026-10-07
- 基线：origin/main @ `f07029cf`（release: v1.6.13），新 worktree + 分支 `scan/compose-parity-20261007`，全程只读（未改产品代码、未构建镜像）
- 范围：`Dockerfile`、`Dockerfile.runner`、`compose.yaml`、`compose.codex-oauth.yaml`、`docker-compose.yml`、`docker-compose.dev.yml`、`docker-compose.ghcr.yml`、`.env.example`、`scripts/docker_compose.py`，对照 `deeptutor/services/config/runtime_settings.py`、`deeptutor/api/main.py`、`web/proxy.ts`、sandbox/runner、workspace、cli_apps 等现行代码
- 去重说明：env 键轴（scan-env-config-drift）、docs 文档轴（docs-env-config-drift）、部署导读（guide-deploy）不在本卡重复；本卡只清点 Docker/compose 编排层与代码默认值/启动器假设的一致性。上游 issue/PR 无同题在办件。

## 总量

| 维度 | 核对项 | 一致 | 漂移 |
| --- | --- | --- | --- |
| 端口映射 | 13 | 11 | 2（D1、D3） |
| 卷挂载 | 11 | 10 | 1（D4） |
| 环境变量 | 13 | 12 | 1（D5） |
| 健康检查 | 8 | 7 | 1（D2） |
| 启动命令/依赖 | 9 | 7 | 1（D6） |
| **合计** | **54** | **47** | **6（另 4 条观察项）** |

## 漂移表

| # | 轴 | 严重度 | 漂移 | 证据（文件:行） | 影响 | 修复建议 |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | 端口 | 中 | podman 路径容器侧端口硬编码，与「端口由 system.json 驱动」的文档矛盾 | `compose.yaml:162-163`（右侧写死 8001/3782）vs `compose.yaml:57-62`、`.env.example:8-13`、`docs-for-user/CONTAINERIZATION.md:434-437`（称改 JSON + HOST_PORT_* 即可；HOST_PORT_* 只改宿主侧） | 改 `backend_port`/`frontend_port` 后映射失效，服务不可达 | 头注/env.example 明示 podman 路径须同时手改映射右侧，或引入与 docker 路径一致的渲染机制 |
| D2 | 健康检查 | 中 | compose.yaml 健康检查固定 `:8001`，与镜像内 JSON 自适应检查分歧 | `compose.yaml:190-195` vs `Dockerfile:517-539`（healthcheck.py 读 system.json）；端点本身存在 `deeptutor/api/main.py:801` | D1 同根：改端口后 compose 判 unhealthy | 改用镜像内 `/app/healthcheck.py`，或注明仅支持默认端口 |
| D3 | 端口 | 低 | Codex OAuth overlay 容器侧变量名与 podman 基础文件体系不匹配 | `compose.codex-oauth.yaml:8-9`（`${DEEPTUTOR_DOCKER_FRONTEND_PORT:-3782}`）vs `CONTAINERIZATION.md:188` 的 podman 组合用法（该体系只定义 `HOST_PORT_*`） | podman 组合下静默回落 3782，非默认 frontend_port 时回调断裂 | overlay 注明 podman 组合仅支持默认端口，或变量双兼容 |
| D4 | 卷 | 低 | dev 覆盖文件残留旧版 `/pb/pb_data` 挂载 | `docker-compose.dev.yml:15` vs `docker-compose.yml:57-64`（基础文件注释明确旧路径曾致崩溃、已迁移） | 卷合并按目标路径去重 → 死挂载并存，误导维护 | 删除 `docker-compose.dev.yml:13-15` 的 pocketbase 覆盖段 |
| D5 | 环境变量 | 低 | TZ 仅 podman 路径传递 | `compose.yaml:179-180`、`.env.example:26-27` vs `docker-compose.yml:100-124`、`docker-compose.ghcr.yml:79-100` 无 TZ | docker/ghcr 部署无法按既定方式设时区，两路径行为不一致 | 两个 docker compose 文件补 `TZ=${TZ:-UTC}` |
| D6 | 启动/依赖 | 低 | 「可选服务」文档语义与硬依赖门禁冲突 | `docker-compose.yml:133-139`、`compose.yaml:200-204`（pocketbase/redis `service_healthy` 硬依赖）vs 两文件自身注释与 `CONTAINERIZATION.md:445-446`（PocketBase 可选、SQLite 回退）、`runtime_settings.py:98-106`（默认 memory 后端、redis_url 空） | 不能按文档语义裁剪 sidecar；编排层无条件启动并门禁 | 注明「可选指应用层回退」，或提供精简变体 |

## 观察项（非漂移）

1. **O1** 宿主端口变量双命名：`HOST_PORT_*`（podman）与 `DEEPTUTOR_DOCKER_*`（docker，`scripts/docker_compose.py:46-71` 渲染）。两处头注均声明互不读取，属有意设计。
2. **O2** entrypoint unset 清单（`Dockerfile:342-367`）未覆盖 render_environment 全部导出键，但 `DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1`（`Dockerfile:117/337`，常量定义 `runtime_settings.py:384`）已整体忽略进程环境，良性。
3. **O3** `compose.yaml:58` 注释把 `./data` bind 称作 "the deeptutor-data volume"，与 `:174` 实际 bind 及 `:226-230` 不用命名卷的说明相悖，术语笔误。
4. **O4** `Dockerfile.runner:12` 手动运行示例 `-p 8900:8900` 与 compose「runner 不发布到宿主」的设计表述（`docker-compose.yml:153-154,180`）不一致，建议示例改 `127.0.0.1:8900:8900`。

## 抽样核实（≥5 条，对照现行代码）

| 主张 | 代码位置 | 结论 |
| --- | --- | --- |
| `/health/ready`、`/health/live` 端点存在 | `deeptutor/api/main.py:796,801` | 一致 |
| render_environment 导出 BACKEND_PORT/FRONTEND_PORT/DEEPTUTOR_API_BASE_URL 等 | `deeptutor/services/config/runtime_settings.py:704-753` | 一致 |
| 默认端口 8001/3782/8090 | `deeptutor/services/config/runtime_settings.py:23-25,94` | 一致 |
| docker.env 由 system.json/integrations.json 渲染 | `scripts/docker_compose.py:46-71` | 一致 |
| sandbox runner 环境名与 8900 端口、/health 端点 | `deeptutor/services/sandbox/config.py:32-33`、`runner/server.py:74,299-315,357-359` | 一致 |
| DEEPTUTOR_WORKSPACE_ROOT/ALLOWED_ROOTS 环境名 | `deeptutor/services/workspace/service.py:29-30` | 一致 |
| cli-apps 目录名（runner 只读挂载路径） | `deeptutor/services/cli_apps/paths.py:42,48` | 一致 |
| proxy.ts 请求时读 DEEPTUTOR_API_BASE_URL | `web/proxy.ts:17-18` | 一致 |
| get_ws_max_size / HTTP_KEEP_ALIVE_TIMEOUT 可导入 | `deeptutor/services/config/__init__.py:29,38` | 一致 |

完整逐项核对数据见同目录 `data.json`（54 项，含每条 文件:行 与判定）；校验和见 `SHA256SUMS`。

## 结论

整体一致性良好：docker 路径（docker-compose.yml/ghcr + `scripts/docker_compose.py`）端口、卷、健康检查、启动命令与代码默认值完全对齐；漂移集中在 **podman 路径（compose.yaml）的容器侧端口/健康检查硬编码（D1/D2，同一根因，中等严重度）** 与 4 处低危不一致（D3-D6）。无安全类问题；未构建镜像、未改任何产品代码。
