"""Contract tests for the OpenAI-compatible voice adapters.

Focused on ``deeptutor/services/voice/adapters/openai_compat.py``: TTS/STT
request construction, response parsing, and the failure branches — transport
errors/timeouts, provider HTTP errors, rate limiting, empty or malformed
audio, and the OpenRouter chat-audio fallback. All HTTP is faked through a
patched ``httpx.AsyncClient.post``; no network, no real keys.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Callable

import httpx
import pytest

from deeptutor.services.voice.adapters.openai_compat import (
    OpenAICompatSTTAdapter,
    OpenAICompatTTSAdapter,
    OpenRouterTTSAdapter,
    _chat_audio_format,
    _join_api_path,
)
from deeptutor.services.voice.base import (
    VoiceProviderError,
    VoiceProviderHTTPError,
)
from deeptutor.services.voice.config import (
    STT_BASE64_JSON,
    STTConfig,
    TTSConfig,
)

Responder = Callable[[int, dict[str, Any]], httpx.Response]


def _capture_post(monkeypatch: pytest.MonkeyPatch, respond: Responder) -> list[dict[str, Any]]:
    """Patch ``httpx.AsyncClient.post`` to record args; ``respond`` fakes the server."""
    calls: list[dict[str, Any]] = []

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        call = {"url": url, **kwargs}
        calls.append(call)
        response = respond(len(calls) - 1, call)
        response.request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def _static(response: httpx.Response) -> Responder:
    return lambda _index, _call: response


def _sse(*chunks: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def _tts_config(**overrides: Any) -> TTSConfig:
    defaults: dict[str, Any] = {
        "model": "tts-1",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test",
    }
    defaults.update(overrides)
    return TTSConfig(**defaults)


def _openrouter_config(**overrides: Any) -> TTSConfig:
    defaults: dict[str, Any] = {
        "model": "openai/gpt-4o-mini-tts",
        "provider_name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "or-key",
    }
    defaults.update(overrides)
    return TTSConfig(**defaults)


def _stt_config(**overrides: Any) -> STTConfig:
    defaults: dict[str, Any] = {
        "model": "whisper-1",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test",
    }
    defaults.update(overrides)
    return STTConfig(**defaults)


# ── OpenAICompatTTSAdapter: request construction ───────────────────────────


@pytest.mark.asyncio
async def test_tts_payload_omits_unset_optionals_and_includes_set_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(
        monkeypatch,
        _static(httpx.Response(200, content=b"ID3", headers={"content-type": "audio/mpeg"})),
    )
    await OpenAICompatTTSAdapter().synthesize("plain", _tts_config())
    await OpenAICompatTTSAdapter().synthesize(
        "fancy",
        _tts_config(voice="alloy", speed=1.25, instructions="Read calmly"),
    )

    assert set(calls[0]["json"]) == {"model", "input", "response_format"}
    assert calls[0]["json"] == {"model": "tts-1", "input": "plain", "response_format": "mp3"}
    assert calls[1]["json"]["voice"] == "alloy"
    assert calls[1]["json"]["speed"] == 1.25
    assert calls[1]["json"]["instructions"] == "Read calmly"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_tts_missing_content_type_falls_back_to_format_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        httpx.Response(200, content=b"ID3"),
        httpx.Response(200, content=b"ID3", headers={"content-type": "application/json"}),
    ]
    calls = _capture_post(monkeypatch, lambda index, _call: responses[index])

    _, wav_type = await OpenAICompatTTSAdapter().synthesize(
        "hi", _tts_config(response_format="wav")
    )
    _, mp3_type = await OpenAICompatTTSAdapter().synthesize("hi", _tts_config())

    assert wav_type == "audio/wav"
    assert mp3_type == "audio/mpeg"
    assert len(calls) == 2


# ── OpenAICompatTTSAdapter: failure branches ───────────────────────────────


@pytest.mark.asyncio
async def test_tts_missing_base_url_raises_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, content=b"ID3")))
    with pytest.raises(VoiceProviderError, match="No endpoint URL configured for TTS."):
        await OpenAICompatTTSAdapter().synthesize("hi", _tts_config(base_url=""))
    assert calls == []


@pytest.mark.asyncio
async def test_tts_transport_timeout_wraps_as_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(_index: int, _call: dict[str, Any]) -> httpx.Response:
        raise httpx.TimeoutException("read timed out")

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="TTS request error"):
        await OpenAICompatTTSAdapter().synthesize("hi", _tts_config())


@pytest.mark.asyncio
async def test_tts_rate_limit_error_preserves_status_and_trims_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "x" * 600
    _capture_post(monkeypatch, _static(httpx.Response(429, text=body)))
    with pytest.raises(VoiceProviderHTTPError) as excinfo:
        await OpenAICompatTTSAdapter().synthesize("hi", _tts_config())
    assert excinfo.value.status_code == 429
    assert "HTTP 429" in str(excinfo.value)
    assert "x" * 400 in str(excinfo.value)
    assert "x" * 401 not in str(excinfo.value)
    assert excinfo.value.body == body


@pytest.mark.asyncio
async def test_tts_empty_audio_response_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(monkeypatch, _static(httpx.Response(200, headers={"content-type": "audio/mpeg"})))
    with pytest.raises(VoiceProviderError, match="TTS provider returned empty audio."):
        await OpenAICompatTTSAdapter().synthesize("hi", _tts_config())


# ── OpenRouterTTSAdapter: fallback gating and chat-audio branches ──────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_openrouter_auth_and_rate_limit_errors_do_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(status, text="denied")))
    with pytest.raises(VoiceProviderHTTPError) as excinfo:
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())
    assert excinfo.value.status_code == status
    assert len(calls) == 1
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/audio/speech"


@pytest.mark.asyncio
async def test_openrouter_chat_audio_http_error_reports_original_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(502, text="bad gateway")

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError) as excinfo:
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())
    assert "original /audio/speech error" in str(excinfo.value)
    assert "HTTP 502" in str(excinfo.value)


@pytest.mark.asyncio
async def test_openrouter_chat_audio_transport_error_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        raise httpx.ConnectError("connection refused")

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="TTS request error"):
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())


def _chat_audio_sse(audio_data: str, *, with_transcript: bool = False) -> str:
    delta: dict[str, Any] = {"audio": {"data": audio_data}}
    if with_transcript:
        delta["transcript"] = "hi"
    return _sse({"choices": [{"delta": delta}]})


@pytest.mark.asyncio
async def test_openrouter_chat_audio_without_chunks_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        return httpx.Response(
            200,
            text=_sse({"choices": [{"delta": {"transcript": "hi"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="no audio chunks"):
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())


@pytest.mark.asyncio
async def test_openrouter_chat_audio_invalid_base64_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        return httpx.Response(
            200,
            text=_chat_audio_sse("a"),
            headers={"content-type": "text/event-stream"},
        )

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="invalid base64"):
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())


@pytest.mark.asyncio
async def test_openrouter_chat_audio_empty_decoded_audio_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        return httpx.Response(
            200,
            text=_chat_audio_sse(""),
            headers={"content-type": "text/event-stream"},
        )

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="returned empty audio"):
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())


@pytest.mark.asyncio
async def test_openrouter_chat_audio_stream_error_chunk_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        return httpx.Response(
            200,
            text=_sse({"choices": []}, {"error": {"message": "quota exceeded"}}),
            headers={"content-type": "text/event-stream"},
        )

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="OpenRouter chat audio error: quota exceeded"):
        await OpenRouterTTSAdapter().synthesize("hi", _openrouter_config())


@pytest.mark.asyncio
async def test_openrouter_chat_audio_request_shape_with_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(500, text="fallback trigger")
        return httpx.Response(
            200,
            text=_chat_audio_sse(base64.b64encode(b"chat-bytes").decode("ascii")),
            headers={"content-type": "text/event-stream"},
        )

    calls = _capture_post(monkeypatch, respond)
    config = _openrouter_config(response_format="pcm", instructions="Read calmly")

    audio, content_type = await OpenRouterTTSAdapter().synthesize("hello", config)

    assert audio == b"chat-bytes"
    assert content_type == "audio/pcm"
    payload = calls[1]["json"]
    assert calls[1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert payload["messages"][0] == {"role": "system", "content": "Read calmly"}
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    assert payload["audio"] == {"voice": "alloy", "format": "pcm16"}
    assert payload["stream"] is True
    assert payload["modalities"] == ["text", "audio"]


def test_collect_audio_line_ignores_non_payload_lines() -> None:
    chunks: list[str] = []
    ignored = [
        "",
        "event: ping",
        "data:",
        "data: [DONE]",
        "data: not-json",
        'data: {"choices": "not-a-list"}',
        'data: {"choices": ["not-a-dict"]}',
        'data: {"choices": [{"delta": "not-a-dict"}]}',
        'data: {"choices": [{"delta": {"audio": {"data": 123}}}]}',
    ]
    for line in ignored:
        OpenRouterTTSAdapter._collect_audio_line(line, chunks)
    assert chunks == []

    OpenRouterTTSAdapter._collect_audio_line(
        'data: {"choices": [{"delta": {"audio": {"data": "QUJD"}}}]}', chunks
    )
    assert chunks == ["QUJD"]


# ── chat-audio URL/format helpers ──────────────────────────────────────────


def test_join_api_path_variants() -> None:
    with pytest.raises(VoiceProviderError, match="No endpoint URL configured"):
        _join_api_path("", "chat/completions")
    assert _join_api_path("https://x.example/v1", "chat/completions") == (
        "https://x.example/v1/chat/completions"
    )
    assert _join_api_path("https://x.example/v1/", "/chat/completions") == (
        "https://x.example/v1/chat/completions"
    )
    assert _join_api_path("https://x.example/v1/chat/completions", "chat/completions") == (
        "https://x.example/v1/chat/completions"
    )
    assert _join_api_path("https://x.example/v1?k=v", "chat/completions") == (
        "https://x.example/v1/chat/completions?k=v"
    )
    assert (
        _join_api_path("https://x.example/v1/chat/completions?k=v", "chat/completions")
        == "https://x.example/v1/chat/completions?k=v"
    )


@pytest.mark.parametrize(
    ("response_format", "expected"),
    [("pcm", "pcm16"), ("PCM", "pcm16"), ("", "mp3"), ("wav", "wav")],
)
def test_chat_audio_format_mapping(response_format: str, expected: str) -> None:
    assert _chat_audio_format(response_format) == expected


# ── OpenAICompatSTTAdapter: request construction and parsing ───────────────


@pytest.mark.asyncio
async def test_stt_missing_base_url_and_empty_audio_raise_before_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, json={"text": "x"})))
    with pytest.raises(VoiceProviderError, match="No endpoint URL configured for STT."):
        await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config(base_url=""))
    with pytest.raises(VoiceProviderError, match="No audio data to transcribe."):
        await OpenAICompatSTTAdapter().transcribe(b"", _stt_config())
    assert calls == []


@pytest.mark.asyncio
async def test_stt_transport_timeout_wraps_as_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(_index: int, _call: dict[str, Any]) -> httpx.Response:
        raise httpx.TimeoutException("write timed out")

    _capture_post(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match="STT request error"):
        await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config())


@pytest.mark.asyncio
async def test_stt_http_error_raises_transcription_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(monkeypatch, _static(httpx.Response(500, text="server exploded")))
    with pytest.raises(VoiceProviderHTTPError) as excinfo:
        await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config())
    assert excinfo.value.status_code == 500
    assert str(excinfo.value).startswith("Transcription failed with HTTP 500")


@pytest.mark.asyncio
async def test_stt_bare_text_response_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(monkeypatch, _static(httpx.Response(200, text="  hello there \n")))
    text = await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config())
    assert text == "hello there"


@pytest.mark.asyncio
async def test_stt_json_choices_message_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(
        monkeypatch,
        _static(httpx.Response(200, json={"choices": [{"message": {"content": " from chat "}}]})),
    )
    text = await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config())
    assert text == "from chat"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{"error": "boom"}, ["not", "a", "dict"]],
)
async def test_stt_json_without_usable_text_raises(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    _capture_post(monkeypatch, _static(httpx.Response(200, json=body)))
    with pytest.raises(VoiceProviderError, match="no `text` field"):
        await OpenAICompatSTTAdapter().transcribe(b"audio", _stt_config())


@pytest.mark.asyncio
async def test_stt_multipart_includes_language_and_extra_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, json={"text": "ok"})))
    await OpenAICompatSTTAdapter().transcribe(
        b"RIFFxxxx",
        _stt_config(language="en", extra_headers={"X-Reply-Format": "v2"}),
        filename="a.wav",
        content_type="audio/wav",
    )
    assert calls[0]["url"] == "https://api.example.com/v1/audio/transcriptions"
    assert calls[0]["files"]["file"] == ("a.wav", b"RIFFxxxx", "audio/wav")
    assert calls[0]["data"]["language"] == "en"
    assert calls[0]["data"]["response_format"] == "json"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["headers"]["X-Reply-Format"] == "v2"


@pytest.mark.asyncio
async def test_stt_base64_json_includes_language_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, json={"text": "ok"})))
    await OpenAICompatSTTAdapter().transcribe(
        b"audiobytes",
        _stt_config(request_style=STT_BASE64_JSON, language="fr"),
        filename="clip.webm",
    )
    assert calls[0].get("files") is None
    assert calls[0]["json"]["language"] == "fr"
    assert calls[0]["json"]["input_audio"] == {
        "data": base64.b64encode(b"audiobytes").decode("ascii"),
        "format": "webm",
    }
    assert calls[0]["headers"]["Content-Type"] == "application/json"


# ── OpenAICompatSTTAdapter.transcribe_cues ─────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_cues_parses_verbose_json_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(
        monkeypatch,
        _static(
            httpx.Response(
                200,
                json={
                    "text": "hello world",
                    "segments": [
                        {"start": 0.0, "end": 1.2, "text": "hello"},
                        {"start": 1.2, "end": 2.0, "text": "world"},
                    ],
                },
            )
        ),
    )
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"RIFFxxxx", _stt_config(), filename="a.wav", content_type="audio/wav"
    )
    assert [(cue.start_seconds, cue.end_seconds, cue.text, cue.timed) for cue in cues] == [
        (0.0, 1.2, "hello", True),
        (1.2, 2.0, "world", True),
    ]


@pytest.mark.asyncio
async def test_transcribe_cues_skips_invalid_segment_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_post(
        monkeypatch,
        _static(
            httpx.Response(
                200,
                json={
                    "text": "good",
                    "segments": [
                        "not-a-dict",
                        {"text": "   "},
                        {"text": "bad-floats", "start": "abc", "end": 1.0},
                        {"text": "negative", "start": -1.0, "end": 1.0},
                        {"text": "reversed", "start": 2.0, "end": 1.0},
                        {"text": "good", "start": 0.5, "end": 1.5},
                    ],
                },
            )
        ),
    )
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"RIFFxxxx", _stt_config(), filename="a.wav", content_type="audio/wav"
    )
    assert [(cue.text, cue.timed) for cue in cues] == [("good", True)]


@pytest.mark.asyncio
async def test_transcribe_cues_verbose_rejected_falls_back_untimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(400, text="response_format not supported")
        return httpx.Response(200, json={"text": "fallback plain"})

    calls = _capture_post(monkeypatch, respond)
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"RIFFxxxx", _stt_config(), filename="a.wav", content_type="audio/wav"
    )
    assert [(cue.text, cue.timed) for cue in cues] == [("fallback plain", False)]
    assert calls[0]["data"]["response_format"] == "verbose_json"
    assert calls[1]["data"]["response_format"] == "json"


@pytest.mark.asyncio
async def test_transcribe_cues_without_segments_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, json={"text": "whole clip"})))
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"RIFFxxxx", _stt_config(), filename="a.wav", content_type="audio/wav"
    )
    assert [(cue.text, cue.timed) for cue in cues] == [("whole clip", False)]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_transcribe_cues_invalid_json_body_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(index: int, _call: dict[str, Any]) -> httpx.Response:
        if index == 0:
            return httpx.Response(
                200, text="not-json{", headers={"content-type": "application/json"}
            )
        return httpx.Response(200, json={"text": "recovered"})

    _capture_post(monkeypatch, respond)
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"RIFFxxxx", _stt_config(), filename="a.wav", content_type="audio/wav"
    )
    assert [(cue.text, cue.timed) for cue in cues] == [("recovered", False)]


@pytest.mark.asyncio
async def test_transcribe_cues_base64_style_uses_plain_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_post(monkeypatch, _static(httpx.Response(200, json={"text": "b64 path"})))
    cues = await OpenAICompatSTTAdapter().transcribe_cues(
        b"audiobytes", _stt_config(request_style=STT_BASE64_JSON), filename="clip.webm"
    )
    assert [(cue.text, cue.timed) for cue in cues] == [("b64 path", False)]
    assert len(calls) == 1
    assert "input_audio" in calls[0]["json"]
