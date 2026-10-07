# 仓库跟踪产物卫生扫描报告（tracked artifacts）

- 扫描对象：HKUDS/DeepTutor @ `origin/main` = `f07029cfc`（release: v1.6.13）
- 扫描方式：纯只读。`git ls-tree -r -l` 全量枚举 3599 个跟踪文件（共 57.6 MB），按 10 类产物模式矩阵（约 40 条正则）逐一匹配；候选路径再用 `git check-ignore --no-index` 复核。未修改任何文件，未执行任何 git 写操作（未 checkout/reset/clean/rm --cached）。
- 与兄弟卡去重：本报告只覆盖"跟踪产物"轴；不涉及文档漂移（scan-docs-drift）、证据完整性（verify-evidence-integrity）、导入成本（scan-import-cost）。

## 结论

**跟踪文件中未发现任何缓存/构建产物/日志/本地数据/OS 杂项（0 条命中）。** 仓库在产物卫生方面状态良好；主要可交付项是 7 处 `.gitignore` 覆盖缺口（均为纯追加规则，无需 `git rm --cached`）。

## 分类扫描明细

| 类别 | 检查模式（节选） | 命中数 |
|---|---|---|
| Python 缓存 | `__pycache__/`、`*.pyc`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.hypothesis/`、`.tox/`、venv | 0 |
| 构建/打包输出 | `dist/`、`build/`、`web/dist/`、`*.tsbuildinfo`、`node_modules/`、`*.egg-info/`、`.next/`、`.vite/` | 0 |
| 测试产物 | `playwright-report/`、`test-results/`、`htmlcov/`、`.coverage*`、`coverage.xml`、`junit*.xml`、`.benchmarks/` | 0 |
| 日志 | `*.log`、`*.log.N`、`logs/` | 0 |
| 本地数据 | `*.db`、`*.sqlite*`、`*.dump`、`backups/`、`*.bak/orig/rej` | 0 |
| OS 杂项 | `.DS_Store`、`Thumbs.db`、`desktop.ini` | 0 |
| 编辑器/IDE | `.idea/`、`.vscode/`、`*.swp`、`*~` | 0 |
| 临时/通用缓存 | `tmp/`、`.cache/` | 0 |

## 特殊跟踪对象评估（非违规，但需知情）

| 路径 | 体积 | 评估 |
|---|---|---|
| `web/contracts/schema/openapi.json` | 1.6 MB | 生成物但为契约优先工作流的一部分（`openapi-typescript` 生成，提交信息如 "chore(contracts): sync browser APIs"），**建议保留跟踪** |
| `web/contracts/generated/api.ts` | 1.1 MB | 同上；web 源码中有 2 个文件直接 import，`git rm --cached` 会立即破坏构建，**建议保留** |
| `web/contracts/generated/turn-protocol.ts`、`schema/turn-protocol.json` | — | 同一契约工作流，**建议保留** |
| `assets/figs/**`（171 个文件，约 24 MB） | 单文件最大 2.6 MB | README/文档引用的截图与架构图，属有意入库的文档资产，非产物 |

**`git rm --cached` 影响面评估：候选集为空。** 唯一"生成物入库"的是契约文件，移除的影响面为 2 处直接 import（`web/` 源码）+ 契约同步工作流，结论为不移除。

## `.gitignore` 修订建议

现有 `.gitignore`（约 300 行）覆盖面已经很好：字节码、构建目录、egg-info、node_modules、Next/vite 输出、`*.tsbuildinfo`、`web/test-results/`、`web/playwright-report/`、pytest/mypy/ruff 缓存、`*.log`、`.DS_Store`、IDE 目录、`*.db/sqlite`、音视频与压缩产物等均已覆盖，且 `deeptutor.egg-info/` 等本地实测均被正确忽略。

以下缺口经 `git check-ignore --no-index` 实测确认（左侧路径当前**不会**被忽略）：

### 建议直接追加（安全，纯追加规则，无历史改写、无 rm --cached）

```gitignore
# 本地备份目录（本地工作区已出现未跟踪 backups/，存在被 git add . 误收的风险）
backups/
# 日志目录整体（现有 *.log 只覆盖文件，logs/ 内非 .log 文件不受保护）
logs/
# pytest-benchmark / hypothesis 本地产物
.hypothesis/
.benchmarks/
# JS 侧 coverage 输出目录（现仅有 .coverage / htmlcov）
coverage/
# junit 报告（现仅有 nosetests.xml）
junit*.xml
```

### 建议确认后追加（低风险，但改变规则作用域）

```gitignore
# 根级临时目录（现仅 web/tmp/）
tmp/
# 将 web/playwright-report/ 与 web/test-results/ 泛化为根级
playwright-report/
test-results/
```

## 体积参考

- 跟踪文件总计：3599 个 / 57.6 MB。
- 最大 blob 前三：`assets/figs/web-1.4.6+/memory/01-3 layer memory graph.png`（2.6 MB）、`web/contracts/schema/openapi.json`（1.6 MB）、`assets/figs/web-1.4.6+/home/09-demo …png`（1.4 MB），均为有意资产。

## 复核命令

```bash
git -C <worktree> ls-tree -r -l HEAD | wc -l                      # 3599
git -C <worktree> ls-tree -r -l HEAD | grep -Ei '__pycache__|\.pyc$|\.DS_Store|tsbuildinfo|playwright-report|test-results|\.pytest_cache|\.log$|\.egg-info|node_modules|/dist/|/build/'   # 空
git -C <worktree> check-ignore -v --no-index backups/x logs/x     # 当前不忽略，证实缺口
```
