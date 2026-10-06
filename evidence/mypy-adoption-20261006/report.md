# mypy 渐进收养宽松面全量清点（AGEN-856 · 2026-10-06）

- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（v1.6.13），只读清点，未改任何产品代码与配置。
- mypy 版本：1.13.0（与 `.pre-commit-config.yaml:113` rev v1.13.0 一致），目标 python_version 3.11。
- 复现：`bash evidence/mypy-adoption-20261006/run_inventory.sh`（每轮 mypy 限时 900s，cache 写在 evidence/raw/ 下，不落 repo 树；汇总脚本纯标准库）。机器差异下错误量可能有 ±个位数浮动，分布结论稳定。

## 一、核心结论：当前 mypy 门禁形同虚设

在 hook 自身环境（pyproject 配置 + hook 参数 + stub 依赖）下，pre-commit mypy 的实际检查表面为 **0 个错误**：97 个错误全部落在 hook 路径排除的目录里（api/routers 46、agents 33、services/rag 18）。也就是说，今天这个 hook 不可能挡住任何提交——唯一真实生效的"放宽"就是"什么都不查"。

## 二、宽松面清单（两处配置的全部放宽项）

`.pre-commit-config.yaml`（TODO 注记 :111，hook :112-121）：
| 行 | 放宽项 | 效果 |
| --- | --- | --- |
| :116 | `--ignore-missing-imports` | 未装 stubs 的三方库一律跳过 |
| :116 | `--no-error-summary` | 隐藏汇总（不掩盖错误，仅展示） |
| :116 | `--no-strict-optional` | 关闭 Optional 语义追踪（union-attr/arg-type 主来源） |
| :117 | exclude `^(tests/|scripts/|deeptutor/agents/|deeptutor/services/rag/|deeptutor/api/routers/)` | 5 类路径完全不送检；正则 `^tests/` 漏掉 `deeptutor/learning/tests/` |
| :118-121 | additional_dependencies 三件套 | 补 yaml/requests/croniter stubs（本地裸跑需自装，见复现脚本） |

`pyproject.toml` `[tool.mypy]`（:498-512）：
| 行 | 放宽项 |
| --- | --- |
| :503-504 | `warn_return_any = false`、`warn_no_return = false` |
| :506-507 | `ignore_missing_imports = true`、`follow_imports = "silent"` |
| :509-512 | `check_untyped_defs / disallow_untyped_defs / disallow_incomplete_defs / no_implicit_optional = false` |
| :515-517 | override `tests.*` → ignore_errors（不匹配 `deeptutor.learning.tests.*`，见建议 2） |
| :519-521 | override `deeptutor.tools.*` → ignore_errors（tools 表面错误被整目录吞掉） |

## 三、量化：七轮限时 mypy 实测

| run | 配置 | 总错误 | pre-commit 表面 |
| --- | --- | --- | --- |
| F hookenv | pyproject + hook 参数 + stubs（= 真实 hook 环境） | 97 | **0** |
| E truegate | 同 F 但不装 stubs | 131 | 33（全为 import-untyped） |
| G hookenv+strict-optional | F 去掉 `--no-strict-optional` | 429 | **262** |
| D | 宽松基线 + `--no-strict-optional` | 144 | 46 |
| A | 宽松基线（无 overrides、无 stubs） | 489 | 321 |
| B | A + `--check-untyped-defs --no-implicit-optional --warn-return-any --warn-no-return` | 946 | 647 |
| C | A + `--disallow-untyped-defs --disallow-incomplete-defs` | 1940 | 1231 |

A 档错误码分布：union-attr 191、arg-type 121、assignment 41、import-untyped 36、index 23、return-value 16、var-annotated 13、attr-defined 12。

### 按目录错误量排名（A 档基线；G 档 = hook 环境去掉 no-strict-optional 的门禁表面）

| 目录 | A | B | C | 文件数 | kLOC | #type:ignore（条/kLOC） |
| --- | --- | --- | --- | --- | --- | --- |
| deeptutor/services | 212 | 385 | 491 | 428 | 105.7 | 44（0.42） |
| deeptutor/api | 65 | 138 | 504 | 53 | 26.9 | 7（0.26） |
| deeptutor/agents | 63 | 100 | 95 | 67 | 18.9 | 9（0.48） |
| deeptutor/partners | 36 | 67 | 62 | 31 | 12.8 | 5（0.39） |
| deeptutor/tools | 26 | 30 | 48 | 34 | 9.5 | 2（0.21） |
| deeptutor/learning | 26 | 87 | 584 | 39 | 14.9 | 0 |
| deeptutor/video_learning | 18 | 22 | 19 | 11 | 3.2 | 3（0.93） |
| deeptutor/multi_user | 10 | 19 | 13 | 20 | 3.9 | 3（0.77） |
| deeptutor/capabilities | 9 | 15 | 24 | 71 | 14.6 | 0 |
| deeptutor/book | 6 | 16 | 12 | 43 | 10.6 | 0 |
| deeptutor/co_writer | 6 | 11 | 16 | 4 | 1.3 | 0 |
| deeptutor/runtime | 5 | 13 | 14 | 51 | 10.8 | 8（0.74） |
| deeptutor/reading | 3 | 11 | 8 | 20 | 6.7 | 9（1.34） |
| deeptutor_cli | 2 | 6 | 4 | 23 | 5.7 | 1（0.18） |
| deeptutor/utils | 1 | 1 | 3 | 9 | 2.2 | 0 |
| deeptutor/knowledge | 1 | 8 | 28 | 9 | 4.5 | 0 |

忽略注释密度全仓共 91 处 `# type: ignore`（1051 个 .py / 约 269 kLOC），密度不是主要矛盾；矛盾在 no-strict-optional 与路径排除面。

## 四、Top 收紧建议（路线卡条目，按性价比排序）

1. **[快赢·一行配置] 补 `deeptutor/learning/tests/` 覆盖缺口** — 该目录既不匹配 `.pre-commit-config.yaml:117` 的 `^tests/`，也不匹配 `pyproject.toml:515-517` 的 `tests.*` 模块 override。修法：pyproject 增 `module = "deeptutor.learning.tests.*"` override（或 exclude 改 `(^|/)tests/`）。收益：立即 -24 处基线 latent 错误（`deeptutor/learning/tests/test_assessment.py:229`、`:230`、`:247`、`:248` 共 14 处为大头），并与"测试不进门禁"的既有意图一致。
2. **[前置修复] `deeptutor/services/config/readiness.py`** — A 档 19 处全仓最高，且全部位于未来门禁表面（G 档同分）：`readiness.py:238`、`:239`、`:243`、`:244`（union-attr，Optional 判空缺失）。修完即可单独合并。
3. **[前置修复] subagent 两文件 29 处** — `deeptutor/services/subagent/opencode_family.py:265`、`:266`、`:268`、`:272`（16 处）；`deeptutor/services/subagent/deepseek_harness.py:270`、`:273`、`:274`、`:278`（13 处）。G 档表面合计 29/262 ≈ 11%。
4. **[前置修复] partners 渠道两文件 20 处** — `deeptutor/partners/channels/matrix.py:175`（assignment）、`:494`-`:496`（union-attr，11 处）；`deeptutor/partners/channels/telegram.py:539`、`:550`、`:569`、`:575`（9 处）。
5. **[前置修复] `deeptutor/services/skill/hub.py:432`-`:435`（10 处）与 `deeptutor/services/session/turns/request_preparer.py:488`、`:489`、`:890`、`:895`（9 处）** — 修完 2-5 后 G 档表面 262 → 约 161，剩余为长尾。
6. **[开关翻转] 移除 `--no-strict-optional`（`.pre-commit-config.yaml:116`）** — 门禁表面 0 → 262。建议在 2-5 完成后翻转并接受长尾逐步清零；union-attr（G 档 149）与 arg-type（55）是主体。预期收益：Optional/None 语义纪律全覆盖，堵住 None 传播类缺陷。
7. **[下一步开关] `check_untyped_defs` 前必清两文件** — `deeptutor/services/session/sqlite_store.py:1956`、`:2079`、`:4236`（B 档 3→68，全仓最大单文件增量 +65）；`deeptutor/api/routers/system.py`（0→30）。两文件清完 ≈ B 档 -95/457，之后可翻 `pyproject.toml:509` 并用 per-module override 渐进铺开。
8. **[长期] `deeptutor/api/routers/` 重新纳入前先补注解** — 该目录被 `.pre-commit-config.yaml:117` 排除；deeptutor/api C 档 504（B→C 增量最大的目录），`deeptutor/api/routers/knowledge.py:697`、`:999`、`:1003`、`:1159` 所在文件 C 档 100、`settings.py` 65、`partners.py` 54、`mastery_path.py` 37。按文件逐个移出 exclude，避免一次性爆量。
9. **[长期] `agents/`、`services/rag/`、tools override（`pyproject.toml:519-521`）同法收编** — A 档 latent：agents 63（`deeptutor/agents/base_agent.py:108`、`:110` 起 16 处）、rag 18 处在 F 档可见；tools 表面被 override 整目录吞掉（G 档 tools 表面 = 0，latent 26），重新纳入时先修 `deeptutor/tools/question/question_extractor.py:332`、`:333`、`:339` 与 `deeptutor/tools/builtin/__init__.py:30`、`:744`。
10. **[可选·低优] stubs 口径对齐** — hook 自带三件套 stubs（`.pre-commit-config.yaml:118-121`），但 `--ignore-missing-imports` 掩盖其余未注解依赖（A 档 36 处 import-untyped，如 `deeptutor/capabilities/obsidian/vault.py:22`、`deeptutor/services/cron/service.py:134`、search providers 全系）。与建议 1 合并为一张低优 chore 卡即可，收益小。

## 五、验收对照

1. 口径可复现：七轮命令全部固化在 `run_inventory.sh`，mypy 钉 1.13.0，每轮 `run_limited.py` 限时 900s。
2. 只读：mypy cache 写入 `evidence/mypy-adoption-20261006/raw/.mypy_cache_*`（提交前删除），pyproject/.pre-commit-config.yaml 零改动；汇总脚本纯标准库。
3. 每条建议均附 path:line 与预期收益（见上）。
