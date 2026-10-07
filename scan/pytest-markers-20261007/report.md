# pytest marker 注册与使用一致性清点（AGEN-1105）

- 输入：`origin/main` @ `f07029cfc`（release v1.6.13），只读 worktree 扫描，未改任何代码。
- 方法：纯 stdlib AST 静态解析（`scripts/scan_markers.py`），覆盖 `[tool.pytest.ini_options].testpaths` 全部 775 个 `.py`（tests/ + deeptutor/learning/tests/）。同输入二次运行输出 SHA256 一致（`9ea74ad6…b9430`），可复跑、结果确定。
- 去重声明：不含运行时抖动（scan-flaky-tests）、隔离（scan-test-isolation）、conftest 重复（scan-conftest-dup）轴。

## 1. 注册清单（pyproject.toml `[tool.pytest.ini_options]`）

| marker | 注册位置 | 注册描述摘要 | 使用点 | 结论 |
|---|---|---|---|---|
| `asyncio` | `pyproject.toml:481` | pytest-asyncio 异步测试 | 3810 处 / 45 个目录 | 已用 |
| `integration` | `pyproject.toml:482` | 需显式配置外部服务 | 3 处 | 已用 |
| `redis_integration` | `pyproject.toml:483` | 需 `DEEPTUTOR_TEST_REDIS_URL` | 2 处 | 已用 |
| `real_llm_resolver` | `pyproject.toml:484` | 保留真实 LLM resolver | 2 处 | 已用 |

`addopts` 含 `--strict-markers`（`pyproject.toml:488`）：任何未注册 marker 在收集期即报错。内置 marker（skip/skipif/xfail/parametrize/usefixtures/filterwarnings/tryfirst/trylast）与插件 marker（pytest-asyncio 的 `asyncio`，唯一声明的 pytest 插件，`requirements/dev.txt:13`）免注册。无 conftest 动态注册（`addinivalue_line` / `add_marker` 全仓 0 命中），marker 注册只有 pyproject 一处，单一事实源。

## 2. 三类分级结果

### 2.1 未注册（使用但未注册）— 0 处
实测与 `--strict-markers` 的保证一致。

### 2.2 已注册未使用 — 0 处
4 个自定义 marker 全部有使用点。

### 2.3 无理由 skip / xfail — 装饰器 0 处 / 运行时 0 处
- 装饰器形态：`@pytest.mark.skipif` 33 处（含 10 处模块级 `pytestmark`：9 处仅 skipif + 1 处与 integration/real_llm_resolver 组合）全部带 `reason=`；`@pytest.mark.skip` 与 `@pytest.mark.xfail` 全仓 0 处。
- 运行时形态：非 importorskip 的 `pytest.skip(…)` 24 处全部带消息（如 `tests/tools/test_rag_tool.py:60`、`tests/runtime/coordination/test_redis_integration.py:18`）；`pytest.xfail(…)` 全仓 0 处。
- 变体 `pytest.importorskip(…)` 无 `reason` 参数 136 处（属 pytest 惯例"模块名即原因"，不计缺陷），分布：tests/services/rag 52、tests/services/partners 30、tests/api 25、tests/reading 8、tests/services/parsing 5、tests/utils 4、tests/services/cron 3、tests/book 2、tests/cli 2、tests/services/llm 2、tests/logging 1、tests/multi_user 1、tests/runtime 1。
- 备注：`pytest.fail(…)` 41 处不属于 skip/xfail 轴，未展开。

## 3. 自定义 marker 使用点（path:line 全量）

- `integration`：
  - `tests/integration/test_prompt_cache.py:28`（模块 `pytestmark`）
  - `tests/services/rag/test_pipeline_integration.py:414`（装饰器，`TestPipelineIntegration.test_pipeline`）
- `redis_integration`：
  - `tests/runtime/coordination/test_redis_integration.py:11`
  - `tests/runtime/coordination/test_redis_stress.py:12`
- `real_llm_resolver`：
  - `tests/integration/test_prompt_cache.py:29`
  - `tests/services/test_task_model_call_sites.py:23`
- `asyncio`：3810 处，集中在 tests/services/partners 466、tests/services 402、tests/services/llm 256、deeptutor/learning/tests 240、tests/api 204、tests/core 196（机读清单见 `data/usage.json` 的 `marker_usage_points.asyncio`）。

## 4. marker 组合约定

| 组合 | 数量 | 约定说明 |
|---|---|---|
| asyncio × parametrize | 98 | 主流异步参数化写法 |
| parametrize × skipif | 12 | 参数级条件跳过 |
| integration × real_llm_resolver × skipif | 7 | 真实 API 三件套，`DEEPTUTOR_CACHE_E2E=1` 门禁（`tests/integration/test_prompt_cache.py:27-32`） |
| asyncio × redis_integration | 5 | `DEEPTUTOR_TEST_REDIS_URL` 门禁（`test_redis_integration.py:11,16-18`；`test_redis_stress.py:12,22-24`） |
| asyncio × skipif | 5 | 条件跳过的异步测试 |
| asyncio × integration、asyncio × real_llm_resolver | 各 1 | 见 §3 使用点 |
| asyncio × usefixtures | 1 | `tests/services/config/test_llm_probe_config.py:115` |

模块级 `pytestmark` 共 19 处：10 处仅 `skipif`（8 个 tests/api 路由文件统一的 `skipif(FastAPI is None, reason="fastapi not installed")`，如 `tests/api/test_capabilities_router.py:20-22`；加 `tests/services/rag/test_lightrag_settings_wiring.py:13`）；6 处纯 asyncio；2 处 asyncio × redis_integration（§3 redis 两个文件）；1 处 integration × real_llm_resolver × skipif（`tests/integration/test_prompt_cache.py:27-32`）；1 处 `real_llm_resolver`（`tests/services/test_task_model_call_sites.py:23`）。

门禁方式：CI（`.github/workflows/tests.yml:286` `pytest -q tests deeptutor/learning/tests`）不做 `-m` 选择；集成类一律"marker + 环境变量门禁"（模块级 skipif 或测试体内带消息的 `pytest.skip`），marker 本身不用于 CI 选择，仅作文档化语义标签。

## 5. 可拆修复卡条目（均为约定统一类，无硬缺陷）

1. [约定统一 · 低] `tests/services/rag/test_pipeline_integration.py:423` 的 `RAG_INTEGRATION_TESTS` 门禁写在测试体内（运行时 `pytest.skip`），与 `tests/integration/test_prompt_cache.py:27-31` 的模块级 `skipif` 风格并存；可统一为 skipif 装饰器，单文件改动。
2. [文档澄清 · 低] `tests/services/test_task_model_call_sites.py:23` 打 `real_llm_resolver` 但无环境变量门禁——与注册描述一致（测试内部 fake LLM 调用、仅保留真实 resolver，全文件走 monkeypatch），建议在 `pyproject.toml:484` 描述中补一句"不要求真实 API key"，避免误读为需要外部服务。
3. [约定记录 · 低] 136 处 `pytest.importorskip` 无 `reason`（`reason` 形参需 pytest>=8.2，当前 floor 为 `pytest>=7.0.0`，`requirements/dev.txt:12`）；不动代码的话，在贡献文档记录"模块名即原因"约定即可。
4. [无需修复] `asyncio` 同时在 `pyproject.toml:481` 注册且由 pytest-asyncio 提供——`--strict-markers` 兼容性所需，应保留。

## 6. 复跑

```bash
python3 scan/pytest-markers-20261007/scripts/scan_markers.py <repo-root> <out.json>
```

机读结果：`data/usage.json`（含全部使用点 path:line、无理由清单、组合矩阵）。`SHA256SUMS` 覆盖本目录全部文件。
