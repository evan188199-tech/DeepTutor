# CI workflows 与门禁链导读（.github/workflows + pre-commit + scripts/check_*）

- 基线：origin/main @ `f07029cfc`（v1.6.13）。锚点均为 `path:line`，相对仓库根，行号在基线 commit 上逐一核对。
- 范围：4 个 GitHub workflow、`.pre-commit-config.yaml`、`scripts/hooks/pre-commit` 与 `scripts/check_*.py` 四个门禁脚本。触发条件、职责边界、失败定位路径。
- 不覆盖：pytest 用例组织与夹具（guide-testing 的轴，本文只锚 CI 入口 `tests.yml:286`）；scripts/ 全量存续判定（见 scripts-inventory 扫描报告 `evidence/scripts-inventory-20261007/report.md`，同基线 commit，只读引用）。

## 1. 门禁链全景：一次改动会撞上哪些门

```
本地提交
  ├─ 轨 A：pre-commit 框架（.pre-commit-config.yaml，装法 CONTRIBUTING.md:126）
  │    hygiene / 文件检查 / ruff / prettier / detect-secrets / bandit / mypy
  └─ 轨 B：零依赖 sh hook（scripts/hooks/pre-commit:7-8）
       repo hygiene + 禁直提 main（启用：git config core.hooksPath scripts/hooks，CONTRIBUTING.md:160）
            │ push / PR（main、dev）
            ▼
repository-hygiene.yml ── 干净工作区 + 无 tracked 生成物
            │ （与 Tests 并行）
tests.yml ── lint → web-tests → (multi-worker-web) → import-check → python-tests → 汇总门
            │ （仅 GitHub Release published 时）
pypi-release.yml ── tag 校验 → on-main 校验 → 版本一致 → 构建 → PyPI
docker-release.yml ── tag 校验 → 多平台镜像 → GHCR
```

| workflow | 文件 | 触发 | 拦什么 | 典型失败 |
| --- | --- | --- | --- | --- |
| Tests | `.github/workflows/tests.yml` | push/PR 到 main+dev 且 paths 命中（:7-32）；每日 cron `17 3 * * *`（:5-6）；手动 dispatch（:4） | 格式、依赖分层、前端门、导入/惰性启动、全量 pytest | 任一 job 红 |
| Repository Hygiene | `.github/workflows/repository-hygiene.yml` | push/PR 到 main+dev，无 paths 过滤（:3-11） | 工作区脏、生成物被跟踪 | "Check tracked generated files" 红 |
| PyPI Release | `.github/workflows/pypi-release.yml` | GitHub Release published（:16-18） | tag 形态、tag 必须在 main、tag==`__version__` | 发布 job 红，包未发 |
| Docker Release | `.github/workflows/docker-release.yml` | GitHub Release published（:13-15） | tag 形态、OCI tag 合法性 | 镜像未推送 |

## 2. tests.yml：主质量门（5 个 job + 汇总门）

- paths 过滤：push 与 PR 各自声明同一组路径（:11-19 / :24-32），只改文档不会触发本 workflow。
- **lint**（:35-62）：`ruff check .`（:54）、`ruff format --check .`（:57），ruff 版本钉死 `0.16.0`（:51，与 `.pre-commit-config.yaml:55` 的 `rev: v0.16.0` 互为对齐）；随后 `lint-imports`（:61，契约在 `.importlinter`）与 AST 分层检查 `python scripts/check_architecture.py`（:62）。
- **web-tests**（:64-107）：`npm ci`（:81）→ `npm run check`（:85）。`check` 的展开在 `web/package.json:20`：`check:fast`（:19，contracts:check → architecture:check → typecheck → test:node → test:unit → lint → i18n:check）+ `build` + `perf:check`（路由预算 `web/package.json:21`）；再装 Playwright Chromium（:87-89）并起本地 3000 端口跑交互/可达性/视觉审计 `npm run audit`（:91-107，即 `web/package.json:28` 的 ui-audit 项目）。
- **multi-worker-web**（:109-153）：门条件 `vars.DEEPTUTOR_MULTI_WORKER_E2E_URL != ''`（:111）——仓库变量未配置时整 job skip，属正常。失败时上传 traces/videos 取证（:145-153）。
- **import-check**（:155-219）：6 项矩阵（3.11–3.14 Linux + 3.14 macOS/Windows，:160-175）；装 `requirements/server.txt` 与 `pip install -e . --no-deps`（:194-199，后者顺带校验 pyproject 元数据）；逐模块 import 冒烟（:201-212）；惰性启动断言（tool registry 不预热 agentic pipeline）与隔离 worker 协议（:214-219）。
- **python-tests**（:221-289）：`needs: import-check`（:224）；redis 7.4 服务容器（:225-234）；按 3.11–3.14 矩阵（:235-238）；LightRAG / GraphRAG SDK 只在 3.12 安装（:264-270）；最小运行时配置来自 `tests/fixtures/ci_model_catalog.json`（:272-281）；实际执行 `pytest -q tests deeptutor/learning/tests`（:286，env 注入 redis URL :289）。
- **test-summary**（:291-312）：`needs` 全部 job（:294）且 `if: always()`（:295）；把每个 job 结果写成 Step Summary 表（:298-308）；任一 job `failure` 则 `exit 1`（:310-312）。注意：`skipped`（multi-worker-web 未配置 fixture）不算失败。

## 3. repository-hygiene.yml：干净工作区门

唯一 job `hygiene`（:14-23）只跑一条命令：`python3 scripts/check_workspace_hygiene.py`（:23）。脚本两层：

1. 工作区必须干净：`git status --porcelain=v1 --untracked-files=all` 有输出即失败（`scripts/check_workspace_hygiene.py:19-24`，入口 :34）。CI 检出的工作区通常干净，此层主要在人工手动跑时起作用。
2. 转发 `check_repo_hygiene.py`（子进程调用在 `scripts/check_workspace_hygiene.py:28`）。该脚本拒绝 tracked 生成物（入口 `scripts/check_repo_hygiene.py:51`，逐文件判定 `violation` :33）：`FORBIDDEN_PARTS` 目录名（`.DS_Store`/`.next`/`__pycache__`/`node_modules`/`htmlcov`/`playwright-report`/`test-results` 等，:10-19）、`.pyc`/`.pyo` 后缀（:21）、`web/out|dist` 构建产物（:35-39）、文件名异常空白/控制字符（:44-46）。

与本地轨 B 的关系：`scripts/hooks/pre-commit:7` 跑的是同一个 `check_repo_hygiene.py`，所以这类问题应在本地 commit 时就被拦下；CI 侧是兜底。

## 4. pypi-release.yml：发布门（deeptutor 包）

- 权限与并发：`id-token: write`（:20-22，PyPI Trusted Publishing，无 token secret）；concurrency 按 tag 排队且不取消（:24-26）。
- **validate-release-tag**（:29-54）：非 `v` 开头的 tag 直接跳过整链（:31）；PEP 440 正则校验（:41-52）。
- **build-and-publish**（:56-182）四道顺序门：
  1. checkout 的是 release tag 本身（:65-69）。
  2. tag 必须是 origin/main 的祖先：`git merge-base --is-ancestor`（:71-81）。从非 main 分支打的 tag 在此被拒。
  3. tag 与 `deeptutor/__version__.py` 归一化相等（:100-134，`Version()` 比较 :113/:121-128）。忘 bump 版本在此被拒。
  4. 构建与元数据：`scripts/prepare_web_package.py` 打包 Next.js 资产（:140-144，占位符注入 :143-144）；只产 wheel（:146-156，sdist 不产的理由见 :152-155 注释）；`twine check` + 校验期望文件名 `deeptutor-<version>-py3-none-any.whl`（:158-176）；最后 `pypa/gh-action-pypi-publish` 发布（:178-182）。
- CLI-only 包不发 PyPI（头注释 :7-8）。

## 5. docker-release.yml：发布门（GHCR 镜像）

- 权限：`packages: write`（:17-19）。
- **validate-release-tag**（:22-60）：同款 PEP 440 校验（:38-49）；输出 `image_tag`（剥 `v`、`+`→`-` 以满足 OCI tag 规则，:50-53）与 `is_stable`（纯 `vX.Y.Z` 才算稳定，:54-58）。
- **build-and-push**（:62-112）：QEMU（:72-73，linux/arm64 交叉构建所需）→ Buildx（:76-77）→ GHCR 登录用 `secrets.GITHUB_TOKEN`（:79-84）→ metadata（:88-95，`latest` 仅当非 pre-release 且 is_stable 时更新，:95）→ 多平台构建推送（:97-112：platforms :103，provenance+sbom :105-106，gha 层缓存 :111-112）。

## 6. 本地门禁：pre-commit 双轨

轨 A（`.pre-commit-config.yaml`，pre-commit 框架）：

| hook | 位置 | 内容 |
| --- | --- | --- |
| deeptutor-repo-hygiene | :15-20 | 本地 repo hook，entry `scripts/check_repo_hygiene.py`（:17），与 CI/轨 B 同脚本 |
| pre-commit-hooks v6.0.0 | :26-47 | 行尾空白（:28）、EOF（:32）、yaml/json/toml（:35/:38/:46）、大文件 ≤6MB（:41）、合并冲突标记（:44）、大小写冲突（:45） |
| ruff-pre-commit v0.16.0 | :54-62 | `ruff --fix`（:57-59）与 `ruff-format`（:61-62）；:49-53 注释说明为何钉版本（与 CI 一致，防漂移） |
| prettier 3.9.6 | :66-76 | 只作用于 `web/` 前端文件（:75 files 白名单，:76）；entry :72、依赖钉版 :73 |
| detect-secrets v1.5.0 | :81-87 | 以 `.secrets.baseline` 为基线（:85） |
| bandit 1.8.0 | :99-105 | 排除 `tests/`（:104）；配置在 `pyproject.toml`（:103） |
| mypy v1.13.0 | :112-118 | 宽松参数（:116）+ 大范围 exclude（:117），渐进采用中 |
| pip-audit | :89-97 | 已注释停用（上游 pip-api 在 Windows 非 ASCII 路径下崩溃，见注释） |

轨 B（`scripts/hooks/pre-commit`，纯 sh、零依赖）：先 hygiene（:7）再禁直提 main（:8）。启用方式 `git config core.hooksPath scripts/hooks`（CONTRIBUTING.md:160）。禁提逻辑在 `scripts/check_branch_policy.py:30`：当前分支为 `main` 且未设 `deeptutor.allowMainCommit=true`（豁免读取 :22）即拒绝（提示语 :35，豁免用后需撤销）。

两轨边界：轨 A 管"代码质量与卫生"（格式、密钥、类型、文件规范），轨 B 只管两条硬规则（生成物入库、直提 main）。轨 B 的存在意义是 fresh checkout 无需装 pre-commit 环境也能拦住生成物（`scripts/hooks/pre-commit:5-6` 注释）。

## 7. scripts/check_* 速查

| 脚本 | 入口 | 拦什么 | 被谁调用 |
| --- | --- | --- | --- |
| `scripts/check_architecture.py` | :177 | `deeptutor/` import 的四层依赖边界 + 跨层依赖环（Tarjan SCC） | tests.yml:62；测试 `tests/architecture/test_import_boundaries.py` |
| `scripts/check_branch_policy.py` | :30 | 直接提交 main（豁免 `deeptutor.allowMainCommit=true`） | scripts/hooks/pre-commit:8 |
| `scripts/check_repo_hygiene.py` | :51 | tracked 生成物 / 字节码 / `web/out` dist / 异常文件名 | `.pre-commit-config.yaml:17`、scripts/hooks/pre-commit:7、check_workspace_hygiene.py:28 |
| `scripts/check_workspace_hygiene.py` | :34 | 工作区不干净（porcelain 非空 :19-24），随后转发 repo hygiene（:28） | repository-hygiene.yml:23 |

## 8. 失败走查：从红色日志回到具体门禁

走查一：PR 上 **"Run Ruff format check"** 红（tests.yml:57）。

1. PR Checks → 失败 job `Lint and Format` → step `Run Ruff format check`。日志形如 `would be reformatted: deeptutor/xxx.py`。
2. 定位：这是格式门，不是逻辑问题。本地执行 `ruff format deeptutor/xxx.py`。
3. 若本地改完 CI 仍红：查本地 ruff 版本是否 `0.16.0`（CI 钉版 tests.yml:51，hook 钉版 `.pre-commit-config.yaml:55`）。版本漂移会让 format 结论不一致——按钉住版本重装。
4. 验证：本地 `ruff format --check .` 零退出后推送，等 CI 变绿。

走查二：发布后 **PyPI Release 在 "Verify release tag is on main"** 红（pypi-release.yml:71-81）。

1. Actions → PyPI Release → 失败 step 日志：`Release tag vX.Y.Z (<sha>) is not on origin/main; refusing to publish to PyPI.`（:79）。
2. 定位：tag 所指 commit 不是 origin/main 的祖先——常见于从修复分支直接打 tag 发 release。PyPI 门拒绝，包未发布。
3. 本地复现验证：`git merge-base --is-ancestor <tag> origin/main && echo on-main || echo not-on-main`。
4. 处置：删 release 与 tag，在 main 上重新打 tag 建 release；无需改任何 workflow 配置。

走查三：push 后 **Repository Hygiene / "Check tracked generated files"** 红（repository-hygiene.yml:23）。

1. 日志按 `path: 原因` 逐行列出（原因文案来自 `scripts/check_repo_hygiene.py` 的 `violation` 返回值 :33-47，如 `generated output` / `compiled bytecode` / `frontend build output` / `unusual filesystem whitespace`）。
2. 若日志先报工作区脏，则来自 `check_workspace_hygiene.py:19-24` 的 porcelain 输出——CI checkout 的主仓工作区不应出现，出现说明 workflow 之外有写动作，先看同 run 其他 step。
3. 本地复现：`python3 scripts/check_workspace_hygiene.py`。
4. 处置：tracked 生成物用 `git rm --cached <path>` 并补 `.gitignore`；文件名空白问题直接改名。不要用 `git update-index --skip-worktree` 之类手段绕过。

## 9. 与相邻文档的边界

- pytest 目录组织、夹具与标记约定 → guide-testing；本文只提供 CI 执行入口 `tests.yml:286`。
- scripts/ 下非门禁脚本（启动器、导出工具等）的用途与存续 → `evidence/scripts-inventory-20261007/report.md`（scripts-inventory 扫描，基线同 `f07029cfc`）。
- 架构分层的业务含义 → `scripts/check_architecture.py` 与 `.importlinter` 契约本体；本文只描述门禁触发方式。
