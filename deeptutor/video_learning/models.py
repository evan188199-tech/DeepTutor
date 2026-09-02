"""Domain records for remote video-learning renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CommandType = Literal[
    "pause", "play", "seek", "volume", "mute", "playback_rate", "fullscreen"
]
CommandStatus = Literal["pending", "acked", "failed", "expired"]
PlaybackState = Literal["playing", "paused", "buffering", "ended", "unknown"]


@dataclass(frozen=True, slots=True)
class Device:
    device_id: str
    owner_id: str
    device_name: str
    device_kind: str
    paired_at: str
    last_seen: str
    workspace_root: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class PlayerSession:
    session_id: str
    owner_id: str
    device_id: str
    instance_origin: str
    video_id: str
    title: str
    position_ms: int
    duration_ms: int
    playback_state: PlaybackState
    playback_rate: float
    updated_at: str
    last_heartbeat_at: str
    controller_token_hash: str = ""
    material_id: str = ""


@dataclass(frozen=True, slots=True)
class PlayerCommand:
    command_id: str
    session_id: str
    owner_id: str
    device_id: str
    command_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: CommandStatus = "pending"
    created_at: str = ""
    acked_at: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceCommand:
    command_id: str
    owner_id: str
    device_id: str
    command_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: CommandStatus = "pending"
    created_at: str = ""
    acked_at: str | None = None
    error: str | None = None


__all__ = [
    "Device",
    "DeviceCommand",
    "PlayerCommand",
    "PlayerSession",
]
