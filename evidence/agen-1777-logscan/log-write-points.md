# 日志调用面高信号写点（人工复核后，仅中性条目）

## A. 凭据/密钥-候选（含 URL 内嵌凭据风险）

| 文件:行 | 域 | 日志级别 | 中性依据 | 建议 |
| --- | --- | --- | --- | --- |
| deeptutor/services/llm/client.py:124 | services | debug | f-string 插值 `clean_url`（经 sanitize_url，但该函数不去除 userinfo/query，见 services/llm/utils.py:144-175） | 中：落盘前剥离 URL userinfo 与 query |
| deeptutor/services/pocketbase_client.py:91 | services | info | f-string 插值 `pocketbase_url` | 中 |
| deeptutor/services/pocketbase_client.py:183 | services | info | f-string 插值 `pocketbase_url` | 中 |
| deeptutor/services/pocketbase_client.py:185 | services | warning | f-string 插值 `pocketbase_url` | 中 |
| deeptutor/services/pocketbase_client.py:191 | services | warning | f-string 插值 `pocketbase_url` 且同行插值 `{exc}` | 中 |
| deeptutor/services/embedding/adapters/cohere.py:128 | services | debug | f-string 插值 `url` | 中（debug 级，默认 INFO 不落盘） |
| deeptutor/services/embedding/adapters/jina.py:114 | services | debug | f-string 插值 `url` | 中（同上） |
| deeptutor/services/embedding/adapters/ollama.py:60 | services | debug | f-string 插值 `url` | 中（同上） |
| deeptutor/services/embedding/adapters/openai_compatible.py:222 | services | debug | f-string 插值 `url` | 中（同上） |
| deeptutor/services/embedding/adapters/openai_sdk.py:131 | services | info | f-string 插值 `self.base_url` | 中 |

说明：未发现任何 logger 调用直接插值 api_key/token/password 类变量（0 处确认）。

## B. 用户内容-候选

| 文件:行 | 域 | 日志级别 | 中性依据 | 建议 |
| --- | --- | --- | --- | --- |
| deeptutor/services/search/__init__.py:255 | services | info | f-string 完整插值 `query`（verbose 开关门控） | 高：完整用户查询明文落盘 |
| deeptutor/services/search/__init__.py:256 | services | info | f-string 插值 `answer[:200]`（verbose 门控） | 高：回答前 200 字符明文落盘 |
| deeptutor/services/search/__init__.py:126 | services | info | f-string 插值 `query[:50]` | 中：截断但仍为用户查询文本 |
| deeptutor/services/rag/pipelines/llamaindex/pipeline.py:296 | services | info | f-string 插值 `query[:50]` | 中 |
| deeptutor/services/rag/service.py:158 | services | info | f-string 插值 `query[:50]` | 中 |
| deeptutor/services/rag/pipelines/llamaindex/pipeline.py:339 | services | warning | f-string 插值 `log_message`（错误结果消息，可含上游文本） | 中 |
| deeptutor/api/routers/knowledge.py:676 | api | info(动态) | f-string 插值 `message`（process-log 桥接，透传任务过程消息） | 中 |
| deeptutor/services/embedding/adapters/cohere.py:136 | services | error | f-string 插值 `response.text`（上游错误响应体，可能回显请求上下文） | 中 |
| deeptutor/services/embedding/adapters/jina.py:122 | services | error | 同上（`response.text`） | 中 |
| deeptutor/services/embedding/adapters/openai_compatible.py:287 | services | error | 同上（`response.text`） | 中 |
| deeptutor/services/search/providers/jina.py:87 | services | error | 同上 | 中 |
| deeptutor/services/search/providers/serper.py:100 | services | error | 同上 | 中 |
| deeptutor/services/search/providers/tavily.py:98 | services | error | 同上 | 中 |
| deeptutor/logging/adapters/llamaindex.py:56 | logging | 桥接 DEBUG | 将 LlamaIndex 记录器设为 DEBUG 并桥接（第三方库日志常含查询/片段；默认 INFO 文件级别不落盘） | 中：文档化或按级别过滤 |
| deeptutor/api/routers/auth.py:1170 | api | info | f-string 插值 `body.username`（账号标识） | 中 |
| deeptutor/api/routers/auth.py:1202 | api | info | f-string 插值 `body.username` | 中 |
| deeptutor/api/routers/auth.py:1444 | api | info | f-string 插值 `body.user_id` | 低 |
| deeptutor/api/routers/auth.py:1891 | api | info | f-string 插值 `body.role` | 低 |

## C. 内网地址-候选

| 文件:行 | 域 | 日志级别 | 中性依据 | 建议 |
| --- | --- | --- | --- | --- |
| deeptutor/services/pocketbase_client.py:91,183,185,191 | services | info/warn | `pocketbase_url`（自托管/内网部署时为内网主机） | 中（与 A 组同点） |
| deeptutor/services/rag/pipelines/llamaindex/document_loader.py:333 | services | info | f-string 插值 `origin.name`（文档来源标识） | 低 |

## D. 异常文本载体（聚合）

- 270 处 `{exc}` / `exc_info` 写点，分布 87 个文件；JsonlFormatter 将异常全文写入 `deeptutor.jsonl`（formatters.py:37-38）。异常消息可间接携带 URL（含内嵌键）、用户文本、内网主机名。
- 头部文件（按出现次数）：api/routers/knowledge.py(33)、api/routers/book.py(31)、services/session/pocketbase_store.py(17)、agents/loop/pipeline.py(12)、api/main.py(11)。
- 建议：中 —— 在 JsonlFormatter 层增加集中式 URL 凭据/内网主机清洗可一次性覆盖全部 270 处；逐行坐标见 `machine-scan-full.csv`（category=exc）。
