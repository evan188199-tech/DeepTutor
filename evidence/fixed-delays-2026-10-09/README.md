# src 侧固定延迟 / 忙等清点与分级（fixed delays & busy-wait inventory)

- 基线：HKUDS/DeepTutor `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14，2026-10-09 fetch）
- 性质：只读扫描。本目录仅新增 evidence 文件，未改动任何产品代码。
- 背景：上游 issue #1903（Local MinerU indexing can hang after CLI termination on Windows，open、无关联 PR）。本卡不修码，只提供其相关时序常量的清点底表（见 §5）。

## 1. 范围与方法

- 扫描根：`deeptutor/`、`deeptutor_cli/`、`scripts/`（Python 产品源码）。
- 排除：任何 `tests/` 目录（含包内 tests，如 `deeptutor/learning/tests/`）、`web/`（TS 侧另有轴）、`assets/`、`docs/`、`examples/`。
- 方法：AST 遍历（`ast.parse` + 自定义 Visitor），非正则，避免把 `timeout = 30` 这类赋值误报为调用超时。常量解析支持：模块级常量、类属性、`__init__` 参数默认值（含 `max(lit, float(param))` 包装）、常量元组下标、字面量四则运算。
- 复算：`python3 scan_fixed_delays.py <repo-root> fixed_delays.csv`（在仓库根目录运行，输出应与本 CSV 完全一致）。

### 计入的类别（kind）

| kind | 含义 |
|---|---|
| `sleep-fixed` | `time.sleep(...)` / `asyncio.sleep(...)` 固定延迟（含常量解析出的值；值列空的为参数化/动态值） |
| `sleep-yield` | `asyncio.sleep(0)` 协作式让出，非真实延迟 |
| `timeout-net` | 网络/操作调用上的硬编码 timeout（httpx/requests/aiohttp/socket/smtp 及业务操作等） |
| `timeout-wait` | 同步原语上的硬编码 timeout（`asyncio.wait_for/wait`、`Event.wait`、`Thread.join`、`Future.result`、队列 get 等） |
| `timeout-lock` | sqlite `connect(timeout=)` 与 `PRAGMA busy_timeout`（锁等待） |

`in_while=True` 表示该调用位于 `while` 循环内，即轮询/忙等上下文（本卡"忙等"的判定口径：固定间隔轮询循环，重点看无上限或上限很松的）。

### 排除与去重（对应三张兄弟卡）

| 排除项 | 计数 | 归属 |
|---|---|---|
| subprocess 轴（`subprocess.run(timeout=)`、`process.wait/communicate(timeout=)`） | 16 条 | scan-subprocess-timeouts |
| tests 侧时序（含包内 tests） | 已从扫描根排除 | scan-flaky-tests |
| async 内阻塞调用轴（本表 0 条 `time.sleep` 落在 async 函数内） | 0 条 | scan-async-blocking |
| 动态（非常量）timeout kwarg，如 `timeout=self._timeout`、`timeout=config.x` | 125 处跳过（不属"固定值表"，仅记录计数） | — |

## 2. 阻塞面分级口径（可复算）

`surface` 由 `scan_fixed_delays.py` 内的有序路径规则表（`SURFACE_RULES`）按"最具体前缀命中"得出，每行 CSV 的 `surface_rule` 列即所命中的规则名，任何人可用脚本复算：

| surface | 路径规则 | 语义 |
|---|---|---|
| `cli` | `scripts/`、`deeptutor_cli/`、`services/cli_apps|codex_auth|codebuddy_auth|github_copilot_auth`、`runtime/launcher.py` | 本地交互/启动路径，直接阻塞用户终端 |
| `request` | `api/`、`app/`、`services/codebuddy_credentials.py`，及其余未命中规则的 `deeptutor/` 模块（agents、llm、rag、session、tools、learning 等默认随请求处理） | 用户请求/会话路径，延长响应或会话尾延迟 |
| `worker` | `services/parsing`（MinerU/docling 等）、`reading/ingestion.py`、`services/embedding|videogen|imagegen|sandbox`、`plugins/`、`services/subagent` | 后台重活/索引管线，占用任务时长与并发槽 |
| `background` | `partners/`、`services/partners|web_source|cron|memory`、`events/`、`runtime/`（除 launcher）、`services/base_sync.py`、`services/app_update.py` | 常驻循环/调度器，影响 CPU 唤醒频率与关停时延 |

混合模块按主导路径归类（如 `reading/store.py` 归 request、`reading/ingestion.py` 归 worker），规则固定在脚本内，不做逐行人工覆盖，保证可复算。

## 3. 汇总

- 扫描文件数：1068；命中总计：**295**（固定值 245 + 参数化/动态 50）
- 按 kind：`sleep-fixed` 113、`timeout-net` 89、`timeout-wait` 64、`timeout-lock` 26、`sleep-yield` 3
- 按阻塞面：`request` 122、`background` 103、`worker` 42、`cli` 28
- 轮询/忙等上下文（`in_while=True`）：94 条
- 锁等待值分布：30s×12、30000ms×6、10s×3、10000ms×1、5s×3、0s×1（各模块不一致，见 §4）
- 明细见 `fixed_delays.csv`（296 行含表头），汇总计数与明细行数一致（295 = 113+89+64+26+3 = 122+103+42+28）。

## 4. Top 风险（按影响排序）

1. **`deeptutor/partners/channels/feishu.py:789` — `await asyncio.sleep(self._WORKING_REACTION_TTL)`，3600s**（background）。每条"处理中"表情消息挂一个 1 小时定时任务；多条消息并发时长期占用任务。建议：TTL 改配置 + 单一 reaper（按到期时间堆）替代每消息一个 task。
2. **`deeptutor/services/embedding/adapters/openai_compatible.py:255,261` — 60s/65s 固定退避**（worker）。429 时 `max(retry_after, 60)` 下限 60s、key 池冷却固定 65s，最多连挂 8 轮 ≈ 最坏 8 分钟嵌入停摆。建议：两值进配置并带抖动。
3. **`deeptutor/agents/loop/agent_loop.py:1241` — `while True: await asyncio.sleep(15.0)`**（request）。每个活跃 turn 一个 15s 心跳轮询。建议：间隔进配置；改事件/条件触发优先。
4. **`deeptutor/api/routers/knowledge.py:4644` — 完成后 `await asyncio.sleep(3)` 再关 WebSocket**（request）。每条进度流固定 +3s 尾延迟。建议：改为客户端 ACK 或可配置 drain 窗口。
5. **`deeptutor/api/routers/settings.py:2335` — SSE 心跳固定 0.35s**（request）。高频固定唤醒；建议心跳间隔进配置（如 1–5s）。
6. **渠道重连梯子全部硬编码**：`zulip.py:229-281` 同步 `time.sleep(2/2/2/5/10)`、`discord.py:104/509`（5s/8s）、`dingtalk.py:203`（5s）、`feishu.py:598`（同步 5s）、`telegram.py:421/1119`（1s/4s）等（background）。无抖动、无配置， storm 时同频重试。建议：统一指数退避工具（base/jitter/max 进配置）。
7. **MinerU 时序常量（#1903 相关背景）**：`services/parsing/engines/mineru/cloud.py:480` 轮询 `time.sleep(poll_interval)`（默认 `DEFAULT_POLL_INTERVAL_SECONDS=4.0`，cloud.py:46，有 monotonic deadline 上限）、`local.py:244` 看门狗 `Event.wait(0.25)` 轮询、`lightrag/pipeline.py:278` 状态轮询 0.2s（worker/background）。#1903 的挂起是生命周期问题，但上表给出其全部时序锚点，便于修复时统一到可配置常量。
8. **sqlite 锁等待值碎片化**：`timeout=0`（`services/workspace/activity.py:19`，立即失败）到 30s，`busy_timeout` 10s 与 30s 并存（如 `services/task_board.py:104`=10s vs `services/session/sqlite_store.py:1126`=30s）。建议：仓库级共享常量（connect 30s / busy 30s）+ 少数刻意的 0 快败场景加注释。
9. **`deeptutor/runtime/launcher.py` 就绪轮询**：`time.sleep(0.2/0.5/1)`（540/549/709/1132/1139/1705 等，cli）。循环多无总上限；建议统一 `wait_until_ready(url, timeout=…, interval=…)` 并暴露 env。
10. **`deeptutor/services/subagent/claude_models.py:188-203`** — 同步 `time.sleep(0.3/1.3/0.5/1.5)` 重试梯子（worker，同步上下文），建议参数化。

## 5. 可配置化建议（通用模式）

- 命名：`DEEPTUTOR_<MODULE>_<PURPOSE>_SECONDS`（如 `DEEPTUTOR_MINERU_POLL_INTERVAL_S`），启动时读 env，默认值保持现值（本表 value 列）。
- 分层：connect/读/总超时分开（httpx.Timeout 已是此形状），业务调用点只引用预算，不再写字面量。
- 轮询循环三要素：`interval`（可配）+ `max_wait`（必须存在）+ `jitter`（渠道重连类必带）。
- 统一退避工具：`backoff(attempt, base, cap, jitter)` 替换各渠道散落的固定梯子。
- sqlite：共享常量模块一次定义，杜绝 0/5/10/30s 混用。

## 6. 复现

```bash
git -C <worktree> rev-parse HEAD        # 应为 6cf793bd868ba5ecbe64722936d4be8fab5a01df
python3 evidence/fixed-delays-2026-10-09/scan_fixed_delays.py . /tmp/re.csv
diff /tmp/re.csv evidence/fixed-delays-2026-10-09/fixed_delays.csv && echo IDENTICAL
sha256sum -c evidence/fixed-delays-2026-10-09/SHA256SUMS   # 在本目录内执行
```
