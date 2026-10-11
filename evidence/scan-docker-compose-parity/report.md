# 容器面静态一致性扫描（Dockerfile/compose × 依赖与配置）

- 基线: HKUDS/DeepTutor `origin/main` `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14, 2026-10-08）
- 方法: 纯静态文本比对，未构建镜像、未启动任何服务。
- 扫描面: `Dockerfile`、`Dockerfile.runner`、`docker-compose.yml`、`docker-compose.ghcr.yml`、`docker-compose.dev.yml`、`compose.yaml`、`compose.codex-oauth.yaml` × `requirements*.txt`、`pyproject.toml`、`packaging/deeptutor-cli/pyproject.toml`，及 settings 默认值导出 `deeptutor/services/config/runtime_settings.py`、`scripts/docker_compose.py`、`scripts/install_extras.py`、`deeptutor/services/sandbox/config.py`、`deeptutor/services/sandbox/runner/server.py`、`deeptutor/services/workspace/service.py`。
- 去重: 本卡为容器面轴，不与 scan-python-deps-drift（import 轴）、scan-env-var-surface（代码读取面轴）、fix-compose-loopback-defaults（loopback 个案修复）重叠；`docker-compose.yml:85-86` 等发布绑定到 0.0.0.0 的问题归 loopback 卡管辖，本报告不列为发现。

## A 版本漂移（3 项）

### A1 [中] runner 镜像 pip 安装集零版本约束，与主镜像钉版本可漂移
- 证据: `Dockerfile.runner:63-75` — numpy、pandas、python-docx、python-pptx、openpyxl、pypdf、pdfplumber、PyMuPDF、reportlab、lxml、defusedxml、Pillow 共 12 包，全部无版本约束。
- 对照: 同名包在主镜像安装集均有界 — `pyproject.toml:67-77` / `requirements/cli.txt:51-63`：`numpy>=1.24,<3.0.0`、`PyMuPDF>=1.26.0`、`Pillow>=10.0.0`、`pypdf>=4.0.0`、`pdfplumber>=0.11.0`、`reportlab>=4.0.0`、`defusedxml>=0.7.1`、`python-docx>=1.1.0`、`openpyxl>=3.1.0`、`python-pptx>=1.0.0`。
- 影响: runner 与主镜像不同时重建时，同名库可解析到不同大版本（如 numpy 2.x vs 主镜像当时解析结果），office skill 在两侧的行为可能不一致。
- 建议: runner 的 pip 集补上与 `requirements/cli.txt` 一致的版本界。
- 核对:
  `grep -n -A13 'pip install --no-cache-dir' Dockerfile.runner`
  `grep -nE 'numpy|PyMuPDF|Pillow|pypdf|pdfplumber|reportlab|defusedxml|python-docx|openpyxl|python-pptx' requirements/cli.txt pyproject.toml`

### A2 [低] ghcr deeptutor 与 pocketbase 使用浮动 `:latest` tag 且 `pull_policy: always`
- 证据: `docker-compose.ghcr.yml:60-61`（`ghcr.io/hkuds/deeptutor:latest` + `pull_policy: always`）、`compose.yaml:138,140`（同 tag + always）、`docker-compose.yml:51` / `compose.yaml:92`（`ghcr.io/muchobien/pocketbase:latest`，后者 `pull_policy: always` 于 `compose.yaml:94`）。
- 影响: 上游任意一次 push 后，下一次 `compose up/restart` 即更换运行版本；与可复现部署目标相悖。redis 已钉 `redis:7.4-alpine`，三处一致（`docker-compose.yml:31`、`docker-compose.ghcr.yml:45`、`compose.yaml:70`）。
- 核对: `grep -nE 'image:|pull_policy' docker-compose.yml docker-compose.ghcr.yml compose.yaml`

### A3 [低] 开发镜像 dev 工具未声明且未钉版本
- 证据: `Dockerfile:576-579` — `pip install --no-cache-dir pre-commit black ruff`（无版本约束）。
- 对照: `requirements/dev.txt:12-17` 只声明 `pre-commit>=3.0.0` 等，完全没有 black/ruff 条目；`pyproject.toml` `[project.optional-dependencies].dev`（`pyproject.toml:275-290`）同样没有 black/ruff。
- 影响: dev 阶段实际安装集在依赖声明面之外，版本可随时间漂移；声明面（dev.txt/dev extra）与镜像内容不一致。
- 核对: `grep -n -B2 -A4 'Install development Python packages' Dockerfile && cat requirements/dev.txt`

### A-通过项（核实无漂移）
- 基础镜像 `python:3.11-slim`（`Dockerfile:64,104`、`Dockerfile.runner:19`）满足 `pyproject.toml:16` `requires-python = ">=3.11,<3.15"`；`requirements.txt:4` "Python >= 3.11 required" 一致；site-packages 复制路径 `python3.11` 与之匹配（`Dockerfile:164`）。
- `requirements/cli.txt:23,45,49-50` 的 `python_version` 标记在 3.11 下正确生效（3.14 分支不适用）。
- `node:22-slim`（`Dockerfile:23,59`）与 `web/package.json`（next ^16.2.3，无 engines 上限）兼容。

## B 缺失依赖（1 项 + 通过项）

### B1 [低] requirements/ 镜像目录未覆盖 8 个 pyproject extras
- 证据: `requirements.txt:6-8` 声称 "Files under requirements/ mirror those extras"；实际 `requirements/` 仅有 cli、dev、math-animator、matrix-e2e、matrix、partners、rag-rerank、server、video-learning 9 个文件，而 `pyproject.toml` 的 extras 还有 `codebuddy`(:154)、`parse-markitdown`(:210)、`parse-docling`(:215)、`parse-pymupdf4llm`(:222)、`parse-liteparse`(:223)、`parse`(:224)、`graphrag`(:260)、`rag-lightrag`(:266) 无对应镜像文件。
- 缓解: 容器内影响有限 — `Dockerfile:178` 复制 `pyproject.toml`，`scripts/install_extras.py:39`（`load_extras`）直接读 pyproject 安装 extras。
- 建议: 为上述 extras 补 requirements/*.txt 镜像，或在 requirements.txt 头注注明哪些 extras 仅支持 pyproject 路径。
- 核对: `ls requirements/ && grep -nE '^\w[\w-]* = \[' pyproject.toml`

### B-通过项（核实无缺失）
- runner pip 集 ⊇ 四个 office SKILL.md 的实际 import：`deeptutor/skills/builtin/{docx,pptx,xlsx,pdf}/SKILL.md` 仅使用 docx、pptx、openpyxl、pypdf、pdfplumber、reportlab、fitz（PyMuPDF）与标准库，`Dockerfile.runner:63-75` 全部覆盖；lxml/defusedxml 为其传递依赖兜底，numpy/pandas 为 `Dockerfile.runner:22-25` 注明的设计内工具。
- compose healthcheck 依赖齐备：主容器 curl 已安装（`Dockerfile:139`）；runner healthcheck 用标准库 urllib（`docker-compose.yml:201-202`）；pocketbase 的 wget 为该镜像自带。
- 主镜像安装链 `requirements.txt`→`partners.txt:14`→`server.txt:11`→`cli.txt` 与 `pyproject.toml:19-94` dependencies 等价（含 extras 递归 `pyproject.toml:162-176,182-204`），`Dockerfile:96-99` 全量安装。

## C env 键未声明 / 声明矛盾（2 项 + 通过项）

### C1 [中] compose.yaml 注释示例引导设置会被 entrypoint 丢弃的死键
- 证据: `compose.yaml:187-189` 注释示例建议取消注释 `POCKETBASE_URL=http://pocketbase:8090` 与 `POCKETBASE_EXTERNAL_URL=...`；但镜像入口脚本固定 unset 这两个键（`Dockerfile:342-367` unset 列表含 `POCKETBASE_URL`、`POCKETBASE_EXTERNAL_URL`），并从 `data/user/settings/integrations.json` 重导出（`deeptutor/services/config/runtime_settings.py:748-752`）。
- 影响: 按示例操作是无效死旋钮，且与同文件 `compose.yaml:57-62` 自己的 "编辑 JSON + restart，而非 compose env" 说明直接矛盾。
- 建议: 删除或改写该注释示例，指向 integrations.json。
- 核对: `grep -n 'POCKETBASE' compose.yaml Dockerfile | grep -v '^Dockerfile:[5-9]'`

### C2 [低] 健康检查端口与 system.json 实际端口仅靠渲染脚本维持一致
- 证据: 容器内实际监听端口由 entrypoint 从 `data/user/settings/system.json` 重导出 `BACKEND_PORT`（`Dockerfile:482`；导出逻辑 `runtime_settings.py:711`），而 `docker-compose.yml:127` 与 `docker-compose.ghcr.yml:103` 的容器内 healthcheck 用 compose 解析期插值 `${DEEPTUTOR_DOCKER_BACKEND_PORT:-8001}`，`compose.yaml:190-195` 更是硬编码 `http://localhost:8001`。
- 影响: 直接编辑 system.json 而不经 `scripts/docker_compose.py` 重渲染（该前置要求写在 `docker-compose.yml:14`）时，healthcheck 探测端口与实际监听端口失配，容器被误判 unhealthy。Dockerfile 自带 HEALTHCHECK 读 JSON（`Dockerfile:517-539` healthcheck.py）无此问题。
- 建议: 三份 compose 的 healthcheck 统一改为 `python /app/healthcheck.py`。
- 核对: `grep -n 'health/ready' docker-compose.yml docker-compose.ghcr.yml compose.yaml Dockerfile`

### C-通过项（核实无未声明键）
- 容器面声明的功能 env 键全部有代码消费者：`DEEPTUTOR_SANDBOX_RUNNER_URL`（docker-compose.yml:107 → sandbox/config.py:32）、`DEEPTUTOR_WORKSPACE_ROOT` / `DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS`（docker-compose.yml:108-109、ghcr:80-81、compose.yaml:181-182 → workspace/service.py:29-30）、`DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS`（docker-compose.yml:178 → sandbox/runner/server.py:160）、`RUNNER_PORT`（Dockerfile.runner:103 → server.py:359）。
- entrypoint unset 的 23 个键全部被 `render_environment` 从 JSON 重导出（`runtime_settings.py:710-752`），unset→重导出闭环，无丢键。
- 端口默认值全链一致：后端 8001（EXPOSE `Dockerfile:534,614`；start-backend.sh `Dockerfile:278,303`；发布 yml:85、ghcr:65、compose.yaml:162）；前端 3782（EXPOSE 同上；start-frontend.sh `Dockerfile:317`；发布 yml:86、ghcr:66、compose.yaml:163、codex-oauth overlay `compose.codex-oauth.yaml:8-9`）；runner 8900 仅内网（EXPOSE `Dockerfile.runner:105`、ENV :103、healthcheck yml:202、引用 yml:107，无 ports 发布）；pocketbase 8090（yml:55、compose.yaml:103）。
- 观察（非缺陷）: 端口发布 env 两套命名 — docker-compose.yml/ghcr 用 `DEEPTUTOR_DOCKER_*`，compose.yaml 用 `HOST_PORT_*`，各自内部一致；`TZ` 仅在 compose.yaml:180 声明，属不对称而非未声明。

## 统计与结论
- 发现 6 项：中 2（A1、C1），低 4（A2、A3、B1、C2）；核实通过项 10。
- 三类均无"阻断级"问题；A1 与 C1 建议优先跟进。
- 本卡为纯扫描证据，无代码改动，故不开上游 PR。
