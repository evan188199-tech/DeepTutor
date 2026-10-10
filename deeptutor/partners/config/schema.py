"""Configuration schema — Pydantic models for partner channels."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


#: Shared default bound (seconds) for one channel send-path network call.
#: A hung platform API would otherwise hold the channel manager's serial
#: outbound lane forever. Channels inherit this via ``send_timeout_seconds``
#: and each channel config can override it.
SEND_TIMEOUT_SECONDS: float = 30.0


class DeliveryOverrides(Base):
    """Per-channel delivery switches."""

    send_progress: bool = Field(
        default=True,
        description="Deliver agent narration progress to this channel.",
    )
    send_tool_hints: bool = Field(
        default=True,
        description="Deliver one-line tool-call hints to this channel.",
    )
    send_timeout_seconds: float = Field(
        default=SEND_TIMEOUT_SECONDS,
        gt=0,
        description=(
            "Bound (seconds) on a single send/send_delta network call. "
            "On expiry the call is cancelled and raises so the channel "
            "manager's retry policy applies."
        ),
    )


class StreamingSupport(Base):
    """Opt-in live streaming for channels that can edit messages in place."""

    streaming: bool = Field(
        default=False,
        description=(
            "Stream replies live by editing the message in place as text arrives. "
            "Requires send_progress: narration rounds stream as they happen."
        ),
    )


class ChannelsConfig(Base):
    """Configuration for chat channels.

    Built-in and plugin channel configs are stored as extra fields (dicts).
    Each channel parses its own config in __init__.
    """

    model_config = ConfigDict(extra="allow")

    # Outbound delivery failures retry with exponential backoff (1s/2s/4s…).
    send_max_retries: int = 3
