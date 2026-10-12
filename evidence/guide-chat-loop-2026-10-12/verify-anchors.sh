#!/usr/bin/env bash
# Verify each path:line cited in guide-agents-chat-loop.md contains the expected anchor.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
pass=0; fail=0
check() {
  local path="$1" line="$2" expect="$3"
  local got
  got="$(sed -n "${line}p" "$path")"
  if printf '%s' "$got" | grep -qF -- "$expect"; then
    printf 'OK   %s:%s  %s\n' "$path" "$line" "$expect"
    pass=$((pass+1))
  else
    printf 'FAIL %s:%s  expected [%s] got [%s]\n' "$path" "$line" "$expect" "$got"
    fail=$((fail+1))
  fi
}

# --- think_stream facet ---
check deeptutor/runtime/agentic/think_stream.py 33 'THINK_OPEN_RE'
check deeptutor/runtime/agentic/think_stream.py 36 '_TAG_HOLDBACK_CHARS = 24'
check deeptutor/runtime/agentic/think_stream.py 39 'class InlineThinkFilter'
check deeptutor/runtime/agentic/think_stream.py 86 'def split_inline_think'
check deeptutor/agents/loop/agent_loop.py 1171 'think_filter = InlineThinkFilter()'
check deeptutor/agents/loop/agent_loop.py 1178 'def _emit_segments'
check deeptutor/agents/loop/agent_loop.py 1385 'content = getattr(delta, "content", None)'
check deeptutor/agents/loop/agent_loop.py 1392 'dsml_filter.feed(content)'
check deeptutor/agents/loop/agent_loop.py 1394 'think_filter.feed(visible_content)'
check deeptutor/agents/loop/agent_loop.py 1523 'dsml_filter.flush()'
check deeptutor/agents/loop/agent_loop.py 1526 'think_filter.flush()'
check deeptutor/agents/loop/agent_loop.py 1369 'reasoning_text = getattr(delta, "reasoning_content"'
check deeptutor/agents/loop/agent_loop.py 1315 'thinking_blocks'
check deeptutor/agents/loop/agent_loop.py 1210 '_maybe_emit_reasoning_progress'
check deeptutor/agents/loop/agent_loop.py 105 'MAX_REASONING_ONLY_RECOVERIES = 2'
check deeptutor/agents/loop/agent_loop.py 398 'def _clean'
check deeptutor/agents/loop/agent_loop.py 126 'def _reasoning_budget_exhausted'
check deeptutor/agents/loop/agent_loop.py 568 'if not final_text:'
check deeptutor/agents/loop/agent_loop.py 574 'reasoning_only_recoveries += 1'
check deeptutor/agents/loop/agent_loop.py 1601 'reasoning_budget_exhausted = bool('
check deeptutor/runtime/agentic/labeled_step.py 215 'post_label_think = InlineThinkFilter()'
check deeptutor/runtime/stream_bus.py 173 'async def thinking'
check deeptutor/runtime/stream_bus.py 156 'async def content'

# --- dsml facet ---
check deeptutor/agents/loop/dsml_tool_calls.py 34 'DSML_SIGNAL_RE'
check deeptutor/agents/loop/dsml_tool_calls.py 39 '_INVOKE_RE'
check deeptutor/agents/loop/dsml_tool_calls.py 60 '_MAX_PARTIAL_TAG_CHARS = 512'
check deeptutor/agents/loop/dsml_tool_calls.py 63 'class DSMLStreamFilter'
check deeptutor/agents/loop/dsml_tool_calls.py 173 'def _coerce_param_value'
check deeptutor/agents/loop/dsml_tool_calls.py 151 'def _schema_types'
check deeptutor/agents/loop/dsml_tool_calls.py 207 'def has_dsml_tool_calls'
check deeptutor/agents/loop/dsml_tool_calls.py 235 'def extract_dsml_tool_calls'
check deeptutor/agents/loop/dsml_tool_calls.py 277 'if not tool_calls:'
check deeptutor/agents/loop/agent_loop.py 296 'self._tool_schema_catalog = tool_schemas'
check deeptutor/agents/loop/agent_loop.py 1174 'dsml_filter = DSMLStreamFilter()'
check deeptutor/agents/loop/agent_loop.py 1548 'extract_dsml_tool_calls(text, self._tool_schema_catalog)'
check deeptutor/agents/loop/agent_loop.py 1550 'if not tool_calls:'
check deeptutor/agents/loop/agent_loop.py 1680 'fallback_dsml = DSMLStreamFilter()'
check deeptutor/agents/loop/agent_loop.py 1554 'forced_tool_choice and tool_choice == "ask_user"'
check deeptutor/agents/loop/agent_loop.py 670 'if _finish_was_truncated(result.finish_reason):'
check deeptutor/runtime/agentic/tool_call_stream.py 35 'class ToolCallAccumulator'

# --- context_budget facet ---
check deeptutor/agents/loop/context_budget.py 37 '_BLOCK_SEGMENTS'
check deeptutor/agents/loop/context_budget.py 57 '@dataclass(slots=True)'
check deeptutor/agents/loop/context_budget.py 58 'class LLMRequestSnapshot'
check deeptutor/agents/loop/context_budget.py 77 'def resolve_window_info'
check deeptutor/agents/loop/context_budget.py 108 'def detect_counter_name'
check deeptutor/agents/loop/context_budget.py 124 'def count_conversation_tokens'
check deeptutor/agents/loop/context_budget.py 141 'def build_context_budget'
check deeptutor/agents/loop/context_budget.py 173 'def _build'
check deeptutor/agents/loop/context_budget.py 211 '# Rank once'
check deeptutor/agents/loop/context_budget.py 230 '"free_tokens": max(0, window.window - used)'
check deeptutor/agents/loop/context_budget.py 241 'def _prompt_block_tokens'
check deeptutor/agents/loop/context_budget.py 256 'def _render_overhead'
check deeptutor/agents/loop/context_budget.py 281 'def _tool_schema_tokens'
check deeptutor/agents/loop/context_budget.py 296 'def _message_tokens'
check deeptutor/agents/loop/context_budget.py 331 'def _default_counter'
check deeptutor/agents/loop/pipeline.py 267 'self._last_prompt_blocks: list[PromptBlock] = []'
check deeptutor/agents/loop/pipeline.py 436 'def _build_system_prompt'
check deeptutor/agents/loop/pipeline.py 446 'self._last_prompt_blocks = self._prompt_assembler.blocks('
check deeptutor/agents/loop/pipeline.py 466 'def _build_loop_messages'
check deeptutor/agents/loop/pipeline.py 1623 'def _guard_context_window'
check deeptutor/agents/loop/pipeline.py 1660 'def measure_context_budget'
check deeptutor/agents/loop/pipeline.py 1667 'return build_context_budget('
check deeptutor/agents/loop/pipeline.py 1677 'def _unloaded_deferred_tool_count'
check deeptutor/agents/loop/agent_loop.py 297 'self._last_request: LLMRequestSnapshot | None = None'
check deeptutor/agents/loop/agent_loop.py 1132 'self._last_request = LLMRequestSnapshot('
check deeptutor/agents/loop/agent_loop.py 385 'if self._last_request is not None:'
check deeptutor/agents/loop/agent_loop.py 386 'budget = self.pipeline.measure_context_budget'
check deeptutor/agents/loop/agent_loop.py 388 'payload["metadata"] = {"context_budget": budget}'
check deeptutor/services/llm/context_window.py 9 'MAX_EFFECTIVE_CONTEXT_WINDOW = 1_000_000'
check deeptutor/services/llm/context_window.py 188 'def resolve_effective_context_window'
check deeptutor/services/session/context_builder.py 49 'def count_tokens'
check deeptutor/agents/loop/prompt_blocks.py 27 'RUNTIME_BLOCK_NAMES'
check deeptutor/agents/loop/prompt_blocks.py 81 'def render'
check deeptutor/agents/loop/prompt_blocks.py 99 'def split_for_replay'
check deeptutor/agents/loop/prompt_blocks.py 119 'def blocks'
check deeptutor/agents/loop/prompt_blocks.py 323 'ChatPromptAssembler = LoopPromptAssembler'
check deeptutor/agents/chat/agentic_pipeline.py 36 'class AgenticChatPipeline'
check deeptutor/agents/chat/capability.py 25 'async def run'
check deeptutor/services/session/usage_recovery.py 36 'budget = scope.get("context_budget") or {}'
check web/hooks/useContextBudget.ts 35 'const budget = meta?.context_budget as ContextBudget | undefined;'

# --- loop wiring (section 4) ---
check deeptutor/agents/loop/agent_loop.py 1037 'async def _call_llm'
check deeptutor/agents/loop/agent_loop.py 110 '_PROVIDER_RETRY_DELAYS = (0.5, 1.5)'
check deeptutor/agents/loop/agent_loop.py 100 'MAX_SETTLEMENT_ROUNDS = 3'
check deeptutor/agents/loop/agent_loop.py 837 'async def _forced_finish'
check deeptutor/agents/loop/agent_loop.py 480 'if not result.tool_calls:'
check deeptutor/agents/loop/agent_loop.py 719 'dispatch = await self.pipeline._dispatch_tool_calls('
check deeptutor/agents/loop/agent_loop.py 731 'if dispatch.pause:'
check deeptutor/agents/loop/agent_loop.py 801 'def _fold_context_checkpoint'
check deeptutor/agents/loop/agent_loop.py 309 'async def run(self)'
check deeptutor/agents/loop/agent_loop.py 403 'async def _run_loop'
check deeptutor/agents/loop/agent_loop.py 1290 'async for chunk in _bounded_stream_chunks'

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
