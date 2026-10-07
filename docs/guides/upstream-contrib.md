# 上游贡献流程核对清单

开 PR 给上游 HKUDS/DeepTutor 之前逐项核对的中文导读，目标是把返工点拦在提交之前。
CI 流水线各 job 怎么跑见 `docs/guides/ci-workflows.md`（分工见文末），本文只回答"开 PR 前要核对什么"。

- 基准：`origin/main` @ `f07029cfc`（v1.6.13，2026-10-07 fetch）。
- 出处均为仓库内文件 `path:line`；行号以上游当前内容为准，会随上游前移，引用失效时以文件内容为准重查。
- 说明：卡面提到的 `DEVELOPMENT_WORKFLOW.md` 在 `origin/main` 上不存在（仅本地 main 工作区有一份未合入上游的版本，本文不引用它）。上游贡献约定实际集中在 `CONTRIBUTING.md`、`AGENTS.md` 与 `.github/` 模板、工作流。

## 与本地推送边界的衔接（先读这段）

1. 本地铁律：只推本卡新建分支到 myfork（`git push myfork HEAD:refs/heads/<分支名>`）；`main`/`dev` 一律不推；任何分支不 force push。
2. 上游依据：PR 一律打 `dev`，不打 `main`（CONTRIBUTING.md:41-42；pull_request_template.md:4-7、37）；`main` 只在发版时前进（pull_request_template.md:5-6）。
3. fork 的 `main`/`dev` 会被同步应用按 `.github/pull.yml:3-10` 定期从 HKUDS 硬重置（`mergeMethod: hardreset`）——在 `main`/`dev` 上留的任何本地提交都可能被抹掉。这是"只推自己的分支、不在 main/dev 上工作"的上游依据。
4. 用法：下列清单在本地全部核对通过后，再过"上游 PR 合适性门禁"（AI 审核、上游 issue/PR 去重、rebase 到 dev、相关测试、公开安全检查）；任一不过就停在本卡分支，不强行开 PR。

## 开 PR 前核对清单

1. **PR 目标分支是 dev（不是 main）**
   功能/重构/API/配置/一般 bug 修复 → `dev`；多用户/多租户 → `multi-user`；拿不准 → `dev`。
   出处：CONTRIBUTING.md:38-42（分支表 + IMPORTANT 禁止直发 main）、46-60（选支规则）；pull_request_template.md:37（模板首项勾选）。

2. **从最新目标分支切出 feature 分支**
   `git checkout dev && git pull origin dev` 后再 `git checkout -b feature/your-feature-name`。
   出处：CONTRIBUTING.md:66-77。

3. **动手前在对应 issue 下声明"我在做"**，优先认领 `good first issue`。
   出处：CONTRIBUTING.md:88-89。

4. **PR 描述关联 issue**：`Closes #...` / `Related to #...`。
   出处：pull_request_template.md:16-18。

5. **提交信息为 `<type>: <短描述>`**，type ∈ feat / fix / docs / style / refactor / test / chore；feat 对应 MINOR、fix 对应 PATCH 版本号。
   出处：CONTRIBUTING.md:212-216（格式）、218-227（类型表）。
   本地既有分支开 PR 前按此逐条自查提交信息。

6. **`pre-commit run --all-files` 本地全量绿**，不只跑改动文件。
   工具链：Ruff、Prettier、detect-secrets、Bandit、MyPy 等（CONTRIBUTING.md:177-187；.pre-commit-config.yaml:54-115）。
   本地警告在 CI 是严格模式，会自动拒绝不过的 PR（CONTRIBUTING.md:189-190）；不要用 `--no-verify` 绕过（CONTRIBUTING.md:148）。

7. **CI 同款检查本地复跑**
   - `ruff check .` + `ruff format --check .`（.github/workflows/tests.yml:53-57，ruff==0.16.0 见 51 行）
   - `lint-imports` + `python scripts/check_architecture.py`（.github/workflows/tests.yml:59-62，依赖分层边界）
   - Python 测试：`pytest -q tests deeptutor/learning/tests`（.github/workflows/tests.yml:283-289；版本矩阵 3.11-3.14，见 238 行）
   - 前端：`npm run check`，Playwright 审计 `WEB_BASE_URL=… npm run audit`（.github/workflows/tests.yml:83-107）

8. **新增了相关测试**（模板硬性勾选项）。
   出处：pull_request_template.md:41。

9. **密钥扫描与基线**：新误报用 `detect-secrets scan > .secrets.baseline` 更新基线，而不是绕过钩子。
   出处：CONTRIBUTING.md:129-135。

10. **Python 编码标准**：所有函数签名带类型注解、优先 f-strings、PEP 8（Ruff 强制）、函数小而专一；新模块/类/公开函数带 Google 风格 docstring。
    出处：CONTRIBUTING.md:194-205。

11. **文档随行**：引入新功能或新配置时同步更新 `README.md`。
    出处：CONTRIBUTING.md:206；模板勾选 pull_request_template.md:42。

12. **依赖变更两处落点**：extras 定义在 `pyproject.toml`，`requirements/` 目录镜像同一批依赖组供 Docker/CI 安装——改依赖两处都要动。
    出处：AGENTS.md:135-138。

13. **工作区卫生**：`web/.next*`、`node_modules`、测试报告、字节码等可再生构建产物不入库；已被跟踪的用 `git rm --cached` 摘除而非删本地文件。
    出处：CONTRIBUTING.md:150-155；仓库卫生 CI 跑 `scripts/check_workspace_hygiene.py`（.github/workflows/repository-hygiene.yml:22-23）；本地自查命令见 CONTRIBUTING.md:143-144。

14. **安全红线**：上传大小限制（通用 100MB / PDF 50MB）与多层校验、文件名消毒防路径穿越；子进程一律 `shell=False`；路径用 `pathlib.Path`；关键脚本 LF 行尾。
    出处：CONTRIBUTING.md:230-242。
    本地补一条：安全细节（复现步骤/PoC/绕过向量）只经附件交给人，不写入任何推送的分支或 PR 文本。

15. **不开空 issue、不重复 issue**：`blank_issues_enabled: false`；模板自带"已搜索现有 issue"查重勾选。
    出处：.github/ISSUE_TEMPLATE/config.yml:1；bug_report.yml:13；feature_request.yml:13。

16. **用对 issue 模板与标签**：bug_report → `bug`+`triage`；feature_request → `enhancement`；docs → `docs`+`triage`；eduhub → `eduhub`+`triage`；question → `question`。
    出处：bug_report.yml:3-4；feature_request.yml:3-4；docs.yml:4；eduhub.yml:4；question.yml:3。

## 发版与 changelog 习惯（只读背景，贡献者一般不触发）

- 版本唯一来源是 `deeptutor/__version__.py`；发版 = 改这里、提交、给该提交打 `v<版本>` tag（deeptutor/__version__.py:3-9）。
- PyPI 发布由 GitHub Release published 触发；tag 必须是 `vMAJOR.MINOR.PATCH`（可选 PEP 440 后缀），必须落在 `origin/main` 上，且与 `__version__.py` 一致（.github/workflows/pypi-release.yml:10-11、71-81、100-134）。
- Docker 镜像同由 release 触发：tag 为去掉 `v` 的版本号，稳定版另更新 `latest`（.github/workflows/docker-release.yml:8-9）。
- changelog 是每版一篇 `assets/releases/verX-Y-Z.md`（当前 `assets/releases/ver1-6-13.md`），旧版归档进 `assets/releases/past_releases/`；新版开头用 "Building on 上一版" 串链（assets/releases/ver1-6-13.md:5）。
- 对贡献者的含义：`feat`/`fix` 提交类型就是下个版本 bump 与 release notes 的素材来源（CONTRIBUTING.md:220-221）；`main` 只在发版时前进（pull_request_template.md:5-6）。

## 常见返工点（按上游模板与 CI 设计反推）

| 返工点 | 拦截项 | 出处 |
| --- | --- | --- |
| PR 打到了 main | 开 PR 前先查 base 分支；打到 main 会被 retarget，多一轮往返 | pull_request_template.md:4-7 |
| 本地只跑了自己改的文件 | `pre-commit run --all-files` 全量跑 | CONTRIBUTING.md:80-84 |
| CI lint 挂 | 用与 CI 同版本 ruff==0.16.0 | .github/workflows/tests.yml:51 |
| 改动跨模块依赖边界 | `lint-imports` / `check_architecture` | .github/workflows/tests.yml:59-62 |
| 构建产物被提交 | workspace hygiene 脚本 | CONTRIBUTING.md:143、150-155 |
| PR 无关联 issue / 无测试 | 模板勾选项逐个过 | pull_request_template.md:16-18、36-43 |

## 与其他 guide 的分工（去重）

- CI 流水线结构、各 job 细节与门禁链 → `docs/guides/ci-workflows.md`（guide-ci-workflows 卡）；本文只把 CI 当作"本地要复跑什么"的依据引用。
- 文档失效引用 / 漂移扫描 → scan-docs-drift 轴的报告；本文不做事后漂移审计，只提供开 PR 前的静态核对项。
