# 发布元数据版本一致性复核 — verify-citation-version-parity-20261011

- 复核基线: HKUDS/DeepTutor `origin/main` @ `6cf793bd8`（commit message: `release: v1.6.14`）
- 复核日期: 2026-10-11；方式: 纯只读，未修改任何被复核文件，本 `evidence/` 目录为分支上唯一新增内容。
- 去重说明: 与 verify-third-party-notices（NOTICES 轴）不重叠；本卡只核对版本号与引用字段。

## 四处对照表

| # | 来源 | 查询位置 | 取值 | 结论 |
|---|------|----------|------|------|
| 1 | CITATION.cff | 仓库根 `CITATION.cff` | 无 `version` 字段（仅有 `cff-version: 1.2.0`，这是 CFF 模式版本号，不是软件版本）；亦无 `date-released`、`doi` | **漂移：缺软件版本字段** |
| 2 | deeptutor/__version__.py | `__version__` 变量 | `__version__ = "1.6.14"` | 基准值；与最新 release 一致 |
| 3 | pyproject.toml | `[project]` 的 `dynamic`/`version` | `dynamic = ["version"]`；`version = {attr = "deeptutor.__version__.__version__"}` → 解析为 1.6.14 | 一致（动态引用 #2，声明为单一事实源） |
| 4 | 最近 release/tag（gh 只读） | Latest release = `v1.6.14`，published `2026-10-08T03:35:21Z`，target `main`，非 draft/非预发布；tag `v1.6.14` → commit `6cf793bd8` | v1.6.14 | 一致；tag 指向的 commit 即本次复核基线 |

## 漂移项与应改文件

- 唯一漂移项: `CITATION.cff` 缺少 `version` 字段（附带缺 `date-released`），导致引用元数据与发布版本脱节，引用者无法对应到具体版本。
- 应改文件: 仅 `CITATION.cff`。
- 其余三处（`deeptutor/__version__.py`、`pyproject.toml`、release/tag）经单一事实源链路两两一致，无需改动。

## 对齐建议（本卡不改文件，仅建议）

1. 在 `CITATION.cff` 顶层补 `version: 1.6.14`，可选补 `date-released: 2026-10-08`（对齐 v1.6.14 发布时间）。
2. 发版流程在同一提交里同步 CITATION.cff（随 bump `__version__` 一起改），或在 CI 加一致性检查：CFF `version` == pyproject 解析出的 version。
3. 引用字段交叉核对（非版本轴）: `title`/`authors` 在顶层与 `preferred-citation` 两处一致（7 位作者逐一相同）；`journal: arXiv preprint arXiv:2604.26962`、`year: 2026`，与标题自洽，无内部矛盾。

## 复现命令（只读）

```bash
# 本地基线（在新 worktree 中，基于 origin/main）
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor worktree add /Users/Shared/DeepTutor/dt-agen1716-wt origin/main
cat /Users/Shared/DeepTutor/dt-agen1716-wt/CITATION.cff
cat /Users/Shared/DeepTutor/dt-agen1716-wt/deeptutor/__version__.py
grep -n '^dynamic\|^version' /Users/Shared/DeepTutor/dt-agen1716-wt/pyproject.toml

# 上游 release/tag（gh 只读）
gh release view v1.6.14 -R HKUDS/DeepTutor --json tagName,name,publishedAt,targetCommitish,isPrerelease,isDraft
gh api 'repos/HKUDS/DeepTutor/tags?per_page=5' --jq '.[] | [.name, .commit.sha[0:9]] | @tsv'
gh release list -R HKUDS/DeepTutor --limit 5
```

## 基线文件哈希

见同目录 `SHA256SUMS`：包含本报告与三个被复核源文件（`CITATION.cff`、`deeptutor/__version__.py`、`pyproject.toml`）在基线 commit `6cf793bd8` 的 SHA256，用于证明复核基线未被改动。
