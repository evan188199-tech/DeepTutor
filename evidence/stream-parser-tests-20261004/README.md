# LLM 流式输出解析失败测试集（AGEN-554）

分支：`pr/test-stream-parser-failures`（基于 origin/main `f07029cfc`，release v1.6.13）
日期：2026-10-04
范围：只新增测试，不改任何产品代码（`git status` 仅两个新测试文件 + 本目录）。

## 覆盖的解析面

1. `deeptutor/services/llm/provider_core/openai_compat_provider.py` — `OpenAICompatProvider._parse_chunks`
   （chat-completions 流后置解析）
2. `deeptutor/services/subagent/hermes_remote_client.py` — `HermesRemoteClient.stream_events`
   （Hermes 网关 data-only SSE 逐行重组）

## 预期失败测试（6 个，对应真实解析缺陷）

### chat-completions 面（`tests/services/llm/test_openai_compat_stream_parse_failures.py`）

| 测试 | 场景 | 现状（失败原因） | 建议修复方向 |
|---|---|---|---|
| `test_parse_chunks_orders_parallel_tool_calls_by_provider_index_not_arrival` | 乱序：index 1 先于 index 0 到达 | `tool_calls` 按到达序返回 `[tool_b, tool_a]`；共享累积器 `ToolCallAccumulator`（`runtime/agentic/tool_call_stream.py`）对同一 wire 协议按 index 排序，两处行为不一致 | `_parse_chunks` 组装时按 `tc_bufs` 的 key 排序（与 `ToolCallAccumulator.collected()` 一致） |
| `test_parse_chunks_does_not_report_stop_for_stream_without_terminal_frame` | 中途截断：网关在最后一个 data chunk 后关闭连接，无任何 finish_reason 帧 | `finish_reason == "stop"`，截断响应与完整响应不可区分 | 记录"是否见过终帧"；未见终帧时给出非 stop 的 finish_reason（如 `error`/`incomplete`） |

### Hermes SSE 面（`tests/services/test_hermes_remote_sse_parse_failures.py`）

| 测试 | 场景 | 现状（失败原因） | 建议修复方向 |
|---|---|---|---|
| `test_empty_data_heartbeat_frame_is_skipped_not_fatal` | 心跳：`data:\n\n`（空 data 心跳帧） | `json.loads("")` 抛 `HermesRemoteProtocolError("invalid_sse_json")`，整条流中止 | 空 data buffer 的帧按 SSE 规则跳过不发事件 |
| `test_event_field_without_data_does_not_bleed_into_next_frame` | 乱序：`event: run.failed` 帧无 data，随后是仅带 data 的帧 | 事件名残留，下一帧被误标 `run.failed`，mapper 按错误事件处理 | 空数据帧的空行边界同时重置 event buffer（SSE 规范行为） |
| `test_pending_frame_is_flushed_when_connection_ends_without_blank_line` | 中途截断：EOF 前最后帧无空行终止 | 该帧被静默丢弃（usage/报告尾帧最容易这样被丢） | 流结束（EOF 或 `[DONE]`）时 flush 仍挂起的完整帧 |
| `test_done_marker_without_blank_line_terminates_cleanly_keeping_the_frame` | 中途截断：`data: {...}\ndata: [DONE]\n` 无空行分隔 | 相邻 data 行被拼成一个 payload，帧丢失且未按 `[DONE]` 干净收尾 | 遇到独立 `[DONE]` data 行先 flush 已完整接收的帧再返回 |

## 基线锚点测试（4 个，当前通过，防止修复回归）

- `test_baseline_chunked_tool_argument_json_is_concatenated_and_parsed` — 分块 JSON 拼接：arguments 分 4 片到达后正确拼装解析。
- `test_baseline_repeated_id_and_name_are_assigned_not_appended` — tool-call 增量合并：网关每片重发 id/name 不会追加（#937 回归防护）。
- `test_baseline_choiceless_usage_tail_frame_is_captured_and_zero_echo_ignored` — usage 尾帧：choice-less 尾帧捕获、CodeBuddy 式挂在 delta 上的 usage 捕获、全零 echo 不冲掉真实计数（`token_counts` 已内置零值过滤，两个解析面均未发现 usage 缺陷）。
- `test_baseline_comment_heartbeats_and_done_marker_are_quiet` — 注释心跳 `: ping` 保持静默且 `[DONE]` 正常收尾。

Responses wire API 的 `response.incomplete` 尾帧（usage + finish_reason="length"）已由现有实现正确处理（`openai_responses/parsing.py:646`），已探测确认，无需失败测试。

## 命令与数字

```
cd /Users/Shared/DeepTutor/dt-agen554-wt
python -m pytest -q -p no:cacheprovider \
  tests/services/llm/test_openai_compat_stream_parse_failures.py \
  tests/services/test_hermes_remote_sse_parse_failures.py
→ 6 failed, 4 passed in 0.67s（6 个失败全部为本卡预期失败，均为断言失败、非导入/装配错误）

python -m pytest -q -p no:cacheprovider \
  tests/core/agentic/test_tool_call_stream.py \
  tests/services/test_hermes_remote_backend_lifecycle.py \
  tests/services/llm/test_openai_compat_reasoning_content.py
→ 57 passed in 0.55s（相邻既有套件不受影响）
```

（本地 macOS 无 `timeout` 命令，等价限时由运行环境 900s 上限保证。）

## 修复卡领取说明

每个失败测试独立成缺陷，可按文件分别领取：chat-completions 面修 `_parse_chunks`（排序 + 终帧跟踪），SSE 面修 `stream_events`（空帧跳过 + event buffer 重置 + 收尾 flush）。全部测试文件含基线锚点，修复后整文件应转绿。
