# 续放清单：20261011 四扫描分诊后续动作（AGEN-1685）

- 依据：triage-table.md。建议 key 为 slug，开卡时按工作区编号规则落正式编号。
- 优先级即建卡与排期顺序；所有卡沿用 GLM 储备卡通用规则（新 worktree/新分支、只推本卡分支、测试限时）。

## A. 建议新建卡（按优先级）

| # | 建议 key | 类型 | P | 主题与最小范围 | 来源 |
|---|---|---|---|---|---|
| 1 | fix-opencode-message-wallclock | fix | P1 | opencode_family POST message/SSE 加可配置 wall-clock（对齐 hermes idle_timeout 语义），默认不回归现契约；附监控告警点说明。测试落点 AGEN-1339 | net#20 |
| 2 | fix-subagent-consult-wallclock | fix | P1 | 本地 CLI consult 等待加可选 wall-clock/心跳（默认关闭）。卡面须写明与 AGEN-1078（清理链）的区别：本项是等待路径非清理路径 | net#24 |
| 3 | fix-web-sync-max-attempts | fix | P1 | scheduler sync 失败 N 次后转显式 error 态，仅手动 retry()/编辑复位；退避封顶逻辑不变。测试落点 AGEN-1148 | net#30 |
| 4 | fix-deps-perplexity-import | fix | P1 | import 名与发行名对齐（`perplexity` vs `perplexityai` 二选一），报错文案同步；与 AGEN-1622 契约补测协调 | deps A8/B6/C15 |
| 5 | fix-deps-crypto-declare | fix | P2 | weixin/msteams crypto 依赖显式声明其一，注释回退序与最小安装行为 | deps A5/A6 |
| 6 | chore-web-locale-orphan-cleanup | chore | P3 | 删孤儿 key 仅限 confirmed 档（en/zh/de 750 + fr 对应档）；guarded 档（729/1910）出人工核对清单不动 | locale 孤儿清单 |
| 7 | chore-web-common-locale-wiring | chore | P3 | common.json 4 文件：接线进 i18n/init.ts 或删除（key 全重复 app.json），二选一并加防回归断言 | locale 文件级孤儿 |
| 8 | fix-web-locales-fr-dir-gap | fix | P3 | fr 目录级新漂移 63 key 补齐；先等 AGEN-1681 复核结论，未含再开 | locale 目录缺口 |
| 9 | chore-deps-transitive-declare | chore | P3 | A1–A4/A9/A10 显式声明或注明"经传递满足"；A7 deepseek_harness 单列 extra 或文档；顺带补 C11–C14 extra 草案 | deps A 类 |
| 10 | chore-deps-prune-unused | chore | P3 | B1–B5/B7–B9 移除或注记保留；B4 pdfplumber 删除前需再核对可选解析引擎面；涉及上游打包面，逐条给兼容论证 | deps B 类 |
| 11 | chore-search-timeout-constants | chore | P3 | search 族 timeout 共享常量+覆盖区间（20/30/60 收敛）；Adapter 层有界重试与工具层 timeout 配置化可评估并入；顺带探针口径统一、copilot_auth connect 拆分两处 P4 | net 离群观察+候选 4/5/6/7/8 |

## B. 已有卡去重（不新建，跟踪复核）

| 主题 | 来源项 | 归属卡（状态） | 动作 |
|---|---|---|---|
| 嵌入在飞并发上限 + LightRAG 透传 | emb M-1/L-2、E-2/E-3 | AGEN-1589（in_review） | 等复核合并，验收含 E-2/E-3 |
| 四适配器有界重试 + 日志脱敏 | emb M-2/M-3/M-4/L-1、E-1/E-4 | AGEN-1588（in_review） | 等复核合并，验收含 E-1/E-4 |
| LlamaIndex per-thread loop 复用 | emb L-3、E-5 | AGEN-1593（in_review） | 等复核合并，验收含 E-5 |
| openai_compatible 429 退避配置化+抖动 | emb I-1 | AGEN-1495（in_review） | 等复核合并 |
| locale 缺失/未定义键收敛 | locale 缺失 fr 59 | AGEN-1681（in_review）+ AI 审核 AGEN-1688（in_progress） | 等审核；复核时确认 56 新漂移全覆盖 |
| fr 目录缺口 466 + pl/uk common.json | locale 目录缺口 466 | AGEN-904（in_review） | 等复核合并 |
| 硬编码文案迁移 | locale 硬编码（本轮漂移 0） | AGEN-905（in_review，fix-web-hardcoded-i18n） | 无动作，零交集 |
| opencode_family 行为补测 | net#20 测试落点 | AGEN-1339（in_review） | 建卡 #1 时引用 |
| web_source 调度器单测 | net#30 测试落点 | AGEN-1148（in_review） | 建卡 #3 时引用 |
| perplexity 契约补测 | deps A8 协调 | AGEN-1622（in_review） | 建卡 #4 时引用 |

## C. 记录不建卡

- net：29 行有界 + n/a 2 行；LLM provider 失败面归 scan-provider-failure-parity、embedding 失败面归 scan-embedding-concurrency（报告已声明只引用）。
- deps：C1–C10（有意保险面，动必装面是上游敏感决策）、C11–C14（可随 #9 顺带）、dev 工具与 python-multipart 注记。
- locale：硬编码文案本轮疑似真实漂移 0。

## D. 汇总

- 四报告合计：P0 **0**；P1 **4**（net#20/#24/#30、deps A8）全部为新 fix 卡候选；P2 3（其中 2 项并入已有卡）；P3 6；P4 记录若干。
- embedding 报告零新卡（100% 已有卡）；locale 主项已有卡；network-timeouts 与 python-deps-drift 是本轮新卡主要来源。
