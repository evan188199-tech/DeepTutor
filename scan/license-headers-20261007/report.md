# 源码 License/SPDX 头一致性清点（AGEN-1104）

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13，2026-10-07 fetch）
- 性质：只读清点，未改动任何代码；本分支仅新增本 `scan/license-headers-20261007/` 目录（报告、复跑脚本、机器可读结果、校验和）
- 结论：**仓库采用"集中式许可"模式——3,064 个一方源码文件中 0 个含 SPDX 标识符或版权行，缺头本身即为仓库现状的统一口径，未发现任何 SPDX id 与 LICENSE 不一致、holder 漂移或 year 漂移**。真正的缺口不是"头写错了"，而是"这一约定没有成文"（CONTRIBUTING.md 无任何 licensing/header 政策说明）。可拆修复卡见"漂移清单与建议"。

## 口径与规则（可复跑）

1. 枚举：`git ls-files`（HEAD 跟踪文件），审计扩展名 `.py .ts .tsx .js .jsx .mjs .cjs .mts .cts .sh .command .bat`，另含 `scripts/hooks/` 下无扩展名 hook（`pre-commit`）。
2. 排除域：`web/vendor/**`（16 个源码文件，自带 LICENSE，属第三方声明轴，与 verify-third-party-notices 卡去重）；`node_modules`（防御性，未跟踪）。
3. 头区判定：每文件仅看前 30 行（含 shebang/编码行）。
4. 基线解析：取 `LICENSE` 文件**尾部 appendix** 的 Copyright 行（正文中的 "copyright" 为定义散文，须跳过）→ 基线为 **Apache-2.0 / "Data Intelligence Lab, The University of Hong Kong" / 2025**。
5. 生成文件豁免（GENERATED）：结构性证据（路径含 `/generated/`、`.generated.`、`.d.ts`）或头区**注释行**内含 generator 标记（auto-generated / regenerate with / generated from / do not edit）。docstring/字符串里的同词不算（已实测修正过一例误报）。
6. 分类桶：`SPDX_OK`、`SPDX_MISMATCH`（SPDX 存在但 ≠ Apache-2.0，HIGH）、`HOLDER_DRIFT`/`YEAR_DRIFT`（有版权行但 holder/年份偏离基线，MEDIUM；year 规则：全部年份 < 基线年 2025 记漂移）、`APACHE_NOTICE`/`COPYRIGHT_ONLY`（有声明但无 SPDX，LOW）、`NO_HEADER`（LOW，按目录聚合报告）、`GENERATED`（INFO）。
7. 复跑命令（干净 worktree 内，Python 3 标准库，无依赖）：

```bash
python3 scan/license-headers-20261007/scan_license_headers.py \
  --json scan/license-headers-20261007/results.json
```

## 逐目录统计表

| directory | total | SPDX_OK | SPDX_MISMATCH | HOLDER_DRIFT | YEAR_DRIFT | APACHE_NOTICE | COPYRIGHT_ONLY | NO_HEADER | GENERATED |
|---|---|---|---|---|---|---|---|---|---|
| `(root)` | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `deeptutor` | 1029 | 0 | 0 | 0 | 0 | 0 | 0 | 1029 | 0 |
| `deeptutor_cli` | 22 | 0 | 0 | 0 | 0 | 0 | 0 | 22 | 0 |
| `deeptutor_web` | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| `scripts` | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 18 | 0 |
| `tests`（顶层 5 + 24 个子目录） | 738 | 0 | 0 | 0 | 0 | 0 | 0 | 738 | 0 |
| `web`（顶层 9 + 12 个子目录） | 1255 | 0 | 0 | 0 | 0 | 0 | 0 | 1248 | 7 |
| **合计** | **3064** | **0** | **0** | **0** | **0** | **0** | **0** | **3057** | **7** |

子目录明细（tests 5/24、web 12/24 行级数字）见 `results.json` 的 `by_dir` 字段；合计口径与上表一致。

- 高危（SPDX_MISMATCH）：**0**
- 中危（HOLDER_DRIFT / YEAR_DRIFT）：**0**
- 低危（NO_HEADER）：3057 项，按目录聚合如上（`deeptutor` 1029、`web` 1248、`tests` 738、`scripts` 18、其余 24），不逐文件罗列。
- 交叉核对：`git grep -liE 'copyright|SPDX-License-Identifier'` 全仓（含 30 行头区之外）仅命中 `web/vendor/`、`LICENSE`、`THIRD_PARTY_NOTICES.md` 与 KaTeX 命令名字符串（`web/lib/latex-commands.ts` 内 `"copyright ..."` 为命令表内容，非版权行），与脚本结果一致。

## 漂移清单与建议（可拆修复卡条目）

| # | 路径/域 | 现状 | 建议 |
|---|---|---|---|
| 1 | `CONTRIBUTING.md` | 全文无 license/header/SPDX 政策；仅根 LICENSE 集中声明 | 新增卡：在 CONTRIBUTING 增加 "Licensing" 一节，成文声明集中式模式；可选二选一——(a) 明确"不加 per-file 头"，或 (b) 新文件统一加单行 `# SPDX-License-Identifier: Apache-2.0`。当前 0 漂移，采纳 (b) 无历史包袱 |
| 2 | `web/vendor/thinking-orbs/`（16 文件，含自带 `LICENSE`） | 内嵌第三方目录，本卡已排除其缺头 | 去重：归 verify-third-party-notices（第三方声明轴）复核其登记；本卡不计 |
| 3 | `web/lib/latex-commands.ts` | 从 `node_modules/katex` 构建产物再生成（仅提取命令名），头注释已写明来源与再生成命令；`THIRD_PARTY_NOTICES.md` 无 katex 条目 | 去重：命令名属事实数据、风险低；依赖版本轴归 scan-deps-drift。如后续采纳 SPDX 政策，生成器模板中补一行 SPDX 即可覆盖 |
| 4 | `web/types/file-system-access.d.ts`、`web/components/common/react-syntax-highlighter-prism-themes.d.ts` | 按规则归 GENERATED 豁免；抽查确认两者为**手写**最小 ambient 声明（非上游复制），无需归属声明 | 无需修复；如未来改为从上游类型包复制，再转第三方声明轴 |
| 5 | `LICENSE` 尾部 | "Copyright 2025"（单年，静态） | 信息项：如未来采纳版权头/年份策略，需决定年份更新规则（当前无头、无冲突） |
| 6 | `scripts/hooks/pre-commit` | 无扩展名 hook，已纳入统计（`scripts` 桶 18 含它），内部含第三方说明段 | 无需修复；列入口径避免漏计 |

## 验收对照

1. 覆盖全部源码目录（deeptutor / deeptutor_cli / deeptutor_web / tests / scripts / web / 根脚本），口径规则成文且脚本可复跑 ✅
2. 缺头（LOW）按目录聚合列出，未逐文件罗列 ✅
3. 未改任何代码；`git diff` 源码零变更，本分支仅新增 `scan/license-headers-20261007/` 下 4 个文件（本报告、脚本、`results.json`、`SHA256SUMS`） ✅
