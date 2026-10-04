# 文档与代码漂移扫描报告（AGEN-485）

- 日期：2026-10-04
- 扫描对象：`HKUDS/DeepTutor` @ `origin/main` = `ef2d9e5c3`（release: v1.6.12），只读
- 方式：在独立 worktree `dt-agen485-wt`（分支 `agen485/docs-drift-scan`）内，对根目录全部 7 个 `.md` 与 `docs-for-user/` 全部 12 个 `.md`（共 3371 行）提取命令、脚本、路径、模块、设置键、Web 路由、API 端点引用，与工作树逐一交叉核对（辅助脚本 `scan_docs_drift.py`，原始提取结果 `refs.json`，552 条引用，其中自动判定噪声 477 条已人工复核归类）
- 不修改任何产品代码；本目录（evidence/docs-drift-2026-10-04/）为唯一产物位置

## 范围说明（与卡面输入的差异）

- 卡面提到的根目录 `CONTAINERIZATION.md` 在 origin/main 上位于 `docs-for-user/CONTAINERIZATION.md`（已覆盖）。
- `DEVELOPMENT_WORKFLOW.md` 与 `LOCAL_FEATURES.md` 在 origin/main 上**不存在**（仅存在于本地检出工作区，含未提交修改，未纳入只读扫描范围）。本报告无法对这两个文件给出上游结论。
- DT-22 §4 已发现的 2 处失效 `TODO.md` 引用：在 origin/main 上 `git grep TODO.md -- "*.md" docs-for-user` 为 0 命中，即上游已修复，按卡面要求不重复列入。

## 一、失效引用清单（4 项）

| # | 位置 | 文档写法 | 实际情况 | 风险 | 修复建议 |
|---|---|---|---|---|---|
| F1 | `AGENTS.md:83-84` | 所有 capability 收敛到 `deeptutor/capabilities/_shared.py` 的 `emit_capability_result()` | `deeptutor/capabilities/_shared.py` 不存在；函数实际在 `deeptutor/agents/_shared/capability_result.py`（`git grep "def emit_capability_result"`） | 中：代理/贡献者按 AGENTS.md 找架构入口会扑空 | 改为 `deeptutor/agents/_shared/capability_result.py` |
| F2 | `AGENTS.md:131` | Python SDK facade 为 `deeptutor/app.py`（`DeepTutorApp`） | `deeptutor/app.py` 不存在；`app` 已是包，facade 在 `deeptutor/app/facade.py`（`git grep "class DeepTutorApp"`） | 低：路径过期但符号名仍可搜索到 | Key Files 表改为 `deeptutor/app/facade.py` |
| F3 | `AGENTS.md:43`（正文）及 46-54（表格）；`SKILL.md:62` | "Seven user-toggleable tools"，列表为 brainstorm / web_search / paper_search / reason / geogebra_analysis / imagegen / videogen，缺 `zotero_search` | `USER_TOGGLEABLE_TOOL_NAMES` 实际为 **8** 项（`deeptutor/tools/builtin/__init__.py:1907-1916`，含 `zotero_search`）；`README.md:670` 已含 zotero_search，即两份文档落后于代码与 README | 中：`--tool zotero_search` 是合法用法但两份面向代理/技能的文档未列出 | 两处补 `zotero_search` 并把 "Seven" 改为 "Eight" |
| F4 | `docs-for-user/watching-workspace.md:3`（`/watching`、`/watching/{sessionId}`）及 `:32`（发布检查路径 `/watching`、`/reading`） | 以 `/watching`、`/reading` 作为页面路径 | 实际路由为 `web/app/(workspace)/learning/watching/[sessionId]`、`.../learning/reading`，即 `/learning/watching`、`/learning/reading`（`/chat` 仍有效，`web/app/(workspace)/chat`） | 中：按文档做发布前 URL 检查会访问 404 路径 | 改为 `/learning/watching`、`/learning/reading` |

## 二、过期命令清单

未发现失效命令。以下命令/脚本已逐一验证存在且签名一致：

- CLI 顶层：`run`（`--session/--tool/-t/--kb/--notebook-ref/--history-ref/--language/-l/--config/--config-json/--format/-f`，deeptutor_cli/main.py:81-121）、`start --dev/--home/--detach`（main.py:127）、`stop`（main.py:152）、`serve --port`（main.py:163）、`chat --capability/-c`（deeptutor_cli/chat.py:52）
- 子命令组与卡面/文档列举一致：`workspace show/set/reset`、`partner list/create/start/stop`、`kb list/info/create/connect-kiwix/add/search/set-default/delete/list-sources/sync`（另有 add/remove-github-source、add/remove-web-source）、`skill search/install/list/remove/login/logout/publish/update`、`memory show/clear`、`session list/show/open/rename/delete`、`notebook list/create/show/add-md/replace-md/remove-record`、`book list/health/refresh-fingerprints`、`plugin list/info`
- REPL 命令（SKILL.md:166-178）与 `deeptutor_cli/chat.py:154-261` 完全对应
- 安装/开发命令：`pip install -e ".[all]"`、extras `cli/server/partners/tutorbot/matrix/matrix-e2e/math-animator/dev/all/codebuddy` 均在 pyproject.toml `[project.optional-dependencies]`；`pip install -e ./packaging/deeptutor-cli`（目录存在）；`deeptutor init --cli`（init_cmd.py:412）；`npm ci --legacy-peer-deps`（web/package-lock.json 存在）
- 脚本：`scripts/check_workspace_hygiene.py`、`scripts/check_repo_hygiene.py`、`scripts/docker_compose.py`、`pre-commit`（.secrets.baseline、scripts/hooks 存在，.gitignore 含 `.next/`、`web/.next-*/`）；`pytest tests/video_learning`（tests/video_learning/ 存在）
- AGENTS.md 能力名 11 个全部在 `deeptutor/runtime/bootstrap/builtin_capabilities.py` 注册；`--config render_mode=manim_video`（agents/visualize/analysis_agent.py:42、capability.py:71）有效

## 三、设置键/路径一致性抽查（通过）

`data/user/settings/*.json`（runtime_settings.py:460）；`system.json`、`auth.json`、`integrations.json`、`interface.json`、`model_catalog.json`、`document_parsing.json`、`skill_hubs.json`、`video_learning.json`（web/.../settings-nav.ts:604-615、tests/video_learning）、`main.yaml`、`agents.yaml` 均在代码中有对应读写；`.deeptutor/data/`、`data/user/.runtime/workspaces.sqlite3`（services/workspace/catalog.py）、`data/system/user-secrets/...`（multi_user/paths.py）、KB 内 `raw/`（knowledge/add_documents.py:154）、`visual_assets/`（services/rag/pipelines/llamaindex/pipeline.py）、memory `L2/L3`（api/routers/memory.py:56-65）、`data-migrations/`（services/workspace/data_migration.py）均一致。

## 四、误报/排除清单（自动扫描命中但确认无问题）

| 排除项 | 理由 |
|---|---|
| README 内 13 个 `%20` 编码图片路径（如 `assets/figs/system/system%20architecture.png`） | 磁盘文件名为含空格原名（如 `system architecture.png`），Markdown 内 URL 编码正确，文件全部存在 |
| `THIRD_PARTY_NOTICES.md:79` `packages/thinking-orbs` | 指上游仓库 Jakubantalik/Libraries 内的路径（归属声明），非本仓库路径；本仓库 `web/vendor/thinking-orbs/` 存在 |
| `docs-for-user/remote-hermes-backend.md` 的 `GET /v1/capabilities`、`POST /v1/runs`、`GET /api/sessions/{session_id}/messages` 等 | 描述外部 Hermes 网关 API；适配器 `deeptutor/services/subagent/hermes_remote*.py`（:82,:108,:198,:288, events:81,120）按同一组路径实现，仓库内自洽；网关侧无法从本仓库验证 |
| `docs-for-user/CONTAINERIZATION.md` 的 `start-frontend.sh`、`node /app/web/server.js`、`/app/data`、`/workspace`、`/tmp`、`/var/run`、`/pb_*` 等 | 容器内部布局：start-frontend.sh 由 Dockerfile:313 生成、standalone server.js 见 Dockerfile:167-170，均与文档一致 |
| `/space/questions`（PRACTICE.md） | 路由存在：`web/app/(utility)/space/questions` |
| `/settings/tools`（AGENTS.md:44） | 动态段落路由 `web/app/(settings)/settings/[section]`，section key "tools" 存在（settings-nav.ts:259） |
| `/register`、`/admin/users`、`/agents`、`/handoff`、`/learning`、`/learning/practice` | 对应路由目录均存在 |
| `GET:feed`、`GET:playlists`、`GET:playlists/*`（watching-workspace.md:42） | 与 `deeptutor/video_learning/invidious_account.py:34-36` 完全一致 |
| `prose 斜杠词`（CI/CD、HTTP/SSE、A/B、JSON/YAML 等） | 行文，非路径 |
| `python -m venv/pip`（README/CONTRIBUTING） | 标准库模块 |
| 运行时生成路径（`outputs/`、`data/user/workspace/`、`historical/` 等） | 运行期产物，代码中有构造点（path_service、workspace/data_migration 等），不应存在于 git 树 |
| `AGENTS.md:86` `capabilities/prompts/{en,zh}/<name>.yaml` | 上下文为包内相对路径，`deeptutor/capabilities/prompts/{en,zh}` 存在（备注级） |

## 五、风险汇总与修复建议

- 高风险：无（未发现会让安装/启动直接失败的失效命令或脚本）。
- 中风险 3 项：F1（架构文档指向不存在的模块）、F3（工具清单缺 zotero_search，两处）、F4（发布检查 URL 过期）。
- 低风险 1 项：F2（facade 路径过期）。
- 修复成本都很低（纯文档改动，共 4 个文件、约 6 行）。建议合并为 1 个 docs-only PR；按仓库惯例 docs-only 可直接进 main（CONTRIBUTING.md:85），由人工决定是否提交。

## 附：产物

- `refs.json`：552 条原始引用提取与逐条判定
- `scan_docs_drift.py`：提取/核对脚本（只读）
- `SHA256SUMS`：本目录全部文件校验和
