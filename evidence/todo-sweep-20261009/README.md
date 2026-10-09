# scan: deeptutor 内联 TODO/FIXME/XXX/HACK 清点（2026-10-09）

## 结论速览

| 指标 | 数值 |
| --- | --- |
| 扫描范围（跟踪文件） | `deeptutor/**`（1,245 个文件，含 1,055 个 .py） |
| 排除 | `**/tests/**`、`**/test_*.py`、`__pycache__` |
| 标记总行数 | **2** |
| 可补测缺口 | 0 |
| 产品缺口 | 0 |
| 噪音 | 2 |
| 入选补测/修复种子 | **0** |

本轮轴（内联标记）基本收割完毕：`deeptutor/**` 源码内没有可执行的 TODO/FIXME/XXX/HACK 工作项，唯一 2 处命中均为陈旧 docstring 引用，属噪音，不产种子、无需建卡。

## 基线与方法

- 基线：`origin/main @ 6cf793bd8`（release: v1.6.14，fetch 于 2026-10-09），独立 worktree 新分支，未触碰主工作区。
- 主扫描：`rg -n --hidden`，模式 `\b(TODO|FIXME|XXX|HACK)\b`，限定 `deeptutor/**` 并排除 tests/test_*/pycache。
- 变体复核：大小写不敏感扫描 `to-do/to_do/fix me/xxx/hack` 变体，命中逐条人工判读，全部为普通英文叙述（"to do"、"what to do"）、memory 条目 id 格式 `m_xxx`、产品名（Hacker News、hacker-feeds-cli）或 to-do 功能文案，无隐藏标记。
- yaml/md/json 一并扫描（agents prompt 模板、SKILL.md），无命中。

## 明细清单

| path:line | 标记 | 原文 | 类别 | 建议焦点 | 去重结论 |
| --- | --- | --- | --- | --- | --- |
| `deeptutor/tools/tex_chunker.py:11` | TODO | `Based on: TODO.md specification` | 噪音 | docstring 元数据引用了未入库的 `TODO.md`（`git ls-files` 全库无该文件），陈旧引用；可顺手删行或改指真实规格文档，非必需 | 不建卡 |
| `deeptutor/tools/tex_downloader.py:11` | TODO | `Based on: TODO.md specification` | 噪音 | 同上，同一模式的成对文件 | 不建卡 |

## 去重结论

- 无新种子，backlog 无需建卡；两条噪音命中均无对应且不需要 backlog 卡。
- 与既有扫描轴 `scan-import-cycles` / `scan-async-tasks` / `scan-logging-consistency` 无重叠，本次为独立的内联标记轴。
- backlog 检索（关键词 TODO/scan）确认无同轴既有卡片。

## 范围外上下文（不产种子，仅供后续轴参考）

- `.pre-commit-config.yaml:111`：`# TODO: Gradually enable stricter checks as types are added` —— 仓库根配置文件，超出 `deeptutor/**` 范围，属真实未完成项，如需可另立配置治理轴。
- `tests/` 目录内 4 行标记，按卡面排除。
- `deeptutor_cli/`、`deeptutor_web/`、`web/`、`scripts/` 全库其余区域（不含 tests）扫描均为 0 命中。

## 复现命令

```bash
rg -n --hidden --glob 'deeptutor/**' \
  --glob '!**/tests/**' --glob '!**/test_*.py' --glob '!**/__pycache__/**' \
  '\b(TODO|FIXME|XXX|HACK)\b'
```

验收对照：
1. 种子 0 条，"每条种子给 path:line 与一句建议、未在 backlog 建卡" 空集成立；
2. 本分支仅新增 `evidence/todo-sweep-20261009/` 下文件，未改任何产品代码；
3. 汇总（总数 2 = 噪音 2 = 明细 2 行；种子 0）与明细一致。
