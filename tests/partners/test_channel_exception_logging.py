"""Neutral-log regression tests for IM channel exception logging.

Channel SDK/HTTP exception messages can carry request URLs, response bodies,
or credential hints. These tests pin the converged behaviour: logs keep
exception type names (or a fixed reason), never the exception text.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger as loguru_logger
import pytest

from deeptutor.partners.channels import feishu, weixin, zulip

_MARKER = "CHANNEL-ECHO-MARKER-8b27"


@pytest.fixture
def loguru_messages() -> Any:
    records: list[str] = []
    handler = loguru_logger.add(lambda message: records.append(str(message)), level="DEBUG")
    try:
        yield records
    finally:
        loguru_logger.remove(handler)


def test_weixin_media_encrypt_key_parse_failure_is_neutral(loguru_messages: list[str]) -> None:
    raw = b"payload-bytes"
    assert weixin._encrypt_aes_ecb(raw, "not-a-valid-key") == raw

    joined = "\n".join(loguru_messages)
    assert "AES key parse failed before encryption (reason=invalid_encoding)" in joined
    assert "aes_key must decode" not in joined


def test_weixin_media_decrypt_key_parse_failure_is_neutral(loguru_messages: list[str]) -> None:
    raw = b"payload-bytes"
    assert weixin._decrypt_aes_ecb(raw, "not-a-valid-key") == raw

    joined = "\n".join(loguru_messages)
    assert "AES key parse failed before decryption (reason=invalid_encoding)" in joined
    assert "aes_key must decode" not in joined


def test_zulip_retry_wrapper_logs_type_name_only(loguru_messages: list[str]) -> None:
    channel = zulip.ZulipChannel.__new__(zulip.ZulipChannel)

    def _failing_call() -> None:
        raise RuntimeError(f"zulip upstream failed: {_MARKER}")

    with pytest.raises(RuntimeError):
        channel._call_with_retry(_failing_call, max_retries=2)

    joined = "\n".join(loguru_messages)
    assert "Zulip API call failed (attempt 1): RuntimeError" in joined
    assert "Zulip API call failed after 2 retries: RuntimeError" in joined
    assert _MARKER not in joined


def test_feishu_ws_shutdown_failure_logs_type_name_only(loguru_messages: list[str]) -> None:
    class _FailingConn:
        async def close(self) -> None:
            raise RuntimeError(f"feishu close failed: {_MARKER}")

    class _FakeClient:
        _conn = _FailingConn()

    asyncio.run(feishu._shutdown_ws_client(_FakeClient(), None))

    joined = "\n".join(loguru_messages)
    assert "Error closing Feishu WebSocket connection: RuntimeError" in joined
    assert _MARKER not in joined
