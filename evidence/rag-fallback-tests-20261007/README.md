# RAG 顶层检索降级链单元测试 evidence

- 分支：`test/rag-fallback-chain-20261007`（基于 origin/main `f07029cfc`，v1.6.13）
- 新增：`tests/services/rag/test_rag_fallback_chain.py`（18 个用例）+ 本说明
- 不含任何产品代码改动：相对 origin/main 仅新增测试文件与本目录。

## 覆盖场景

### provider_binding 回退链（kb_config.json → metadata.json → 默认 provider）

1. kb_config.json 存在但没有该 KB 条目 → 回落 metadata.json 的 `rag_provider`
2. kb_config.json 损坏（非法 JSON）→ 跳过、回落 metadata.json
3. metadata.json 损坏（非法 JSON）→ 默认 provider（llamaindex）
4. metadata 记录了已下线的 provider 字符串 → `normalize_provider_name` 归一化为默认
5. KB 无任何绑定文件，以及 kb_name 为空 → 默认 provider

### factory 归一化回退

6. None / 空串 / 空白 / 未知 provider → 默认 provider；已知名称大小写与空白容忍

### RAGService.search 降级路径

7. pageindex（Reasoning as Retrieval）引擎 → 短路返回 guard 结果（`error_type=reasoning_as_retrieval_required`），全程不实例化、不调用 pipeline
8. pipeline 抛 `TimeoutError` → 硬失败向上传播（本层不吞异常；降级语义通过 error_type 结果表达，而非异常吞噬）
9. pipeline 返回 `error_type` / `needs_reindex` → 部分结果原样返回、provider 权威盖章、并发出的 status 事件带 `call_state=error` 与 `needs_reindex`
10. L1 记忆 trace 故障（`get_memory_store` 抛错）→ 搜索照常成功（best-effort 旁路永不阻塞主链路）
11. 多用户 path service 不可用（`get_path_service` 抛错）→ 构造时回落 `DEFAULT_KB_BASE_DIR`
12. `RAG_PROVIDER` 环境变量缺失 / 垃圾值 → `get_current_provider` 回落默认；合法值归一化

### SmartRetriever 超时 / 部分结果 / LLM 回退

13. 单个查询注入 `TimeoutError` → 该查询被丢弃，幸存查询仍聚合出答案与 sources（部分结果语义；每个查询都被尝试过）
14. 全部查询超时 → `{"answer": "", "sources": []}`，且聚合 LLM 不被调用
15. 查询生成 LLM 抛错 → 回落 `[context[:200]]`
16. 查询生成 LLM 返回空白 → 回落 `[context[:200]]`
17. 查询生成 LLM 返回带编号多行 → 正确去编号并按 `max_queries` 截断
18. 聚合 LLM 抛错 → 回落为段落原文以空行拼接

## 命令与数字

环境：`/Users/Shared/DeepTutor/.venv`（Python 3.13.13、pytest 9.1.1、pytest-asyncio 1.4.0），worktree 基于 origin/main `f07029cfc`。所有运行均包 900 秒时限（macOS 无 `timeout` 命令，用 `perl -e 'alarm 900; exec @ARGV' -- <cmd>` 等价实现）。

```
python -m pytest -q -p no:cacheprovider tests/services/rag/test_rag_fallback_chain.py
→ 18 passed in 0.27s

python -m pytest -q -p no:cacheprovider \
  tests/services/rag/test_rag_fallback_chain.py tests/services/rag/test_rag_pipelines.py
→ 31 passed in 0.42s

python -m pytest -q -p no:cacheprovider tests/services/rag --ignore=tests/services/rag/eval
→ 658 passed, 12 failed, 31 skipped in 25.32s
```

12 个失败为 origin/main 既有失败：移除本测试文件后复跑同一命令得到相同的 12 failed（640 passed），失败集中在
`test_embedding_binding.py`（6）、`test_graphrag_pipeline.py`（3）、`test_lightrag_roles.py`（3），与新增测试无关。

`ruff check` 与 `ruff format --check` 对新文件均通过。
