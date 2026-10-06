"""Native wire contracts: auth, resource selection, streaming termination and ASR."""

import base64
from copy import deepcopy
import io
import json
import wave

import httpx
import pytest

from deeptutor.services.config.provider_runtime import (
    resolve_stt_runtime_config,
    resolve_tts_runtime_config,
)
from deeptutor.services.voice.adapters.volcengine import VolcengineSTTAdapter, VolcengineTTSAdapter
from deeptutor.services.voice.audio import pcm_to_wav
from deeptutor.services.voice.base import VoiceProviderError
from deeptutor.services.voice.config import STTConfig, TTSConfig
from deeptutor.services.voice.options import voice_model_options


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def tts(**overrides):
    values = {
        "model": "seed-tts-2.0",
        "api_key": "speech-secret",
        "base_url": "https://openspeech.bytedance.com/api/v3",
        "voice": "zh_female_vv_uranus_bigtts",
    }
    return TTSConfig(**(values | overrides))


def stt(**overrides):
    values = {
        "model": "bigmodel",
        "api_key": "speech-secret",
        "base_url": "https://openspeech.bytedance.com/api/v3",
    }
    return STTConfig(**(values | overrides))


def event(code=0, data=None):
    return "data: " + json.dumps({"code": code, "data": data}) + "\n\n"


def failing(exc):
    """A transport handler that raises without producing a response."""

    def handle(request):
        raise exc

    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id,header", [("", "X-Api-Key"), ("legacy", "X-Api-Access-Key")])
async def test_tts_native_auth_resource_language_speed_and_complete_wav(
    monkeypatch, app_id, header
):
    pcm = b"\x00\x00\x01\x00"

    def handle(request):
        assert str(request.url).endswith("/api/v3/tts/unidirectional/sse")
        assert request.headers[header] == "speech-secret"
        assert request.headers["X-Api-Resource-Id"] == "seed-tts-2.0"
        assert "authorization" not in request.headers
        if app_id:
            assert request.headers["X-Api-App-Id"] == app_id
            assert "X-Api-App-Key" not in request.headers
        body = json.loads(request.content)
        params = body["req_params"]
        assert params["audio_params"] == {"format": "pcm", "sample_rate": 16000, "speech_rate": 25}
        assert json.loads(params["additions"]) == {
            "explicit_language": "ja",
            "context_texts": ["Speak gently."],
        }
        assert params["speaker"] == "zh_female_vv_uranus_bigtts"
        return httpx.Response(
            200, text="event: 352\n" + event(data=base64.b64encode(pcm).decode()) + event(20000000)
        )

    transport(monkeypatch, handle)
    audio, mime = await VolcengineTTSAdapter().synthesize(
        "こんにちは",
        tts(
            app_id=app_id,
            response_format="wav",
            sample_rate=16000,
            speed=1.25,
            language="ja",
            instructions="Speak gently.",
        ),
    )
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getframerate() == 16000
        assert wav.readframes(2) == pcm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        event(data="YWJj"),
        event(45000000),
        event(data="invalid!!!") + event(20000000),
        event(20000000),
        "data: not-json\n\n",
    ],
)
async def test_tts_rejects_partial_failed_empty_and_malformed_streams(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, text=body))
    with pytest.raises(VoiceProviderError):
        await VolcengineTTSAdapter().synthesize("hello", tts())


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["", "legacy"])
async def test_stt_base64_upload_and_timestamps(monkeypatch, app_id):
    audio = pcm_to_wav(b"\x00\x00" * 160, 16000)

    def handle(request):
        assert str(request.url).endswith("/auc/bigmodel/recognize/flash")
        assert request.headers["X-Api-Resource-Id"] == "volc.bigasr.auc_turbo"
        assert request.headers["X-Api-Sequence"] == "-1"
        assert request.headers["X-Api-Access-Key" if app_id else "X-Api-Key"] == "speech-secret"
        if app_id:
            assert request.headers["X-Api-App-Key"] == app_id
            assert "X-Api-App-Id" not in request.headers
        body = json.loads(request.content)
        assert base64.b64decode(body["audio"]["data"]) == audio
        assert body["audio"]["language"] == "ja-JP"
        assert body["request"] == {"model_name": "bigmodel", "show_utterances": True}
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={
                "result": {
                    "text": "Hello",
                    "utterances": [{"start_time": 120, "end_time": 1200, "text": "Hello"}],
                }
            },
        )

    transport(monkeypatch, handle)
    config = STTConfig(
        model="bigmodel",
        api_key="speech-secret",
        app_id=app_id,
        language="ja-JP",
        base_url="https://openspeech.bytedance.com/api/v3",
    )
    cues = await VolcengineSTTAdapter().transcribe_cues(audio, config)
    assert (cues[0].start_seconds, cues[0].end_seconds, cues[0].text) == (0.12, 1.2, "Hello")


@pytest.mark.asyncio
@pytest.mark.parametrize("code,success", [("20000003", True), ("45000001", False), (None, False)])
async def test_stt_checks_business_status_even_on_http_200(monkeypatch, code, success):
    transport(
        monkeypatch,
        lambda r: httpx.Response(200, headers={"X-Api-Status-Code": code} if code else {}, json={}),
    )
    config = STTConfig(model="bigmodel", api_key="key", base_url="https://speech.test/api/v3")
    call = VolcengineSTTAdapter().transcribe(pcm_to_wav(b"\0\0", 16000), config)
    if success:
        assert await call == ""
    else:
        with pytest.raises(VoiceProviderError):
            await call


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"voice": ""}, "speaker ID"),
        ({"response_format": "flac"}, "mp3, wav, pcm, or ogg_opus"),
        ({"sample_rate": 11025}, "sample rate"),
        ({"speed": 3}, "between 0.5 and 2"),
        ({"speed": 0.1}, "between 0.5 and 2"),
        ({"speed": float("nan")}, "between 0.5 and 2"),
    ],
)
async def test_tts_rejects_invalid_voice_format_sample_rate_and_speed(
    monkeypatch, overrides, fragment
):
    transport(monkeypatch, lambda r: pytest.fail("no HTTP request expected"))
    with pytest.raises(VoiceProviderError, match=fragment):
        await VolcengineTTSAdapter().synthesize("hello", tts(**overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", ["", "***"])
async def test_missing_speech_credentials_are_rejected_before_any_request(monkeypatch, api_key):
    transport(monkeypatch, lambda r: pytest.fail("no HTTP request expected"))
    with pytest.raises(VoiceProviderError, match="API key"):
        await VolcengineTTSAdapter().synthesize("hello", tts(api_key=api_key))
    with pytest.raises(VoiceProviderError, match="API key"):
        await VolcengineSTTAdapter().transcribe(pcm_to_wav(b"\0\0", 16000), stt(api_key=api_key))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt,mime",
    [
        ("mp3", "audio/mpeg"),
        ("pcm", "audio/pcm;rate=24000;channels=1"),
        ("ogg_opus", "audio/ogg"),
    ],
)
async def test_tts_audio_params_resource_override_and_content_type_mapping(monkeypatch, fmt, mime):
    pcm = b"\x01\x02\x03\x04"

    def handle(request):
        assert request.headers["X-Api-Resource-Id"] == "custom-resource"
        req = json.loads(request.content)["req_params"]
        assert req["audio_params"] == {"format": fmt, "sample_rate": 24000}
        assert "additions" not in req
        return httpx.Response(
            200, text=event(data=base64.b64encode(pcm).decode()) + event(20000000)
        )

    transport(monkeypatch, handle)
    audio, content_type = await VolcengineTTSAdapter().synthesize(
        "hello", tts(response_format=fmt, resource_id="custom-resource")
    )
    assert (audio, content_type) == (pcm, mime)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "respond,fragment",
    [
        (lambda r: httpx.Response(401, text="private speech-secret body"), "code 401"),
        (lambda r: httpx.Response(500, json={"error": "private speech-secret body"}), "code 500"),
        (failing(httpx.ConnectError("connection refused")), "connection failed or timed out"),
        (failing(httpx.ReadTimeout("too slow")), "connection failed or timed out"),
    ],
)
async def test_tts_http_and_transport_failures_do_not_leak_details(monkeypatch, respond, fragment):
    transport(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match=fragment) as caught:
        await VolcengineTTSAdapter().synthesize("private text", tts())
    assert "speech-secret" not in str(caught.value)
    assert "private text" not in str(caught.value)


@pytest.mark.asyncio
async def test_stt_rejects_empty_audio_before_any_request(monkeypatch):
    transport(monkeypatch, lambda r: pytest.fail("no HTTP request expected"))
    with pytest.raises(VoiceProviderError, match="No audio data"):
        await VolcengineSTTAdapter().transcribe(b"", stt())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "respond,fragment",
    [
        (lambda r: httpx.Response(403, text="private speech-secret body"), "code 403"),
        (failing(httpx.ReadTimeout("too slow")), "connection failed or timed out"),
        (
            lambda r: httpx.Response(
                200, headers={"X-Api-Status-Code": "20000000"}, text="{not-json"
            ),
            "Malformed Volcengine STT response",
        ),
        (
            lambda r: httpx.Response(
                200, headers={"X-Api-Status-Code": "20000000"}, json={"result": {}}
            ),
            "no transcript",
        ),
    ],
)
async def test_stt_http_transport_and_payload_failures_do_not_leak_details(
    monkeypatch, respond, fragment
):
    transport(monkeypatch, respond)
    with pytest.raises(VoiceProviderError, match=fragment) as caught:
        await VolcengineSTTAdapter().transcribe(pcm_to_wav(b"\0\0", 16000), stt())
    assert "speech-secret" not in str(caught.value)
    assert "private speech-secret body" not in str(caught.value)


@pytest.mark.asyncio
async def test_stt_cues_skip_unusable_timestamp_rows(monkeypatch):
    def handle(request):
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={
                "result": {
                    "text": "keep drop",
                    "utterances": [
                        {"start_time": 120, "end_time": 1200, "text": "keep"},
                        {"start_time": 2000, "end_time": 500, "text": "backwards"},
                        {"start_time": 300, "text": "no-end"},
                        {"text": "no-times"},
                        {"start_time": "x", "end_time": "y", "text": "junk"},
                        "not-a-dict",
                    ],
                }
            },
        )

    transport(monkeypatch, handle)
    cues = await VolcengineSTTAdapter().transcribe_cues(pcm_to_wav(b"\0\0", 16000), stt())
    assert [(c.start_seconds, c.end_seconds, c.text, c.timed) for c in cues] == [
        (0.12, 1.2, "keep", True)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,utterances,expected",
    [
        ("hello", [], [(0.0, 0.0, "hello", False)]),
        ("", [], []),
        ("   ", [{"start_time": 2000, "end_time": 500, "text": "backwards"}], []),
        (
            "hello",
            [{"start_time": 2000, "end_time": 500, "text": "backwards"}],
            [(0.0, 0.0, "hello", False)],
        ),
    ],
)
async def test_stt_cues_fall_back_to_one_untimed_cue_without_usable_timestamps(
    monkeypatch, text, utterances, expected
):
    def handle(request):
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={"result": {"text": text, "utterances": utterances}},
        )

    transport(monkeypatch, handle)
    cues = await VolcengineSTTAdapter().transcribe_cues(pcm_to_wav(b"\0\0", 16000), stt())
    assert [(c.start_seconds, c.end_seconds, c.text, c.timed) for c in cues] == expected


def catalog(provider="volcengine_speech", model="seed-tts-2.0"):
    return {
        "version": 1,
        "connections": [
            {
                "id": "speech",
                "provider": provider,
                "api_key": "secret",
                "app_id": "legacy",
                "base_url": "",
            }
        ],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {"connection_id": "speech", "binding": provider},
                        "models": [{"id": "m", "model": model}],
                    }
                ],
            }
        },
    }


def test_model_specific_defaults_and_shared_legacy_credentials():
    c = catalog()
    before = deepcopy(c)
    config = resolve_tts_runtime_config(c)
    assert config.provider_name == "volcengine_speech"
    assert config.app_id == "legacy" and config.api_key == "secret"
    assert config.base_url == "https://openspeech.bytedance.com/api/v3"
    assert config.voice == "zh_female_vv_uranus_bigtts"
    assert resolve_tts_runtime_config(catalog(model="seed-tts-1.0")).voice.endswith("moon_bigtts")
    assert (
        resolve_tts_runtime_config(
            catalog("openrouter", "google/gemini-3.1-flash-tts-preview")
        ).voice
        == "Kore"
    )
    assert (
        resolve_tts_runtime_config(catalog("groq", "canopylabs/orpheus-v1-english")).response_format
        == "wav"
    )
    assert c == before
    c["services"]["stt"] = deepcopy(c["services"]["tts"])
    c["services"]["stt"]["profiles"][0]["models"][0]["model"] = "bigmodel"
    assert resolve_stt_runtime_config(c).app_id == "legacy"


def test_voice_choices_are_per_model_and_unknown_models_have_no_false_voice_defaults():
    assert "marin" not in [
        v["id"] for v in voice_model_options("openai", "tts", "tts-1-hd")["voices"]
    ]
    assert "marin" in [
        v["id"]
        for v in voice_model_options("openai", "tts", "gpt-4o-mini-tts-2025-12-15")["voices"]
    ]
    assert voice_model_options("openrouter", "tts", "private/voice-model")["voices"] == []
    assert voice_model_options("dashscope", "tts", "qwen3-tts-instruct-flash")["instructions"]
    assert voice_model_options("siliconflow", "tts", "FunAudioLLM/CosyVoice2-0.5B")["voices"][0][
        "id"
    ].endswith(":alex")


def test_qwen_audio_defaults_and_hints_match_the_selected_model():
    plus = catalog("dashscope", "qwen-audio-3.0-tts-plus")
    before = deepcopy(plus)
    config = resolve_tts_runtime_config(plus)
    assert config.voice == "longanlingxin" and config.response_format == "mp3"
    assert plus == before
    options = voice_model_options("dashscope", "tts", "qwen-audio-3.0-tts-plus")
    assert [v["id"] for v in options["voices"]] == ["longanlingxin", "longanlufeng"]
    assert options["docs_url"].endswith("qwen-audio-tts-voice-list")
    assert "Beijing" in options["configuration_note"]
    assert (
        resolve_tts_runtime_config(catalog("dashscope", "qwen-audio-3.0-tts-flash")).voice
        == "longanfengyue"
    )
    # Future Qwen-Audio models must not silently acquire Qwen3's Cherry voice.
    assert resolve_tts_runtime_config(catalog("dashscope", "qwen-audio-9.0-tts-plus")).voice == ""


@pytest.mark.parametrize(
    "suffix,service",
    [
        ("tts/unidirectional/sse", "tts"),
        ("auc/bigmodel/recognize/flash", "stt"),
    ],
)
def test_native_full_endpoint_is_preserved_and_shared_base_is_derived(suffix, service):
    from deeptutor.services.config.provider_links import provider_endpoint
    from deeptutor.services.voice.base import join_audio_path

    base = "https://speech.example/api/v3"
    endpoint = f"{base}/{suffix}"
    assert join_audio_path(endpoint + "?region=test", suffix) == endpoint + "?region=test"
    assert provider_endpoint(endpoint, service, "stt" if service == "tts" else "tts") == base


@pytest.mark.asyncio
async def test_preview_enforces_model_text_limit_before_sending():
    from deeptutor.services.voice.preview import synthesize_preview

    with pytest.raises(ValueError, match="at most 200"):
        await synthesize_preview(
            catalog("groq", "canopylabs/orpheus-v1-english"), "p", "m", "x" * 201
        )


def test_native_speech_credentials_and_model_options_survive_catalog_save(tmp_path):
    from deeptutor.services.config.model_catalog import (
        ModelCatalogService,
        redact_catalog_secrets,
        restore_catalog_secrets,
    )

    store = ModelCatalogService(tmp_path / "catalog.json")
    saved = store.save(catalog())
    restored = restore_catalog_secrets(redact_catalog_secrets(saved), saved)
    loaded = store.save(restored)
    config = resolve_tts_runtime_config(loaded, service=store)
    assert config.api_key == "secret"
    assert config.app_id == "legacy"
    assert config.adapter == "volcengine"
    assert config.model == "seed-tts-2.0"
