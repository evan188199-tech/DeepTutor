# 原子写 tmp 清理与 fsync 一致性扫描报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
- **扫描日期**: 2026-10-05（UTC）
- **范围**: `deeptutor/` 全目录（排除 `tests/`），只读静态扫描，**未修改任何代码**
- **方式**: ripgrep 模式定位（`os.replace`/`os.rename`/`tempfile.*`/`fsync`）+ 逐处人工复核清理路径与 fsync 链路
- **对照**: `myfork/agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md`；上游开放 PR #1751、#620

## 1. 结论（PASS）

| 判定轴 | HIGH | MEDIUM | LOW |
| --- | --- | --- | --- |
| tmp 残留（写失败/中断后不清理） | 0 | 3 | 2 |
| 耐久性（fsync 缺失或被吞） | 2 | 3 | 3 |
| 并发（固定名 tmp 竞态） | 0 | 2 | 1 |

- 全仓库共 **41 处 `os.replace`**、38 处 `tempfile.*` 写入点、**20 处文件 fsync**。
- **目录 fsync 为 0 处**（系统性缺口，见 H2）。
- 清理纪律总体良好：绝大多数写入点有 `finally` 清理；问题集中在 6 个文件的固定模式。

## 2. 命中清单

风险判定：残留 = tmp/暂存文件在失败路径遗留；耐久 = 崩溃/断电后目标文件可能为空、半截或回退旧版；并发 = 固定名 tmp 被并发写者共享。

### HIGH

**H1 · fsync 失败被静默吞掉（耐久）**
- `deeptutor/services/file_io.py:53-55`（`atomic_write_json`）、`deeptutor/services/file_io.py:78-80`（`atomic_write_text`）：`try: os.fsync(...) except OSError: pass`。fsync 失败（ENOSPC/EIO）被吞，调用方以为已落盘。
- 影响面大：`atomic_write_json/text` 被 **约 48 个文件** 引用（进度追踪、memory、knowledge base 配置、session 迁移、book、co-writer 等）。
- **已覆盖去重**: fix-fsync-durability → 上游开放 PR **#1751**（`myfork/fix/atomic-write-fsync-warning`，只改 `file_io.py` + 测试）。本项不另拆卡。

**H2 · rename 后无目录 fsync（耐久，系统性）**
- 全仓库 41 处 `os.replace` 后均未 fsync 父目录（`rg 'O_DIRECTORY|dirfd'` 为 0 命中）。POSIX 语义下 rename 本身未持久化：断电后可能回退为旧文件或丢失新文件，文件内容 fsync 无法弥补。
- 典型高价值目标：`deeptutor/utils/config_manager.py:88`（main.yaml）、`deeptutor/services/config/settings_draft.py:104`、`deeptutor/services/config/model_catalog.py:313`、`deeptutor/services/mcp/config.py:149`（注释自述"torn write 会静默断连全部 server"）。
- 最省的修法：在 `file_io._atomic_replace` 单点补目录 fsync，各分散点按需跟进。
- **未覆盖**：#1751 未涉及；建议独立拆卡。

### MEDIUM

**M1 · attachment_store 写入无 fsync + 固定名 tmp（耐久 + 并发）**
- `deeptutor/services/storage/attachment_store.py:179-190`（`_write_sync`）：`tmp.open("wb")` → `write` → `os.replace`，**无 flush/fsync**；断电后目标可能是空/半截附件且静态句柄已可访问。tmp 为固定名 `target.suffix + ".tmp"`，同一附件并发写会互踩。
- 残留：清理正确（`finally: tmp.unlink()`）。

**M2 · file_library 写入无 fsync + 固定名 tmp（耐久 + 并发）**
- `deeptutor/services/storage/file_library.py:176-187`（`_write_file`）：与 M1 完全相同的模式。库文件断电回退为空/半截；清理正确。

**M3 · worker_process 结果写回无 fsync 且失败残留（耐久 + 残留）**
- `deeptutor/runtime/worker_process.py:53-58`：`staged.write_bytes(...)`（无 fsync）→ `os.replace`。整段无 `finally`：`write_bytes` 半路失败（ENOSPC）时 `.tmp` 残留，进程打印 traceback 后退出。固定名 `.tmp`（单作业唯一路径，并发风险低）。

**M4 · memory snapshot save_state 无 fsync、无清理（耐久 + 残留 + 并发）**
- `deeptutor/services/memory/snapshot/store.py:63-70`（`save_state`）：`tmp.write_text(...)` → `os.replace`，无 fsync、**无 try/finally**，写失败时 `.json.tmp` 残留；固定名 `.json.tmp`。

**M5 · tex_downloader 失败路径不清理 temp_dir（残留）**
- `deeptutor/tools/tex_downloader.py:87`（`tempfile.mkdtemp(dir=self.workspace_dir)`）：`rmtree` 只在成功返回前执行（:131）；`requests.RequestException` 分支（:132-133）与兜底 `except Exception` 分支（:134-135）直接 `return`，**每次失败下载在 workspace_dir 遗留一个 `tmp*` 目录**（含下载的源码包）。

**M6 · mineru attempt 目录只增不回收（残留，设计取舍）**
- `deeptutor/services/parsing/engines/mineru/local.py:200,321-330`：失败的 `.mineru-attempt-*` 目录按注释（#1612）有意保留供排查，但全仓库**无任何回收/配额机制**，长期运行下磁盘无界增长。建议加"保留最近 N 个/按龄清理"。

**M7 · reading store 目录交换无 fsync（耐久）**
- `deeptutor/reading/store.py:426-436`、`:591-599`、`:754-762`、`:1160-1170`：copy2/copytree → 双 rename（带 backup 回滚，逻辑完善）→ 清理。但无任何 fsync：断电后 material 目录内容或 rename 可能回退，回滚点本身也可能不持久。阅读材料属可再生成内容，降级为 MEDIUM。

### LOW

**L1 · office_preview 缓存写有意尽力而为（耐久）**
- `deeptutor/services/office_preview.py:157-170`：无 fsync + `except OSError: pass`，注释明示"缓存写失败不得影响预览"；清理正确。符合语义，仅记录。

**L2 · learning 迁移 `_copy_atomic` 无 fsync（耐久）**
- `deeptutor/learning/migration.py:92-99`：`shutil.copy2` → replace，唯一 tmp（uuid）、清理正确。归档数据，低危。

**L3 · workspace export 无 fsync（耐久）**
- `deeptutor/services/workspace/service.py:750-762`：`copyfile` → sha 校验 → replace；唯一 tmp、清理正确、错误上抛。校验缓解了半截写入被采纳的风险。

**L4 · visualizer 安装无 fsync（耐久）**
- `deeptutor/visualizers/store.py:157-167`：mkdtemp staging → copytree/copy2 → replace；finally 清理正确。

**L5 · subagent 图片 staging 的清理窗口缺口（残留）**
- `deeptutor/capabilities/subagent/tools.py:160-163`：`_stage_images`（:242 mkdtemp）成功后、`try:` 开始前有一句 `await _stream("question", ...)`（:163），此时抛错则 staging 目录泄漏。窗口极窄，低危。

**L6 · mcp/cli_apps 固定名 `.tmp`（并发）**
- `deeptutor/services/mcp/oauth.py:118-128`、`deeptutor/services/mcp/secrets.py:165-179`、`deeptutor/services/mcp/user_config.py:206-218`、`deeptutor/services/mcp/config.py:140-149`、`deeptutor/services/cli_apps/state.py:194-204`：固定 `{name}.tmp`。fsync、chmod 0600、清理均正确；单写者假设下可接受，与 M1/M2 统一改 mkstemp 即可顺带消除。

**L7 · sqlite legacy 迁移 rename 吞错（耐久）**
- `deeptutor/services/session/sqlite_store.py:268-273`：`os.replace` 失败时 `except OSError: pass`（有注释，回退为空库初始化）。行为有说明，低危。

### 无需修复（良好样本）

`deeptutor/services/codex_auth/storage.py:87-102`、`deeptutor/video_learning/invidious_account_storage.py:70-82`（token_hex + O_EXCL + fsync + chmod + finally）、`deeptutor/services/memory/consolidator/meta.py:161-174`、`deeptutor/utils/config_manager.py:82-95`、`deeptutor/services/settings/interface_settings.py:250-264`、`deeptutor/services/config/settings_draft.py:94-106`、`deeptutor/services/config/model_catalog.py:301-315`、`deeptutor/partners/channels/msteams.py:769-789`、`deeptutor/services/mcp/*`（除 L6 的固定名外）、`deeptutor/services/parsing/engines/mineru/checkpoints.py:83-97`、`deeptutor/services/rag/visual_assets.py:374-386`、`deeptutor/services/rag/pipelines/lightrag/ingress.py:197-300`（uuid staging + rmtree 兜底，`_write_new_bytes` 只写 staging 内路径，失败不会污染最终路径）、`deeptutor/api/routers/knowledge.py:332,365-368`（zip tmp finally 清理）、`deeptutor/api/routers/reading.py:1062,1095-1097`、`deeptutor/reading/ingestion.py:983,1050-1052`、`deeptutor/learning/migration.py:205-222`（staging 有续跑语义，非残留）、`deeptutor/services/cli_apps/installer.py:127-157`（backup 回滚正确）、`deeptutor/services/doctor.py:198-206`（delete=True 自清理）。

## 3. 与既有卡 / PR 的去重标注

| 既有工作 | 覆盖条目 | 本卡处理 |
| --- | --- | --- |
| fix-fsync-durability → 上游 PR **#1751**（open，`file_io.py` + 测试） | H1（file_io 两处吞 fsync） | 已覆盖，不拆卡；M1-M4/L 系列的补 fsync 建议复用其落地后的统一模式 |
| 上游 PR **#620** `fix/kb-config-atomic-store`（open） | knowledge_base_config 的原子写走 `file_io.atomic_write_json` | 随 H1 修复自动受益，无需单独处理 |
| fix-upload-residue | `deeptutor/api/routers/knowledge.py:530,541`（`_save_uploaded_files` 失败清理的 unlink 吞错，dt22 已列 MEDIUM） | 本扫描确认其余上传临时文件（knowledge.py:332、reading.py:1062、reading/ingestion.py:983）清理完好，无新增重复条目 |
| scan-persistence（`agent/dt22-todo-scan`） | 各清理路径的 `except OSError: pass` 吞错（如 attachment_store/file_library finally 内的 unlink 抑制） | 本卡按"清理存在但被抑制"处理，不重复计数；dt22 报告未覆盖本卡的耐久轴与并发轴 |

## 4. 可拆修复卡条目（建议）

1. **fix-atomic-fsync-extend**（依赖 #1751 合并）：M1、M2、M3、M4 补 flush+fsync，直接改用 `file_io` 帮助函数或其落地后的告警模式。
2. **fix-atomic-residue**：M3（worker_process 补 finally）、M5（tex_downloader 失败分支 rmtree）、L5（staging 创建挪进 try）。
3. **fix-atomic-unique-tmp**：M1、M2、M4、L6 固定名 tmp 改 `mkstemp`，顺带消除并发竞态。
4. **fix-dir-fsync**：H2 系统性补父目录 fsync，首选在 `file_io._atomic_replace` 单点实现，config/mcp 等自管点跟进。
5. **fix-mineru-attempt-gc**：M6 为 `.mineru-attempt-*` 增加按龄/数量回收。

## 5. 复现命令

```bash
rg -n --no-heading -e 'os\.replace\(|os\.rename\(|shutil\.move\(' deeptutor/ -g '*.py' -g '!tests/**'
rg -n --no-heading -e 'tempfile\.(NamedTemporaryFile|mkstemp|mkdtemp|TemporaryDirectory)\(' deeptutor/ -g '*.py' -g '!tests/**'
rg -n --no-heading 'fsync' deeptutor/ -g '*.py' -g '!tests/**'
rg -n --no-heading -e 'O_DIRECTORY|dirfd' deeptutor/ -g '*.py' -g '!tests/**'   # 目录 fsync：0 命中
```

## 6. 风险评级标准

- **HIGH**：数据丢失/损坏路径宽（被大量调用方共享）或直接作用于用户数据主链路。
- **MEDIUM**：单条链路上的耐久缺口、失败路径残留会随时间累积、或并发窗口真实存在。
- **LOW**：有注释/校验/回滚缓解，或触发窗口极窄、影响为缓存/可再生数据。
