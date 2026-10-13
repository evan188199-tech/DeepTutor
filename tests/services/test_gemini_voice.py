"""Gemini native speech wire format, failure handling and catalog integration."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import wave

import httpx
import pytest

from deeptutor.services.config.provider_runtime import TTS_PROVIDERS, resolve_tts_runtime_config
from deeptutor.services.voice import synthesize_speech
from deeptutor.services.voice.adapters.gemini import GeminiTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import TTSConfig
from deeptutor.services.voice.options import voice_model_options, voice_options
from deeptutor.services.voice.preview import synthesize_preview

NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


def transport(monkeypatch, handler):
    """Intercept actual HTTP requests without calling the speech service."""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def config(**overrides):
    """Build a speech configuration with non-secret test credentials."""
    values = {
        "model": "gemini-2.5-flash-preview-tts",
        "api_key": "test-key",
        "base_url": NATIVE_BASE,
        "voice": "Kore",
        "response_format": "wav",
    }
    return TTSConfig(**(values | overrides))


def success(pcm: bytes = b"\x01\x00\x02\x00", mime: str = "audio/L16;codec=pcm;rate=24000"):
    """Return the documented generateContent audio envelope."""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(pcm).decode()}}
                    ]
                }
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        NATIVE_BASE,
        NATIVE_BASE + "/",
        # The LLM connection default: the vendor's OpenAI-compatible mount.
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ],
)
@pytest.mark.parametrize(
    "fmt,mime", [("wav", "audio/wav"), ("pcm", "audio/pcm;rate=24000;channels=1")]
)
async def test_native_request_and_decoded_audio(monkeypatch, base_url, fmt, mime):
    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == (
            f"{NATIVE_BASE}/models/gemini-2.5-flash-preview-tts:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-key"
        assert json.loads(request.content) == {
            "contents": [{"parts": [{"text": "Hello"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}},
            },
        }
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    audio, content_type = await GeminiTTSAdapter().synthesize(
        "Hello", config(base_url=base_url, voice="Puck", response_format=fmt)
    )
    assert content_type == mime
    if fmt == "wav":
        with wave.open(BytesIO(audio)) as wrapped:
            assert wrapped.getnchannels() == 1
            assert wrapped.getsampwidth() == 2
            assert wrapped.getframerate() == 24000
            assert wrapped.readframes(wrapped.getnframes()) == b"\x01\x00\x02\x00"
    else:
        assert audio == b"\x01\x00\x02\x00"


@pytest.mark.asyncio
async def test_model_prefix_stripped_and_default_voice_used(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    await GeminiTTSAdapter().synthesize(
        "Hello", config(model="models/gemini-2.5-pro-preview-tts", voice="")
    )
    assert str(requests[0].url) == (
        f"{NATIVE_BASE}/models/gemini-2.5-pro-preview-tts:generateContent"
    )
    body = json.loads(requests[0].content)
    assert (
        body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
        == "Kore"
    )


@pytest.mark.asyncio
async def test_instructions_prompt_the_spoken_text(monkeypatch):
    def handle(request):
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["text"] == "Say cheerfully: Hello"
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    await GeminiTTSAdapter().synthesize("Hello", config(instructions="Say cheerfully"))


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [24000, 44100])
async def test_wav_follows_inline_mime_rate(monkeypatch, rate):
    def handle(request):
        return httpx.Response(200, json=success(mime=f"audio/L16;codec=pcm;rate={rate}"))

    transport(monkeypatch, handle)
    audio, _ = await GeminiTTSAdapter().synthesize("Hello", config())
    with wave.open(BytesIO(audio)) as wrapped:
        assert wrapped.getframerate() == rate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"candidates": []},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": "spoken aloud"}]}}]},
        {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"mimeType": "audio/L16", "data": ""}}]}}
            ]
        },
        {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"mimeType": "audio/L16", "data": "!!!"}}]}}
            ]
        },
    ],
)
async def test_rejects_failed_empty_and_malformed_responses(monkeypatch, body):
    def handle(request):
        return httpx.Response(200, text=json.dumps(body) if body is not None else "not-json")

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError) as caught:
        await GeminiTTSAdapter().synthesize("Hello", config())
    assert "test-key" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 429, 500])
async def test_http_failures_map_to_voice_provider_http_error(monkeypatch, status):
    transport(monkeypatch, lambda r: httpx.Response(status, text="private-text test-key"))
    with pytest.raises(VoiceProviderHTTPError) as caught:
        await GeminiTTSAdapter().synthesize("Hello", config())
    assert caught.value.status_code == status
    assert "test-key" not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_is_a_voice_provider_error(monkeypatch):
    def handle(request):
        raise httpx.ReadTimeout("private-text", request=request)

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError, match="timed out"):
        await GeminiTTSAdapter().synthesize("Hello", config())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": " "},
        {"model": "models/"},
        {"model": " "},
        {"response_format": "mp3"},
        {"speed": 1.5},
    ],
)
async def test_invalid_settings_fail_before_http(monkeypatch, overrides):
    def handle(request):
        pytest.fail("Invalid configuration must not issue an HTTP request")

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError):
        await GeminiTTSAdapter().synthesize("Hello", config(**overrides))


def catalog(connection_url: str = ""):
    """Use the same provider connection shape as Settings."""
    return {
        "version": 1,
        "connections": [
            {
                "id": "speech",
                "provider": "gemini",
                "api_key": "test-key",
                "base_url": connection_url,
            }
        ],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {
                            "connection_id": "speech",
                            "binding": "gemini",
                            "default_base_url": NATIVE_BASE,
                        },
                        "models": [{"id": "m", "model": "gemini-2.5-flash-preview-tts"}],
                    }
                ],
            }
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection_url,expected_base",
    [
        # No explicit URL: the TTS table default is written into the profile.
        ("", NATIVE_BASE),
        # The vendor's OpenAI-compatible mount; the adapter rebases it onto the
        # native generateContent route (covered in the adapter tests above).
        (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
    ],
)
async def test_gemini_binding_resolves_to_native_adapter_and_default_base(
    monkeypatch, connection_url, expected_base
):
    resolved = resolve_tts_runtime_config(catalog(connection_url))
    assert resolved.provider_name == "gemini"
    assert resolved.adapter == TTS_PROVIDERS["gemini"].adapter == "gemini_tts"
    assert resolved.model == "gemini-2.5-flash-preview-tts"
    assert resolved.base_url == expected_base
    assert resolved.api_key == "test-key"
    # The catalog stores no format; the provider fallback fixes WAV.
    assert resolved.response_format == "wav"


@pytest.mark.asyncio
async def test_preview_synthesizes_through_native_protocol(monkeypatch):
    """The #1951 flow: preview on a Gemini binding no longer lacks an endpoint."""

    def handle(request):
        assert str(request.url).startswith(f"{NATIVE_BASE}/models/gemini-2.5-flash-preview-tts:")
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    audio, content_type = await synthesize_preview(catalog(), "p", "m", "Hello")
    assert content_type == "audio/wav"
    with wave.open(BytesIO(audio)) as wrapped:
        assert wrapped.getframerate() == 24000


@pytest.mark.asyncio
async def test_read_aloud_uses_catalog_gemini_selection(monkeypatch):
    def handle(request):
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    audio, content_type = await synthesize_speech(
        "Hello world", catalog=catalog(), math_speak=False
    )
    assert content_type == "audio/wav"
    assert audio


def test_settings_offer_speech_models_and_default_voice():
    options = voice_options("gemini", "tts")
    assert [model["id"] for model in options["models"]] == [
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
    ]
    assert options["docs_url"] == "https://ai.google.dev/gemini-api/docs/speech-generation"
    fallback = voice_model_options("gemini", "tts", "models/gemini-3.1-flash-tts-preview")
    assert fallback["formats"] == ["wav", "pcm"]
    assert fallback["voices"] == []


def test_settings_lists_gemini_for_tts_and_connects_the_vendor_credential():
    from deeptutor.api.routers import settings as settings_router

    choices = settings_router._provider_choices()
    gemini = {item["value"]: item for item in choices["tts"]}["gemini"]
    assert gemini["base_url"] == NATIVE_BASE
    assert gemini["default_model"] == "gemini-2.5-flash-preview-tts"
    assert gemini["default_voice"] == "Kore"
    # Gemini is not offered for transcription: there is no native STT adapter.
    assert "gemini" not in {item["value"] for item in choices["stt"]}

    target = {item["provider"]: item for item in settings_router._connection_targets()}["gemini"]
    assert target["services"]["tts"]["provider"] == "gemini"
    assert target["services"]["tts"]["base_url"] == NATIVE_BASE
    assert target["services"]["tts"]["default_voice"] == "Kore"
    assert "stt" not in target["services"]
