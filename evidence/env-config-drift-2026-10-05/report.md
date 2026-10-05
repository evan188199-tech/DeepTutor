# 环境变量与配置键漂移清点（四方对照）

- 卡: AGEN-714 · 日期: 2026-10-05 · 基线: origin/main `f07029cfc`（release v1.6.13）· 只读扫描，未改任何代码
- 方法: `git grep` 全仓枚举 `os.environ[...] / os.environ.get / os.getenv`（排除 tests）+ 常量回溯；对照面 = 后端代码读取点 / compose·Dockerfile·.env.example / 全部跟踪 `*.md`（活文档为主，历史 release notes 单独标注）/ `web/` 前端读取点
- 目录变量总数: 146 + 补充 compose/外部条目 6 = **152**
- 去重声明: 本卡只清点 env 键名层面；settings JSON↔env 链路机制（`_apply_*_process_overrides`、`render_environment` 的双写语义）属 scan-settings 范围，文档整体结构漂移属 scan-docs-drift 范围，依赖 import 属 scan-deps-drift 范围。重叠条目已在分级列标注。

## 漂移分级汇总

| 分级 | 数量 | 说明 |
|---|---|---|
| A 默认值不一致 | 2 | 文档漂移，scan-settings/scan-docs-drift 重叠 |
| B1′ 解析引擎未文档化（与已文档 DOCLING_* 不对称） | 10 | scan-docs-drift 重叠 |
| B1 用户面未文档化 | 50 | scan-docs-drift 建议覆盖 |
| B2 运维面未文档化 | 55 | scan-settings 链路相邻 |
| C 命名/别名漂移 | 2 | scan-settings 链路相邻 |
| G 模型/缓存目录变量 | 4 | scan-deps-drift 相邻（依赖下载面） |
| D 内部/平台变量（无需文档） | 13 | — |
| E 构建/测试工具变量（无需用户文档） | 10 | — |
| F compose 插值/入口脚本专用（代码不读，符合设计） | 0 | scan-docs-drift 相邻 |
| 补充条目 | 6 | compose 插值/入口脚本/外部网关 |

## A · 默认值不一致（高优先，修复成本最低）

| 变量 | 代码读取点 | compose | 文档 | 前端 | 标注 |
|---|---|---|---|---|---|
| `LLM_RETRY__BASE_DELAY` | `deeptutor/config/settings.py:24` | — | `deeptutor/config/settings.py:8-9`（模块 docstring 自述） | — | docstring 写 default=3 / 1.0，Field 实际 default=8 / 5.0（:23-24）；去重：属 scan-settings 链路自文档漂移 |
| `LLM_RETRY__MAX_RETRIES` | `deeptutor/config/settings.py:23` | — | `deeptutor/config/settings.py:8-9`（模块 docstring 自述） | — | docstring 写 default=3 / 1.0，Field 实际 default=8 / 5.0（:23-24）；去重：属 scan-settings 链路自文档漂移 |

## B1′ · 解析引擎变量：MINERU_/TIKA 与已文档 DOCLING_* 不对称（高优先）

README.md:815 明确文档化 `DOCLING_MODE` / `DOCLING_API_BASE_URL` / `DOCLING_API_TOKEN`，但同页描述的 MinerU（9 个键）与 Tika（1 个键）走同一覆盖链（`_apply_mineru/_apply_pageindex/_apply_ima_process_overrides`）却零文档：

| 变量 | 代码读取点 | compose | 文档 | 前端 | 标注 |
|---|---|---|---|---|---|
| `MINERU_ALLOW_LOCAL_MODEL_DOWNLOAD` | `deeptutor/services/config/runtime_settings.py:942` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_API_BASE_URL` | `deeptutor/services/config/runtime_settings.py:928` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_API_TOKEN` | `deeptutor/services/config/runtime_settings.py:930` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_LANGUAGE` | `deeptutor/services/config/runtime_settings.py:940` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_LOCAL_CLI_PATH` | `deeptutor/services/config/runtime_settings.py:932` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_MODE` | `deeptutor/services/config/runtime_settings.py:926` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_MODEL_DOWNLOAD_ENDPOINT` | `deeptutor/services/config/runtime_settings.py:936` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_MODEL_SOURCE` | `deeptutor/services/config/runtime_settings.py:934` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `MINERU_MODEL_VERSION` | `deeptutor/services/config/runtime_settings.py:938` | — | — | — | 去重：scan-docs-drift 建议覆盖 |
| `TIKA_SERVER_URL` | `deeptutor/services/config/runtime_settings.py:1211` | — | — | — | 去重：scan-docs-drift 建议覆盖 |

## B1 · 用户面未文档化变量

| 变量 | 代码读取点 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `ALIYUN_IQS_API_KEY` | `deeptutor_cli/init_wizard.py:228` | — | — | — |
| `ARK_API_KEY` | `deeptutor_cli/init_wizard.py:200` | — | — | — |
| `BAIDU_API_KEY` | `deeptutor_cli/init_wizard.py:221` | — | — | — |
| `BOCHA_API_KEY` | `deeptutor_cli/init_wizard.py:207` | — | — | — |
| `BRAVE_API_KEY` | `deeptutor_cli/init_wizard.py:148` | — | — | — |
| `CHAT_ATTACHMENT_MAX_CHARS_PER_DOC` | `deeptutor/services/config/runtime_settings.py:875` | — | — | — |
| `CHAT_ATTACHMENT_MAX_CHARS_TOTAL` | `deeptutor/services/config/runtime_settings.py:877` | — | — | — |
| `CHAT_ATTACHMENT_MAX_FILE_MB` | `deeptutor/services/config/runtime_settings.py:871` | — | — | — |
| `CHAT_ATTACHMENT_MAX_TOTAL_MB` | `deeptutor/services/config/runtime_settings.py:873` | — | — | — |
| `CHAT_PRIOR_IMAGE_REINJECT_MAX` | `deeptutor/services/config/runtime_settings.py:879` | — | — | — |
| `CODEBUDDY_API_KEY` | `deeptutor/services/llm/provider_core/codebuddy_provider.py:26; deeptutor/services/llm/provider_core/codebuddy_http_provider.py:208` | — | — | — |
| `CODEBUDDY_BASE_URL` | `deeptutor/services/codebuddy_credentials.py:166` | — | — | — |
| `CODEBUDDY_INTERNET_ENVIRONMENT` | `deeptutor/services/codebuddy_credentials.py:171` | — | — | — |
| `CODEX_HOME` | `deeptutor/services/subagent/models.py:139` | — | — | — |
| `DEEPTUTOR_CAPABILITY_ROUTING_ENABLED` | `deeptutor/services/config/runtime_settings.py:869` | — | — | — |
| `DEEPTUTOR_CODEBUDDY_AUTH_FILE` | `deeptutor/services/codebuddy_credentials.py:104` | — | — | — |
| `DEEPTUTOR_CODEBUDDY_BACKEND` | `deeptutor/services/llm/provider_core/codebuddy_http_provider.py:229` | — | — | — |
| `DEEPTUTOR_HUB_TOKEN` | `deeptutor_cli/skill.py:34` | — | — | — |
| `DEEPTUTOR_LINKED_FOLDER_ROOTS` | `deeptutor/services/rag/linked_kb.py:32` | — | — | — |
| `DEEPTUTOR_OPENAI_API_KEY` | `deeptutor/services/search/source_filter.py:537` | — | — | — |
| `DEEPTUTOR_RAG_RETRIEVAL_PROFILE` | `deeptutor/services/rag/pipelines/llamaindex/config.py:95` | — | — | — |
| `DEEPTUTOR_REDIS_KEY_PREFIX` | `deeptutor/services/config/runtime_settings.py:919` | — | — | — |
| `DEEPTUTOR_REDIS_URL` | `deeptutor/services/config/runtime_settings.py:917` | — | — | — |
| `DEEPTUTOR_TURN_COORDINATION_BACKEND` | `deeptutor/services/config/runtime_settings.py:915` | — | — | — |
| `DOUBAO_API_KEY` | `deeptutor_cli/init_wizard.py:200` | — | — | — |
| `DSH_HOME` | `deeptutor/services/subagent/deepseek_harness.py:254` | — | — | — |
| `EDUHUB_TOKEN` | `deeptutor_cli/skill.py:35` | — | — | — |
| `FIRECRAWL_API_KEY` | `deeptutor_cli/init_wizard.py:190` | — | — | — |
| `GITHUB_TOKEN` | `deeptutor/services/github_source/client.py:55` | — | — | — |
| `GOOGLE_WEB_RISK_API_KEY` | `deeptutor/services/search/source_filter.py:546` | — | — | — |
| `GROQ_API_KEY` | `deeptutor/partners/transcription.py:18` | — | — | — |
| `IMA_API_KEY` | `deeptutor/services/config/runtime_settings.py:962` | — | — | — |
| `IMA_CLIENT_ID` | `deeptutor/services/config/runtime_settings.py:960` | — | — | — |
| `IQS_API_KEY` | `deeptutor_cli/init_wizard.py:228` | — | — | — |
| `JINA_API_KEY` | `deeptutor_cli/init_wizard.py:162` | — | — | — |
| `LANGUAGE` | `deeptutor/services/config/launch_settings.py:95` | — | — | — |
| `LLM_TREAT_PRIVATE_AS_LOCAL` | `deeptutor/services/llm/utils.py:73` | — | — | — |
| `PAGEINDEX_API_KEY` | `deeptutor/services/config/runtime_settings.py:948` | — | — | — |
| `PERPLEXITY_API_KEY` | `deeptutor_cli/init_wizard.py:183` | — | — | — |
| `QIANFAN_API_KEY` | `deeptutor_cli/init_wizard.py:221` | — | — | — |
| `RAG_PROVIDER` | `deeptutor/services/rag/service.py:309` | — | — | — |
| `RAG_RETRIEVAL_PROFILE` | `deeptutor/services/rag/pipelines/llamaindex/config.py:95` | — | — | — |
| `SEARCH_API_KEY` | `deeptutor_cli/init_wizard.py:148` | — | — | — |
| `SERPER_API_KEY` | `deeptutor_cli/init_wizard.py:169` | — | — | — |
| `SERPLY_API_KEY` | `deeptutor_cli/init_wizard.py:176` | — | — | — |
| `TAVILY_API_KEY` | `deeptutor_cli/init_wizard.py:155` | — | — | — |
| `UI_LANGUAGE` | `deeptutor/services/config/launch_settings.py:94` | — | — | — |
| `WEB_RISK_API_KEY` | `deeptutor/services/search/source_filter.py:546` | — | — | — |
| `ZHIPUAI_API_KEY` | `deeptutor_cli/init_wizard.py:214` | — | — | — |
| `ZHIPU_API_KEY` | `deeptutor_cli/init_wizard.py:214` | — | — | — |

## B2 · 运维面未文档化变量

| 变量 | 代码读取点 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `AUTH_COOKIE_SECURE` | `deeptutor/services/config/runtime_settings.py:725,896` | Dockerfile | — | — |
| `AUTH_ENABLED` | `deeptutor/services/config/runtime_settings.py:721,886` | Dockerfile, compose.yaml | d/CONTAINERIZATION.md | web/next.config.js:69 |
| `AUTH_PASSWORD_HASH` | `deeptutor/services/config/runtime_settings.py:723,892` | Dockerfile | — | — |
| `AUTH_PRIVATE_LOGIN_HOSTS` | `deeptutor/services/config/runtime_settings.py:726,898` | — | README.md | — |
| `AUTH_TOKEN_EXPIRE_HOURS` | `deeptutor/services/config/runtime_settings.py:724,894` | Dockerfile | — | — |
| `AUTH_TRUSTED_FRONTEND_PROXY_IPS` | `deeptutor/api/routers/auth.py:116` | — | README.md | — |
| `AUTH_USERNAME` | `deeptutor/services/config/runtime_settings.py:722,890` | Dockerfile | — | — |
| `BACKEND_PORT` | `deeptutor/services/config/launch_settings.py:91; deeptutor/services/config/runtime_settings.py:711,844` | .env.example, Dockerfile, compose.yaml | d/CONTAINERIZATION.md | web/next.config.js:51 |
| `BACKEND_WORKERS` | `deeptutor/services/config/runtime_settings.py:712,864` | Dockerfile | — | — |
| `CHAT_ATTACHMENT_DIR` | `deeptutor/services/config/runtime_settings.py:719,860` | Dockerfile | d/workspaces.md | — |
| `CORS_ORIGIN` | `deeptutor/services/config/runtime_settings.py:716,854` | Dockerfile | — | — |
| `CORS_ORIGINS` | `deeptutor/services/config/runtime_settings.py:717,856` | Dockerfile | — | — |
| `DEEPTUTOR_API_BASE_URL` | `deeptutor/services/config/runtime_settings.py:742` | .env.example, Dockerfile, compose.yaml | d/CONTAINERIZATION.md | — |
| `DEEPTUTOR_AUTH_ENABLED` | `deeptutor/services/config/runtime_settings.py:747` | Dockerfile | d/CONTAINERIZATION.md | web/proxy.ts:29 |
| `DEEPTUTOR_BACKEND_READY_TIMEOUT` | `deeptutor/runtime/launcher.py:35; deeptutor/runtime/launcher.py:58` | — | — | — |
| `DEEPTUTOR_CLI_APP_INSTALL_TIMEOUT_S` | `deeptutor/services/cli_apps/installer.py:60` | — | — | — |
| `DEEPTUTOR_CONTAINER` | `deeptutor/services/app_update.py:155` | — | — | — |
| `DEEPTUTOR_DEV_RELOAD` | `deeptutor/api/run_server.py:68` | — | — | — |
| `DEEPTUTOR_FRONTEND_READY_TIMEOUT` | `deeptutor/runtime/launcher.py:36` | — | — | — |
| `DEEPTUTOR_HERMES_REMOTE_API_KEY` | `deeptutor/services/subagent/config.py:81; deeptutor/services/subagent/hermes_remote.py:77` | — | d/remote-hermes-backend.md | — |
| `DEEPTUTOR_HOME` | `deeptutor/runtime/home.py:40; deeptutor/runtime/launcher.py:1306; deeptutor_cli/init_cmd.py:417` | — | README.md | — |
| `DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES` | `deeptutor/services/config/runtime_settings.py:384` | Dockerfile | — | — |
| `DEEPTUTOR_ISOLATED_WORKERS` | `deeptutor/runtime/isolated_worker.py:29` | — | — | — |
| `DEEPTUTOR_MODE` | `deeptutor/runtime/mode.py:22; deeptutor/runtime/mode.py:39` | — | — | — |
| `DEEPTUTOR_PGID` | `deeptutor/services/setup/data_volume.py:150` | Dockerfile | — | — |
| `DEEPTUTOR_PUBLIC_URL` | `deeptutor/video_learning/invidious_account.py:29; deeptutor/services/mcp/oauth.py:212` | — | d/watching-workspace.md | — |
| `DEEPTUTOR_PUID` | `deeptutor/services/setup/data_volume.py:149` | Dockerfile | — | — |
| `DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS` | `deeptutor/services/sandbox/runner/server.py:162` | dc.yml | — | — |
| `DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS` | `deeptutor/services/sandbox/config.py:33` | Dockerfile, dc.yml | README.md | — |
| `DEEPTUTOR_SANDBOX_MAX_CONCURRENT` | `deeptutor/services/sandbox/config.py:35` | — | — | — |
| `DEEPTUTOR_SANDBOX_MAX_PER_MINUTE` | `deeptutor/services/sandbox/config.py:36` | — | — | — |
| `DEEPTUTOR_SANDBOX_RUNNER_URL` | `deeptutor/services/sandbox/config.py:32` | Dockerfile, Dockerfile.runner, dc.yml | README.md | — |
| `DEEPTUTOR_VERSION_CHECK_ENABLED` | `deeptutor/services/config/runtime_settings.py:710,842` | — | — | — |
| `DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS` | `deeptutor/services/workspace/service.py:30; deeptutor/services/workspace/service.py:102` | compose.yaml, dc.ghcr.yml, dc.yml | README.md, d/CONTAINERIZATION.md | — |
| `DEEPTUTOR_WORKSPACE_ROOT` | `deeptutor/services/workspace/service.py:29; deeptutor/services/workspace/service.py:98` | compose.yaml, dc.ghcr.yml, dc.yml | README.md, d/CONTAINERIZATION.md | — |
| `DISABLE_SSL_VERIFY` | `deeptutor/services/config/runtime_settings.py:718,858` | Dockerfile | README.md | — |
| `DOCLING_API_BASE_URL` | `deeptutor/services/config/runtime_settings.py:1197` | — | README.md | — |
| `DOCLING_API_TOKEN` | `deeptutor/services/config/runtime_settings.py:1199` | — | README.md | — |
| `DOCLING_MODE` | `deeptutor/services/config/runtime_settings.py:1195` | — | README.md | — |
| `ENVIRONMENT` | `deeptutor/services/llm/openai_http_client.py:36` | — | — | — |
| `FRONTEND_PORT` | `deeptutor/services/config/launch_settings.py:92; deeptutor/services/config/runtime_settings.py:713,846` | Dockerfile, compose.yaml | d/CONTAINERIZATION.md | — |
| `LLM_RETRY__EXPONENTIAL_BACKOFF` | `deeptutor/config/settings.py:25` | — | — | — |
| `NEXT_PUBLIC_API_BASE` | `web/next.config.js:61` | Dockerfile, compose.yaml | d/CONTAINERIZATION.md | web/next.config.js:61 |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | `web/next.config.js:59` | Dockerfile, compose.yaml | d/CONTAINERIZATION.md | web/next.config.js:59 |
| `NEXT_PUBLIC_APP_VERSION` | `web/features/settings/sections/AboutSettingsSection.tsx:168` | Dockerfile | — | web/features/settings/sections/AboutSettingsSection.tsx:168 |
| `OPENAI_API_KEY` | `deeptutor/services/llm/config.py:79; deeptutor/services/llm/client.py:116; deeptutor/services/search/source_filter.py:537` | — | README.md | — |
| `OPENAI_BASE_URL` | `deeptutor/services/llm/config.py:86; deeptutor/services/llm/client.py:123` | — | — | — |
| `PGID` | `deeptutor/services/setup/data_volume.py:150` | Dockerfile, dc.ghcr.yml, dc.yml | d/CONTAINERIZATION.md | — |
| `POCKETBASE_ADMIN_EMAIL` | `deeptutor/services/config/runtime_settings.py:751,910` | Dockerfile | — | — |
| `POCKETBASE_ADMIN_PASSWORD` | `deeptutor/services/config/runtime_settings.py:752,912` | Dockerfile | — | — |
| `POCKETBASE_EXTERNAL_URL` | `deeptutor/services/config/runtime_settings.py:750,908` | Dockerfile, compose.yaml | — | — |
| `POCKETBASE_PORT` | `deeptutor/services/config/runtime_settings.py:749,906` | Dockerfile | — | — |
| `POCKETBASE_URL` | `deeptutor/services/config/runtime_settings.py:748,904` | Dockerfile, compose.yaml | d/CONTAINERIZATION.md | — |
| `PUID` | `deeptutor/services/setup/data_volume.py:149` | Dockerfile, dc.ghcr.yml, dc.yml | d/CONTAINERIZATION.md | — |
| `RUNNER_PORT` | `deeptutor/services/sandbox/runner/server.py:359` | Dockerfile.runner | — | — |

## C · 命名/别名漂移

| 变量 | 代码读取点 | compose | 文档 | 前端 | 标注 |
|---|---|---|---|---|---|
| `PUBLIC_API_BASE` | `deeptutor/services/config/runtime_settings.py:850` | — | — | — | `NEXT_PUBLIC_API_BASE_EXTERNAL` 的未文档化别名，同函数两键同写一字段 |
| `DEEPTUTOR_BACKEND_WORKERS` | `deeptutor/services/config/runtime_settings.py:863` | Dockerfile:345 | —（`BACKEND_WORKERS` 同函数 :864 双读） | — | 前缀/无前缀双名并存，仅无前缀名出现在 Dockerfile:280 入口默认 |
| `NEXT_PUBLIC_AUTH_ENABLED` | `deeptutor/services/config/runtime_settings.py:727,887` | — | — | `web/next.config.js:68,75` | 鉴权开关三名并存：`AUTH_ENABLED`（有文档 d/CONTAINERIZATION.md:533）/ `DEEPTUTOR_AUTH_ENABLED`（同页）/ 本名未文档化 |

## D–G · 内部/工具/缓存/compose 专用变量（无需用户文档，列出防误判）

**G 模型/缓存目录变量**（scan-deps-drift 相邻（依赖下载面））

| 变量 | 代码读取点 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `DOCLING_ARTIFACTS_PATH` | `deeptutor/services/parsing/engines/docling/engine.py:52` | — | — | — |
| `DOCLING_CACHE_DIR` | `deeptutor/services/parsing/engines/docling/engine.py:45` | — | — | — |
| `HF_HOME` | `deeptutor/services/parsing/engines/mineru/readiness.py:35; deeptutor/services/parsing/engines/docling/engine.py:59` | — | — | — |
| `MODELSCOPE_CACHE` | `deeptutor/services/parsing/engines/mineru/readiness.py:41` | — | — | — |

**D 内部/平台变量（无需文档）**（—）

| 变量 | 代码读取点 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `COLUMNS` | `deeptutor/services/subagent/claude_models.py:163` | — | — | — |
| `DEEPTUTOR_DETACHED_TOKEN` | `deeptutor/runtime/launcher.py:74; deeptutor/runtime/launcher.py:1300` | — | — | — |
| `DEEPTUTOR_DETACHED_WORKER` | `deeptutor/runtime/launcher.py:73; deeptutor/runtime/launcher.py:1301` | — | — | — |
| `DEEPTUTOR_LAUNCHER_PID` | `deeptutor/services/app_update.py:615` | — | — | — |
| `DEEPTUTOR_SUPERVISOR_PID` | `deeptutor/runtime/memory_probe.py:100` | — | — | — |
| `INVOCATION_ID` | `deeptutor/services/app_update.py:208; deeptutor/services/app_update.py:216` | — | — | — |
| `LINES` | `deeptutor/services/subagent/claude_models.py:164` | — | — | — |
| `LOCALAPPDATA` | `deeptutor/services/codebuddy_credentials.py:89` | — | — | — |
| `PYTHONUNBUFFERED` | `deeptutor/api/run_server.py:23` | Dockerfile, Dockerfile.runner | — | — |
| `SSL_CERT_DIR` | `deeptutor/services/llm/openai_http_client.py:57` | — | — | — |
| `SSL_CERT_FILE` | `deeptutor/services/llm/openai_http_client.py:56` | — | — | — |
| `TERM` | `deeptutor/services/subagent/claude_models.py:162` | — | — | — |
| `XDG_DATA_HOME` | `deeptutor/services/codebuddy_credentials.py:96` | — | — | — |

**E 构建/测试工具变量（无需用户文档）**（—）

| 变量 | 代码读取点 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `DEEPTUTOR_BUILD_SKIP_MISSING` | `web/scripts/build.mjs:82` | — | — | web/scripts/build.mjs:82 |
| `DEEPTUTOR_MULTI_WORKER_CONTROL_PATH` | `web/tests/e2e/fixtures/runtime.ts:59` | — | — | web/tests/e2e/fixtures/runtime.ts:59 |
| `DEEPTUTOR_MULTI_WORKER_CONTROL_URL` | `web/tests/e2e/fixtures/runtime.ts:49` | — | — | web/tests/e2e/fixtures/runtime.ts:49 |
| `DEEPTUTOR_MULTI_WORKER_E2E` | `web/tests/e2e/fixtures/runtime.ts:45` | — | — | web/tests/e2e/fixtures/runtime.ts:45 |
| `DEEPTUTOR_NEXT_DIST_DIR` | `web/next.config.js:98` | — | — | web/next.config.js:98 |
| `DEEPTUTOR_NEXT_TSCONFIG` | `web/next.config.js:103` | — | — | web/next.config.js:103 |
| `DEEPTUTOR_TURN_E2E_FIXTURE` | `web/tests/e2e/turn-lifecycle.audit.ts:6` | — | — | web/tests/e2e/turn-lifecycle.audit.ts:6 |
| `PW_SERIAL` | `web/playwright.config.ts:7` | — | — | web/playwright.config.ts:7 |
| `VERCEL` | `web/scripts/build.mjs:93` | — | — | web/scripts/build.mjs:93 |
| `WEB_BASE_URL` | `web/playwright.config.ts:4` | — | — | web/playwright.config.ts:4 |

## 补充条目（代码不直接读取，属部署面）

| 变量 | 消费方 | compose | 文档 | 前端 |
|---|---|---|---|---|
| `DEEPTUTOR_WORKSPACE_HOST` | `—（compose 卷插值）` | `compose.yaml:177; dc.yml:98,168-169; dc.ghcr.yml:77` | `README.md:422; d/CONTAINERIZATION.md:117` | `—` |
| `HOST_PORT_BACKEND/FRONTEND/POCKETBASE` | `—（compose 端口插值）` | `compose.yaml:103,162-163; .env.example:21-23` | `d/CONTAINERIZATION.md:437（前缀）` | `—` |
| `DEEPTUTOR_DOCKER_BACKEND_PORT/FRONTEND_PORT/POCKETBASE_PORT` | `—（compose 端口插值）` | `dc.yml:55,85-86,127; dc.ghcr.yml:65-66; compose.oauth:8-9` | `—（仅 dc.yml:21 头注释）` | `—` |
| `BACKEND_HOST/FRONTEND_HOST` | `—（Dockerfile 入口）` | `Dockerfile:281,303,318-322` | `README.md:483; d/CONTAINERIZATION.md:305` | `—` |
| `TZ` | `—（经 compose 注入容器）` | `.env.example:25; compose.yaml:180` | `.env.example:25` | `—` |
| `API_SERVER_KEY` | `—（外部 Hermes 网关服务端密钥）` | `—` | `d/remote-hermes-backend.md:88` | `—` |

## 可拆卡条目

1. **fix(docs): settings.py docstring 默认值对齐** — `deeptutor/config/settings.py:8-9` 的 `default: 3` / `1.0` 改为 8 / 5.0（或反向确认产品意图）。1 行改动。
2. **docs: 解析引擎 env 参考补全** — MinerU 9 键 + `TIKA_SERVER_URL`，对齐 README.md:815 的 DOCLING_* 段落写法。
3. **docs: 搜索/抓取 provider key 自动检测清单** — `deeptutor_cli/init_wizard.py:137-228` 的 17 个键 + `SEARCH_API_KEY` 回退，说明“首个非空生效”顺序语义。
4. **docs: runtime_settings 覆盖链 env 参考** — `CHAT_ATTACHMENT_MAX_*`(4) / `CHAT_PRIOR_IMAGE_REINJECT_MAX` / `DEEPTUTOR_CAPABILITY_ROUTING_ENABLED` / `DEEPTUTOR_TURN_COORDINATION_BACKEND` / `DEEPTUTOR_REDIS_URL` / `DEEPTUTOR_REDIS_KEY_PREFIX` / `PAGEINDEX_API_KEY` / `IMA_CLIENT_ID` / `IMA_API_KEY`（`deeptutor/services/config/runtime_settings.py:840-970,1211`）。
5. **docs: .env.example 补 `DEEPTUTOR_WORKSPACE_HOST`** — compose.yaml:177 支持但 `.env.example`（仅 4 键）未列；同时为 dc.yml/dc.ghcr.yml 的 `DEEPTUTOR_DOCKER_*_PORT` 家族补一处活文档。
6. **docs(可选): CODEBUDDY_* 与 HUB token 命名参考** — 5 个 CODEBUDDY 键 + `DEEPTUTOR_HUB_TOKEN`/`EDUHUB_TOKEN` 双名，只写名称与用途，不写凭据获取细节。
7. **refactor(评估): 别名收敛** — `PUBLIC_API_BASE`、`DEEPTUTOR_BACKEND_WORKERS` 双名、鉴权三名；先评估外部使用再决定废弃或文档化。

## 验收对照

- 每项含 path:line 与四方命中情况：见上表（—=该面无命中）
- 去重标注：A 节属 scan-settings；B1′/B1 文档缺口与补充条目 5 属 scan-docs-drift 候选；G 节缓存目录属 scan-deps-drift 相邻；链路机制本身不在本卡展开
- 未改任何代码：本分支仅新增 evidence/ 目录

## 历史档案标注说明

`assets/releases/past_releases/*.md` 为历史发布存档，不计入活文档；仅以下键曾出现在存档中（其余 B 类键连存档都没有）：`DEEPTUTOR_ISOLATED_WORKERS`(ver1-6-4)、`DEEPTUTOR_DEV_RELOAD`(ver1-5-8)、`ENVIRONMENT`(ver1-3-10)、`SSL_CERT_FILE/DIR`(ver1-5-15)、`SERPER_API_KEY`(ver1-1-0-beta)、`PERPLEXITY_API_KEY`/`BAIDU_API_KEY`/`RAG_PROVIDER`(ver0-4-0)、`GOOGLE_WEB_RISK_API_KEY`(ver1-6-11)、`GITHUB_TOKEN`(ver1-2-2)、`TIKA_SERVER_URL`(ver1-5-15)。
