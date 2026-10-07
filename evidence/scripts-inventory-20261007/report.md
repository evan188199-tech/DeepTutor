# scripts/ 目录用途清单扫描

- 基线：`origin/main` @ `f07029cfc`（release: v1.6.13，2026-10-07 fetch）
- 范围：`scripts/` 全部 18 个文件（17 个顶层 + `scripts/hooks/pre-commit`），共 2452 行
- 结论速览：**13 个保留**（其中 3 个为弱引用/兼容层）、**5 个候选清理**（只列不改，删除与否由人决定）
- 本次扫描未修改任何代码；本目录为唯一新增内容

## 方法

1. `rg -n --hidden --no-ignore -g '!.git/' -F '<文件名>'`（覆盖 `.github/`、`.pre-commit-config.yaml` 等隐藏路径；排除脚本自身匹配与 `evidence/`）。
2. 对 `update.py` 额外排除 `app_update.py` 假阳性，并人工核对 `deeptutor/services/memory/consolidator/__init__.py:26`（其 "update.py" 指该包自身 `modes/update.py`，与本脚本无关）。
3. 定向复核运行时调用：`deeptutor/`、`deeptutor_cli/`、`web/`、`docs-for-user/`、`README.md`、`CONTRIBUTING.md`、`pyproject.toml`、`Dockerfile*`、`docker-compose*.yml`。
4. CI 可达性核对：`.github/workflows/tests.yml:286` 运行 `pytest -q tests …`，因此 `tests/scripts/*` 的全部测试在 CI 中实际执行（下文"测试引用"均为 CI 可达）。

「有效引用」= 测试之外的 CI / 文档 / 代码 / 配置引用。仅被自身测试引用的脚本列入「候选清理」。

## 汇总表

| 脚本 | 行数 | 用途 | 关键引用（有效） | 存续结论 |
| --- | --- | --- | --- | --- |
| `_cli_kit.py` | 31 | scripts 共享 CLI 输出工具 | 无（仅测试） | **候选清理** |
| `check_architecture.py` | 197 | AST 依赖分层边界检查 | CI tests.yml:62 | 保留 |
| `check_branch_policy.py` | 43 | 禁止直接提交 main | `hooks/pre-commit`:8 | 保留 |
| `check_repo_hygiene.py` | 69 | 拒绝误跟踪生成物 | `.pre-commit-config.yaml`:17 等 3 路门禁 | 保留 |
| `check_workspace_hygiene.py` | 47 | 要求干净工作区并转发 hygiene 检查 | CI repository-hygiene.yml:23 | 保留 |
| `docker_compose.py` | 132 | 按设置渲染端口的 docker compose 包装器 | README.md:423 等 20+ 处 | 保留 |
| `export_discord_history.py` | 639 | 只读导出 Discord 服务器历史 | 无（仅测试） | **候选清理** |
| `export_frontend_contracts.py` | 14 | 前端契约导出 CLI 薄包装 | web/contracts/README.md:9 | 保留 |
| `install_extras.py` | 150 | 容器可选依赖（DEEPTUTOR_EXTRAS）安装器 | Dockerfile:464 | 保留 |
| `pb_setup.py` | 302 | PocketBase 集合 bootstrap | pocketbase_client.py:102（错误消息指引） | 保留（弱引用） |
| `prepare_web_package.py` | 68 | 打包 deeptutor_web 包数据 | CI pypi-release.yml:141 | 保留 |
| `reading_refresh_figures.py` | 188 | 已入库 PDF 图片重提取（可加 caption） | deeptutor/reading/refresh.py:15 | 保留 |
| `start_backend.bat` | 24 | Windows 后端启动 | 仅历史 release note | **候选清理** |
| `start_frontend.bat` | 12 | Windows 前端启动 | 仅历史 release note | **候选清理** |
| `start_tour.py` | 55 | 设置向导兼容包装（→ `deeptutor init`） | 测试 + i18n 残留 | 保留（弱引用） |
| `start_web.py` | 39 | 启动兼容包装（→ `deeptutor start`） | 测试 + 历史 release note | 保留（弱引用） |
| `update.py` | 434 | 源码 checkout 安全 fast-forward 更新器 | 无（仅测试） | **候选清理** |
| `hooks/pre-commit` | 8 | sh git hook（hygiene + branch policy） | CONTRIBUTING.md:160 | 保留 |

## 候选清理清单（只列不改）

按验收口径（无有效引用）列出 5 个，**不做任何删除**：

1. `scripts/_cli_kit.py` — 全仓无任何导入方（`rg '_cli_kit' scripts/` 零命中）。唯一引用是自身单测 `tests/scripts/test_cli_kit.py:11` 和历史 release note `assets/releases/past_releases/ver1-2-4.md:23`。注意漂移：release note 描述的"长列表滚动 UI"在当前 31 行文件里已不存在，只剩 stdout reconfigure + banner/log 三个函数。
2. `scripts/export_discord_history.py` — 一次性社区运维工具（只读 bot token 导出消息历史）。唯一引用 `tests/scripts/test_export_discord_history.py:14`；CI、文档、运行时代码均无引用。是第三方依赖（httpx）在 scripts/ 里的唯一使用者。
3. `scripts/start_backend.bat` — Windows 启动方式已被 `deeptutor start` 取代（README.md:251、312-318）。唯一引用 `assets/releases/past_releases/ver1-4-5.md:63`（历史归档）。
4. `scripts/start_frontend.bat` — 同上，唯一引用 `assets/releases/past_releases/ver1-4-5.md:63`。
5. `scripts/update.py` — git checkout 安全更新器。唯一引用 `tests/scripts/test_update.py:10`。应用内更新已走 PyPI 路径（`deeptutor/services/app_update.py`，消费方 `deeptutor/runtime/launcher.py:1220`、`deeptutor/api/routers/system.py:23`、`deeptutor/runtime/update_worker.py:14`），本脚本无文档/代码引用；对源码 clone 用户仍是可用手工工具，去留交人工判断。

## 逐脚本明细

### 1. scripts/_cli_kit.py

- 用途：scripts 间共享的 CLI 输出小工具——import 时把 stdout 重配为 `errors="replace"`（防旧 Windows 代码页在打印 emoji 时崩溃），并提供 `banner` / `log_success` / `log_error`。
- 入口：无（纯库模块，无 `__main__`；设计为被导入）。
- 依赖：仅标准库（sys）。
- 引用点：
  - `tests/scripts/test_cli_kit.py:11`（importlib 按路径加载并测 stdout 行为；CI 经 tests.yml:286 执行）
  - `assets/releases/past_releases/ver1-2-4.md:23`（历史 release note）
- 有效引用：**无**。无任何脚本或产品代码导入它。
- 结论：候选清理。

### 2. scripts/check_architecture.py

- 用途：AST 级依赖边界检查——解析 `deeptutor/` 全部 import（含函数内 import），按 core / domain_runtime / application / adapter 四层判定违规，并用 Tarjan SCC 检测跨层依赖环。
- 入口：`python scripts/check_architecture.py [--root ROOT]`（`main` 在 scripts/check_architecture.py:177）。
- 依赖：仅标准库（argparse、ast、dataclasses、pathlib、sys）。
- 引用点：
  - `.github/workflows/tests.yml:62`（CI 门禁 `python scripts/check_architecture.py`）
  - `tests/architecture/test_import_boundaries.py:11`（测试以子进程运行本脚本）
- 结论：保留（CI tests 工作流直接调用）。

### 3. scripts/check_branch_policy.py

- 用途：拒绝在 `main` 分支直接提交；临时豁免通道为 `git config deeptutor.allowMainCommit=true`（用后需手动撤销）。
- 入口：`python3 scripts/check_branch_policy.py`（`main` 在 scripts/check_branch_policy.py:30）。
- 依赖：标准库 + git。
- 引用点：
  - `scripts/hooks/pre-commit:8`（git hook 链第二步）
  - `tests/scripts/test_branch_policy.py:10`（按路径加载测试）
- 启用方式：`CONTRIBUTING.md:160`（`git config core.hooksPath scripts/hooks`）。
- 结论：保留（pre-commit hook 组成部分）。

### 4. scripts/check_repo_hygiene.py

- 用途：拒绝误跟踪的生成物——`__pycache__` / `.next` / `node_modules` / `*.pyc` / `web/out|dist` / `htmlcov` / `playwright-report` 等，以及文件名中的异常空白字符。
- 入口：`python3 scripts/check_repo_hygiene.py`（`main` 在 scripts/check_repo_hygiene.py:51）。
- 依赖：标准库 + git。
- 引用点：
  - `.pre-commit-config.yaml:17`（pre-commit 框架本地 hook `deeptutor-repo-hygiene`）
  - `scripts/hooks/pre-commit:7`（sh hook 第一步）
  - `scripts/check_workspace_hygiene.py:28`（被其子进程调用）
  - `CONTRIBUTING.md:144`（贡献者命令表）
  - `tests/scripts/test_pre_commit_hook.py:15,30`、`tests/scripts/test_workspace_hygiene.py:34`
- 结论：保留（pre-commit 框架、sh hook、CI hygiene 链三路共同依赖，是 scripts/ 中被引用最广的门禁）。

### 5. scripts/check_workspace_hygiene.py

- 用途：要求工作区干净（`git status --porcelain` 为空，含未跟踪文件），随后转发执行 `check_repo_hygiene.py`。
- 入口：`python3 scripts/check_workspace_hygiene.py`（`main` 在 scripts/check_workspace_hygiene.py:34）。
- 依赖：标准库 + git；调用 `scripts/check_repo_hygiene.py`。
- 引用点：
  - `.github/workflows/repository-hygiene.yml:23`（CI Repository Hygiene 工作流，作用于 main/dev 的 push 与 PR）
  - `CONTRIBUTING.md:143`
  - `tests/scripts/test_workspace_hygiene.py:11`
- 结论：保留（CI 直接调用）。

### 6. scripts/docker_compose.py

- 用途：`docker compose` 包装器——从 `data/user/settings/system.json` + `integrations.json` 渲染端口变量写入 `docker.env`（Compose 无法直接读 JSON 设置），剥除宿主机的 `BACKEND_PORT` 等环境变量避免泄漏进容器，预创建 `DEEPTUTOR_WORKSPACE_HOST` workspace 及 `outputs/` bind 目录（避免 root 属主）。
- 入口：`python scripts/docker_compose.py [compose 参数…]`（`main` 在 scripts/docker_compose.py:98，缺省 `up -d`）。
- 依赖：标准库；运行时需要 PATH 上有 `docker`。
- 引用点：
  - `docker-compose.yml:7,8,9,14,21`（头注释使用说明）
  - `docker-compose.ghcr.yml:8,15`、`docker-compose.dev.yml:4`
  - `README.md:423`
  - `docs-for-user/CONTAINERIZATION.md:118,178,183,203`
  - 多语言 README：`assets/README/README_CN.md:226`、`README_TW.md:226`、`README_JA.md:226`、`README_FR.md:226`、`README_ES.md:226`、`README_PT.md:226`、`README_RU.md:226`、`README_PL.md:226`、`README_HI.md:226`、`README_TH.md:232`、`README_AR.md:226`
  - `assets/releases/past_releases/ver1-6-5.md:50`、`ver1-4-0.md:101`（测试提及）
  - `tests/scripts/test_docker_compose.py:13`
- 结论：保留（Compose 部署的用户主路径，文档引用覆盖面最大）。

### 7. scripts/export_discord_history.py

- 用途：以只读 bot token 导出 Discord 服务器历史——分页拉取全部可见文字频道与活动/归档线程消息（含限流重试），写一个本地 JSON；附件只存元数据不下载二进制。
- 入口：`python scripts/export_discord_history.py --guild-id <id> [--days 90]`（需环境变量 `DISCORD_BOT_TOKEN`）。
- 依赖：第三方 `httpx`（scripts/ 中唯一第三方依赖使用者）+ 标准库。
- 引用点：
  - `tests/scripts/test_export_discord_history.py:14`（唯一引用）
- 有效引用：**无**。CI、文档、运行时代码均不引用。
- 结论：候选清理（一次性社区运维工具，去留交人工）。

### 8. scripts/export_frontend_contracts.py

- 用途：后端前端契约导出器的 CLI 薄包装（14 行）——把项目根注入 `sys.path` 后转发 `deeptutor.api.contracts.export:main`，支持 `--check`。
- 入口：`python scripts/export_frontend_contracts.py [--check]`。
- 依赖：`deeptutor` 包（`deeptutor/api/contracts/export.py`）。
- 引用点：
  - `web/contracts/README.md:9`（契约变更后的再生成命令）
  - `web/contracts/README.md:13`（声称 CI 在后端契约测试中运行 `--check`）
- 澄清：CI 实际通过 `tests/api/test_frontend_contract_export.py`（`render_contracts` / `write_contracts`）直接测模块，不经过本脚本；`web/contracts/README.md:13` 的 "CI runs … --check" 表述与实现略有出入（记录为观察项，不改）。
- 结论：保留（文档指定的契约再生成入口，逻辑由模块级测试间接覆盖）。

### 9. scripts/install_extras.py

- 用途：容器可选依赖安装器——读 `DEEPTUTOR_EXTRAS` 声明，从 `pyproject.toml` 解析对应 extra 的依赖列表并 pip 安装；已满足的 extra 只花一次元数据查询；**永不致命**（失败仍 exit 0，不拖垮部署）。
- 入口：容器启动路径自动调用；也支持 `python scripts/install_extras.py --dry-run "<name>"` 预览。
- 依赖：标准库（argparse、re、subprocess、tomllib、pathlib）。
- 引用点：
  - `Dockerfile:464`（镜像构建终点：`python /app/scripts/install_extras.py "${DEEPTUTOR_EXTRAS}" || true`）
  - `docker-compose.yml:116`、`docker-compose.ghcr.yml:93`（DEEPTUTOR_EXTRAS 注释指引）
  - `assets/releases/past_releases/ver1-5-17.md:73`（用户指引）
  - `tests/scripts/test_install_extras.py:19`
- 结论：保留（镜像构建 / 容器启动路径的组成部分，#762 修复的载体）。

### 10. scripts/pb_setup.py

- 用途：PocketBase 集合 bootstrap——按内置 schema 创建/补齐 collections 的字段与索引，可重复执行（幂等）。
- 入口：`python scripts/pb_setup.py`（要求 `data/user/settings/integrations.json` 中的 `pocketbase_url` / `pocketbase_admin_email` / `pocketbase_admin_password`）。
- 依赖：`deeptutor.services.config` + 第三方 `pocketbase` 包。
- 引用点：
  - `deeptutor/services/pocketbase_client.py:102`（运行时错误消息文本指引："Collection management (scripts/pb_setup.py) will not work."）
- 有效引用：弱——仅一条错误消息字符串，无文档引用（README 与 docs-for-user 均未提及该脚本）。
- 结论：保留（代码在缺集合时主动指向它，功能上是引导链一环）；若未来重构 PocketBase 引导流程可一并评估（只记录，不改）。

### 11. scripts/prepare_web_package.py

- 用途：发布打包——跑 `web` 的 `npm run build`（可 `--skip-build` 复用现有产物），把 `web/.next/standalone` + `static` + `public` 组装进 `deeptutor_web/` Python 包目录并写 `BUILD_INFO`。
- 入口：`python scripts/prepare_web_package.py [--skip-build]`。
- 依赖：`npm`（构建 web）；标准库（shutil、subprocess）。
- 引用点：
  - `.github/workflows/pypi-release.yml:141`（发布流水线 "Build packaged Web assets" 步骤）
- 结论：保留（PyPI 发布必需步骤，不可清理）。

### 12. scripts/reading_refresh_figures.py

- 用途：对已入库的 PDF 阅读材料就地重提取内嵌图片（`extractor == "pymupdf"` 且原始文件还在磁盘上），可选通过配置模型补 caption；标注/书签/阅读进度保留。破坏性就地重写 `data/user/workspace/reading`，非 dry-run 需 `--yes` 且交互确认。
- 入口：`python scripts/reading_refresh_figures.py --all|--material ID [--dry-run] [--caption|--no-caption] --yes`。
- 依赖：`deeptutor.reading.refresh`、`deeptutor.reading.store`（运行需项目 venv）。
- 引用点：
  - `deeptutor/reading/refresh.py:15`（运行库 docstring 指向本 CLI："The CLI wrapper lives in ``scripts/reading_refresh_figures.py``."）
  - `assets/releases/past_releases/ver1-6-11.md:56`（用户操作指引）
- 结论：保留（运行库文档指向的维护 CLI）。

### 13. scripts/start_backend.bat

- 用途：Windows 后端启动——切到项目根、激活 `.venv`、设 UTF-8 环境变量、`python -m deeptutor.api.run_server`（8001 端口）。
- 入口：cmd / 双击执行。
- 依赖：Windows cmd + 项目根 `.venv`。
- 引用点：
  - `assets/releases/past_releases/ver1-4-5.md:63`（唯一引用，历史归档）
- 有效引用：**无现行引用**。README 的推荐路径是 `deeptutor init` → `deeptutor start`（README.md:251、312-318）。
- 结论：候选清理。

### 14. scripts/start_frontend.bat

- 用途：Windows 前端启动——`web/` 下 `npm run dev -- -p 3782`。
- 入口：cmd / 双击执行。
- 依赖：Windows cmd + Node.js。
- 引用点：
  - `assets/releases/past_releases/ver1-4-5.md:63`（唯一引用，与 start_backend.bat 同一行）
- 结论：候选清理。

### 15. scripts/start_tour.py

- 用途：设置向导**兼容包装器**——转发 `deeptutor_cli.init_cmd.run_init`（即 `deeptutor init`），只写 `data/user/settings`，不装依赖不启动服务。
- 入口：`python scripts/start_tour.py [--cli] [--home DIR]`。
- 依赖：`deeptutor_cli.init_cmd`。
- 引用点：
  - `tests/scripts/test_start_tour.py:9`（CI 可达）
  - `web/locales/fr/app.json:801`（i18n 残留：`"Run python scripts/start_tour.py in your terminal."` 仅存在于 fr 语言包，web 源码与 en/zh 语言包均无此 key —— 纯漂移残留）
  - `.github/ISSUE_TEMPLATE/docs.yml:41`（issue 模板示例文字，非功能引用）
  - `assets/releases/past_releases/ver1-2-4.md:16,39`、`ver1-3-5.md:73`、`ver1-4-0-beta.md:275`、`ver1-1-0-beta.md:38`（全部历史）
- 结论：保留（兼容包装器，docstring 明确指向 `deeptutor init`/`deeptutor start`，有测试兜底）；属弱引用——现行 README/docs 已不引用，fr locale 残留可作为后续清理观察项。

### 16. scripts/start_web.py

- 用途：启动**兼容包装器**——转发 `deeptutor.runtime.launcher.start`（即 `deeptutor start`，backend+frontend 一键启动）。
- 入口：`python scripts/start_web.py [--home DIR] [--dev]`。
- 依赖：`deeptutor.runtime.launcher`。
- 引用点：
  - `tests/scripts/test_start_web.py:9`（CI 可达）
  - 历史 release note：`assets/releases/past_releases/ver1-1-0-beta.md:38`、`ver1-2-4.md:39`、`ver1-3-0.md:56`、`ver1-3-1.md:93`、`ver1-3-5.md:17,60,72`、`ver1-3-9.md:43`、`ver1-4-0-beta.md:274`
- 有效引用：无现行文档/代码引用（与 start_tour.py 同属被 `deeptutor start` 取代的兼容层）。
- 结论：保留（兼容包装器，有测试兜底；弱引用，长期可与 start_tour.py 一并评估）。

### 17. scripts/update.py

- 用途：源码 git checkout 的安全更新器——fetch → 展示本地/远端差异（ahead/behind、进出提交、diff stat、脏文件）→ 交互确认 → 仅允许 fast-forward pull；分叉、脏区、本地领先均拒绝并给出指引；按变更文件提示依赖重装命令。
- 入口：`python scripts/update.py [--yes] [--repo PATH]`。
- 依赖：标准库 + git。
- 引用点：
  - `tests/scripts/test_update.py:10`（唯一有效引用；CI 可达）
  - 澄清：`deeptutor/services/memory/consolidator/__init__.py:26` 出现的 "update.py" 是该包自身 `modes/update.py` 子模块的布局说明，与本脚本无关。
- 有效引用：**无**。应用内更新链路走 PyPI（`deeptutor/services/app_update.py`，消费方 `deeptutor/runtime/launcher.py:1220,1265`、`deeptutor/runtime/update_worker.py:14`、`deeptutor/api/routers/system.py:23`、`deeptutor/services/session/turns/lifecycle.py:27`），不经本脚本；CONTRIBUTING/README/docs-for-user 均未提及。
- 结论：候选清理（对源码 clone 用户仍是可用的手工工具，去留交人工）。

### 18. scripts/hooks/pre-commit

- 用途：sh 写成的 git pre-commit hook——依次跑 `check_repo_hygiene.py` 与 `check_branch_policy.py`；刻意零依赖，让 fresh checkout 在装全 pre-commit 环境之前也能拦住生成物。
- 入口：git hook——按 `CONTRIBUTING.md:160` 执行 `git config core.hooksPath scripts/hooks` 后，每次 commit 自动触发。
- 依赖：python3 + git。
- 引用点：
  - `CONTRIBUTING.md:160`（启用说明）
  - `tests/scripts/test_pre_commit_hook.py:23`（以 `sh scripts/hooks/pre-commit` 子进程实测两步都被调用）
- 结论：保留（贡献者工作流）。

## 观察项（只记录，不在本卡处理）

- `web/contracts/README.md:13` 声称 "CI runs `python scripts/export_frontend_contracts.py --check`"，实际 CI 走的是模块级测试 `tests/api/test_frontend_contract_export.py`，不经过该脚本——表述与实现有偏差。
- `web/locales/fr/app.json:801` 残留指向 `scripts/start_tour.py` 的 i18n 字符串，对应 key 在 web 源码与 en/zh 语言包中已不存在。
- `_cli_kit.py` 在 `assets/releases/past_releases/ver1-2-4.md:23` 中描述的"长列表滚动 UI"功能与当前文件内容不符（历史功能已删）。

## 复核命令

```bash
# 引用扫描（基线 f07029cfc）
rg -n --hidden --no-ignore -g '!.git/' -g '!evidence/**' -F 'docker_compose.py' .
rg -n --hidden --no-ignore -g '!.git/' '(^|[^a-zA-Z0-9_./-])update\.py' . | grep -v app_update
# CI 调用点
rg -n 'scripts/' .github/workflows/
# SHA256 校验
sha256sum -c evidence/scripts-inventory-20261007/SHA256SUMS
```
