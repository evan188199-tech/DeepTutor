"""Private, versioned model messages retained independently of display text.

Each assistant row owns one complete turn, including its prepared user input,
context updates and tool exchanges. Retention operates on these whole turns;
an older database without this metadata continues to use display history.

Replay is bounded, though: historical tool results are operational state
(full mastery maps, repeated status dumps) that used to ride verbatim into
every later main-loop request. Older turns' results are condensed to an
excerpt at replay time — the stored turns themselves are never rewritten.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any

MODEL_TURN_KEY = "model_turn"
MODEL_TURN_VERSION = 1

#: Replay-budget defaults (issue #1920). The newest completed turns replay
#: verbatim so the model keeps the current authoritative state; older tool
#: results keep a bounded excerpt while a shared budget holds the whole
#: condensed axis flat as the session grows. All three knobs are
#: environment overrides; setting the per-result cap to ``0`` restores the
#: pre-#1920 replay byte-for-byte.
DEFAULT_REPLAY_FULL_TOOL_TURNS = 1
DEFAULT_REPLAY_TOOL_RESULT_MAX_CHARS = 4_000
DEFAULT_REPLAY_TOOL_RESULTS_TOTAL_CHARS = 32_000
_REPLAY_FULL_TOOL_TURNS_ENV = "DEEPTUTOR_REPLAY_FULL_TOOL_TURNS"
_REPLAY_TOOL_RESULT_MAX_CHARS_ENV = "DEEPTUTOR_REPLAY_TOOL_RESULT_MAX_CHARS"
_REPLAY_TOOL_RESULTS_TOTAL_CHARS_ENV = "DEEPTUTOR_REPLAY_TOOL_RESULTS_TOTAL_CHARS"

#: Tools whose results embed the learner's own words are tutoring record,
#: not operational state — they are never condensed.
_LEARNER_REPLY_TOOLS = frozenset({"ask_user"})

_REPLAY_TOOL_RESULT_CONDENSED = (
    "[older tool result of {original} characters condensed to keep replay "
    "history bounded; call the same tool again if the full content is "
    "still needed]"
)
_MESSAGE_KEYS = frozenset(
    {
        "role",
        "content",
        "tool_calls",
        "tool_call_id",
        "name",
        "reasoning_content",
        "thinking_blocks",
        "_provider_response_state",
        "_context_snapshot",
    }
)


def normalize_model_turn(value: Any) -> dict[str, Any] | None:
    """Read an internal turn record only when its tool protocol is complete.

    Unknown versions and incomplete writes fall back to the displayed exchange.
    Do not truncate reasoning, image blocks or tool arguments during replay.
    """
    if not isinstance(value, dict) or value.get("version") != MODEL_TURN_VERSION:
        return None
    if "system" in value and not isinstance(value["system"], str):
        return None
    tools = value.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            return None
        for tool in tools:
            if (
                not isinstance(tool, dict)
                or not isinstance(tool.get("function"), dict)
                or not isinstance(tool["function"].get("name"), str)
            ):
                return None
    route = value.get("route")
    if route is not None and (
        not isinstance(route, dict)
        or any(not isinstance(route.get(key), str) for key in ("provider", "model"))
    ):
        return None
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    pending: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            return None
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                return None
            pending.remove(call_id)
        elif pending:
            return None
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or (calls and role != "assistant"):
            return None
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                return None
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id or call_id in pending:
                return None
            pending.add(call_id)
        if message.get("content") is not None and not isinstance(message["content"], (str, list)):
            return None
        cleaned.append({k: v for k, v in message.items() if k in _MESSAGE_KEYS})
    if pending:
        return None
    record = {"version": MODEL_TURN_VERSION, "messages": cleaned}
    for key in ("system", "tools", "route", "request_fingerprint"):
        if key in value:
            record[key] = value[key]
    try:
        return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return None


def model_turn(row: dict[str, Any]) -> dict[str, Any] | None:
    metadata = row.get("metadata")
    return (
        normalize_model_turn(metadata.get(MODEL_TURN_KEY)) if isinstance(metadata, dict) else None
    )


def history_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Keep an admitted user and its assistant together across budget cuts."""
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        if (
            row.get("role") == "assistant"
            and model_turn(row) is not None
            and groups
            and groups[-1][-1].get("role") == "user"
        ):
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def replay_group(
    rows: list[dict[str, Any]], route: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Prefer the model's complete exchange over the corresponding UI rows."""
    from .context_builder import expand_message_context

    if rows and rows[-1].get("role") == "assistant":
        record = model_turn(rows[-1])
        if record is not None:
            messages = record["messages"]
            if route and record.get("route") and record["route"] != route:
                # Signed thinking/encrypted response items belong to the route
                # that produced them. Tool evidence and public text are portable.
                for message in messages:
                    for key in ("_provider_response_state", "thinking_blocks", "reasoning_content"):
                        message.pop(key, None)
                    for call in message.get("tool_calls") or []:
                        call.pop("extra_content", None)
            return messages
    messages = []
    for row in rows:
        expanded = expand_message_context(row)
        metadata = row.get("metadata") or {}
        if row.get("role") == "assistant" and expanded:
            from .provider_response_state import normalize_provider_response_state

            state = normalize_provider_response_state(metadata.get("provider_response_state"))
            if state:
                expanded[-1]["_provider_response_state"] = state
        messages.extend(expanded)
    return messages


def _replay_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _condense_group_tool_results(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
    remaining_chars: int,
) -> tuple[list[dict[str, Any]], int]:
    """Condense one older turn's oversized tool results.

    Returns the (possibly new) message list plus the remaining shared
    budget. Learner replies (``ask_user``), non-text payloads and results
    already within ``max_chars`` are left untouched, and no stored record
    is ever mutated — condensed messages are new dicts.
    """
    tool_names: dict[Any, str] = {}
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if isinstance(function.get("name"), str):
                tool_names[call.get("id")] = function["name"]
    condensed: list[dict[str, Any]] = []
    changed = False
    for message in messages:
        content = message.get("content")
        if (
            message.get("role") == "tool"
            and isinstance(content, str)
            and len(content) > max_chars
            and tool_names.get(message.get("tool_call_id")) not in _LEARNER_REPLY_TOOLS
        ):
            keep = min(max_chars, max(0, remaining_chars))
            remaining_chars -= keep
            excerpt = content[:keep].rstrip()
            notice = _REPLAY_TOOL_RESULT_CONDENSED.format(original=len(content))
            message = {
                **message,
                "content": f"{excerpt}\n\n{notice}" if excerpt else notice,
            }
            changed = True
        condensed.append(message)
    return (condensed if changed else messages), remaining_chars


def condense_replayed_tool_results(
    groups: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    """Bound the historical tool-result payload of a replayed conversation.

    The newest ``DEEPTUTOR_REPLAY_FULL_TOOL_TURNS`` turn groups replay
    verbatim; older groups keep a per-result excerpt while a shared
    character budget holds the whole condensed axis flat as the session
    grows. The budget is spent newest-condensable-group first, so the most
    recent excerpts stay the fullest and only the oldest results degrade
    to a bare re-fetch notice.
    """
    max_chars = _replay_env_int(
        _REPLAY_TOOL_RESULT_MAX_CHARS_ENV, DEFAULT_REPLAY_TOOL_RESULT_MAX_CHARS
    )
    if max_chars <= 0 or len(groups) < 2:
        return groups
    full_turns = max(
        1,
        _replay_env_int(_REPLAY_FULL_TOOL_TURNS_ENV, DEFAULT_REPLAY_FULL_TOOL_TURNS),
    )
    first_condensable = len(groups) - full_turns
    if first_condensable <= 0:
        return groups
    remaining = max(
        0,
        _replay_env_int(
            _REPLAY_TOOL_RESULTS_TOTAL_CHARS_ENV, DEFAULT_REPLAY_TOOL_RESULTS_TOTAL_CHARS
        ),
    )
    condensed: dict[int, list[dict[str, Any]]] = {}
    for index in range(first_condensable - 1, -1, -1):
        condensed[index], remaining = _condense_group_tool_results(
            groups[index], max_chars=max_chars, remaining_chars=remaining
        )
    return [condensed.get(index, group) for index, group in enumerate(groups)]


def replay_history(
    rows: list[dict[str, Any]],
    summary: str = "",
    route: dict[str, str] | None = None,
    *,
    condense_tool_results: bool = True,
) -> list[dict[str, Any]]:
    """Replay stored turns as model messages, optionally budgeted.

    ``condense_tool_results=False`` returns the raw, unbudgeted replay —
    used by the summarizer's drift-free rebuild, which must fold the full
    evidence into the summary before it scrolls out of the window.
    """
    groups = [replay_group(group, route) for group in history_groups(rows)]
    if condense_tool_results:
        groups = condense_replayed_tool_results(groups)
    messages = (
        [{"role": "system", "content": f"[Conversation summary]\n{summary}"}] if summary else []
    )
    for group_messages in groups:
        messages.extend(group_messages)
    return messages


def complete_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close calls interrupted before their results could be admitted."""
    result = deepcopy(messages)
    pending: dict[str, None] = {}
    for message in result:
        for call in message.get("tool_calls") or []:
            pending[call["id"]] = None
        if message.get("role") == "tool":
            pending.pop(message.get("tool_call_id"), None)
    for call_id in pending:
        result.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "The turn was interrupted before this tool result was available. Do not assume it succeeded.",
            }
        )
    return result
