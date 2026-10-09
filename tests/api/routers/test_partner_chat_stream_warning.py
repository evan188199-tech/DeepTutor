"""A failing turn in the partner chat SSE stream leaves a server-side trace."""

from __future__ import annotations

import logging

import pytest

import deeptutor.api.routers.partners as partners_router

_LOGGER = "deeptutor.api.routers.partners"


class _FailingManager:
    async def send_message(self, *args, **kwargs):
        raise RuntimeError("turn backend down")


@pytest.mark.asyncio
async def test_chat_stream_warns_and_still_emits_sse_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(partners_router, "get_partner_manager", lambda: _FailingManager())
    payload = partners_router.ChatMessageRequest(content="hi", session_id="sess-123")

    chunks: list[str] = []
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        async for chunk in partners_router._partner_chat_stream("ada", payload, "acct-1"):
            chunks.append(chunk)
    stream = "".join(chunks)

    assert "event: error" in stream
    assert "turn backend down" in stream
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "ada" in message
    assert "sess-123" in message
    assert "turn backend down" in message
