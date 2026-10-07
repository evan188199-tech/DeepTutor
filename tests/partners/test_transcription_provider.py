"""Tests for the Groq voice transcription provider.

Covers normalization of transcription results and tolerance of empty,
missing, and malformed inputs without touching the network: every HTTP
interaction goes through a fake ``httpx.AsyncClient.post``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from deeptutor.partners.transcription import GroqTranscriptionProvider

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class _PostRecorder:
    """Captures POST calls and replays scripted responses or errors."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch, script: list[Any]) -> None:
        recorder = self

        async def fake_post(
            self: httpx.AsyncClient, url: str, **kwargs: Any
        ) -> httpx.Response:
            recorder.calls.append({"url": url, **kwargs})
            outcome = script[min(len(recorder.calls) - 1, len(script) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            outcome.request = httpx.Request("POST", url)
            return outcome

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def _text_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _make_audio(tmp_path: Path) -> Path:
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFFxxxx")
    return audio


def _provider(monkeypatch: pytest.MonkeyPatch, api_key: str | None = "groq-key") -> (
    GroqTranscriptionProvider
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return GroqTranscriptionProvider(api_key=api_key)


# ── Construction / API key resolution ────────────────────────────────────


@pytest.mark.parametrize(
    ("api_key", "env_value", "expected"),
    [
        ("explicit-key", "env-key", "explicit-key"),
        (None, "env-key", "env-key"),
        (None, None, None),
        ("", "env-key", "env-key"),
    ],
    ids=["explicit-wins", "env-fallback", "no-key", "empty-key-falls-back"],
)
def test_api_key_resolution(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    env_value: str | None,
    expected: str | None,
) -> None:
    if env_value is None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GROQ_API_KEY", env_value)
    provider = GroqTranscriptionProvider(api_key=api_key)
    assert provider.api_key == expected
    assert provider.api_url == GROQ_URL


# ── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_returns_text_and_request_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response({"text": "hello world"})])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == "hello world"

    call = recorder.calls[0]
    assert call["url"] == GROQ_URL
    assert call["headers"]["Authorization"] == "Bearer groq-key"
    assert call["timeout"] == 60.0
    assert call["files"]["file"][0] == "clip.wav"
    assert call["files"]["model"] == (None, "whisper-large-v3")


@pytest.mark.asyncio
async def test_transcribe_accepts_str_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response({"text": "ok"})])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(str(audio)) == "ok"


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "  spaced  "},
        {"text": "你好"},
    ],
    ids=["empty-string", "whitespace-preserved", "non-ascii"],
)
@pytest.mark.asyncio
async def test_transcribe_result_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response(payload)])
    provider = _provider(monkeypatch)

    expected = payload["text"]
    assert await provider.transcribe(audio) == expected


# ── Missing inputs return empty string without HTTP calls ────────────────


@pytest.mark.asyncio
async def test_missing_api_key_returns_empty_without_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response({"text": "should-not-happen"})])
    provider = _provider(monkeypatch, api_key=None)

    assert await provider.transcribe(tmp_path / "clip.wav") == ""
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_missing_file_returns_empty_without_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response({"text": "should-not-happen"})])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(tmp_path / "does-not-exist.wav") == ""
    assert recorder.calls == []


# ── Malformed responses and transport failures degrade to empty string ───


@pytest.mark.asyncio
async def test_missing_text_key_defaults_to_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [_text_response({})])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == ""


@pytest.mark.asyncio
async def test_http_error_status_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(
        monkeypatch,
        [httpx.Response(500, json={"error": {"message": "boom"}})],
    )
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == ""
    assert len(recorder.calls) == 1


@pytest.mark.asyncio
async def test_non_json_body_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [httpx.Response(200, text="<html>oops</html>")])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == ""


@pytest.mark.asyncio
async def test_truncated_json_body_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(
        monkeypatch,
        [httpx.Response(200, content=b'{"text": "unclos')],
    )
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == ""


@pytest.mark.asyncio
async def test_network_error_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _make_audio(tmp_path)
    recorder = _PostRecorder()
    recorder.install(monkeypatch, [httpx.ConnectError("connection refused")])
    provider = _provider(monkeypatch)

    assert await provider.transcribe(audio) == ""
