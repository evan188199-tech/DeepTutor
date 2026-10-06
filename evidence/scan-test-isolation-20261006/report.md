# 测试隔离审计（tmp / env / 全局态残留清点）

- 分支：`scan/test-isolation-20261006`（基于 `origin/main` @ `f07029cfc`，release v1.6.13）
- 日期：2026-10-06
- 性质：只读静态扫描，未修改任何产品代码，未运行测试。

## 1. 口径

- 对象：仓库内全部 Python 测试文件（文件名 `test_*.py` / `*_test.py`，含包内 `deeptutor/**/tests/`；排除 `deeptutor/services/config/test_runner.py` 这类包内非测试模块与 `tests/services/llm/test_llm_live.py` 手工连通性脚本）。
- 方法：`scripts/scan_isolation.py` 基于 AST 的静态检测（非正则），8 个检测器：
  - `ENV_MUTATION`：绕过 monkeypatch/patch.dict 直接写 `os.environ`（含 `pop/setdefault/update/clear/putenv`），模块级写入直接判高危；
  - `TMP_UNMANAGED`：`tempfile.mkdtemp` / `NamedTemporaryFile(delete=False)` 在本文件内无可见 `rmtree`/`addCleanup` 清理路径；
  - `TMP_NO_CTX`：`TemporaryDirectory` 未用 `with` 且无 `.cleanup()`；
  - `TMP_LITERAL_WRITE`：对字面量 `/tmp/...` 路径的真实写盘形态（`open(..., "w")`、`Path(...).write_*/touch/mkdir`、以及把共享 tmp 路径作为 `output_dir`/`kb_base_dir` 等输出参数传入生产代码）；
  - `CWD_WRITE`：字面量相对路径写盘（污染 pytest cwd / 工作区）；
  - `GLOBAL_MUTATION`：测试代码对导入模块属性、单例惯用属性（`_instance/_cache/_registry` 等）的直接赋值，或 `setattr(<module>, ...)`、`global` 语句；同一函数内有 `finally`+`original` 还原时降级为 medium 并标 `mitigation=finally-restore`；
  - `MONKEYPATCH_UNDO`：`monkeypatch.undo()`（会连带撤销 fixture 安装的补丁）；
  - `FIXTURE_SCOPE_RISK`：`scope="session"/"module"` fixture 且触碰 env/临时目录/可变容器/无 teardown。
- 复核：全部 35 条机扫结果逐条人工复核，报告"复核"列给出 确认 / 已缓解 / 误报 三态结论；严重级别以复核后为准。
- 数据与路径约定见 `data/coverage.json`（路径相对扫描 worktree 根）。

## 2. 覆盖统计

| 指标 | 数值 |
| --- | --- |
| 仓库 Python 文件 | 1818 |
| 扫描的测试文件 | 727 |
| 测试代码行数 | 182,959 |
| 机扫发现 | 35（17 个文件） |
| 复核后确认真问题 | 7 条行级发现（4 个文件）+ 1 条 harness 外溢提示 |
| 跳过文件 | `deeptutor/services/config/test_runner.py`（生产模块）、`tests/services/llm/test_llm_live.py`（手工脚本） |

机扫分型计数（复核前）：GLOBAL_MUTATION 27、TMP_LITERAL_WRITE 4、TMP_UNMANAGED 2、MONKEYPATCH_UNDO 1、FIXTURE_SCOPE_RISK 1；ENV_MUTATION / TMP_NO_CTX / CWD_WRITE 均为 0。

卫生面信号（好实践的规模）：`monkeypatch.setattr` 3112 处、`monkeypatch.setenv` 132 处、`tmp_path` 相关行 4974 行、`cache_clear()` 14 处。根 `tests/conftest.py` 已有 autouse 守卫 `_guard_real_owner_secrets` 防止测试写入真实账户树。整体隔离纪律较好，env 轴零未缓解发现。

## 3. Top 问题（补测优先级）

1. **`tests/api/test_co_writer.py:15`** — 模块导入期把 `deeptutor.services.config.load_config_with_main` 永久替换为返回空配置的 stub，**从不还原**；pytest 收集期即导入，stub 对整个测试会话全局生效，任何后续依赖真实配置加载的测试都被污染。建议：改用 `monkeypatch.setattr(_dt_config, "load_config_with_main", stub)` 于 fixture 中（auto-undo）。
2. **`tests/services/rag/test_llamaindex_faiss_vector_store.py:63`** — autouse fixture 设置 llama_index 全局 `Settings.embed_model = _FakeEmbed()`，**从不还原**；本模块跑完后全局嵌入模型保持 fake，后续任何使用 `Settings` 的测试（如嵌入角色相关）拿到假向量。建议：fixture 内先存 `original = Settings.embed_model`，yield 后还原（或 monkeypatch.setattr）。
3. **`tests/core/test_prompt_manager.py:16-17、172-173`** — 两个 `setup_method` 直接 `PromptManager._instance = None; PromptManager._cache = {}`，只重置不保存还原；单例被驱逐后由后续测试按各自环境重建，产生顺序耦合（若其他测试在 monkeypatch 环境下填充缓存，跨文件可见）。建议：改为 fixture 保存/还原，或暴露 `cache_clear()` 式的显式重置 API。
4. **`tests/services/llm/test_config_module.py:16`** — `_reset_config_cache()` 置 `config_module._LLM_CONFIG_CACHE = None`；各测试开头重置，但用 fake resolver 跑过的测试结束后**缓存里留着假配置**（`deeptutor/services/llm/config.py:251` 命中缓存即返回），会话内其他未重置的调用方可能读到 `sk-or-test` 假密钥配置。建议：测试用 fixture try/finally 收尾时再重置一次，或让 `get_llm_config` 缓存可注入/可清除。

harness 外溢提示：`tests/services/rag/test_pipeline_integration.py` 是 `python -m`/`asyncio` 手工 harness（无 pytest 可收集的模块级 test 函数），自带 finally teardown（:298-301），pytest 运行不会触发其 `mkdtemp`；但它与正式测试同目录同名前缀，建议迁出 `tests/` 或改名，避免误收集与误读。

## 4. 分型清单（全部 35 条，含复核结论）

严重度列 = 机扫级别；复核列：✅=确认（建议修），🟡=已缓解（建议标准化为 monkeypatch），❌=误报/受控。

### 4.1 GLOBAL_MUTATION — 未缓解（确认）

| 位置 | 摘要 | 严重度 | 复核 | 建议 |
| --- | --- | --- | --- | --- |
| `tests/api/test_co_writer.py:15` | 导入期永久 stub `load_config_with_main`，会话级污染 | high | ✅ | fixture + monkeypatch.setattr（Top-1） |
| `tests/services/rag/test_llamaindex_faiss_vector_store.py:63` | fixture 改 llama_index 全局 `Settings.embed_model` 不还原 | high | ✅ | fixture 保存/还原（Top-2） |
| `tests/core/test_prompt_manager.py:16` | `PromptManager._instance = None` 无保存还原 | high | ✅ | fixture 化重置（Top-3） |
| `tests/core/test_prompt_manager.py:17` | `PromptManager._cache = {}` 无保存还原 | high | ✅ | 同上 |
| `tests/core/test_prompt_manager.py:172` | 同 :16（TestPromptManagerLanguages） | high | ✅ | 同上 |
| `tests/core/test_prompt_manager.py:173` | 同 :17（TestPromptManagerLanguages） | high | ✅ | 同上 |
| `tests/services/llm/test_config_module.py:16` | `_LLM_CONFIG_CACHE = None`，假配置驻留缓存 | high | ✅ | 收尾再重置（Top-4） |

### 4.2 GLOBAL_MUTATION — 已缓解（建议标准化为 monkeypatch）

| 位置 | 摘要 | 严重度 | 复核 | 建议 |
| --- | --- | --- | --- | --- |
| `tests/api/test_space_mcp.py:383` | `space_mcp.probe_server` 换 fake | medium | 🟡 | try/finally 已还原；改 monkeypatch.setattr |
| `tests/api/test_space_mcp.py:393` | 同上（还原行） | medium | 🟡 | 同上 |
| `tests/logging/test_task_log_stream.py:82,93` | `KnowledgeTaskStreamManager._instance` + logger 四元组 | medium | 🟡 | finally 已还原；建议 monkeypatch fixture 复用 |
| `tests/logging/test_task_log_stream.py:114,125` | 同上 | medium | 🟡 | 同上 |
| `tests/logging/test_task_log_stream.py:148,162` | 同上 | medium | 🟡 | 同上 |
| `tests/logging/test_task_log_stream.py:183,195` | 同上 | medium | 🟡 | 同上 |
| `tests/services/cli_apps/test_provider.py:239,243` | `provider.run_app` 换 fake | medium | 🟡 | finally 已还原；改 monkeypatch |
| `tests/utils/test_circuit_breaker.py:94,99` | `circuit_breaker.circuit_breaker` 换实例 | medium | 🟡 | finally 已还原；改 monkeypatch |
| `tests/utils/test_circuit_breaker.py:106,113` | 同上 | medium | 🟡 | 同上 |
| `tests/utils/test_circuit_breaker.py:120,127` | 同上 | medium | 🟡 | 同上 |
| `tests/services/partners/test_lark_keep_alive.py:20,25` | `lark_http._INSTALLED` / SDK transport（autouse fixture `_restore_transport` 保存/yield/还原） | high→实际已缓解 | 🟡 | 模式正确；机扫未识别 fixture 还原，人工确认无残留 |

### 4.3 TMP_UNMANAGED / TMP_LITERAL_WRITE / 其他

| 位置 | 摘要 | 严重度 | 复核 | 建议 |
| --- | --- | --- | --- | --- |
| `tests/services/rag/test_pipeline_integration.py:91` | `mkdtemp` 于 harness `setup` | medium | ❌ | 非 pytest 收集的独立 harness，`run_all_tests` 内 finally teardown（:298-301）；建议迁出 `tests/` 防误收集 |
| `tests/services/skill/test_skill_hub.py:413` | `_FakeProvider.fetch` 内 `mkdtemp` | medium | ❌ | 目录经 `FetchedSkill.cleanup_dir` 协议由生产代码清理，测试断言 `last_cleanup` 已删（:445） |
| `tests/core/test_builtin_tools.py:450` | `output_dir="/tmp/out"` 传入工具 | medium | ❌ | `web_search` 被 fake 拦截仅捕获参数，无实际写盘；仍建议改 `tmp_path` 防未来实现变化 |
| `tests/services/rag/eval/test_eval_runner.py:69` | `kb_base_dir="/tmp/kbs"` 传入评估器 | medium | ❌ | `search_fn` 为 recorder，仅转发参数；同上建议 |
| `tests/services/rag/test_weknora_pipeline.py:240` | `get_pipeline("weknora", kb_base_dir="/tmp/kbs")` | medium | ❌ | 构造器仅存字段不写盘（`pipelines/weknora/pipeline.py:20-21`）；同上建议 |
| `tests/tools/test_rag_tool.py:75` | `get_pipeline("lightrag", kb_base_dir="/tmp/kb-test")` | medium | ❌ | 构造器仅存字段（`pipelines/lightrag/pipeline.py:99-101`）；同上建议 |
| `deeptutor/learning/tests/test_v2_migration.py:213` | `monkeypatch.undo()` | low | 🟡 | 本文件无 autouse fixture 冲突，undo 只回退本测试的 setattr；建议显式 try/finally 更稳 |

### 4.4 FIXTURE_SCOPE_RISK

| 位置 | 摘要 | 严重度 | 复核 | 建议 |
| --- | --- | --- | --- | --- |
| `tests/utils/test_document_images.py:42` | module 级 fixture `png` | medium | ❌ | 返回不可变 `bytes`，无共享可变状态；保持现状即可 |

## 5. 补测优先级建议

1. P0：Top-1（co_writer 导入期 stub）——影响面最大（全会话），修复成本最低。
2. P1：Top-2 / Top-3 / Top-4（全局单例与缓存驻留）——都是"跑完即泄漏"型，补 fixture 还原 + 各加一条"顺序无关"回归（如单独 `-p no:randomly` 双顺序跑或反转文件顺序冒烟）。
3. P2：4.2 节已缓解的 20 处——统一迁到 monkeypatch.setattr，可顺带删除样板 save/finally 代码。
4. P3：`/tmp` 字面量参数统一换 `tmp_path`，防生产实现未来开始真实写盘。

## 6. 复现与哈希自证

```bash
# 数据复跑（确定性输出，无时间戳；两次运行逐字节一致）
sh evidence/scan-test-isolation-20261006/scripts/verify_rerun.sh
# 预期输出：
# MATCH  findings.json
# MATCH  coverage.json

# 机器结果
cat evidence/scan-test-isolation-20261006/data/coverage.json
cat evidence/scan-test-isolation-20261006/data/findings.json
```

开发期验证：连续两次 `verify_rerun.sh` 均 MATCH。SHA256 见同目录 `SHA256SUMS`（覆盖 report、data、scripts）。

## 7. 边界与去重

- 不覆盖：时序/sleep 类 flaky（归 scan-flaky-tests）、悬空 asyncio 任务（归 scan-async-tasks）。本卡只做 tmp/env/全局态/共享 fixture 四轴。
- 仅静态分析：不做动态验证、不运行测试、不改产品代码；JS/web 侧测试不在本轮口径内。
- 安全说明：本轮未发现涉及密钥泄露或注入利用细节的问题，无需附件。
