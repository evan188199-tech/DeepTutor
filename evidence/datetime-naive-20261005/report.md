# 全仓库 naive/aware datetime 混用清点（read-only scan）

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13），新 worktree 只读扫描，未改任何代码。
- 范围：`deeptutor/`（排除 tests）。工具：`scan_datetime.py`（AST 全量调用点 + 函数内数据流 naive/aware 配对），人工复核全部比较点与写入方约定。
- 对照：`myfork/agent/dt22-todo-scan`（evidence/todo-scan-2026-10-03/report.md，DT-22 报告 _iso 与进度时间戳条目）；去重对象：fix-tz-flaky（`myfork/fix/tz-stable-runtime-context-tests[-v2]`）、verify-dt22-drift（`myfork/agent/agen666-dt22-drift-scan`）、scan-lock-usage（`myfork/scan/lock-usage-20261005`）。

## 总量（AST 命中，deeptutor/，347 个调用点）

| 模式 | 数量 | 说明 |
|---|---|---|
| `datetime.now()`（无 tz） | 98 | naive 本地时间 |
| 其中 `.isoformat()` 序列化 | 73 | naive 本地字符串入库/返回 |
| `datetime.now(tz)` | 60 | aware（含 `timezone.utc`/`UTC` 别名） |
| aware `.isoformat()` | 36 | 正确 UTC 序列化 |
| `now(utc).replace(tzinfo=None).isoformat()` | 8 | 剥时区序列化（见 L2） |
| `fromisoformat(...)` | 13 | 9 处未知时区 + 4 处 Z 归一化 |
| `fromtimestamp(no-tz)` | 6 | naive 本地解读 |
| `fromtimestamp(tz)` | 10 | aware，无风险 |
| `datetime.utcnow()` / `utcfromtimestamp()` | 0 | 遗留 API 未使用 |

Python 基线 `>=3.11`，`fromisoformat` 可解析空格分隔与 Z 后缀；naive 输入返回 naive，是下述分级的前提。

## L1 混用比较（naive vs aware/unknown 比较点；当前均不崩溃，属"写方约定脆弱"的潜在风险）

| # | 位置 | 判定依据 | 分级 | 去重 |
|---|---|---|---|---|
| 1 | `deeptutor/api/routers/knowledge.py:4387` | `datetime.now()`(naive) − `fromisoformat(ts)`(未知)；`ts` 来自 progress `timestamp`，本文件 8 处写方均为 `datetime.now().isoformat()`(naive，:304/:1048/:1098/:2101/:3667/:4338/:4364/:4499)，`:4364` 还可注入 `task_metadata.finished_at`（`task_id_manager.py:78` naive）。任一写方改为 aware 字符串即 TypeError，且被 `except Exception: pass` 吞掉 → `has_active_task=False`，WS 提前关闭，无日志 | HIGH（潜在，静默失败） | **DT-22 HIGH 已列**（原 :4353，drift 后行号 +34）；随卡②修复 |
| 2 | `deeptutor/api/routers/knowledge.py:4433`（比较点 :4435） | 同 #1 的第二处：`progress_time=fromisoformat(timestamp)`，`now=datetime.now()`，`age_seconds<300` 判定进度新鲜度；aware 写入 → TypeError 被吞 → 不推送进度 | HIGH（潜在，静默失败） | **DT-22 HIGH 已列**（原 :4402）；随卡②修复 |
| 3 | `deeptutor/knowledge/manager.py:104` | `_entry_updated_after`: `fromisoformat(raw) > cutoff`，cutoff 为 naive（:690 `datetime.now()-timedelta`）；只捕 `ValueError` 不捕 `TypeError`——aware `updated_at` 会**未捕获崩溃**（init/孤儿清理路径）。当前写方全部 naive（:542/:752/:881/:928/:977/:1024/:1078），且 `metadata.last_updated` 用 `strftime("%Y-%m-%d %H:%M:%S")`（`add_documents.py:497/:569`、`initializer.py:105`），3.11 可解析但非 ISO 规范 | MEDIUM（潜在崩溃+格式漂移） | 新发现；卡④ |
| 4 | `deeptutor/knowledge/manager.py:2145`（比较点 :2146） | `prev_mtime=fromisoformat(prev_mtime_str)` 与 `file_mtime=fromtimestamp(st_mtime)`(naive 本地，:2139) 比较；写方 :2213-2215 与 `knowledge.py:1190` 均存 naive 本地 mtime。同机一致；换机/时区变化/DST 切换 → 全量误判 modified（重复重索引，不丢数据） | MEDIUM（正确性可接受，浪费索引） | DT-22 列了 knowledge.py:1193（原行号）OSError 视角；时区视角为新发现；卡⑤ |
| 5 | `deeptutor/services/base_sync.py:32` | `is_stale`: aware `now(utc)` − `fromisoformat(last)`，naive 输入 `replace(tzinfo=utc)` 防御。当前写方 `web_source/sync.py:46`、`github_source/sync.py:35` 均为 `now(timezone.utc).isoformat()`(aware) 一致；但 naive-本地字符串一旦写入即按 UTC 解读，staleness 偏移整时区 | MEDIUM-LOW（潜在偏移，防御已做一半） | 新发现；卡⑥ |
| 6 | `deeptutor/api/utils/task_id_manager.py:96` | `finished_time=fromisoformat(finished_at)` vs naive `cutoff`（:91）；写方 :78 naive，一致。aware 写入 → except 跳过清理 → 内存泄漏（不崩溃） | LOW | 新发现；随卡②一起改 |

正面参照（已有正确防御模式，修复卡可复用）：`deeptutor/services/memory/recall.py:69-77`（naive→UTC 归一化）、`deeptutor/multi_user/device_credentials.py:37-46`、`deeptutor/services/partners/links.py:97-102`（ValueError 兜底 datetime.min）。

## L2 序列化丢时区（写入/透传时丢失 tz 信息，消费端无法还原）

| # | 位置 | 判定依据 | 分级 | 去重 |
|---|---|---|---|---|
| 1 | `deeptutor/partners/channels/mochat.py:118`、`:1013`（写）→ `:222`（读） | 写方 `now(utc).replace(tzinfo=None).isoformat()` **剥 Z**，存的是 UTC 挂钟却无时区标记；读方 `parse_timestamp` 做 `.replace("Z","+00:00")` 后 `.timestamp()`——naive 输入按**宿主机本地**解读 → 非 UTC 宿主（如 UTC+8）epoch 偏 8 小时，消息时间戳/去重排序错位。写读同仓可复现的缺陷链 | HIGH（非 UTC 宿主必错） | 新发现；卡① |
| 2 | `deeptutor/services/memory/snapshot/adapters.py:49`（`_iso` 字符串分支） | 字符串输入仅试解析后**原样透传**（Z、+00:00、naive 混存，格式不归一）；下游混合消费时 naive 条目排序/比较偏移。数值分支 :56 `fromtimestamp(ts, tz=utc).isoformat()` 正确 | MEDIUM | **DT-22 HIGH 已列**（原 :51）；verify-dt22-drift 确认仍在且 #1764/#1765 只覆盖 read_* 三个 LOW（:87/:138/:171），**不含 `_iso`**；卡③ |
| 3 | `deeptutor/services/session/pocketbase_store.py:98`（`_to_float` 兜底） | naive 字符串 `.replace("Z","+00:00")` 后仍 naive → `.timestamp()` 按本地解读为 epoch；PB 自动字段 `created/updated` 为 UTC-Z（aware，正确），legacy/自写 naive 值偏移 | MEDIUM-LOW | **DT-22 MEDIUM 已列**（原 :99，ValueError 视角）；时区视角并入卡⑥ |
| 4 | `deeptutor/services/rag/pipelines/pageindex/storage.py:77`、`deeptutor/services/rag/pipelines/lightrag/storage.py:295`、`deeptutor/services/rag/index_versioning.py:318`、`deeptutor/services/rag/pipelines/graphrag/storage.py:110`、`deeptutor/services/parsing/cache.py:88` | `now(utc).replace(tzinfo=None).isoformat()+"Z"`：剥时区再补 Z 字面量——瞬时值正确、往返一致，但属脆弱写法（忘补 Z 即成 L2#1），建议统一 helper | LOW（风格/易碎） | 新发现；归入卡⑦ |
| 5 | `deeptutor/book/storage.py:370` | 同上剥 tz，但仅日志行尾手写 `` `tsZ` `` 标签，展示用途 | LOW | 新发现；归入卡⑦ |

## L3 仅本地时间存储（naive 本地时间入库/下发，未含 tz）

| # | 位置（代表） | 判定依据 | 分级 | 去重 |
|---|---|---|---|---|
| 1 | 进度/任务时间戳——**会被再次解析判定**：`knowledge.py:304/:1048/:1098/:2101/:3667/:4338/:4364/:4499`；`task_id_manager.py:60/:78`；`manager.py:542/:752/:881/:928/:977/:1024/:1078`（`updated_at`/`last_sync`）；`add_documents.py:497/:569`、`initializer.py:105`（strftime）；`knowledge.py:3846/:1190` | 全部 `datetime.now().isoformat()`/strftime naive 本地；跨时区部署（Docker 宿主 TZ ≠ 开发机）时 progress 新鲜度(±300s 阈值)、孤儿清理宽限、增量同步判定整体偏移数小时；是 L1#1/#2/#4 的共同根因 | MEDIUM（随部署环境触发） | 与 fix-tz-flaky 无关（那是测试侧）；随卡②/④/⑤根治 |
| 2 | 展示/ID 用途（不参与判定，逐文件列出）：`agents/research/data_structures.py:78/:200/:201/:207/:259/:450/:468/:486`；`co_writer/edit_agent.py:146/:214/:234/:281/:310/:333/:356`；`api/routers/co_writer.py:341/:454`；`services/search/__init__.py:66/:109`；`services/partners/sessions.py:178/:413`；`tools/question/question_extractor.py:297/:301`；`api/routers/question.py:99/:201/:249`；`api/routers/knowledge.py:262`（task_key 片段）等，合计 naive 本地 isoformat/strftime 约 73+ 处 / 38 文件 | 仅日志、事件流、operation_id、搜索历史展示；无 fromisoformat 回读比较（已 grep 证实）。跨时区仅影响日志可读性 | LOW（可批量机械化替换） | 新发现；卡⑦储备 |
| 3 | `deeptutor/agents/loop/prompt_blocks.py:245` | `datetime.now().astimezone()`：naive→附加宿主时区；runtime context 展示用，日期正确性依赖宿主时区 | LOW | **fix-tz-flaky 已涉及**：`myfork/fix/tz-stable-runtime-context-tests[-v2]` 只改了 `tests/agents/chat/test_runtime_context.py`（测试端特意改回 naive 以匹配现状），生产代码未动；不新开卡，随卡⑦顺带 |
| 4 | `deeptutor/tools/cron_tool.py:27/:49-53`、`deeptutor/services/search/providers/aliyun_iqs.py:36` | cron `_parse_at` naive 输入按宿主本地解读（有注释、有意为之）；aliyun 供应商把 epoch 转本地日期作过滤参数，非 UTC 宿主日期可能偏一天 | LOW | 新发现；归入卡⑦ |

## 与既有工作去重对照

| 来源 | 条目 | 本扫描处置 |
|---|---|---|
| DT-22（dt22-todo-scan） | knowledge.py:4353/:4402（HIGH，吞没） | 行号漂移 → :4387/:4433-4435；从时区视角升级为 L1 潜在混用，**不重复开卡**，随卡②修复根因 |
| DT-22 | snapshot/adapters.py:51/:56（`_iso`） | :49/:56；:51 → L2#2 卡③；:56 数值分支无时区风险 |
| DT-22 | pocketbase_store.py:99（MEDIUM） | :98 → L2#3；DT-22 卡与卡⑥互补 |
| DT-22 | knowledge.py:1193（MEDIUM，OSError） | :1190 → L1#4/L3#1 时区视角；卡⑤ |
| verify-dt22-drift（agen666） | `_iso`:51 仍在、#1764/#1765 不含 `_iso` | 采纳其结论；卡③明确补此缺口 |
| fix-tz-flaky（tz-stable-runtime-context-tests-v2） | 仅改 test_runtime_context.py | 生产侧 `prompt_blocks.py:245` 未修 → 记入 L3#3，随卡⑦ |
| scan-lock-usage（scan/lock-usage-20261005） | 锁使用扫描 | 报告 0 处 datetime 命中，无交叠；links.py `_update` 的文件锁与本扫描的 `expires_at` 解析属不同关注点 |

上游 PR 撞车检查：`gh pr list -R HKUDS/DeepTutor --author @me --state open` 共 30 条开放 PR，无 datetime/时区相关分支；本卡为纯只读扫描，不开 PR。

## 可拆修复卡条目（建议）

| 卡 | 标题草案 | 范围 | 优先级 |
|---|---|---|---|
| ① | fix: mochat 时间戳剥时区导致宿主本地误读 | mochat.py:118/:1013 停止剥 Z（或读方 naive→UTC 归一），`:222` 侧回归 | HIGH |
| ② | fix: 知识库进度时间戳统一 aware-UTC | knowledge.py 8 写点 + task_id_manager.py:78 改 `now(timezone.utc).isoformat()`；:4387/:4433 解析加 naive 归一并区分 ValueError/TypeError（顺带消除 DT-22 两处 HIGH 吞没的根因） | HIGH |
| ③ | fix: snapshot `_iso` 字符串分支归一化为 aware-UTC | adapters.py:49（补 #1764/#1765 未覆盖缺口，verify-dt22-drift 已确认） | MEDIUM |
| ④ | fix: `_entry_updated_after` 捕 TypeError + 双侧归一；`last_updated` 弃 strftime 改 ISO | manager.py:104/:690 + add_documents.py/initializer.py 3 写点 | MEDIUM |
| ⑤ | fix: linked-folder mtime 存 aware ISO（或 epoch float） | manager.py:2139/:2213-2215、knowledge.py:1190 | MEDIUM |
| ⑥ | fix: base_sync/pocketbase/task_id_manager naive 解读统一（assume-UTC 显式化 + 测试） | base_sync.py:26-33、pocketbase_store.py:98、task_id_manager.py:96 | MEDIUM-LOW |
| ⑦ | refactor: 展示类 naive 时间戳批量切 aware helper（分模块拆 PR） | L3#2 清单 38 文件 + strip-Z 五处统一 helper + prompt_blocks.py:245 | LOW（储备） |

## 复现/核对命令

```
python3 evidence/datetime-naive-20261005/scan_datetime.py deeptutor > /tmp/out.json   # 全量调用点
rg -n 'datetime\.now\(\)' deeptutor/ --type py -g '!**/test*'                          # 98 处 naive now
rg -n 'fromisoformat' deeptutor/ --type py -g '!**/test*'                              # 13 处解析点
```

原始命中明细见 `datetime_scan.json`（347 调用点，含文件/行号/模式/naive-aware 判定）。
