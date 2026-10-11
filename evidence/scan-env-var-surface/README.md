# scan: 环境变量读取面清点（os.environ 调用点 × settings 映射）

- 基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）
- 分支：`dt-agen1578-scan-env-var-surface`（只读扫描，零代码改动；本目录为唯一产物）
- 明细：`env-read-inventory.tsv`（每行一个读取点；`(动态名)`/`(写入侧)` 行为特殊行）

## 1. 范围与方法

- 静态 grep：`os.environ[...]`、`os.environ.get`、`os.environ.setdefault`、`os.getenv`、`environ.copy()`，覆盖 `deeptutor/`、`deeptutor_cli/`、`scripts/`、`packaging/`、`deeptutor_web/`、`examples/`（后两处零命中）。
- 生产代码读取点：99 处（55 个文件）；`tests/` 另有 31 处，均为测试夹具，不参与三态分类。
- 间接名（模块常量、registry 字段、配置文件字段）全部追到字面名后归类；无 `from os import environ` 别名导入、无 `environb`/`putenv`。
- `web/`、`deeptutor_web/` 的 TS `process.env`（20 处）为浏览器/Next 侧独立面，不在本卡 Python `os.environ` 范围。

## 2. settings 体系边界（判定口径）

"入 settings 体系" = 满足以下任一：

1. `deeptutor/services/config/runtime_settings.py` 的 process-override 读侧（`_process_env_value`，行 842–1211）或 `render_environment` 导出侧（行 704–755）；
2. `deeptutor/config/settings.py` pydantic BaseSettings（`env_prefix="LLM_"` + `__` 嵌套）；
3. `deeptutor_cli/init_wizard.py` `env_keys` 声明（env→settings 文件引导，行 136–227，读取点 566/598）；
4. `deeptutor/services/provider_registry.py` `env_key` 字段（由 `openai_compat_provider.py:258–266` `_setup_env` 注入，litellm 库内读取）。

三态结论：
- **纳管**：命中上述任一通道；
- **未纳管**：功能代码直读、无 settings 通道（含 OS 标准变量与进程协议变量，均如实标注）；
- **疑似弃用**：遗留别名——存在主名且仅作兼容回退，建议合并或移除。

## 3. 总量与三态分布

| 维度 | 数量 |
|---|---|
| 字面调用点（grep 命中，含透传） | 99 |
| 展开后具名读取点（TSV 数据行） | 182 |
| 唯一变量名 | 170 |
| 动态名机制（`api_key_env` / 技能 `requires.env`） | 2 |
| 读取点=纳管 | 107（settings 读侧 52 + pydantic 3 + env_keys 17 + registry 30 + 与之同名的直读旁路 5） |
| 读取点=未纳管 | 69（含 OS 标准变量、进程协议变量、写侧专属 6） |
| 读取点=疑似弃用（遗留别名） | 6 |

注：99 个字面调用点中，settings 读侧的 `_process_env_value` 机制在字面层只有一处调用，展开为 52 个具名变量后计入 TSV；同一变量多处读取按读取点分行（如 `BACKEND_PORT`）。

## 4. 命名漂移清单（同概念多名字）

| 概念 | 主名 | 别名/旧名 | 位置 |
|---|---|---|---|
| RAG 检索档位 | `DEEPTUTOR_RAG_RETRIEVAL_PROFILE` | `RAG_RETRIEVAL_PROFILE` | runtime_settings.py:978–979；llamaindex/config.py:95 |
| 后端 worker 数 | `DEEPTUTOR_BACKEND_WORKERS`（读侧首选） | `BACKEND_WORKERS`（导出侧仍产旧名） | runtime_settings.py:863–864 vs :717 |
| 外部 API 基址 | `NEXT_PUBLIC_API_BASE_EXTERNAL` | `PUBLIC_API_BASE`（仅读侧遗留） | runtime_settings.py:848 vs :850 |
| moderation key | `OPENAI_API_KEY` | `DEEPTUTOR_OPENAI_API_KEY` | source_filter.py:537 |
| Web Risk key | `GOOGLE_WEB_RISK_API_KEY` | `WEB_RISK_API_KEY` | source_filter.py:546 |
| 容器 UID/GID | `PUID`/`PGID` | `DEEPTUTOR_PUID`/`DEEPTUTOR_PGID` | data_volume.py:149–150 |
| UI 语言 | `UI_LANGUAGE` | `LANGUAGE`（POSIX 回退） | launch_settings.py:94–95 |
| hub token | `DEEPTUTOR_HUB_TOKEN` | `EDUHUB_TOKEN` | deeptutor_cli/skill.py:34–35 |
| 火山 key | `ARK_API_KEY` | `DOUBAO_API_KEY` | init_wizard.py:199 |
| 智谱 key | `ZHIPU_API_KEY` | `ZHIPUAI_API_KEY`（wizard 别名 + registry env_extras 写入同名） | init_wizard.py:213；provider_registry.py:478 |
| 千帆 key | `QIANFAN_API_KEY` | `BAIDU_API_KEY` | init_wizard.py:220 |
| 阿里 IQS key | `ALIYUN_IQS_API_KEY` | `IQS_API_KEY` | init_wizard.py:227 |
| 搜索 key 兜底 | （各 provider 主名） | `SEARCH_API_KEY`（全部 13 个搜索 provider 共享回退） | init_wizard.py:147–227 |
| GROQ key | registry 声明 | `partners/transcription.py:18` 旁路直读同名字符串（隐式耦合） | — |

## 5. 未纳管清单（建议评估是否收编）

按风险/价值排序：

1. **行为开关类**（用户可感知，最适合收编 settings）：`RAG_PROVIDER`、`DEEPTUTOR_CODEBUDDY_BACKEND`、`CODEBUDDY_BASE_URL`、`CODEBUDDY_INTERNET_ENVIRONMENT`、`LLM_TREAT_PRIVATE_AS_LOCAL`、`DEEPTUTOR_ISOLATED_WORKERS`、`AUTH_TRUSTED_FRONTEND_PROXY_IPS`、`DEEPTUTOR_SANDBOX_MAX_CONCURRENT`、`DEEPTUTOR_SANDBOX_MAX_PER_MINUTE`、`DEEPTUTOR_CLI_APP_INSTALL_TIMEOUT_S`、`LEARNING_DEBUG`、`DEEPTUTOR_DEV_RELOAD`。
2. **部署/编排类**（compose/Dockerfile 引用，读侧与部署面强耦合）：`DEEPTUTOR_WORKSPACE_ROOT`、`DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS`、`DEEPTUTOR_SANDBOX_RUNNER_URL`、`DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS`、`RUNNER_PORT`、`DEEPTUTOR_PUBLIC_URL`（两处一致）。
3. **端点覆盖组**：`DEEPTUTOR_GITHUB_COPILOT_CLIENT_ID`、`DEEPTUTOR_GITHUB_DEVICE_CODE_URL`、`DEEPTUTOR_GITHUB_ACCESS_TOKEN_URL`、`DEEPTUTOR_GITHUB_USER_URL`、`DEEPTUTOR_COPILOT_TOKEN_URL`、`DEEPTUTOR_COPILOT_BASE_URL`、`DEEPTUTOR_CODEBUDDY_AUTH_FILE`。
4. **凭据类直读**：`GITHUB_TOKEN`、`GROQ_API_KEY`（transcription 旁路）、`DEEPTUTOR_HERMES_REMOTE_API_KEY`（默认名，配置可改）、`DISCORD_BOT_TOKEN`（运维脚本）、`DEEPTUTOR_HUB_TOKEN`/`EDUHUB_TOKEN`（CLI）。
5. **OS/工具标准变量**（不建议收编，仅登记）：`PATH`、`LANG`、`LOCALAPPDATA`、`XDG_DATA_HOME`、`SSL_CERT_FILE`、`SSL_CERT_DIR`、`HF_HOME`、`MODELSCOPE_CACHE`、`DOCLING_CACHE_DIR`、`DOCLING_ARTIFACTS_PATH`、`CODEX_HOME`、`DSH_HOME`。
6. **进程协议/平台探测变量**（有意绕过 settings，仅登记）：`DEEPTUTOR_HOME`、`DEEPTUTOR_MODE`、`DEEPTUTOR_DETACHED_TOKEN`、`DEEPTUTOR_DETACHED_WORKER`、`DEEPTUTOR_SUPERVISOR_PID`、`DEEPTUTOR_LAUNCHER_PID`、`INVOCATION_ID`、`ENVIRONMENT`、`DEEPTUTOR_CONTAINER`、`DEEPTUTOR_BACKEND_READY_TIMEOUT`、`DEEPTUTOR_FRONTEND_READY_TIMEOUT`。
7. **动态名读取**：`setup_config.py:83`（配置文件 `api_key_env` 字段，属 settings 体系）、`skill/service.py:387`（技能清单 `requires.env`，未纳管）。

## 6. 疑似弃用清单（遗留别名，5 个）

| 变量 | 主名 | 位置 |
|---|---|---|
| `PUBLIC_API_BASE` | `NEXT_PUBLIC_API_BASE_EXTERNAL` | runtime_settings.py:850 |
| `RAG_RETRIEVAL_PROFILE` | `DEEPTUTOR_RAG_RETRIEVAL_PROFILE` | runtime_settings.py:979；llamaindex/config.py:95 |
| `DEEPTUTOR_OPENAI_API_KEY` | `OPENAI_API_KEY` | source_filter.py:537 |
| `WEB_RISK_API_KEY` | `GOOGLE_WEB_RISK_API_KEY` | source_filter.py:546 |
| `EDUHUB_TOKEN` | `DEEPTUTOR_HUB_TOKEN` | deeptutor_cli/skill.py:35 |

注：wizard 内 `DOUBAO/ZHIPUAI/BAIDU/IQS/SEARCH_API_KEY` 为 env_keys 显式声明的兼容别名，归"纳管+漂移"，不计疑似弃用。

## 7. 全环境透传与白名单（非单变量读取，仅登记）

- 全量透传：launcher.py:833/1229/1518、subagent/process.py:74、subagent/opencode_server.py:103、docling/local_worker.py:49、codebuddy_provider.py:826、scripts/docker_compose.py:114。
- 白名单过滤：`("PATH","HOME","LANG","LC_ALL","TMPDIR","SSL_CERT_FILE","SSL_CERT_DIR")` — plugins/lifecycle.py:380、plugins/runtime.py:400、cli_apps/installer.py:243（lifecycle/runtime 额外放行代理五项）；`_SAFE_ENV_KEYS = ("PATH","PATHEXT","HOME","LANG","LC_ALL","TMPDIR","SYSTEMROOT")` — sandbox/backends.py:291。

## 8. 去重边界（与其他卡不重复）

- **scan-docs-user-drift**：用户文档面的 env 变量记载/漂移归该卡；本卡只认代码读取点。
- **scan-lightrag-params**：`LIGHTRAG_*`/`GRAPHRAG_*` 由 lightrag 库内消费，仓内 Python 代码零直读（已验证），不在此展开。
- TS 侧 `process.env`（web/ 20 处）不在本卡 Python 范围。

## 9. 复核命令

```bash
# 基线
git -C <checkout> rev-parse origin/main   # 6cf793bd868ba5ecbe64722936d4be8fab5a01df

# 全部生产读取点（本卡主扫描，应得 99 行）
grep -rn "os\.environ\[\|os\.environ\.get\|os\.environ\.setdefault\|os\.getenv\|environ\.copy()" \
  --include="*.py" deeptutor/ deeptutor_cli/ scripts/ packaging/ | wc -l

# settings 读侧/导出侧清单
grep -n "_process_env_value(\"" deeptutor/services/config/runtime_settings.py
sed -n '704,755p' deeptutor/services/config/runtime_settings.py

# env_keys 声明与读取
grep -n "env_keys" deeptutor_cli/init_wizard.py

# provider registry env_key 声明
grep -n 'env_key="' deeptutor/services/provider_registry.py | sed -E 's/.*env_key="([^"]*)".*/\1/' | sort -u

# 间接常量名解析（抽查）
grep -rn "ENV = \"DEEPTUTOR_" deeptutor/ --include="*.py" | grep -v os.environ

# 测试面计数（不参与分类）
grep -rn "os\.environ\|os\.getenv" --include="*.py" tests/ | wc -l   # 31

# 完整性校验
sha256sum -c SHA256SUMS
```

## 10. 局限

- 三态判定为静态推断：litellm 等三方库对 registry `env_key` 的库内读取不在仓内，无法逐行引用。
- `settings.py` 的 pydantic 读取发生在 import 期，无 `os.environ` 直读行号，以 settings.py:43–50 为锚点。
- 动态名（`api_key_env`、技能清单 `requires.env`）只登记机制，无法枚举全部实例。
