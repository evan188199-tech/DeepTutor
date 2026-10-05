# DeepTutor 测试体系导读（tests 组织 · conftest · mock 模式 · 运行与耗时 · CI 入口）

> 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release v1.6.13）。所有 `path:line` 均以该提交为准。
> 实测环境：macOS + Python 3.13 venv（`/Users/Shared/DeepTutor/.venv`），未配置 Redis/外部服务，未装可选 SDK（lightrag/graphrag）。
> 本文不改任何代码；所有命令可直接复制运行（`python` 指项目 venv 的 Python，测试命令均已限时）。

---

## 1. 全景：两侧测试栈与统一入口

DeepTutor 的测试分两侧，入口都在各自的配置文件里：

| 侧 | 配置 | 测试路径 | 运行器 |
|---|---|---|---|
| Python 后端 | `pyproject.toml:477-493` | `tests/` + `deeptutor/learning/tests`（`testpaths`，pyproject.toml:478） | pytest（`pytest>=7` + `pytest-asyncio`，pyproject.toml:275-276） |
| Web 前端 | `web/vitest.config.mts:13-22` + `web/package.json:14-15` | `web/tests/` | 双通道：`*.spec.ts(x)` → Vitest（jsdom）；`*.test.ts` → tsc 编译后 Node 内置 test runner |

pytest 关键配置（`pyproject.toml:477-493`）：

- `pythonpath = ["."]`（:479）：从仓库根运行即无需安装即可 import `deeptutor`。
- 自定义标记（:480-485）：`integration`（需外部服务）、`redis_integration`（需 `DEEPTUTOR_TEST_REDIS_URL`）、`real_llm_resolver`（测 LLM 配置解析本身时保留真实 resolver）、`asyncio`。
- `asyncio_default_fixture_loop_scope = "function"`（:486）；**未开 `asyncio_mode = auto`**，异步用例必须显式 `@pytest.mark.asyncio`。
- `addopts`（:487-493）：`--strict-markers --strict-config --disable-warnings --tb=short --import-mode=importlib`。

开发依赖安装（AGENTS.md:144-152，`[dev]` extra 含 pytest/pre-commit 等）：

```bash
timeout 600 pip install -e ".[dev]"           # Python 侧
cd web && timeout 900 npm ci --legacy-peer-deps   # 前端侧（CI 同款，tests.yml:81）
```

---

## 2. tests/ 目录组织（Python 侧）

`tests/` 按 `deeptutor/` 的包结构镜像组织；`deeptutor/learning/tests` 是唯一放在包内的例外（对应 `testpaths` 第二项）。

当前规模（705 个 `tests/**/test_*.py` + 23 个 learning = **728 个文件、9277 个用例**；全量收集 13s）：

| 目录 | 文件数 | 对应被测代码 |
|---|---|---|
| `tests/services/` | 314 | `deeptutor/services/**`（最大域，内含 rag/partners/cli_apps/sandbox/codex_auth 等子域） |
| `tests/api/` | 70 | `deeptutor/api/routers/**`（router 合同测试） |
| `tests/agents/` | 43 | `deeptutor/agents/**`（chat/question/research/notebook/…） |
| `tests/multi_user/` | 36 | `deeptutor/multi_user/**` |
| `tests/core/`、`tests/runtime/` | 29 / 28 | 核心能力协议、runtime 编排/registry/launcher |
| `tests/book/`、`tests/reading/` | 27 / 25 | 阅读与书本链路 |
| `tests/tools/`、`tests/capabilities/` | 21 / 21 | 工具与能力（capability）实现 |
| 其余 | — | knowledge 19、cli 16、scripts 10、utils 9、logging 7、app 7、video_learning 6、partners 4、i18n 3、顶层散件 3（`test_matrix_requirements.py` 等） |

结构约定：

- 测试文件一律 `test_*.py`；用例函数 `test_*`。
- 目录可有 `__init__.py`（如 `tests/api/__init__.py`），配合 `--import-mode=importlib`（pyproject.toml:492）避免同名模块冲突。
- 共享静态素材放 `tests/fixtures/`（CI 模型目录 `ci_model_catalog.json`、lightrag_bridge 采样等）。
- router 合同测试的公共辅助在 `tests/api/route_introspection.py:10`（`iter_effective_route_paths`，兼容 FastAPI 新版懒加载路由）。

```bash
# 看某个域有哪些测试
ls tests/services/rag/
timeout 120 python -m pytest -q -p no:cacheprovider tests/api --collect-only | tail -3
```

---

## 3. conftest 分层与 fixture

### 3.1 根 conftest：`tests/conftest.py`（311 行）

两类内容：

**autouse 全局防护/隔离（每个测试自动生效）**：

| fixture | 作用 | 位置 |
|---|---|---|
| `_guard_real_owner_secrets` | 任何测试写穿到真实账号状态树（OAuth/MCP/CLI-apps）即 fail 并清理，防静默污染 | conftest.py:48-71 |
| `_guard_legacy_multi_user_migration` | 把 legacy `multi-user/` 根指向不可存在路径，防止真实目录被迁移 | conftest.py:74-90 |
| `_isolate_codebuddy_login` | 屏蔽开发者本机 CodeBuddy 登录态，保证与 CI 一致 | conftest.py:93-116 |
| `_isolate_llm_config` | 给所有测试固定的 fake LLM 配置并清 `_LLM_CONFIG_CACHE`，消除顺序依赖；测解析本身用 `real_llm_resolver` 标记逃生（:243-249） | conftest.py:224-266 |
| `_isolate_application_container` | 每个测试前后清空进程级 DI 容器单例 | conftest.py:269-283 |
| `_restore_process_env` | 兜底恢复测试直接改坏的 `os.environ`（monkeypatch 之外） | conftest.py:286-303 |
| `_isolate_usage_ledger` | 用量账本指向 tmp，防 mock 调用计入真实统计 | conftest.py:306-311 |

**共享 fixture**：`stream_bus`（:124）、`minimal_context`/`rich_context`（:135/:145，`UnifiedContext` 两档）、`tmp_db_path`+`sqlite_store`（:170/:177）、`stub_capability`（:202）、`fake_llm_config`（:212，MagicMock 版 LLMConfig）。

### 3.2 域级 conftest（5 个）

| 文件 | 提供什么 |
|---|---|
| `tests/services/rag/conftest.py:11` | `pytest_addoption` 注册 `--pipeline`（只能写在 conftest，不能写在测试模块） |
| `tests/services/partners/conftest.py:19` | `partners_root`：把 admin/multi-user 全部根重定向到 `tmp_path`；外加脚本化 chat-loop orchestrator 脚手架 |
| `tests/multi_user/conftest.py:21` | `mu_isolated_root`：重定向 `multi_user` 全局路径并清 `_path_services` 缓存 |
| `tests/services/cli_apps/conftest.py:18` | autouse `cli_app_roots`：双根（installs + preferences）都进 tmp |

分层规则：**能进域级 conftest 的不复制进测试文件**；新域如需重定向路径，仿照 `cli_apps/conftest.py` 写 autouse fixture——根 conftest 的防护会在你漏重定向时直接 fail（见 conftest.py:66-71 的报错信息）。

```bash
# 查看某个目录生效的 fixture
timeout 120 python -m pytest -q -p no:cacheprovider tests/multi_user --fixtures | head -20
```

---

## 4. 常用 mock / fake 模式

Python 侧（按使用面排序，基于全仓扫描）：

1. **monkeypatch 路径隔离**（411 个文件使用）：`tmp_path` + `monkeypatch.setattr(paths, "SYSTEM_ROOT", ...)` 是本仓库的标准隔离手法，样例见 `tests/services/cli_apps/conftest.py:18-28`、`tests/multi_user/conftest.py:21`。
2. **手写 Fake 类**（108 个文件定义 `class Fake*`）：比 MagicMock 更能锁定合同。样例：`tests/core/test_agentic_client_api_format.py:37`（`FakeAnthropicProvider`）；partners 的脚本化 orchestrator（`tests/services/partners/conftest.py:19` 起的脚手架）。
3. **autouse 环境隔离**：LLM 配置（conftest.py:224）、DI 容器（:269）、环境变量（:286）、用量账本（:306）都由根 conftest 托管，测试内**不要**自己再去 patch 这些全局。
4. **MagicMock**（25 个文件）：轻量场景；共享版即 `fake_llm_config`（conftest.py:212）。
5. **显式异步**：`@pytest.mark.asyncio`（274 个文件），因为没开 auto 模式。
6. **可选依赖守卫**：fastapi 缺席时 `skipif` 整文件（`tests/api/test_knowledge_router.py:22-32` 的 `pytestmark` 模式），保证轻量环境也能收集。
7. **外部服务标记**：`@pytest.mark.integration`（`tests/integration/`）、`@pytest.mark.redis_integration`（`tests/runtime/coordination/test_redis_integration.py`、`test_redis_stress.py`，未设 `DEEPTUTOR_TEST_REDIS_URL` 时自动跳过）。

前端侧：

1. **`vi.mock` 模块替换**（90 个 spec/test 文件使用）；`vitest.config.mts:20-21` 设 `clearMocks: true` + `restoreMocks: true`，setup 里 `afterEach` 再兜底 `vi.restoreAllMocks()`（`web/tests/setup/rendered.ts:86-90`），mock 不会跨用例泄漏。
2. **存储注入**：setup 用 `MemoryStorage` 替换 `localStorage`/`sessionStorage`（rendered.ts:11-49），并拦截意外的 React `act` 警告（:80-84）、`afterEach` 自动 `cleanup()`（:86-90）——组件测试不需要自己清理。
3. **JSON 快照素材**：`web/tests/fixtures/provider-trace-events.json`、`turn-lifecycle.json`，协议类测试直接 import。
4. **确定性 Node 测试**：`*.test.ts` 不跑在 jsdom 里，禁止碰 DOM；别名由 `web/scripts/register-node-test-aliases.cjs` 在运行时注册。

```bash
# 复制运行：找一个现成的 fake 模式样例
timeout 120 python -m pytest -q -p no:cacheprovider "tests/core/test_agentic_client_api_format.py::test_anthropic_style" 2>/dev/null || \
timeout 120 python -m pytest -q -p no:cacheprovider tests/core/test_agentic_client_api_format.py -k format
```

---

## 5. 运行命令与耗时分布

### 5.1 Python（本机实测，2026-10-04，串行）

常用命令：

```bash
# 全量（等价 CI python-tests 步，tests.yml:286）
timeout 900 python -m pytest -q -p no:cacheprovider tests deeptutor/learning/tests
# 单域 / 单文件 / 单用例 / 关键字
timeout 300 python -m pytest -q -p no:cacheprovider tests/services/rag
timeout 300 python -m pytest -q -p no:cacheprovider tests/api/test_knowledge_router.py
timeout 300 python -m pytest -q -p no:cacheprovider tests/reading -k citation
# Redis 集成（需本地 Redis）
DEEPTUTOR_TEST_REDIS_URL=redis://127.0.0.1:6379/0 timeout 300 python -m pytest -q -p no:cacheprovider tests/runtime/coordination
```

耗时分布（`timeout 900 python -m pytest -q -p no:cacheprovider <dir>` 实测）：

| 目录 | 用例数 | 耗时 | 备注 |
|---|---|---|---|
| tests/services | 4597（+33 skip） | **76s** | 最大头，占全量约 1/3 |
| tests/multi_user | 361 | 48s | 路径隔离重，第二慢 |
| tests/app | 24 | 32s | launcher 子进程测试，用例少但贵 |
| tests/api | 790 | 18s | |
| tests/agents | 410 | 10s | |
| tests/runtime | 206（+4 skip） | 5.0s | skip = redis_integration |
| tests/reading | 415 | 4.7s | |
| deeptutor/learning/tests | 610 | 4.5s | |
| tests/scripts | 52 | 2.7s | |
| tests/tools | 250 | 2.2s | |
| tests/cli | 101 | 2.1s | |
| tests/capabilities | ~400 | 2.0s | |
| tests/video_learning | 99 | 2.0s | |
| tests/architecture | 1 | 1.5s | |
| tests/utils | 140 | 1.4s | |
| tests/core | 266 | 1.3s | |
| tests/knowledge | 165 | 1.3s | |
| tests/book | 180 | 0.8s | |
| 其余 9 个小域 | ~116 | 合计 <2s | logging/config/i18n/visualizers/textbook_struct/plugins/partners/integration |

- 全量 ≈ **9277 用例 / 约 4.5–5 分钟**（串行，本机）。
- 已知环境敏感用例：`tests/agents/chat/test_runtime_context.py` 的 3 个"注入当前日期"用例在本机日期/TZ 下失败（上游 #1732/#1733 正是修这类时区稳定性）；`tests/services/sandbox/test_sandbox.py::test_runner_server_executes_and_truncates_output` 偶发失败。二者均与本次基线代码无关，属本机环境差异。

### 5.2 前端（`web/`，双通道实测）

```bash
cd web
timeout 900 npm run test:unit      # Vitest：*.spec.ts(x)
timeout 900 npm run test:node      # tsc 编译 + node --test：*.test.ts
timeout 900 npm run check:fast     # contracts:check + architecture:check + typecheck + test:node + test:unit + lint + i18n:check
timeout 300 npx vitest run tests/integration/smoke.spec.tsx   # 单文件
timeout 900 npm run audit          # Playwright 审计矩阵：需要先起 web 服务，本地一般不跑，留给 CI
```

| 通道 | 命令（package.json） | 覆盖 | 实测 |
|---|---|---|---|
| Vitest | `test:unit`（package.json:15，配置 vitest.config.mts:13-22） | `tests/**/*.spec.ts(x)`：123 文件 / **518 用例** | ~16s（冷 transform；二次更快） |
| Node test runner | `test:node`（package.json:14，脚本 web/scripts/run-node-tests.mjs） | `tests/**/*.test.ts`：210 文件 / **1253 用例** | ~5s（tsc 编译占大头，runner 本体 1.3s） |

分工原则：**要 DOM/React 交互 → `*.spec.tsx`（Vitest + @testing-library/react）；纯逻辑/协议/契约/配置解析 → `*.test.ts`（Node runner，最快最稳）**。`check:fast`（package.json:19）是本地等价 CI 的最小完整门禁。

---

## 6. CI 里的测试入口

全部在 `.github/workflows/tests.yml`（触发：push/PR 到 main/dev 且路径命中 deeptutor/tests/web 等，:7-32；每日 03:17 cron，:5-6）：

| Job | 位置 | 内容 | 本地等价 |
|---|---|---|---|
| `lint` | tests.yml:35 | `ruff check` + `ruff format --check` + `lint-imports` + `scripts/check_architecture.py`（:53-62） | `ruff check . && ruff format --check .` |
| `web-tests` | tests.yml:64 | `npm ci --legacy-peer-deps`（:81）→ **`npm run check`**（:85，= check:fast + build + perf:check）→ 起 Next 服务跑 Playwright 审计（:87-107） | `npm run check:fast`；audit 留给 CI |
| `multi-worker-web` | tests.yml:109 | 四 worker 浏览器验收，仅当仓库变量配置了 E2E URL 才跑（:111） | — |
| `import-check` | tests.yml:155 | 6 平台矩阵（3.11–3.14 × Linux/macOS/Windows）导入+懒加载+隔离 worker 协议检查（:201-217） | — |
| `python-tests` | tests.yml:221 | 4 版本矩阵 + Redis service 容器（:225-234）；写最小 runtime config 并拷 `tests/fixtures/ci_model_catalog.json`（:272-281）；`pytest -q tests deeptutor/learning/tests`（:286）；`DEEPTUTOR_TEST_REDIS_URL`（:289） | 第 5.1 节全量命令 |
| `test-summary` | tests.yml:291 | 汇总上述各 job 结果并决定最终红绿（:298-312） | — |

> 注意：CI 的 Python 用例跑在有 Redis 的环境；本地没有 Redis 时 `redis_integration` 用例自动 skip（本机全量 run 即 33 skip 的来源）。LightRAG/GraphRAG SDK 只装在 CI 的 3.12 档（:264-270），本地未装时相关用例 skip 而非 fail。

---

## 7. 为某模块新增测试：放哪、怎么写（清单）

**Python 侧**

1. **定位**：被测代码 `deeptutor/services/foo/bar.py` → `tests/services/foo/test_bar.py`（镜像包路径）；router `deeptutor/api/routers/x.py` → `tests/api/test_x_router.py`；`deeptutor/learning/**` → 包内 `deeptutor/learning/tests/`（testpaths 第二项，pyproject.toml:478）。
2. **命名**：文件 `test_*.py`、函数 `test_*`；新标记需先登记 `pyproject.toml:480-485`（`--strict-markers` 会拒绝未登记标记）。
3. **异步**：协程用例加 `@pytest.mark.asyncio`（未开 auto 模式）。
4. **隔离**：凡触碰 `data/`、`multi-user/`、任何持久化根 → `tmp_path` + `monkeypatch.setattr` 重定向（模板：`tests/services/cli_apps/conftest.py:18`）；涉及整个新域就写域级 conftest fixture。根 conftest 防护（conftest.py:48）会把泄漏变成显式 fail。
5. **LLM 相关**：默认信任根 conftest 的固定 fake 配置；只有测"配置解析本身"才加 `@pytest.mark.real_llm_resolver`（conftest.py:243）。
6. **外部依赖**：需要 Redis → `@pytest.mark.redis_integration`；需要其他外部服务 → `@pytest.mark.integration`；可选 SDK 依赖 → 仿 `tests/api/test_knowledge_router.py:22` 的 `pytestmark = pytest.mark.skipif(...)`。
7. **Router 合同**：`_build_app()` + `TestClient`（50 个现成样例在 `tests/api/`），路由断言用 `tests/api/route_introspection.py:10` 的 `iter_effective_route_paths`。
8. **验证命令**（按范围递增，全部限时）：
   ```bash
   timeout 300 python -m pytest -q -p no:cacheprovider tests/services/foo/test_bar.py
   timeout 300 python -m pytest -q -p no:cacheprovider tests/services/foo
   timeout 900 python -m pytest -q -p no:cacheprovider tests deeptutor/learning/tests
   ruff check tests/services/foo && ruff format --check tests/services/foo
   ```

**前端侧**

1. **选通道**：渲染/交互/可访问性 → `web/tests/<feature>.spec.tsx`（Vitest）；纯逻辑、协议解析、store、契约 → `web/tests/<feature>.test.ts`（node --test）。
2. **导入**：`@` 别名指向 `web/`（vitest.config.mts:9-11）；DOM 断言直接用 `@testing-library/jest-dom/vitest` matchers（setup 已加载）。
3. **mock**：`vi.mock` 置于 import 之前；无需手动清（clearMocks/restoreMocks + afterEach 已兜底）；`localStorage` 不要自己 stub，setup 已注入 MemoryStorage。
4. **协议/契约变更**：跑 `npm run contracts:generate` 更新生成契约，`contracts:check` 会在 CI 校验（package.json:17-18）；架构依赖变化看 `npm run architecture:check`（depcruise，package.json:27），守卫类测试（如 `web/tests/no-page-module-imports.test.ts`）也会拦。
5. **验证命令**：
   ```bash
   cd web
   timeout 300 npx vitest run tests/<你的>.spec.tsx
   timeout 900 npm run test:node
   timeout 900 npm run check:fast
   ```
6. **不要本地起服务跑 Playwright**：`*.audit.ts` 与 e2e 属 CI job（tests.yml:87-107），本地仅在明确需要时按 Playwright 项目单跑。

---

## 8. 备注

- `CONTRIBUTING.md` 的测试相关内容集中在"Common Commands"（CONTRIBUTING.md:139-148，pre-commit/hygiene）与"Generated Files and Worktrees"（:150-172，每个 feature 一个 worktree、保持主 checkout 干净）。`DEVELOPMENT_WORKFLOW.md` **不在 origin/main 中**（仅本机工作区有未提交副本），其"Verification gates"（最小门禁 → 提交前更大门禁）思想已折入第 5、7 节，引用时请注意它不是已提交文档。
- 本文所有数字为 2026-10-04 单机实测，用于量级参考；CI（ubuntu、4 个 Python 版本、含 Redis）耗时会不同。
