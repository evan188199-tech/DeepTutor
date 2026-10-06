# 临时文件卫生清点报告（mkdtemp / NamedTemporaryFile / 残留清理）

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
- **扫描日期**: 2026-10-06（UTC）
- **范围**: 全仓库 `*.py`（排除 `web/`、`evidence/`、虚拟环境），只读静态扫描，**未修改任何产品代码**（本分支仅新增 `evidence/` 下文件）
- **方式**: `scripts/scan_tempfile_hygiene.py`（stdlib AST + 定向正则，输出确定性 JSON）+ 逐处人工复核清理路径；重跑输出逐字节一致（见 §6）
- **去重轴**: scan-atomic-write（`scan/atomic-write-tmp-fsync-20261005`，原子写/固定名 tmp/fsync 轴）、scan-persistence（`docs/persistence-scan-20261004`，存储面/无界增长轴）、fix-swallow-log-batch（`agent/agen928-swallow-log-batch`，v1.6.13 七处 LOW 吞错点）

## 1. 结论（PASS）

| 维度 | 结果 |
| --- | --- |
| 生产代码 tempfile API 使用点 | **38 处 / 31 文件**（mkstemp 11、TemporaryDirectory 11、mkdtemp 9、NamedTemporaryFile 7） |
| 自动清理（with 上下文 / delete=True） | 13 处，全部正确 |
| 手动清理点（mkdtemp/mkstemp/ delete=False） | 25 处；24 处有 try/finally 或等价回收；**2 处已知缺口**（tex_downloader、subagent staging，见去重表） |
| 废弃/危险 API | `tempfile.mktemp` 0 处、`gettempdir` 0 处、`SpooledTemporaryFile` 0 处 |
| `/tmp` 硬编码 | 仅 2 处且均在沙箱命名空间内（`cli_apps/runner.py:117`、`sandbox/backends.py:208`，带 nosec 注释，非宿主路径） |
| **本轴新增缺口** | **HIGH 0 / MEDIUM 6 / LOW 2**（G1–G8，见 §4） |

总体判断：临时文件生命周期纪律整体良好——统一的 `file_io` 原子写、mkstemp/uuid 唯一命名为主流，全部 5 处 `NamedTemporaryFile(delete=False)` 都有 try/finally 兜底。缺口集中在两类：**partner/用户状态类小文件的 ad-hoc 固定名 `.tmp` 写入缺 try/finally**（异常即残留），以及**沙箱执行环境 TMPDIR 目录无任何回收责任方**（跨进程累积）。

## 2. 口径

- "使用点" = AST 识别的 `tempfile.*` 调用（`data/tempfile-usage.json`）+ 正则识别的 ad-hoc tmp 路径构造（`with_suffix/with_name(...tmp)`、f-string `/ f"...tmp"`、`TMPDIR/TMP/TEMP` env、`/tmp` 字面量；`data/tmp-path-patterns.json`）。
- "残留" = 异常/失败/强杀路径上临时文件或目录未被本进程或任何后续机制删除。
- "跨进程残留" = 临时文件由子进程/沙箱进程产生或持有、父进程异常退出后无人回收。
- `tests/`、`scripts/` 命中单列，不计入生产缺口（抽检均有 tearDown/清理断言：`tests/services/rag/test_pipeline_integration.py:108-110`、`tests/services/skill/test_skill_hub.py:281-282,445`）。

## 3. 使用点统计

### 3.1 tempfile API（38 处生产调用）

| API | 数量 | 清理形态 |
| --- | --- | --- |
| `TemporaryDirectory` | 11 | 全部 `with` 自动回收：isolated_worker×2、voice/audio、dashscope、audio_overview、office_preview:101、graphrag preflight、mineru cloud×2、normalization、visualizers/store:137 |
| `mkstemp` | 11 | 唯一名 + try/finally，全部正确：file_io×2（`delete=False` finally 兜底）、workspace/service×2、codex_auth、config_manager、interface_settings、settings_draft、model_catalog、consolidator/meta、visual_assets、msteams、visualizers 路由（去重见 §5） |
| `mkdtemp` | 9 | 手动回收：6 处正确（reading×2、skill/hub×2、claude_models、visualizers/store:158）；3 处已知缺口/取舍（tex_downloader、subagent/tools、mineru/local，见 §5） |
| `NamedTemporaryFile` | 7 | `delete=True` 2 处（doctor、question/capability，with 自动删）；`delete=False` 5 处全部有 try/finally unlink（knowledge、checkpoints、office_preview、file_io×2） |

### 3.2 ad-hoc tmp 路径（28 处生产命中）

- 唯一命名 + 完整清理（良好样本）：`partners/web_continuity.py:92`、`video_learning/invidious_account_storage.py:70`（token_hex + finally）、`rag/pipelines/lightrag/ingress.py:200`（uuid staging + rmtree 兜底）、`services/skill/service.py:690`（固定名但有 finally rmtree，见 G8）。
- 固定名 `.tmp` 写入（残留/并发面）：既有轴已覆盖 9 处（§5 去重表），**本轴新增 7 处**（§4 G1–G5）。
- TMPDIR 治理：`services/workspace/execution.py:79-81` 为沙箱子进程设置 workspace 私有 TMPDIR（见 G6）；`sandbox/backends.py:291`、`cli_apps/installer.py:243` 为白名单透传（设计如此）；`/tmp` 字面量仅存在于沙箱命名空间内。

## 4. 缺口清单（本轴新发现，含建议）

### MEDIUM（异常路径残留 / 并发 / 跨进程累积）

**G1 · 用户头像写入：固定名 tmp、无锁、无 try/finally（残留 + 并发）**
- `deeptutor/multi_user/identity.py:446-448`：`tmp = directory / f"{user_id}.{ext}.tmp"` → `write_bytes` → `replace`。写失败（ENOSPC/中断）即残留 `.tmp`；同用户并发换头像共用同一 tmp 名，可能互踩半截内容（头像目录无任何锁，`_USERS_WRITE_LOCK` 只保护 users.json）。
- 建议：改 `tempfile.mkstemp(dir=directory)` + try/finally unlink，套用 `codex_auth/storage.py:87-102` 模式。

**G2 · Partner config.yaml 写入：固定名 tmp、无 finally（残留 + 并发）**
- `deeptutor/services/partners/manager.py:656-658`：`path.with_suffix(path.suffix + ".tmp")` → `write_text` → `replace`，无 try/finally、无锁。写失败残留 `config.yaml.tmp`；多 worker 下并发保存互踩。
- 建议：try/finally unlink；参考同模块 `partners/web_continuity.py:91-97`（uuid + finally）或统一走 `file_io.atomic_write_json` 的 yaml 变体。

**G3 · Partner Group 存储四处：持锁写 tmp 但无 finally（残留）**
- `deeptutor/services/partner_groups/store.py:81-87`（group config）、`:186-210`（messages replace）、`:318-324`（invocation save）、`:364-383`（invocation transition）：均在 `_lock_for(path)` 内写固定名 `.tmp`，写路径抛错（含 `:209` write_text 失败）时 tmp 残留且锁已释放。另注：`_lock_for` 是 threading.Lock，多进程不共享（锁纪律归 scan-persistence §4 既有条目，此处只记残留）。
- 建议：四处统一 try/finally unlink（写成功 replace 后 unlink 为 no-op，可用 `missing_ok=True`）。

**G4 · Partner draft 保存：同 G3 模式（残留）**
- `deeptutor/services/partners/drafts.py:103-109`：锁内写 `path.with_suffix(".tmp")`，无 finally。
- 建议：同 G3。

**G5 · Visualizer 状态文件：固定名 `.tmp`、无锁、无 finally（残留 + 并发）**
- `deeptutor/visualizers/store.py:71-76`：`save_state` 固定 `state_file.suffix + ".tmp"`，无 try/finally（同文件 `:137,:158` 的安装 staging 反而是良好样本）。install/uninstall 与 enable/disable 并发保存时互踩。
- 建议：try/finally unlink；可并入 G1 的统一修法。

**G6 · 沙箱执行 TMPDIR 无回收责任方（跨进程累积，无界）**
- `deeptutor/services/workspace/execution.py:66,79-81` 为沙箱内 exec/cli 子进程设置 `TMPDIR/TMP/TEMP = <task>/.deeptutor/execution/tmp`（`agents/_shared/tool_runtime.py:74-83` 注入）。全仓库无任何代码回收该目录（同级的 `home/`、`cache/`、`exec_calls/` 亦无），工作区生命周期内只增不减；模型生成代码产生的临时文件全部落在这里，属典型"跨进程写入、无人认领"。
- 建议：workspace 打开或定时任务按龄/按尺寸修剪 `execution/tmp`（以及 `exec_calls/`，后者归 scan-persistence 无界增长轴跟进）；或在 `prepare_workspace_execution_env` 改为按 turn 建子目录 + turn 结束钩子清理。

### LOW（记录，暂不建议单独动）

**G7 · isolated_worker 临时目录在父进程强杀时泄漏（跨进程，有界）**
- `deeptutor/runtime/isolated_worker.py:126,181`：`TemporaryDirectory("deeptutor-worker-")` 包住子进程；优雅路径（含 timeout/CancelledError）清理正确，但父进程 SIGKILL 时 worker 子进程与 `deeptutor-worker-*` 目录同留系统 tmp。系统 tmp 重启即清，量级有界。
- 建议：仅记录；若要做，可在启动时清扫无主 `deeptutor-worker-*`（参考 mineru attempt GC 思路）。

**G8 · skill 安装 staging 固定名（并发窗口极窄）**
- `deeptutor/services/skill/service.py:690-702`：`.install-{slug}.tmp` 固定名，但预清理 + finally rmtree 完整；仅同 slug 并发安装会在 staging 上互踩。
- 建议：改 `tempfile.mkdtemp(dir=self._root)` 即可，顺手项。

## 5. 与既有轴的去重标注

| 既有工作 | 覆盖点位 | 本卡处理 |
| --- | --- | --- |
| scan-atomic-write M1/M2（attachment_store:181、file_library:179 固定名 tmp + 无 fsync） | 残留清理本身正确，问题在耐久/固定名 | 不重复计数；G1–G5 的修法可复用其 fix-atomic-unique-tmp 建议 |
| scan-atomic-write M3（worker_process.py:55 无 finally 残留）、M5（tex_downloader.py:87 失败不清理）、L5（subagent/tools.py:160-163 staging 窗口） | mkdtemp/暂存残留的已知缺口 | 本轴确认仍存在，归其 fix-atomic-residue 卡，不拆新卡 |
| scan-atomic-write M4（memory/snapshot/store.py:63）、L6（mcp×4、cli_apps/state 固定名 `.tmp`） | 固定名并发面 | 同上，随 fix-atomic-unique-tmp 统一 |
| scan-atomic-write M6（mineru/local.py:200 attempt 目录无 GC） | 跨进程无界残留（有意保留供排查） | 已有 fix-mineru-attempt-gc 建议，不重复 |
| scan-atomic-write H1（file_io.py:43-55,69-80 fsync 吞错 → 上游 PR #1751） | 耐久轴 | 清理路径（finally unlink）本轴复核为正确，无新增 |
| scan-persistence §4（线程锁 vs flock、无界增长清单） | `partner_groups/drafts` threading.Lock、`.deeptutor` 增长 | G3/G6 只记残留/TMPDIR 面，锁纪律与总量治理归其卡 |
| fix-swallow-log-batch（agen928：mineru slice checkpoint 载入吞错、失败态诊断写吞错等七处） | v1.6.13 LOW 吞错点 | 日志面已由该分支补齐；清理语义未变，本轴不重复计数；`checkpoints.py:90` 写入路径本轴复核为正确（fsync + finally） |

## 6. 复现与哈希自证

```bash
EV=evidence/scan-tempfile-hygiene-20261006
python3 $EV/scripts/scan_tempfile_hygiene.py . /tmp/tfrerun   # 任意输出目录
diff -r $EV/data /tmp/tfrerun && echo IDENTICAL               # 本卡实测：RERUN-IDENTICAL
shasum -a 256 -c $EV/SHA256SUMS                                # 在仓库根执行
```

数据文件为确定性输出（排序、相对路径、无时间戳），重跑逐字节一致；`summary.json` 摘要：38 生产调用 / 31 文件、`delete=False` 5 处、ad-hoc tmp 模式 28 行、`mktemp`/`gettempdir` 0 命中。

## 7. 补齐优先级（建议拆卡）

1. **fix-tmp-residue-finally**（P1，机械小改）：G1–G5 统一 try/finally unlink（或统一 mkstemp helper），一次 PR 可收口，覆盖 partner/identity/visualizer 全部状态文件写入。
2. **fix-execution-tmp-gc**（P2）：G6 沙箱 TMPDIR（连带 `exec_calls/`）按龄/按尺寸修剪。
3. 沿用 scan-atomic-write 已建议的 fix-atomic-residue（M3/M5/L5）与 fix-atomic-unique-tmp（M1/M2/M4/L6 + 本轴 G8 顺手）。
4. 仅记录：G7。

## 8. 风险评级标准

- **HIGH**：用户主数据链路上的残留/损坏，或被大量调用方共享的系统性缺口。本轴无。
- **MEDIUM**：异常路径必然残留、并发窗口真实存在、或跨进程无界累积。
- **LOW**：有缓解（重启回收/窗口极窄/清理完整仅命名固定），或影响为可再生数据。
