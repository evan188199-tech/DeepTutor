# 导读：文件 IO 与路径服务（file_io / path_service）

- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14，2026-10-08），新 worktree 分支 `evidence/guide-file-io-path-durability-20261009`
- 范围：`deeptutor/services/file_io.py`（实际 117 行）+ `deeptutor/services/path_service.py`（实际 530 行），及其直接依赖 `runtime/home.py`、`utils/secret_files.py`、`multi_user/paths.py`、`services/workspace/context.py`
- 性质：只读导读文档，不改任何产品/测试代码
- 去重说明：`fix/*-fsync` 系列（storage-write-fsync-tmp、atomic-replace-dir-fsync、worker-process-fsync、snapshot-store-fsync、reading-store-dir-fsync 等）是历史修复卡，本卡只导读现状原语；`test/atomic-write-contract` 与 `test/path-service-*` 是测试卡，本文仅引用其测试锚点

## TL;DR

`file_io.py` 提供"同目录临时文件 + fsync + 原子 rename"两个写原语（`atomic_write_json`/`atomic_write_text`），全仓 53 个产品文件、223 处调用。`path_service.py` 是 `data/` 目录树的唯一布局契约方：默认根 `<runtime-home>/data`，运行态全部收敛在 `<root>/user/` 下，共享数据（KB、parse_cache、memory、learning_journal）挂在 `<root>/` 层；经 `get_path_service()` 按账号/内容工作区动态换根。仍有少数调用点硬编码 `data/user/...` 相对路径绕过该契约（见第 4 节）。

## 1. file_io.py：持久写原语（117 行）

### 1.1 入口与分层

| 符号 | 行锚点 | 角色 |
| --- | --- | --- |
| `atomic_write_json(path, payload)` | `deeptutor/services/file_io.py:72` | 公共入口：UTF-8 JSON，indent=2、`ensure_ascii=False`、尾部换行（:85-86） |
| `atomic_write_text(path, text)` | `deeptutor/services/file_io.py:95` | 公共入口：UTF-8 文本 |
| `_sync_to_disk(handle, path)` | `deeptutor/services/file_io.py:25` | fsync 文件句柄；失败只告警不抛错 |
| `_atomic_replace(src, dst)` | `deeptutor/services/file_io.py:48` | `Path.replace` 原子换入；Windows PermissionError 指数退避重试 |
| `_FSYNC_WARNING_INTERVAL_SECONDS = 60.0` | `deeptutor/services/file_io.py:20` | fsync 告警限流间隔 |

模块 docstring 明确依赖零外部包（`file_io.py:1`），`__all__` 只导出两个写函数（`file_io.py:117`）。

### 1.2 写入契约（两个入口完全同构）

1. **建父目录**：`path.parent.mkdir(parents=True, exist_ok=True)`（`file_io.py:75`、`:98`）。
2. **同目录临时文件**：`tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False)`（`file_io.py:78-83`、`:101-106`）——临时文件与目标同目录，保证 rename 同文件系统、原子性成立；跨目录的 temp 目录方案会破坏这一点。
3. **flush + fsync 文件数据**（`file_io.py:87-88`、`:109-110`）：先 `handle.flush()` 再 `_sync_to_disk`，保证 rename 前内容已落盘。
4. **原子换入**：`src.replace(dst)`（`file_io.py:60`）= POSIX `rename(2)`，读者要么看到旧文件要么看到完整新文件，不存在部分写入窗口。
5. **finally 清理临时文件**：`temporary_path.unlink(missing_ok=True)`（`file_io.py:90-92`、`:112-114`）——写失败（含 json.dump 抛错）时残留 temp 被清掉，原目标文件完好（tests/services/test_file_io.py:31、:48 覆盖这两个场景）。

### 1.3 失败语义

- **fsync 失败 = 限流告警，不失败写入**（`file_io.py:16-19` 注释说明了取舍）：换入的内容是完整的，只是"不保证断电后持久"。告警按 monotonic 时钟限流为 60s 一次，用 `_fsync_warning_lock` 保证多线程下只更新一次时间戳（`file_io.py:21-22`、`:31-39`）；测试锚点 `tests/services/test_file_io.py:70`、`:90`、`:110`。
- **rename 遇 PermissionError = 指数退避重试 5 次**（0.2s 起步、封顶 1.6s，`file_io.py:56-67`）：针对 Windows 上杀毒/索引器/并发读者短暂锁住目标文件的场景；重试耗尽后抛出最后一次错误（`:68-69`），此时新内容仍在临时文件里，`finally` 会把它清掉。
- **边界说明**：原语只 fsync 文件句柄，不 fsync 父目录；目录 fsync 由上层存储自行处理（这正是历史 `fix/*-fsync` 系列卡在 book/reading/snapshot/worker 等存储里补的内容）。使用本原语即接受该语义。

### 1.4 消费面

53 个产品模块引用两个入口（`deeptutor/knowledge/*`、`deeptutor/book/storage.py`、`deeptutor/co_writer/storage.py`、`deeptutor/reading/store.py`、`deeptutor/multi_user/{grants,guardians,identity}.py`、`deeptutor/services/{memory,notebook,parsing,rag,session,workspace}/*` 等），共 223 处调用；8 个测试文件覆盖。约定：**凡是"状态文件整文件重写"的场景都应走这两个入口**，追加型日志/SQLite 不在其职责内。

## 2. path_service.py：目录布局契约（530 行）

### 2.1 根解析链

- `PACKAGE_ROOT = Path(__file__).resolve().parents[2]`（`deeptutor/runtime/home.py:9`）；`get_runtime_data_root()` = `<runtime-home>/data`（`home.py:46-49`），runtime-home 优先级：显式参数 > `DEEPTUTOR_HOME` 环境变量 > CWD（`home.py:28-43`）。
- `PathService.__init__`（`path_service.py:85-90`）：`workspace_root` 默认 `<home>/data` 并 resolve；`user_data_dir = <workspace_root>/user`；`project_root = workspace_root.parent`。
- 单例与多例并存：`PathService.get_instance()`（`path_service.py:92-96`，CLI/无请求态）与 `get_path_service()`（`path_service.py:516-521`）→ `multi_user.paths.get_current_path_service()`（`deeptutor/multi_user/paths.py:164-167`）→ 按当前账号 scope 取缓存实例（`paths.py:140-146`，缓存键 `scope.cache_key`，根：admin=`data/`、user=`data/users/<uid>`、partner=`data/partners/<id>`，见 `paths.py:1-15` 模块 docstring）。解析失败即报错，绝不回落 admin（`path_service.py:519-521` 注释）。

### 2.2 布局契约表（`<root>` = workspace_root，默认 `<runtime-home>/data`）

| 路径 | 产出方法 | 行锚点 | 归属/说明 |
| --- | --- | --- | --- |
| `<root>/user/` | `user_data_dir` / `get_user_root()` | `path_service.py:90`、`:118` | 运行态总根，多用户时每账号一份 |
| `<root>/user/settings/` | `get_settings_dir()` / `get_settings_file()` / `get_runtime_config_file()` | `path_service.py:225`、`:233`、`:238` | JSON/YAML 设置；补 `.json`/`.yaml` 后缀 |
| `<root>/user/.runtime/` | `get_runtime_state_dir()` | `path_service.py:228` | 活跃运行私有状态，"永不属于内容工作区"（docstring） |
| `<root>/user/workspace/` | `get_workspace_dir()` / `get_agent_base_dir()` | `path_service.py:222`、`:274` | 内容工作区根 |
| `<root>/user/workspace/{memory,notebook,co-writer,chat,book,reading,timed_media}/` | `get_workspace_feature_dir()` | `path_service.py:243` | `WorkspaceFeature` Literal（`:53-61`；reading/timed_media 仅为类型预留） |
| `<root>/user/workspace/chat/{chat,deep_solve,deep_question,deep_research,math_animator,_detached_exec}/` | `get_chat_feature_dir()` | `path_service.py:249` | `ChatWorkspaceFeature`（`:44-51`） |
| `<root>/user/workspace/chat/<feature>/<task|session_id>/` | `get_task_workspace()` / `get_session_workspace()` / `get_task_dir()` | `path_service.py:252`、`:256`、`:287` | 每回合/每会话一目录 |
| `<root>/user/workspace/chat/<...>/sessions.json` | `get_session_file()` | `path_service.py:284` | agent 会话索引 |
| `<root>/user/workspace/notebook/{<id>.json, notebooks_index.json}` | `get_notebook_file()` / `get_notebook_index_file()` | `path_service.py:293`、`:296` | |
| `<root>/user/workspace/co-writer/{history.json, tool_calls/, audio/, documents/doc_<id>/{manifest.json,...}}` | `get_co_writer_*()` | `path_service.py:385-406` | |
| `<root>/user/workspace/book/book_<id>/{manifest.json, spine.json, progress.json, inputs.json, log.md, pages/<page>.json, assets/, learning_captures.json}` | `get_book_*()` / `ensure_book_root()` | `path_service.py:410-450` | |
| `<root>/user/chat_history.db` | `get_chat_history_db()` | `path_service.py:134` | 会话 SQLite |
| `<root>/user/logs/` | `get_logs_dir()` | `path_service.py:455` | |
| `<root>/knowledge_bases/` | `get_knowledge_bases_root()` | `path_service.py:121` | **`<root>` 层共享，不在 user/ 下** |
| `<root>/parse_cache/` | `get_parse_cache_root()` | `path_service.py:124` | 内容寻址解析缓存，键 `(source_hash, parser_signature)` |
| `<root>/memory/` | `get_memory_dir()` | `path_service.py:299` | **注意：根层，不是 workspace/memory**（见 2.5 漂移） |
| `<root>/learning_journal/` | `get_learning_journal_dir()` | `path_service.py:302` | memory 的兄弟目录（#740） |
| `data/system/user-secrets/<owner>/` | `owner_secrets_dir()` / `get_owner_secrets_dir()` | `deeptutor/multi_user/paths.py:217`、`:238` | 沙箱永不挂载；0700 每次重申（`:233-235`） |

`ensure_all_directories()`（`path_service.py:489-513`）一次性物化整棵树：user 根、settings、.runtime、workspace、memory、notebook、logs 用 `ensure_private_directory`（0700，`deeptutor/utils/secret_files.py:13-18`）；co-writer/book + 六个 chat feature + tool_calls/audio/reports 子目录用普通 mkdir。启动入口 `setup/init.py` 打印的同名树与此契约一致（`deeptutor/services/setup/init.py:157` 附近）。

### 2.3 能力名 → 目录映射

- `_AGENT_TO_WORKSPACE`（`path_service.py:74-82`）：solve→chat/deep_solve、chat→chat/chat、question→chat/deep_question、research→chat/deep_research、math_animator→chat/math_animator、co-writer→co-writer、exec_workspace→chat/_detached_exec、logs→logs。
- `_resolve_feature_root`（`path_service.py:260-272`）：六个 chat feature 走 `get_chat_feature_dir`，memory/notebook/co-writer/book 走 `get_workspace_feature_dir`，未知 feature 直接 `ValueError`——这是"新能力必须登记"的守门点。

### 2.4 公共产物白名单（读侧契约）

`resolve_public_output_path()`（`path_service.py:140-217`）把"解析 + 授权"合成一步：resolve 后必须落在 `user_data_dir` 内（`:154-158`）、必须是已存在文件（`:160`）、后缀不在 `_PRIVATE_SUFFIXES`（settings/源码/运行时文件，`.md` 被刻意豁免，`:83`、`:166`），再按目录形状白名单放行：co-writer/audio、`workspace/outputs/chat/<session>/<turn>/{exec,media,cli}`、deep_solve/math_animator 的 artifacts、chat 下 code_runs/media/exec/cli、`_detached_exec`（`:170-215`）。`is_public_output_path()`（`:219`）是其布尔包装。测试锚点：`tests/services/test_path_service.py:12`、`:48`、`:96`。

### 2.5 多用户与内容工作区叠层

- 账号 scope（`multi_user/paths.py`）：`ensure_scope_workspace()` 对每个 scope 根跑 `PathService(workspace_root=root).ensure_all_directories()` 再补 knowledge_bases/memory（`paths.py:113-125`）——PathService 是"自相似"的：user 工作区根内部再长一个同构 `<root>/user/` 树。
- 内容工作区叠层（`deeptutor/services/workspace/context.py:107-144`）：`WorkspacePathService` 把数据树重定位到 `<content_root>/.deeptutor/data`，但 **settings、.runtime、memory 保持账号级**（`:127-135`），且拒绝 `.deeptutor` 符号链接（`:111-120`）。`scoped_path_service()`（`:146-165`）在 scope 与账号根不匹配或存储被移动时抛 `WorkspaceError`，绝不静默换根。
- memory 迁移：`migrate_legacy_memory_markdown()`（`path_service.py:309-356`）把旧 `workspace/memory/*.md` 一次性搬进根层 memory，冲突进 `backup/legacy-workspace/`，写 `.migrated-to-data-memory-v2` 标记；刻意不放在只读 getter 里（`:313-316` 注释）。测试锚点：`tests/services/test_path_service.py:150`、`:184`、`:215`；runtime-home 默认：`tests/services/test_path_service_runtime_home.py:8`。

### 2.6 文档漂移观察（只记录，不改码）

1. 模块 docstring 树（`path_service.py:5-24`）仍画着 `workspace/memory/`，而代码 `get_memory_dir()` 返回根层 `<root>/memory`（`:299-300`）且迁移逻辑以根层为目标——树形图过时。
2. 同一 docstring 未列 `knowledge_bases/`、`parse_cache/`、`learning_journal/`（根层共享）以及多用户的 `users/`、`partners/`、`system/`（`multi_user/paths.py:6-11` 另有说明）。
3. 命名分叉：path_service 的运行态目录叫 `.runtime`（`:231`），launcher 的 detached/web 运行态叫 `runtime`（`deeptutor/runtime/launcher.py:65`、`:78`）——两个不同目录，易混淆。

## 3. 布局契约速查（写入原语 × 目录）

两个写原语本身与 path_service **零耦合**（只收 `Path`），目录契约完全由调用方经 path_service 取得后再传入。典型组合：`atomic_write_json(get_settings_file("system"), ...)`、`atomic_write_text(get_book_log_file(id), ...)`。因此**新增目录约定时，正确路径是给 PathService 加 getter 并登记 `_resolve_feature_root`/`ensure_all_directories`，而不是在调用点拼字符串**。

## 4. 目录约定：path_service 依赖 vs 硬编码清单（验收 3）

### 4.1 走 path_service（契约内）

settings/.runtime/workspace 六 chat feature/co-writer/book/notebook/logs/chat_history.db/memory/learning_journal/knowledge_bases/parse_cache 的常规读写，经 `get_path_service()`（产品代码 110 处调用、86 个文件引用）或注入的 PathService 实例完成；磁盘物化统一由 `ensure_all_directories()`/各 `ensure_*` 负责。

### 4.2 硬编码 / 绕过点（按影响分组）

| 位置 | 硬编码内容 | 说明 |
| --- | --- | --- |
| `deeptutor/services/config/loader.py:26` | `root / "data" / "user" / "settings"` | `get_runtime_settings_dir()` 自建 settings 路径，与 `get_settings_dir()` 契约平行；`deeptutor/services/config/launch_settings.py:80` 同型。默认根下两者等价，非默认 workspace_root 下可能分叉 |
| `deeptutor/runtime/launcher.py:65`、`:78` | `Path("data")/"user"/"runtime"/"web"`、`.../"runtime"` | 相对 CWD 的运行态目录，不经 runtime-home 解析也不经 path_service（见 2.6-3 的 `.runtime` vs `runtime` 命名分叉） |
| `deeptutor/api/routers/knowledge.py:137` | `PROJECT_ROOT / "data" / "knowledge_bases"` | 模块级 KB 根，未用 `get_knowledge_bases_root()`（后者是 workspace_root 相对、随 scope 移动） |
| `deeptutor/services/base_sync.py:41` | `get_path_service().project_root / "data" / "knowledge_bases"` | 半硬编码：用了 path_service 但从 `project_root`（=workspace_root.parent，`:89`）重推 KB 根；admin 默认下与 `get_knowledge_bases_root()` 等价，user scope（`data/users/<uid>`）下会推到 `data/users/data/knowledge_bases`，属于契约分裂风险点，调用方应以 getter 为准 |
| `deeptutor/services/app_update.py:472` | `get_runtime_home(home) / "data" / "user" / "update"` | 更新任务存储，绕过 `get_settings_dir()`/`.runtime` 约定 |
| `deeptutor/agents/research/request_config.py:179`、`:183` | `"./data/user/workspace/chat/deep_research"`（含 `/reports`） | 作为配置缺省值下发（可被 `paths.research_*` 覆盖），是 fallback 字符串而非 path_service 产物 |
| `deeptutor/multi_user/identity.py:40-41`、`deeptutor/services/session/sqlite_store.py:273`、`path_service.py:319` | 旧版 `data/user/auth_users.json`、`data/chat_history.db`、`project_root/"data"` | 一次性 legacy 迁移锚点，硬编码属预期 |

其余 `data/user/...` 字符串（如 `book/storage.py:7`、`co_writer/storage.py:7`、`utils/config_manager.py:14-18`、`services/auth.py:7-19` 等）仅出现在 docstring/注释中描述布局，运行时仍走 path_service，不构成硬编码。

## 5. 测试锚点与去重

| 测试 | 锚点 | 覆盖 |
| --- | --- | --- |
| `tests/services/test_file_io.py` | :18、:31、:48、:60、:70、:90、:110 | 建父目录+原子换入、失败清 temp、失败保原文件、fsync 失败仍写入、告警限流恢复 |
| `tests/services/test_path_service.py` | :12、:48、:96、:130、:150、:184、:215 | 公共产物白名单（3 例）、feature 映射、memory 纯 getter+迁移、迁移冲突、ensure_all 私有权限 |
| `tests/services/test_path_service_runtime_home.py` | :8 | DEEPTUTOR_HOME 默认根 |
| `tests/multi_user/test_owner_path_service.py`、`tests/multi_user/test_identity_and_paths.py` | — | owner 解析与账号 scope 路径 |

## 6. 验收对照

1. **布局契约与写入原语全覆盖、结论有行锚点**：第 1 节覆盖 file_io 全部 4 个函数与失败语义；第 2 节覆盖 path_service 根解析、完整布局契约表（2.2）、feature 映射、公共产物白名单、多用户叠层，全部结论带 `文件:行` 锚点。
2. **不改任何产品/测试代码**：本分支相对 `origin/main` 仅新增 `evidence/guide-file-io-path-durability-20261009/report.md` 一个文件。
3. **明确列出 path_service 依赖 vs 硬编码**：第 4 节清单，7 组硬编码点全部带行锚点，并区分 legacy 迁移（预期）与平行实现（风险）。
