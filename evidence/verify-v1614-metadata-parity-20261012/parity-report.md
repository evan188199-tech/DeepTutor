# v1.6.14 版本元数据四方对账 — verify-v1614-metadata-parity-20261012

- 基线: HKUDS/DeepTutor `origin/main` @ `6cf793bd8`（commit message: `release: v1.6.14`；tag `v1.6.14` 即指向此 commit，latest release，published 2026-10-08T03:35:21Z，非 draft/非预发布）
- 日期: 2026-10-12；方式: 纯只读对账，未修改任何被复核文件，本 `evidence/` 目录为分支上唯一新增内容。
- 去重说明:
  - `evidence/verify-citation-version-parity-20261011`（上一轮扫描，myfork 分支）已覆盖 CITATION.cff / `__version__.py` / 根 pyproject / release-tag 轴；本轮复核其唯一漂移项（CITATION.cff 缺 version）在基线 commit 上仍未修复，其余结论一致。
  - `verify-third-party-notices`（NOTICES 轴）不重叠：本轮不审计 `THIRD_PARTY_NOTICES.md` 内容。
  - 本卡新增覆盖: compose/打包引用轴与 README/docs 声明轴。

## 四方对账表

### 第一方: deeptutor/__version__.py（单一事实源）

| # | 位置 | 取值 | 结论 |
|---|------|------|------|
| 1 | `deeptutor/__version__.py:9` | `__version__ = "1.6.14"` | 基准值；与 tag/release v1.6.14 一致 |
| 2 | `deeptutor/__version__.py:3-6`（docstring） | 声明 CI 校验 tag == 此值；web 徽标与 CLI 横幅直接读取本文件 | 链路声明与实际相符（见下方交叉核对） |

### 第二方: CITATION.cff

| # | 位置 | 取值 | 结论 |
|---|------|------|------|
| 1 | `CITATION.cff:1` | `cff-version: 1.2.0`（CFF 模式版本，非软件版本） | 全文件 1-26 行无 `version`、无 `date-released`、无 `doi` → **漂移：缺软件版本字段** |
| 2 | `CITATION.cff:3-9` 与 `:11-26` | `title`/`authors` 顶层与 `preferred-citation` 逐一相同（7 位作者一致），`journal: arXiv preprint arXiv:2604.26962`、`year: 2026` | 引用字段自洽（沿上一轮结论，本轮复核未变） |

### 第三方: compose / 打包引用

| # | 位置 | 取值 | 结论 |
|---|------|------|------|
| 1 | `pyproject.toml:10` + `pyproject.toml:304-305` | `dynamic = ["version"]`；`version = {attr = "deeptutor.__version__.__version__"}` → 1.6.14 | 一致（动态引用第一方） |
| 2 | `packaging/deeptutor-cli/pyproject.toml:7` + `:79` | 同上 dynamic/attr 链 → 1.6.14 | 一致 |
| 3 | `compose.yaml:138` | `image: ghcr.io/hkuds/deeptutor:latest` | 浮动 tag，无 1.6.14 pin（见说明） |
| 4 | `docker-compose.ghcr.yml:60` | `image: ghcr.io/hkuds/deeptutor:latest` | 同上；`:10-11` 注释说明手动 pin，示例仍是 `1.0.0` |
| 5 | `docker-compose.yml:78-80`、`docker-compose.dev.yml:18`、`compose.codex-oauth.yaml`（仅端口覆盖） | 本地 `build:`（`Dockerfile` / `Dockerfile.runner`）或 overlay，无版本字符串 | 无版本引用，无冲突 |
| 6 | `Dockerfile:106-108` | LABEL 仅 `maintainer` + `description` | 无 OCI 版本 label（如 `org.opencontainers.image.version`） |
| 7 | `.github/workflows/pypi-release.yml:100-116` | 发布前校验 release tag == `deeptutor/__version__.py` 解析值 | 一致性护栏存在，与 docstring 声明相符 |
| 8 | `.github/workflows/docker-release.yml:30-50,86-87` | 要求镜像版本 tag；稳定版额外推 `latest` | `:latest` 为发布流程设计行为，非漂移 |
| 9 | `web/package.json:3` | `"version": "1.0.0"`（包名 `opentutor-web`） | 前端包版本与应用版本 1.6.14 脱节（该字段不参与发布链路，信息项） |
| 10 | `deeptutor/partners/__init__.py:11` | `__version__ = "2.0.0"` | 子包（IM channel 层）自有版本，独立命名空间，非冲突（信息项） |

### 第四方: README / docs 版本声明

| # | 位置 | 取值 | 结论 |
|---|------|------|------|
| 1 | `README.md:51` | 最新发布条目 `[2026.10.8] v1.6.14` → releases/tag/v1.6.14 | 一致 |
| 2 | `README.md:224` | "v1.6.14 is live. `pip install -U deeptutor`" | 一致 |
| 3 | `assets/releases/ver1-6-14.md:1,5,51` | v1.6.14 Release Notes 存在，compare v1.6.13...v1.6.14 | 一致 |
| 4 | `README.md:679` | 截图状态声明 "current for v1.6.5"、截图仍为 "v1.4.6 references" | **漂移：自我声明的过期基准，落后 1.6.14 九个小版本** |
| 5 | `docs/guides/events-and-progress-chain.md:3` | 基线 `origin/dev @ fe003ddce`（v1.6.12） | **漂移：内部指南基线落后当前 main（v1.6.14）** |
| 6 | `docs/guides/tools-surface.md:3` | 基线 `origin/dev @ fe003ddce`（v1.6.12） | 同上 |
| 7 | `docs-for-user/KNOWLEDGE_MIGRATION.md:4` | "matches the v1.6.0 Knowledge Center" | 历史特性参照，按原文自洽，无漂移 |
| 8 | 全库字面量扫描 | `1.6.14` 仅出现于 `__version__.py:9`、`README.md:51,224`、`assets/releases/ver1-6-14.md`；无硬编码旧应用版本残留于 CLI/runtime/web 消费方（横幅/更新检查/插件注册表均动态导入 `deeptutor.__version__`，见 `deeptutor/runtime/banner.py:15,538`、`deeptutor/services/app_update.py:22`、`deeptutor/plugins/registry.py:21,167`） | 零遗漏确认 |

## 不一致清单（逐条附 path:line）

| # | 严重度 | 不一致项 | 位置 |
|---|--------|----------|------|
| 1 | 中 | CITATION.cff 缺软件版本字段 `version`（附代缺 `date-released`），引用元数据与 v1.6.14 脱节（上一轮已发现，本轮确认基线上仍未修复） | `CITATION.cff:1-26` |
| 2 | 低 | README 截图状态自述过期：声明以 v1.6.5 为准、截图停留在 v1.4.6 参照 | `README.md:679` |
| 3 | 低 | 内部指南基线声明停留在 v1.6.12（fe003ddce），落后当前 v1.6.14 | `docs/guides/events-and-progress-chain.md:3`；`docs/guides/tools-surface.md:3` |
| 4 | 信息 | web 前端包版本 `1.0.0` 与应用版本脱节（不参与发布链路） | `web/package.json:3` |
| 5 | 信息 | compose 镜像引用全部浮动 `:latest`，无任何 1.6.14 版本化引用；手动 pin 文档示例为 `1.0.0`（`:latest` 本身为 docker-release 流程设计行为） | `compose.yaml:138`；`docker-compose.ghcr.yml:10-11,60` |
| 6 | 信息 | 镜像无 OCI 版本 LABEL | `Dockerfile:106-108` |

## 修复建议（本卡不执行）

1. 在 `CITATION.cff` 顶层补 `version: 1.6.14` 与 `date-released: 2026-10-08`；长期做法是发版提交随 bump 同步该文件，或在 CI 复用 `pypi-release.yml:100-116` 的解析逻辑加 CFF 一致性检查。
2. 下一次文档轮换时刷新 `README.md:679` 截图状态行与截图集。
3. 指南基线（清单 #3）在各自指南下次修订时 rebase 到新基线，或加 "基线已过期" 提示；不单独为版本号发 PR。
4. 可选：`Dockerfile` 以 build-arg 从 `__version__.py` 注入 `org.opencontainers.image.version` LABEL；可选将 `web/package.json` 版本随应用版本生成或移除该字段。
5. compose 的 `:latest` 属设计行为，如需改进仅需把 `docker-compose.ghcr.yml:11` 示例更新为当前版本号写法。

## 复核命令（只读）

```bash
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor worktree add -b evidence/verify-v1614-metadata-parity-20261012 <wt-path> origin/main
# 四方取值
sed -n '9p' deeptutor/__version__.py
grep -n 'version\|date-released' CITATION.cff
grep -nE 'dynamic|attr = ' pyproject.toml packaging/deeptutor-cli/pyproject.toml
grep -nE 'hkuds/deeptutor' compose.yaml docker-compose.ghcr.yml
grep -n 'v1\.6\.14\|v1\.6\.5\|v1\.6\.12' README.md docs/guides/*.md
gh release view v1.6.14 -R HKUDS/DeepTutor --json tagName,publishedAt,targetCommitish,isDraft,isPrerelease
```

## 基线文件哈希

见同目录 `SHA256SUMS`：被复核源文件在基线 commit `6cf793bd8` 的 SHA256，用于证明复核基线未被改动。
