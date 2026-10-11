# triage: 20261011 四扫描报告高危项分诊表（AGEN-1685，只读）

- 基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）；输入为 myfork/scan/{network-timeouts,embedding-concurrency,web-locale-keys,python-deps-drift}-20261011 四报告。
- 方法：纯只读分诊。逐项标注严重度（P0–P4）、可修性（易/中/难）、建议卡型与建议 key；已有修复/测试卡的主题标去重。抽样复核 5 处关键断言（见文末命令），全部与报告一致。
- 去重边界（任务给定）：secret-defaults 与 hardcode-paths 两报告已另建修复卡（AGEN-1652/1653 线），不在本卡范围。
- 严重度：P0=数据损坏/不可用级，本轮**无 P0**；P1=显著可靠性/功能缺陷且修复面小；P2=应修、机械或有界风险；P3=卫生/批量项；P4=观察记录。

## 1. scan-network-timeouts（34 行：有界 29 / 弱 3 / 缺失 0 / n-a 2）

| 项 | 结论 | 严重度 | 可修性 | 建议 |
|---|---|---|---|---|
| #20 opencode_family.py POST message/SSE read=None、无 wall-clock | 弱：远端静默挂起时 consult 无限等待，仅回合取消可中断 | P1 | 易（对齐 hermes idle_timeout 语义加可配置上限） | fix 卡 `fix-opencode-message-wallclock`；相关 AGEN-1339（行为补测）可作测试落点，无覆盖性 fix 卡 |
| #24 process.py 本地 CLI consult 等待无 timeout（:9 声明契约） | 弱：与 hermes idle_timeout 机制不一致，CLI 挂起拖死会话线程 | P1 | 易（默认关闭保契约 + 可选 wall-clock/心跳） | fix 卡 `fix-subagent-consult-wallclock`；AGEN-1078 只覆盖清理链无界等待，不覆盖本项，需在卡面写明区别 |
| #30 web_source/scheduler.py sync 失败退避重排 attempt 无上限 | 弱：坏源无限占用调度，无"最大尝试后转 error 态"出口 | P1 | 易（N 次失败转显式 error + 手动复位） | fix 卡 `fix-web-sync-max-attempts`；测试落点参考 AGEN-1148（调度器单测） |
| #2/#3/#6/#7/#9/#11 search 族 timeout 20/30/60 离散离群、failover 最坏串行 Σ(timeout) | 有界但无共享常量约束 | P3 | 易 | chore 卡 `chore-search-timeout-constants`（含候选 4：共享默认+覆盖区间） |
| search requests 层无有界重试（瞬时抖动直接触发 failover） | 改善项 | P3 | 易（Adapter 层 Retry(total=1,…)） | 并入 `chore-search-timeout-constants` 或独立小 fix |
| 候选 8：工具层未接 provider timeout 参数（用户不可调） | 改善项 | P3 | 中（涉及配置面） | 并入 `chore-search-timeout-constants` 评估 |
| 候选 6：探针口径不统一（ping 5s vs readiness 1.5–3s） | 观察项 | P4 | 易 | 记录，随 P3 卡顺带 |
| 候选 7 + 边界外：github_copilot_auth connect 未拆分（×3 处）、image_utils/tex_downloader/primitives 均有界 | 弱/有界 | P4 | 易 | connect 拆分一行改动，随 P3 卡顺带 |
| 其余 29 行有界 + n/a 2 行 | 无动作 | n/a | — | 保留报告原表，不建卡 |
| 去重 | LLM provider 失败面归 scan-provider-failure-parity 卡；embedding 失败面归 scan-embedding-concurrency 卡（报告已声明只引用） | — | — | 不重复清点 |

## 2. scan-embedding-concurrency（4 MEDIUM / 3 LOW / 1 INFO + 5 补测条目）——全部已有卡，去重为主

| 项 | 结论 | 严重度 | 可修性 | 去重/建议 |
|---|---|---|---|---|
| M-1 嵌入层无按 endpoint 并发上限 | 实：client.py:67-85 只做起步间隔；多 KB re-index 可打满本地后端 | P1 | 中 | **已有修复卡 AGEN-1589（in_review）**，范围逐字覆盖 M-1；无需新卡 |
| M-2/M-3/M-4 cohere/jina/dashscope_native 无重试无 429 处理 | 实：单发 raise_for_status 直抛，首败报废整跑 | P1 | 易 | **已有修复卡 AGEN-1588（in_review）**，四适配器（含 L-1 ollama）+ 日志脱敏；无需新卡 |
| L-1 ollama 瞬时错误不重试、connect/read 未分 | 实（仅本地路径） | P2 | 易 | 并入 AGEN-1588 |
| L-2 LightRAG embedding_func_max_async/embedding_batch_num 未透传 | 实（SDK 默认 8 有界但不受设置控制） | P2 | 易 | 并入 AGEN-1589 |
| L-3 LlamaIndex 同步嵌入每批新建事件循环 | 实（性能/健壮性，非竞态） | P3 | 易 | **已有修复卡 AGEN-1593（in_review）** |
| I-1 openai_compatible 429 固定 ≥60s 台阶、8 轮无全局预算 | 行为可接受 | P4 | 易 | **已有修复卡 AGEN-1495（in_review）**（退避进配置+抖动） |
| 补测条目 E-1/E-4 | 契约测试：429/TransportError 注入、退避与 Retry-After | P2 | 易 | 随 AGEN-1588 验收；现有失败分支补测参考 AGEN-913 |
| 补测条目 E-2/E-3 | 在飞上限回归 + 透传默认值断言 | P2 | 易 | 随 AGEN-1589 验收 |
| 补测条目 E-5 | per-thread loop 复用并发断言 | P3 | 易 | 随 AGEN-1593 验收（落点 test_client_runtime.py）；本地路径补测另参考 AGEN-1547 |
| 汇总 | 本报告 8 项发现与 5 条补测全部有归属卡（4 fix 卡 in_review），**本轮零新卡**；续放动作为复核合并 | — | — | — |

## 3. scan-web-locale-keys（四清单）

| 项 | 结论 | 严重度 | 可修性 | 去重/建议 |
|---|---|---|---|---|
| 缺失 key fr 59（56 为 fix-web-locales-parity 后新漂移） | 实：抽样 `Add a note for this segment` fr=0/en=1 | P2 | 易（机械补齐+回归） | **已有修复卡 AGEN-1681（in_review，卡面明确按本报告修）**，AI 审核 AGEN-1688 进行中 |
| fr 目录级缺口 529 | 466 已被 fix 分支覆盖；63 为新漂移 | P3 | 易 | 466 归 AGEN-904（in_review）去重；63 新漂移 → AGEN-1681 复核未含则开 `fix-web-locales-fr-dir-gap` |
| 孤儿 key：en/zh/de 1479 候选（750 confirmed + 729 guarded）、fr 1910（含 909 fr-only 历史） | 实（278 处动态 t() 致漏报/误报风险，已用 guard 档隔离） | P3 | 中（confirmed 档可批量删，guarded 档须人工核对） | 无卡 → 新建 `chore-web-locale-orphan-cleanup`（只删 confirmed 档，guarded 档出人工核对清单） |
| common.json 4 文件（各 37 key）未被 init.ts 加载、key 全重复于 app.json（148 实例文件级孤儿） | 实：init.ts 无 common 引用（已抽样） | P3 | 易（接线或删除，二选一） | 无卡 → 新建 `chore-web-common-locale-wiring` |
| 硬编码文案 31 处/17 文件，疑似真实漂移 0 | 与 fix-web-hardcoded-i18n（AGEN-905）10 文件零交集 → v1.6.14 后无新增漂移 | n/a | — | 无动作；去重标注 AGEN-905 |
| 汇总 | 主项（缺失键）已有卡；缺口 63/孤儿/common.json 三项续放新卡 | — | — | — |

## 4. scan-python-deps-drift（A10 + B9+2 + C15）

| 项 | 结论 | 严重度 | 可修性 | 建议 |
|---|---|---|---|---|
| A8+B6+C15 perplexity：代码 import `perplexity`，声明/提示装 `perplexityai`，二者不可互换 | 实（已抽样）：声明失效，provider 恒走降级报错 | P1 | 易（import 名与发行名二选一对齐） | fix 卡 `fix-deps-perplexity-import`；与 AGEN-1622（perplexity 契约补测）协调 |
| A5/A6 weixin/msteams crypto（pycryptodome/cryptography）双回退、均无直接声明 | 实：靠 extras 传递兜底，最小安装下通道降级 | P2 | 易（显式声明其一 + 注释回退序） | fix 卡 `fix-deps-crypto-declare` |
| A1–A4/A9/A10 anyio/starlette/fsspec/lxml/pandas/pyarrow 顶层或 lazy 直用、仅传递依赖满足 | 实：可跑但声明面失真 | P3 | 易（显式声明或注明"经传递满足"） | chore 卡 `chore-deps-transitive-declare`（A7 deepseek_harness 单列 extra 或文档，并入本卡） |
| B1–B5 nest_asyncio/tenacity/prompt_toolkit/pdfplumber/oauth-cli-kit 声明未用（测试固化不用） | 实：可移除；pdfplumber 删除前需再核对可选引擎面 | P3 | 中（涉上游打包面，需兼容论证） | chore 卡 `chore-deps-prune-unused`（B4 谨慎项单独标注） |
| B7–B9 python-socks/socksio/websocket-client 声明未用 | 传递消费/被 async websockets 取代 | P4 | 易 | 并入 `chore-deps-prune-unused`（注记保留亦可） |
| C1–C10 可选被当必宣（有守卫/回退，注释自认 soft） | 有意保险面，运行不受影响 | P4 | 难（动必装面是上游敏感决策） | 记录不建卡；留待上游打包策略讨论 |
| C11–C14 anthropic/pageindex/ddgs/redis lazy 无守卫、无 extra 出口 | 缺包时对应功能 ImportError，声明面无可选出口 | P4 | 中 | 记录不建卡；可随 `chore-deps-transitive-declare` 顺带补 extra 草案 |
| 汇总 | 1 项 P1 新 fix + 1 项 P2 fix + 2 张 P3 chore；无 P0 | — | — | — |

## 抽样复核命令（全部只读，在 /Users/Shared/DeepTutor 执行）

```bash
git fetch --multiple origin myfork
git show origin/main:deeptutor/services/subagent/opencode_family.py | sed -n '69,71p'   # read=None 契约注释
git show origin/main:deeptutor/services/embedding/adapters/cohere.py | sed -n '128,140p' # 无重试
git show origin/main:deeptutor/services/search/providers/perplexity.py | sed -n '35,42p' # import 名错位
git show origin/main:web/locales/fr/app.json | grep -c "Add a note for this segment"     # =0
git show origin/main:web/i18n/init.ts | grep -c common                                   # =0
```
