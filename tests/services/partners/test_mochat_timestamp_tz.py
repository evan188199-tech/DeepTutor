"""Regression tests for Mochat timestamp timezone handling.

Writers used to serialize ``now(utc).replace(tzinfo=None)`` — a UTC wall
clock without its offset — and the reader interpreted such naive strings in
the host's local timezone, shifting epochs by the local UTC offset. These
tests pin the fixed contract: written timestamps are aware UTC strings, and
naive legacy values are read as UTC.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.mochat import (
    MochatChannel,
    MochatConfig,
    _make_synthetic_event,
    parse_timestamp,
)

NON_UTC_TZ = "Asia/Shanghai"  # UTC+08:00, no DST


@pytest.fixture
def non_utc_tz():
    """Force the process-local timezone to a non-UTC zone for the test."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is unavailable on this platform")
    original = os.environ.get("TZ")
    os.environ["TZ"] = NON_UTC_TZ
    time.tzset()
    try:
        yield NON_UTC_TZ
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


def _make_channel(partners_root: Path, **overrides) -> MochatChannel:
    defaults = {
        "enabled": True,
        "claw_token": "claw-secret",
        "agent_user_id": "agent-1",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = MochatConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return MochatChannel(config, bus)


class TestParseTimestamp:
    def test_naive_string_is_read_as_utc_not_host_local(self, non_utc_tz: str) -> None:
        expected = int(datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert parse_timestamp("2026-01-01T12:30:00") == expected

    def test_z_suffix_and_offsets_still_resolve(self, non_utc_tz: str) -> None:
        utc_epoch = int(datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert parse_timestamp("2026-01-01T12:30:00Z") == utc_epoch
        assert parse_timestamp("2026-01-01T12:30:00+00:00") == utc_epoch
        shifted = int(datetime(2026, 1, 1, 4, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert parse_timestamp("2026-01-01T12:30:00+08:00") == shifted

    def test_garbage_and_non_string_values_still_return_none(self) -> None:
        assert parse_timestamp("") is None
        assert parse_timestamp("   ") is None
        assert parse_timestamp("not-a-date") is None
        assert parse_timestamp(None) is None
        assert parse_timestamp(12345) is None


class TestSyntheticEventTimestamp:
    def test_default_timestamp_is_aware(self, non_utc_tz: str) -> None:
        event = _make_synthetic_event("m-1", "user-1", "hi", None, "g-1", "s-1")
        parsed = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_default_timestamp_epoch_stays_near_now_on_non_utc_host(self, non_utc_tz: str) -> None:
        before_ms = datetime.now(timezone.utc).timestamp() * 1000
        event = _make_synthetic_event("m-1", "user-1", "hi", None, "g-1", "s-1")
        after_ms = datetime.now(timezone.utc).timestamp() * 1000
        got = parse_timestamp(event["timestamp"])
        assert got is not None
        assert before_ms - 1000 <= got <= after_ms + 1000

    def test_explicit_timestamp_is_passed_through(self) -> None:
        event = _make_synthetic_event(
            "m-1", "user-1", "hi", None, "g-1", "s-1", timestamp="2026-01-01T00:00:00Z"
        )
        assert event["timestamp"] == "2026-01-01T00:00:00Z"


class TestCursorFileUpdatedAt:
    def test_saved_cursor_file_records_aware_utc_updated_at(self, partners_root: Path) -> None:
        channel = _make_channel(partners_root)
        channel._session_cursor["session_1"] = 42

        asyncio.run(channel._save_session_cursors())

        data = json.loads(channel._cursor_path.read_text("utf-8"))
        parsed = datetime.fromisoformat(str(data["updatedAt"]).replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        drift_s = abs(datetime.now(timezone.utc).timestamp() - parsed.timestamp())
        assert drift_s < 300
