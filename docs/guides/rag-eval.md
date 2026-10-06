# DeepTutor `services/rag/eval` 评估子系统导读

- 基线：origin/main @ `f07029cfc`（v1.6.13），86 个相关测试全绿（`tests/services/rag/eval` + `tests/cli/test_kb_eval_cli.py`）。
- 范围：`deeptutor/services/rag/eval/`（5 个模块）+ 入口 CLI `deeptutor kb eval`（`deeptutor_cli/kb.py:419`）+ 评测数据流上游 `rag_search`/`RAGService` 的交界处。
- 所有锚点形如 `path:line`，相对仓库根；本导读不改任何代码。
- 去重边界：RAG 管线/引擎实现见 guide-rag-pipelines（管线轴），嵌入模型见 guide-embedding（嵌入轴）。本文只在数据流交界处引用它们，不展开。

## 1. 这套子系统是什么

`deeptutor kb eval --dataset set.jsonl KB名` 把一份 QA 集对某个知识库跑检索，输出 Recall@k / Precision@k / nDCG@k / MRR / Hit@k / MAP@k。两条设计决定：

1. **gold 是原文摘录，不是 chunk id**（`deeptutor/services/rag/eval/dataset.py:3-7`）——换引擎、重建索引、重嵌入后评测集仍有效，因为匹配按文本做。
2. **指标是排序上的纯函数，不调 LLM 评审**（`deeptutor/services/rag/eval/metrics.py:10-11`）——分数可复现、可 diff，`--save` 存基线再对比即是回归门（`deeptutor/services/rag/eval/__init__.py:8-9`）。

评估全程只读：不改 KB、不动索引（`deeptutor/services/rag/eval/__init__.py:11-12`）。

## 2. 模块地图

```
deeptutor_cli/kb.py:419            kb eval 命令：加载 QA 集 → 解析绑定 provider → 跑评估 → 渲染/存 JSON
        │
        ▼
deeptutor/services/rag/eval/dataset.py:191   load_dataset()：.jsonl/.ndjson/.json → EvalDataset（pydantic, extra=forbid）
        │
        ▼
deeptutor/services/rag/eval/runner.py:126    RetrievalEvaluator：逐 case 检索（生产同路径）→ 生成 hits → 打分
        │   └─ 默认检索 deeptutor/tools/rag_tool.py:15 rag_search → deeptutor/services/rag/service.py:86 RAGService.search → 绑定管线
        ▼
deeptutor/services/rag/eval/matching.py:141  RelevanceMatcher：chunk 文本 ↔ gold 摘录 判定"命中了哪些 gold"
        ▼
deeptutor/services/rag/eval/metrics.py:166   evaluate_hits()：hits → QueryMetrics（6 指标）
        ▼
deeptutor/services/rag/eval/report.py:29     EvalReport：聚合（宏平均）+ to_json/summary_lines
```

分层一句话：**dataset 定"评什么"，runner 定"怎么把检索结果变成 hits"，matching 定"什么算命中"，metrics 定"hits 怎么变成分数"，report 定"分数怎么呈现"。**

## 3. 评测口径：dataset

### 3.1 Case 结构（`deeptutor/services/rag/eval/dataset.py:39-47`）

- `query` 必填非空（validator 见 dataset.py:49-56）；`gold` 必填、至少一条非空摘录，单字符串自动转单元素列表（dataset.py:58-64）；`id`/`notes` 可选，null/缺省按空串（dataset.py:75-79）。
- `EvalCase`/`EvalDataset` 均 `extra="forbid", frozen=True`（dataset.py:42,85）——写错字段名（如 `ansr`）直接报错，不会静默吞掉。
- 无 `id` 的 case 按文件序自动编 `q1,q2,…`（dataset.py:111-116,147）；**重复 id 直接拒绝**（dataset.py:182-188），保证报告行不歧义。

### 3.2 文件格式与错误面（`load_dataset`，dataset.py:191-235）

- `.jsonl`/`.ndjson`：每行一个 case（推荐，diff 友好，dataset.py:11-13）；坏 JSON 报行号（dataset.py:159-161）。`.json`：裸列表或 `{"name","cases"}`（dataset.py:165-179）。
- 名字优先级：显式参数 > 文件内 `name` 字段 > 文件名 stem（dataset.py:235）。
- 错误全部收敛为 `EvalDatasetError`，带 文件+case 序号+query 摘录（dataset.py:135-146），CLI 原样红字输出并 exit 1（`deeptutor_cli/kb.py:64-72`）。
- `limited(n)` 只做前缀截断（dataset.py:99-103）——`--limit` 是"前 N 条"，不是抽样。

## 4. 数据流：一次评估怎么跑

1. CLI 校验 KB 存在（kb.py:440-442），**先解析绑定 provider**（kb.py:445 → `deeptutor/services/rag/provider_binding.py:45`，kb_config.json → metadata.json → 默认 llamaindex）；`pageindex`/`pageindex-oss` 直接拒绝——它们"推理即检索"，没有可打分的排序列表（kb.py:81-88；`RAGService.search` 侧还有第二道 error envelope，`deeptutor/services/rag/service.py:96-108`）。
2. `RetrievalEvaluator.evaluate`（runner.py:170-201）逐 case 顺序调用 `evaluate_case`（runner.py:203-239），**一 case 一次检索**。
3. 检索走生产同路径：默认 `search_fn` 是 `rag_search`（runner.py:109-123，惰性 import 便于替换）；`rag_search` 未给 `kb_base_dir` 时走多用户 `resolve_for_rag`（`deeptutor/tools/rag_tool.py:36-43`），CLI 则钉死在 `<project_root>/data/knowledge_bases`（kb.py:31-34）。`RAGService.search` 路由到 KB 绑定管线（service.py:127），并把返回的 `provider` 强制覆写为绑定值（service.py:135-137）。
4. 结果归一：`_extract_sources`（runner.py:76-93）优先取 `sources` 列表（非 Mapping 项被丢弃，runner.py:86）；没有 sources 但有 `content`/`answer` 时，整块上下文当**一个 span** 打分（runner.py:90-92，`SOURCE_MODE_CONTEXT`）。上下文模式让 LightRAG/GraphRAG 报告类输出也能评"材料回没回来"，但精度粗。
5. 错误判定：`needs_reindex` 或 `error_type` 即失败 case（runner.py:96-106,221-223）；检索抛异常/返回非 Mapping 也记失败（runner.py:214-219）。**失败 case 进报告但不进均值**（report.py:41-49,60-65）——引擎不可达时报告"0 of N scored"而不是误导性低分（runner.py:9-12）。
6. 每个 case：rank≤k 的每条 citation 文本过 matcher → `hits[i]` = 第 i+1 名覆盖的 gold 序号集合（frozenset，runner.py:226-228）→ `evaluate_hits` 出 6 指标（runner.py:235）。
7. 报告：`EvalReport.aggregate()` 宏平均 + `queries_scored`/`queries_failed` 计数（report.py:60-65）；`to_dict()` 带逐 case `matched_gold` 与 `context_only` 标记（report.py:81-89, runner.py:63-73）；CLI rich 表格 + summary 行（kb.py:121-140, report.py:96-108），`--format json` 时 stdout 只有 JSON、进度静默（kb.py:97-99）。

## 5. 匹配口径：什么算"命中"

`RelevanceMatcher`（`deeptutor/services/rag/eval/matching.py:141`）按 case 构建，gold 预 tokenize（matching.py:107-117）。chunk 文本对一条 gold 命中，当且仅当：

1. **包含**：归一化后一方完整包含另一方 → ratio=1.0（matching.py:193-199）。正向覆盖（chunk 含 gold）无条件成立；**反向**（截断引用是 gold 的前缀，LlamaIndex/GraphRAG 会把 `content` 截到 200 字符）要求 chunk 至少有 `min_tokens` 个 token 才算（matching.py:195-199），防"the model"这类泛化短语蹭匹配。
2. **token 重叠**：共享 token 数 ÷ **较短侧** token 数 ≥ `min_ratio`(默认 0.5) **且** 共享 ≥ `min_tokens`(默认 4)（matching.py:201-204, 阈值定义 29-31）。除以短侧是刻意的——4 token 截断引用全在长 gold 里也得 1.0（matching.py:125-129）。

配套口径：

- 归一化 = 小写 + 折叠空白（matching.py:44-46）；token = ASCII 词 + **逐个 CJK 字符**（matching.py:35-38），中文不依赖分词器，但一个汉字就是一个 token，`min_tokens=4` 对中文意味着至少共享 4 个字。
- citation 文本按 `content → text → snippet → excerpt → summary` 取（`SOURCE_TEXT_KEYS`，matching.py:41-67）；**取不到文本的记录得空串、永不匹配**——新引擎的 citation 字段名若不在此列，会静默全 0 分，这是接引擎时第一处要核对的地方。
- 阈值非法即抛错（matching.py:77-82）；CLI 的 `--min-ratio` 只改 ratio，`min_tokens` 恒为默认 4（kb.py:454）。
- 一条 chunk 可同时覆盖多条 gold（MatchResult.indices 多元，matching.py:174-181）；匹配器拒绝全空 gold，`gold_count` 只数非空摘录（matching.py:152-163）。

## 6. 指标计算：公式与口径细节

全部在 `deeptutor/services/rag/eval/metrics.py`，输入都是 `hits`（每 rank 的 gold 序号集合）。**集合语义是核心：同一 gold 被多个 chunk 覆盖只算一次。**

| 指标 | 定义 | 锚点 |
|---|---|---|
| Recall@k | 前 k 名覆盖的 **去重** gold 数 / gold 总数 | metrics.py:53-61 |
| Precision@k | 前 k 名中"有命中"的 rank 数 / **实际返回数**（不足 k 不惩罚小库） | metrics.py:64-74 |
| nDCG@k | 二进制增益，**每 rank 只在引入"新" gold 时给 1**，理想 DCG 用 `min(gold_count, k)` | metrics.py:110-130 |
| MRR（受 k 截断） | 第一条命中 rank 的倒数 | metrics.py:82-87 |
| Hit@k | 前 k 名任一命中 → 1.0 | metrics.py:77-79 |
| MAP@k | 每个**新** gold 首现 rank 的 precision 之和 / gold 总数，封顶 1.0 | metrics.py:90-102 |

聚合：宏平均（逐 case 等权），round 4 位；空列表给 0 不报错（metrics.py:185-197）。展示 3 位（report.py:20-25）。

## 7. 已知坑（补测/调参前先看）

1. **MRR 键名没有 @k 但受 k 截断**（键名 metrics.py:30，计算 runner.py:235→metrics.py:179）——跨 run 对比换 k 时 MRR 也会变，别当成"全程 MRR"。
2. **precision 与 recall 可反向背离**：两个 chunk 引同一条 gold（gold 有 2 条）→ recall=0.5 但 precision=1.0（测试锁定 tests/services/rag/eval/test_eval_metrics.py:66-74）。precision 高不代表覆盖全。
3. **nDCG 的"新 gold 才给增益"**：重复引用同一 gold 不能替代缺失的 gold（metrics.py:111-118，tests/services/rag/eval/test_eval_metrics.py:158-165）。
4. **失败 case 不进均值**：对比两次 run 必须先看 `queries_failed`/`queries_scored`（report.py:60-65）；全失败报告的指标是 0.0 而非报错（report.py:62 + metrics.py:188-190），容易被误读成"质量崩了"。
5. **上下文模式粒度粗**：`content`-only 引擎整块算一个 span（runner.py:90-92）——precision 恒为 0 或 1，nDCG/MAP 也随之退化；看 `context_only` 标记（report.py:85）再解读。
6. **`sources` 列表被截到 k**（runner.py:227），`--top-k` 同时是检索 top_k 和指标截断（kb.py:423, runner.py:212）——调 k 会改变检索本身，不只改变统计窗口。
7. **citation key 白名单**（§5）：`source_text` 不认识的形状 → 永不匹配（静默 0）。engine 报告 provider 以 service 覆写为准（service.py:137），per-case 再取 result 值（runner.py:237）。
8. **CLI 与库 API 的 KB 根目录可能不同**：CLI 钉死项目级目录（kb.py:31-34），直接调 `RetrievalEvaluator` 不传 `kb_base_dir` 走多用户路由（rag_tool.py:36-43）。
9. **`--limit` 是前缀**（§3.2）：做子集评测时注意 case 顺序即文件序。
10. **报告 round 粒度**：JSON 里 4 位、表格 3 位（metrics.py:162 + report.py:20），diff 基线时用 JSON。

## 8. 测试覆盖与可拆卡条目

现有 6 个测试文件、86 用例（2026-10-06 实测全绿 0.82s）：dataset/matching/metrics/runner/report 各一 + CLI 一。核心口径（集合语义、阈值、失败排除、CLI 参数透传、pageindex 拒绝、json+save 纯净输出）均有锁定。**未覆盖/弱覆盖点，可直接拆卡：**

| # | 位置 | 缺口 | 建议卡 |
|---|---|---|---|
| 1 | `deeptutor/services/rag/eval/dataset.py:209-210` | 目录输入的拒绝分支无测试（只测了缺文件/坏后缀/空集） | 补 `load_dataset(dir)` 报 "must be a file" |
| 2 | `deeptutor/services/rag/eval/dataset.py:218-223` | 读取 OSError 与非 UTF-8 两条错误路径无测试 | 补只读坏编码文件用例 |
| 3 | `deeptutor/services/rag/eval/matching.py:198` | "短子串 + token 不足" 走 overlap 被拒无直接断言（现有测试只盖 overlap floor 与 ≥4 token 截断） | 补 2-token gold 子串不匹配 |
| 4 | `deeptutor/services/rag/eval/runner.py:86` | `sources` 混入非 Mapping 项被过滤无测试 | 补混合列表打分用例 |
| 5 | `deeptutor/services/rag/eval/runner.py:90-92` | 仅 `answer` 无 `content` 时进入上下文模式无测试（现测只用 `content`） | 补 answer-only → `source_mode=content` |
| 6 | `deeptutor/services/rag/eval/runner.py:103-105` | 仅 `error_type`（无 answer/content）时错误文本回退为类型名，无测试 | 补裸 error_type envelope |
| 7 | `deeptutor/services/rag/eval/runner.py:185-190` | 失败 case 也回调 progress 无断言（现测只走成功路径） | 补 progress 含失败 case |
| 8 | `deeptutor_cli/kb.py:100-102,109-118` | progress 的 failed 行渲染、`--save` 写盘 OSError→exit 1 无 CLI 测试 | 补 CLI 失败行与坏保存路径 |
| 9 | `deeptutor_cli/kb.py:430-432` | `--min-ratio` 下界（≤0 或 0 值）只测了上界 1.5（tests/cli/test_kb_eval_cli.py:182-188） | 补 0/负值 exit 1 |
| 10 | `deeptutor/services/rag/eval/matching.py:174-181` | 一 chunk 覆盖两条 gold 时 `ratio` 取最大值无断言 | 补多 gold best-ratio |

复测命令（限时）：
`python3 -m pytest -q -p no:cacheprovider tests/services/rag/eval tests/cli/test_kb_eval_cli.py`

## 9. 快用参考

```bash
# 基线
deeptutor kb eval mykb -d set.jsonl --top-k 5 --save baseline.json
# 改配置后对比（stdout 纯 JSON，可 diff）
deeptutor kb eval mykb -d set.jsonl --top-k 5 --mode hybrid --format json --save after.json
```

QA 集样例（jsonl，每行一个 case）：

```json
{"id": "attention-1", "query": "What is attention?", "gold": ["Attention weighs each token."], "notes": "ch.3"}
```
