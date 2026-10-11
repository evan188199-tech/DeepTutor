# scan: 硬编码路径清点（Path.home / expanduser vs path_service 归口）

- 基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）
- 分支：`scan/hardcode-paths-20261011`（只读扫描，不改代码）
- 范围：`deeptutor/`、`deeptutor_cli/` 生产 Python 代码；`tests/` 不在本卡范围（runtime home 语义由 tests/services/test_path_service_runtime_home.py 定义，本文只引用）；`web/`（TS/浏览器侧）无 path_service 对应物，不适用。
- 机读清单：`callsites.tsv`（96 个调用点，含 path:line、代码片段、判定、依据）。

## 归口参照

- 运行时数据根：`deeptutor/runtime/home.py` — `DEEPTUTOR_HOME`（默认 cwd）→ `<home>/data`。
- 归口服务：`deeptutor/services/path_service.py`（`PathService`，含 `get_knowledge_bases_root()`、`get_research_dir()` 等）；多用户层 `deeptutor/multi_user/paths.py`（`SYSTEM_ROOT` 等派生自 `get_runtime_home()`）。
- 运行时 home 重定向失效的定义：某调用点在 `DEEPTUTOR_HOME=X` 且进程 cwd≠X 时，仍把数据落到 cwd 相对路径或 OS home，导致数据不随 runtime home 迁移/隔离。

## 结果概览

| 判定 | 数量 |
|---|---|
| 迁移候选（P0/P1/P2） | 7 |
| 可选优化（P3，系统临时目录暂存，已有清理） | 3 |
| 豁免：输入归一化（expanduser 解析用户/配置路径，默认根已归口） | 61 |
| 豁免：外部工具/外部缓存（OS home 约定，env 可覆盖） | 8 |
| 豁免：沙箱内部（namespace 内路径、env 白名单） | 7 |
| 豁免：已归口/瞬态（dir= 落在工作区内、finally/cleanup 清理） | 10 |

`Path.home()` 共 9 处，全部为外部工具凭据/缓存发现（CodeBuddy、Codex、DSH、docling/HF/ModelScope）或沙箱 home 排除检查，无一是 DeepTutor 自有运行时数据，均不随 DEEPTUTOR_HOME 重定向——这是正确语义（工具状态属于 OS 用户，不属于 runtime home）。

`expanduser` 共 67 行（29 文件），绝大多数是对用户/配置输入路径的归一化（CLI kb、KB vault 外挂目录、partner 渠道媒体引用、workspace catalog/service 根、cron/web_source 仓库路径——后两者的默认根分别来自 admin PathService 与 SYSTEM_ROOT），属正确用法。

写死临时目录共 17 处命中：5 处 `mkdtemp(dir=…)` 已落工作区内；6 处系统临时目录暂存且均有 finally/cleanup 清理（reading.py:1113、capabilities/subagent/tools.py:181-184、claude_models.py:229、skill/hub.py `FetchedSkill.cleanup_dir` 析构、ingestion.py）；2 处为沙箱 namespace 内部路径（backends.py:208、cli_apps/runner.py:117，注释已声明）；4 处仅为子进程 env 保留键白名单。

## 迁移候选（7 条）

| # | 位置 | 问题 | 建议 | 优先级 |
|---|---|---|---|---|
| 1 | `deeptutor/knowledge/manager.py:328` | `KnowledgeBaseManager(base_dir="./data/knowledge_bases")` 默认值 cwd 相对；`deeptutor/book/kb_health.py:41` 的裸构造回退会在 cwd≠runtime home 时指向不存在的目录（该文件 docstring 已自述此坑） | 默认 `base_dir=None` 时改从 `PathService.get_knowledge_bases_root()` 派生 | P0 |
| 2 | `deeptutor/knowledge/add_documents.py:39` | `DEFAULT_BASE_DIR` 重复同一字面量 | 随 #1 一并收敛到 PathService 派生 | P0 |
| 3 | `deeptutor/knowledge/initializer.py:41` | 默认 `base_dir` 同字面量 | 同 #1 | P1 |
| 4 | `deeptutor/knowledge/initializer.py:337` | 第二入口默认值同字面量 | 同 #1 | P1 |
| 5 | `deeptutor/agents/research/request_config.py:179,183` | 研究输出目录回退字面量 `./data/user/workspace/chat/deep_research[reports]`；`deeptutor/services/config/loader.py:74-79` 已注入 PathService 绝对路径，回退仅在 paths 缺键时生效，一旦触发即 cwd 相对 | 回退改为 `PathService.get_research_dir()` / `get_research_reports_dir()` | P1 |
| 6 | `deeptutor/services/setup/init.py:47` | `DEFAULT_MAIN_SETTINGS` 内 `tools.exec.allowed_roots=["./data/user"]`，cwd 相对；实际 exec 边界走 `workspace/service.py` 的 env+PathService 机制（service.py:101-110），该键疑似遗留 | 删除该键，或改为 PathService 绝对派生，避免误导配置者 | P2 |
| 7 | `deeptutor/book/kb_health.py:41` | 裸 `KnowledgeBaseManager()` 兜底（见 #1），且 `except Exception` 过宽，会吞掉 multi-user 解析真实错误 | #1 落地后兜底自然安全；建议同时收窄异常面 | P1 |

可选（P3，不计入候选）：`api/routers/reading.py:1062`、`capabilities/subagent/tools.py:242`、`services/subagent/claude_models.py:159` 三处系统临时目录暂存均有清理，如需统一审计/配额可迁 `get_runtime_state_dir()` 下的暂存区。

## 重定向语义健康点（对照验证）

- `deeptutor/runtime/launcher.py:65,78`：`Path("data")…` 常量只作相对片段，`launcher.py:164,745` 以 `runtime_home` 为根拼接，重定向正确。
- `deeptutor/partners/config/paths.py`、`deeptutor/multi_user/paths.py`、`deeptutor/services/cron/service.py:414-419`、`web_source/scheduler.py:37-39`：全部锚定 admin PathService / SYSTEM_ROOT。
- `deeptutor/services/config/loader.py:60-79` `_inject_runtime_paths`：把 PathService 派生的绝对路径注入 config，是归口正道。

## 去重与引用

- guide-file-io-path-durability（导读）：文件 IO/路径持久性导读，本卡不重复其内容，仅引用。
- tests/services/test_path_service_runtime_home.py：runtime home 默认解析语义的测试，仅引用，不在本卡复述或修改。
- 上游去重：HKUDS/DeepTutor 开放 PR/issue 检索无同主题（硬编码路径清点/path 归口）实现或 PR。

## 范围外备注

- `scripts/docker_compose.py:89`（宿主 compose 工作区，env 可覆盖）与 `start_deeptutor.command` 属部署面，不属 path_service 归口范围；已人工核对无 home 写死问题。
