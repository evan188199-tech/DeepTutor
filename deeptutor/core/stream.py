"""
Stream Event Protocol
=====================

Defines the unified streaming event format used by all tools, capabilities,
and plugins to communicate progress and results to consumers (CLI, WebSocket, SDK).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any


class StreamEventType(str, Enum):
    """All possible event types in a streaming session."""

    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    THINKING = "thinking"
    OBSERVATION = "observation"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"
    SOURCES = "sources"
    RESULT = "result"
    ERROR = "error"
    SESSION = "session"
    SESSION_META = "session_meta"
    DONE = "done"
    WAIT_FOR_INPUT = "wait_for_input"


@dataclass
class StreamEvent:
    """
    A single streaming event emitted during a chat turn.

    Attributes:
        type: The semantic kind of this event.
        source: Which tool / capability / plugin produced it (e.g. "deep_solve").
        stage: Current stage within the source (e.g. "planning").
        content: Human-readable text payload.
        metadata: Arbitrary structured data (tool args, sources, metrics, …).
        timestamp: Unix epoch seconds when the event was created.
    """

    type: StreamEventType
    source: str = ""
    stage: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    seq: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "source": self.source,
            "stage": self.stage,
            "content": self.content,
            "metadata": self.metadata,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
        }


# Neutral messages for terminal turn failures, keyed by failure code.
# ``str(exc)`` of an LLM/provider error can embed provider URLs, request ids
# and provider response bodies; that text belongs in server logs only. The
# chat-visible error event and the persisted turn error use these messages
# instead, with the failure code appended so it can be quoted to support.
_TURN_ERROR_MESSAGES: dict[str, str] = {
    "provider_error": "The AI service is temporarily unavailable. Please try again.",
    "provider_transport": "The AI service is temporarily unavailable. Please try again.",
    "reasoning_budget_exhausted": "The model stopped before finishing its answer. Please try again.",
    "worker_lost": "The worker executing this turn was lost; regenerate to retry",
    "internal_error": "The assistant response failed. Please try again.",
}

_DEFAULT_TURN_ERROR_MESSAGE = _TURN_ERROR_MESSAGES["internal_error"]


def neutral_turn_error_message(error_code: str = "") -> str:
    """Map a turn failure code to a neutral, user-facing message.

    Empty codes resolve to ``internal_error``; unknown codes keep the
    internal-error wording but still quote the code itself, so every
    terminal failure carries both a stable message and its code.
    """
    code = str(error_code or "").strip() or "internal_error"
    base = _TURN_ERROR_MESSAGES.get(code, _DEFAULT_TURN_ERROR_MESSAGE)
    return f"{base} (error code: {code})"
