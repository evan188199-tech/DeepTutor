# Docker/compose 部署面漂移清点（docker-compose-drift scan）

- 日期：2026-10-07
- 基线：origin/main @ `f07029cf`（release: v1.6.13），新 worktree + 新分支 `scan/docker-compose-drift-20261007`，全程只读（未改产品代码、未构建镜像、未启动服务）
- 范围：`Dockerfile`（全部 5 个 stage）、`Dockerfile.runner`、`docker-compose.yml`、`docker-compose.dev.yml`、`docker-compose.ghcr.yml`、`compose.yaml`、`compose.codex-oauth.yaml`、`.github/workflows/docker-release.yml`、`README.md` 部署节（L253-479）、`docs-for-user/CONTAINERIZATION.md`，对照代码契约 `deeptutor/services/config/runtime_settings.py`、`deeptutor/services/setup/`、`deeptutor/services/cli_apps/paths.py`、`deeptutor/services/codex_auth/constants.py`、`scripts/install_extras.py`
- 去重（按卡面）：不覆盖代码内环境变量 vs settings 轴（scan-env-config-drift）、依赖版本轴（scan-deps-drift）；`scripts/docker_compose.py` 仅作端口渲染行为参照（scan/scripts-inventory-20261007 卡所有）
- 旁卡重合：myfork 分支 `scan/compose-parity-20261007`（agen-1003）已覆盖 compose↔代码默认值轴（其 `evidence/compose-parity-20261007/report.md`，同基线 f07029cf）。本卡与之重合的条目在表中标注「重合」，均经本卡独立复核（两侧 path:line 为本卡实读证据）；Dockerfile 构建目标轴、workflow 轴、README 轴、dev/ghcr 细节为本卡独有

## 总量

| 分类 | 数量 |
| --- | --- |
| 漂移 | 7（中危 2、低危 5） |
| 观察项（info） | 3 |
| 通过项（负结果，无漂移） | 9 组 |
| 可拆修复卡建议 | 5 |

## 漂移表

| # | 轴 | 严重度 | 漂移 | 证据 A（一侧） | 证据 B（另一侧） | 判定依据 | 重合 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | 构建目标 | 中 | Dockerfile 头部文档化的裸 `docker build` 默认产出 development 镜像（含 vim/pre-commit/uvicorn --reload），与生产意图相反 | `Dockerfile:8`（`docker build -t deeptutor:local .`，无 `--target`） | `Dockerfile:547`（`FROM production AS development` 是最后一个 stage，即默认构建目标） | Docker 默认 target = 最后 stage；`docker-compose.yml:81`、`.github/workflows/docker-release.yml:102` 均显式 `target: production` 反证生产面从不依赖默认值 | 本卡独有 |
| D2 | 端口/健康检查 | 中 | podman 路径（compose.yaml）容器侧端口硬编码，无法跟随 system.json 端口修改，且两处文档宣称可以 | `compose.yaml:162-163`（右侧写死 `8001`/`3782`）、`compose.yaml:190-195`（healthcheck 写死 `:8001`） | `compose.yaml:57-62`（头注称「改 JSON + restart」即可）、`docs-for-user/CONTAINERIZATION.md:434-437`（称 `HOST_PORT_*` 可替代改右侧；实为只改宿主侧） | 对照正确实现：`docker-compose.yml:85-86,127` + `scripts/docker_compose.py:54-62` 双侧均由 wrapper 从 JSON 渲染；podman 路径改 `backend_port` 后映射与健康检查同时失效 | 重合（旁卡 D1+D2，本卡独立复核） |
| D3 | 卷挂载 | 低 | dev 覆盖文件把基础文件已修复删除的 PocketBase 旧挂载路径重新引入 | `docker-compose.dev.yml:15`（`./data/pocketbase:/pb/pb_data`） | `docker-compose.yml:57-64`（注释明确上游 entrypoint 用绝对路径 `/pb_data`，`/pb/pb_data` 是曾致 `mkdir /pb_data: read-only file system` 崩溃的旧示例）、`compose.yaml:111-113` 同用 `/pb_data` | compose 合并时 volumes 追加：dev 覆盖叠加出死挂载；`docs-for-user/CONTAINERIZATION.md:454-460` 亦记录了该修复，dev 文件未同步 | 重合（旁卡 D4） |
| D4 | 启动依赖 | 低 | PocketBase 在编排层是硬依赖（service_healthy 门禁），与自身注释及文档「可选、SQLite 回退」语义冲突 | `docker-compose.yml:136-137`（`pocketbase: condition: service_healthy`；`compose.yaml:203-204` 同） | `docker-compose.yml:46-48`（「Leave integrations.pocketbase_url blank to run without PocketBase (SQLite fallback)」）、`docs-for-user/CONTAINERIZATION.md:445-452`、`deeptutor/services/config/runtime_settings.py:100`（`redis_url` 默认空 = 内存回退） | 按文档裁剪 sidecar（不启动 pocketbase）会被 depends_on 阻塞，「可选」只在应用层成立，编排层不可裁剪 | 重合（旁卡 D6） |
| D5 | 卷挂载 | 低 | dev 覆盖的三条 data 窄挂载与基础文件整树挂载冗余，系 ghcr 整树迁移前残留 | `docker-compose.dev.yml:41-43`（`./data/user`、`./data/memory`、`./data/knowledge_bases`） | `docker-compose.yml:97`（`./data:/app/data` 整树）；`docker-compose.ghcr.yml:68-77` + `docs-for-user/CONTAINERIZATION.md:208-231` 记录了整树迁移 | 覆盖合并后窄挂载被整树包含，无行为差异，属历史残留未清理 | 本卡独有 |
| D6 | 环境变量 | 低 | TZ 仅 podman 路径传入，docker/ghcr 路径无法按同一方式设时区 | `compose.yaml:180`（`TZ=${TZ:-UTC}`） | `docker-compose.yml:100-124`、`docker-compose.ghcr.yml:79-100`（environment 段均无 TZ）；文档未提 TZ | 同一产品三种部署形状时区行为不一致 | 重合（旁卡 D5） |
| D7 | 命名一致性 | 低 | 同一旋钮跨文件命名不一致：PocketBase 容器名、网络名、PocketBase 宿主端口变量 | `docker-compose.yml:52`（`pocketbase`）、`docker-compose.yml:215` / `docker-compose.ghcr.yml:117`（`deeptutor-network`）、`docker-compose.yml:55`（`${DEEPTUTOR_DOCKER_POCKETBASE_PORT:-8090}`） | `compose.yaml:93`（`deeptutor-pocketbase`）、`compose.yaml:222-224`（网络名 `deeptutor`）、`compose.yaml:103`（`${HOST_PORT_POCKETBASE:-8090}`）；wrapper 只渲染 `DEEPTUTOR_DOCKER_*`（`scripts/docker_compose.py:54-62`） | 单文件内部自洽、可运行；跨文件一致性缺口，混用两文件（同宿主）会撞容器名 | 重合（旁卡 O1 有宿主端口双命名，容器名/网络名为本卡补充） |

## 观察项（info，非缺陷）

| # | 内容 | 证据 |
| --- | --- | --- |
| I1 | ghcr 路径无 PocketBase 服务，文档「bring the pocketbase service up alongside」未区分该形状 | `docker-compose.ghcr.yml:41-114`（仅 redis+deeptutor） vs `docs-for-user/CONTAINERIZATION.md:445-450` |
| I2 | Dockerfile.runner 手动运行示例把 8900 发布到所有接口（`-p 8900:8900`），与 compose「runner 不发布到宿主/仅内网」设计表述不一致 | `Dockerfile.runner:12` vs `docker-compose.yml:153-154,180` | 
| I3 | compose.yaml:58 注释把 `./data` bind 称作 "the deeptutor-data volume"，与 `:174` 实际 bind 及 `:226-230`「不用命名卷」说明相悖（术语笔误） | `compose.yaml:58` vs `compose.yaml:174,226-230` |

（I2 重合旁卡 O4、I3 重合旁卡 O3，附本卡证据。）

## 通过项（负结果，本轮验证一致）

1. **DEEPTUTOR_EXTRAS / DEEPTUTOR_APT_PACKAGES 命名全库唯一**（本卡核心轴）：`Dockerfile:438-439,449-452,462-464`、`docker-compose.yml:117-118`、`docker-compose.ghcr.yml:95-96`、`README.md:429`、`scripts/install_extras.py` 机器 uniq 验证各仅 1 个 token；entrypoint 以位置参数传值与 `scripts/install_extras.py:103`（`names` 位置参数）契约一致
2. **镜像引用唯一**：`ghcr.io/hkuds/deeptutor` 在 8 个部署面文件 20 处字节级一致；`ghcr.io/muchobien/pocketbase` 3 处一致；卷名 `deeptutor-data` 20 处一致（uniq 机器验证）
3. **workflow ↔ Dockerfile ↔ ghcr**：`docker-release.yml:92`（镜像）、`:93-95`（版本 tag 去 v + 稳定 latest）、`:102`（target production）、`:103`（amd64+arm64）与 `Dockerfile:23`（BUILDPLATFORM 前端构建）、`:104`（production stage）、`docker-compose.ghcr.yml:60-61`（`ghcr.io/hkuds/deeptutor:latest` + pull_policy）一致
4. **端口字面量与代码契约**：`3782/8001/8090` 默认值（`Dockerfile:278,317,482-483,534`）↔ compose 三文件；`:8900`（`Dockerfile.runner:103-105`）↔ `docker-compose.yml:107`；`1455/1457`（`deeptutor/services/codex_auth/constants.py:16` `CODEX_CALLBACK_PORTS=(1455,1457)`）↔ `compose.codex-oauth.yaml:8-9` 与 `docs-for-user/CONTAINERIZATION.md:157-206`
5. **entrypoint Python 契约全部存在**：`init_user_directories`（`deeptutor/services/setup/init.py:145`）、`check_container_data_volume`（`deeptutor/services/setup/data_volume.py:145`）、`export_runtime_settings_to_env`（`runtime_settings.py:1503`）、`get_ws_max_size`（`runtime_settings.py:1451`）、`HTTP_KEEP_ALIVE_TIMEOUT`（`deeptutor/services/config/__init__.py:29`）；`DEEPTUTOR_API_BASE_URL`/`DEEPTUTOR_AUTH_ENABLED` 由 `render_environment` 导出（`runtime_settings.py:742,747`），均在 entrypoint unset 清单内（`Dockerfile:364-365`）
6. **cli-apps 只读挂载路径与代码一致**：`docker-compose.yml:175`（`/app/data/cli-apps:ro`）↔ `deeptutor/services/cli_apps/paths.py:42`（`CLI_APPS_DIRNAME="cli-apps"`，root 为 `data/cli-apps`）
7. **README 部署节与镜像行为一致**：loopback-only 示例（`README.md:258-261,402-405,466-467`）↔ CONTAINERIZATION 建议；`README.md:424`（省略时 `./data/user/workspace`）↔ `scripts/docker_compose.py:23` `DEFAULT_WORKSPACE_HOST` 与 `docker-compose.yml:98`；`README.md:427`「仅 3782 必须发布」↔ `Dockerfile:309-312` proxy 请求时改写设计
8. **dev 覆盖挂载的源码目录全部存在**：`docker-compose.dev.yml:23-38` 所列 `web/{app,components,features,lib,hooks,context,i18n,locales,public}` 与仓库实际目录逐一比对一致
9. **redis_url 注释准确**：`docker-compose.ghcr.yml:43` ↔ `deeptutor/services/config/runtime_settings.py:100`（默认空 = 内存回退）

## 可拆修复卡建议

| 卡 | 内容 | 覆盖 | 规模 |
| --- | --- | --- | --- |
| 卡A | Dockerfile 构建目标：development stage 前置，或 `Dockerfile:8` 头部示例加 `--target production`（一行修复） | D1 | 小 |
| 卡B | docker-compose.dev.yml 清理：删除 `:13-15` pocketbase 覆盖段与 `:41-43` 冗余 data 窄挂载（同文件一次 PR） | D3+D5 | 小 |
| 卡C | compose.yaml 端口/健康检查 JSON 化（容器侧变量化或改用镜像内 `/app/healthcheck.py`，见 `Dockerfile:517-539`）并修正 `CONTAINERIZATION.md:434-437` 与 `compose.yaml:57-62` 表述 | D2 | 中 |
| 卡D | PocketBase 依赖语义：depends_on 降级为可选（profile/条件）或文档明示「可选指应用层回退」 | D4 | 中 |
| 卡E | 低危打包：两个 docker compose 文件补 `TZ`（D6）+ 命名统一或差异说明（D7）+ I1 文档补 ghcr 形状说明 | D6+D7+I1 | 小 |

## 结论

Docker 部署面整体一致性良好： extras 环境变量命名、镜像引用、端口契约、entrypoint 代码契约经机器验证全部对齐，workflow（docker-release.yml）与 Dockerfile/ghcr 无漂移。漂移集中在：**裸构建默认 target 漂移（D1，本卡独有）**、**podman 路径端口/健康检查硬编码（D2，与旁卡 scan/compose-parity-20261007 同根因）**，及 5 处低危不一致。无安全类问题；未构建镜像、未改任何产品代码、未启动任何服务。
