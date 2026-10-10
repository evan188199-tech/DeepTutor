"""Contract tests for the GraphRAG completion adapter using fake transports.

These tests exercise the adapter's request mapping, response/stream parsing and
capability-cache behaviour against fake transport objects only — no real
provider endpoints are contacted and no credentials are involved.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from pydantic import BaseModel
import pytest

pytest.importorskip("graphrag_llm")

from graphrag_llm.completion.lite_llm_completion import LiteLLMCompletion

from deeptutor.services.rag.pipelines.graphrag import completion_adapter
from deeptutor.services.rag.pipelines.graphrag.completion_adapter import (
    register_completion_adapter,
)
from deeptutor.services.rag.pipelines.graphrag.errors import (
    GraphRagStructuredOutputError,
    GraphRagStructuredOutputTruncatedError,
)


class _Finding(BaseModel):
    summary: str
    explanation: str


class _Report(BaseModel):
    title: str
    summary: str
    findings: list[_Finding]
    rating: int
    rating_explanation: str


class BadRequestError(Exception):
    """Name-compatible provider rejection of an unsupported request parameter."""

    status_code = 400


class RateLimitError(Exception):
    """Name-compatible provider throttling error."""

    status_code = 429


class AuthenticationError(Exception):
    """Name-compatible provider credential rejection."""

    status_code = 401


class _Config:
    def __init__(
        self,
        model_provider: str = "deepseek",
        model: str = "deepseek-v4-flash",
        api_base: str = "https://api.deepseek.com",
    ) -> None:
        self.model_provider = model_provider
        self.model = model
        self.api_base = api_base


class _MetricsStore:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update_metrics(self, *, metrics) -> None:
        self.updates.append(metrics)


class _Transport:
    """Fake completion transport recording request kwargs without network I/O."""

    def __init__(self, *, response=None, error: BaseException | None = None) -> None:
        self.sync_calls: list[dict] = []
        self.async_calls: list[dict] = []
        self._response = response
        self._error = error

    def _completion(self, **kwargs):
        self.sync_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response

    async def _completion_async(self, **kwargs):
        self.async_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _report_payload() -> dict:
    return {
        "title": "Compatibility",
        "summary": "The adapter returned structured output.",
        "findings": [{"summary": "Finding", "explanation": "Validated locally."}],
        "rating": 8,
        "rating_explanation": "The response matched the schema.",
    }


def _response(payload: dict | str, *, finish_reason: str | None = "stop") -> SimpleNamespace:
    choices = None
    if finish_reason is not None:
        choices = [SimpleNamespace(finish_reason=finish_reason)]
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=content, formatted_response=None, choices=choices)


def _fake_adapter_instance(
    transport: _Transport,
    *,
    config: _Config | None = None,
    track_metrics: bool = True,
):
    adapter_cls = completion_adapter._get_adapter_class()
    instance = object.__new__(adapter_cls)
    instance._model_config = config or _Config()
    instance._track_metrics = track_metrics
    instance._metrics_store = _MetricsStore()
    instance._completion = transport._completion
    instance._completion_async = transport._completion_async
    return instance


def _fail_native(self, **_kwargs):
    raise AssertionError("native transport must not be reached")


async def _fail_native_async(self, **_kwargs):
    raise AssertionError("native transport must not be reached")


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    completion_adapter.clear_capability_cache()
    yield
    completion_adapter.clear_capability_cache()


# ---------------------------------------------------------------------------
# Capability cache
# ---------------------------------------------------------------------------


def test_capability_cache_keys_are_normalized_per_endpoint() -> None:
    config = _Config(
        model_provider="DeepSeek",
        model="DeepSeek-V4-Flash",
        api_base="https://api.deepseek.com/",
    )
    assert not completion_adapter._uses_json_object(config)

    completion_adapter._remember_json_object(config)

    assert completion_adapter._uses_json_object(config)
    same_endpoint = _Config(
        model_provider="deepseek",
        model="deepseek-v4-flash",
        api_base="https://api.deepseek.com",
    )
    assert completion_adapter._uses_json_object(same_endpoint)

    other_model = _Config(model="deepseek-v4-pro")
    assert not completion_adapter._uses_json_object(other_model)

    completion_adapter.clear_capability_cache()
    assert not completion_adapter._uses_json_object(config)


@pytest.mark.parametrize(
    ("provider", "api_base", "expected"),
    [
        ("anthropic", "https://api.anthropic.com", False),
        ("anthropic", "https://eu.anthropic.com/v1", False),
        ("anthropic", "https://compatible-provider.example/v1", True),
        ("anthropic", "compatible-provider.example/v1", True),
        ("anthropic", "", False),
        ("deepseek", "https://compatible-provider.example/v1", False),
    ],
)
def test_prompt_only_detection_scopes_third_party_anthropic_endpoints(
    provider: str, api_base: str, expected: bool
) -> None:
    config = _Config(provider, "claude-compatible-model", api_base)
    assert completion_adapter._uses_prompt_only_structured_output(config) is expected


# ---------------------------------------------------------------------------
# Request mapping
# ---------------------------------------------------------------------------


def test_schema_instruction_targets_last_user_message_without_mutation() -> None:
    marker = "must match this JSON schema exactly"

    string_messages = completion_adapter._messages_with_schema("Return one report.", _Report)
    assert string_messages.startswith("Return one report.")
    assert marker in string_messages

    original = [
        {"role": "system", "content": "You summarize."},
        {"role": "user", "content": "Return one report."},
    ]
    messages = completion_adapter._messages_with_schema(original, _Report)
    assert messages is not original
    assert messages[-1]["content"].startswith("Return one report.")
    assert marker in messages[-1]["content"]
    assert original[-1]["content"] == "Return one report."

    no_user = [{"role": "system", "content": "You summarize."}]
    messages = completion_adapter._messages_with_schema(no_user, _Report)
    assert messages[-1] == {
        "role": "user",
        "content": completion_adapter._schema_instruction(_Report),
    }

    passthrough = {"messages": "raw"}
    assert completion_adapter._messages_with_schema(passthrough, _Report) is passthrough


def test_format_fallback_kwargs_moves_schema_into_messages_and_drops_response_format() -> None:
    kwargs = {
        "messages": "Return one report.",
        "response_format": _Report,
        "model": "deepseek-v4-flash",
    }

    fallback = completion_adapter._format_fallback_kwargs(kwargs, _Report)

    assert "response_format" not in fallback
    assert "json schema" in fallback["messages"].lower()
    assert fallback["model"] == "deepseek-v4-flash"
    assert kwargs["response_format"] is _Report
    assert kwargs["messages"] == "Return one report."


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_format_response_validates_payload_into_model_instance() -> None:
    response = _response(_report_payload())

    formatted = completion_adapter._format_response(response, _Report)

    assert isinstance(formatted.formatted_response, _Report)
    assert formatted.formatted_response.title == "Compatibility"


def test_format_response_maps_truncation_to_retryable_error() -> None:
    response = _response('{"title": "trunc', finish_reason="length")

    with pytest.raises(GraphRagStructuredOutputTruncatedError) as exc_info:
        completion_adapter._format_response(response, _Report)

    assert exc_info.value.code == "graphrag_model_output_truncated"
    assert exc_info.value.retryable is True


def test_format_response_without_finish_reason_stays_incompatible() -> None:
    response = _response("not json", finish_reason=None)

    with pytest.raises(GraphRagStructuredOutputError) as exc_info:
        completion_adapter._format_response(response, _Report)

    assert not isinstance(exc_info.value, GraphRagStructuredOutputTruncatedError)
    assert exc_info.value.code == "graphrag_model_incompatible"


# ---------------------------------------------------------------------------
# Fallback request construction (sync and async)
# ---------------------------------------------------------------------------


def test_fallback_sync_wraps_request_and_updates_metrics() -> None:
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)
    metrics = {"input_tokens": 3}

    response = completion_adapter._fallback_sync(
        instance,
        {"messages": "Return one report.", "metrics": metrics, "stream": False},
        _Report,
    )

    assert isinstance(response.formatted_response, _Report)
    call = transport.sync_calls[0]
    assert call["metrics"] is metrics
    assert call["response_format_json_object"] is True
    assert "response_format" not in call
    assert len(call["messages"]) == 1
    assert call["messages"][0]["role"] == "user"
    assert call["messages"][0]["content"].startswith("Return one report.")
    assert instance._metrics_store.updates == [metrics]


def test_fallback_sync_skips_metrics_when_tracking_disabled() -> None:
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport, track_metrics=False)

    completion_adapter._fallback_sync(instance, {"messages": "Return one report."}, _Report)

    assert transport.sync_calls[0]["metrics"] is None
    assert instance._metrics_store.updates == []


def test_fallback_sync_rejects_streaming_request() -> None:
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)

    with pytest.raises(ValueError, match="not supported for streaming"):
        completion_adapter._fallback_sync(
            instance,
            {"messages": "Return one report.", "stream": True},
            _Report,
        )

    assert transport.sync_calls == []
    assert instance._metrics_store.updates == []


def test_fallback_async_rejects_streaming_request() -> None:
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)

    with pytest.raises(ValueError, match="not supported for streaming"):
        asyncio.run(
            completion_adapter._fallback_async(
                instance,
                {"messages": "Return one report.", "stream": True},
                _Report,
            )
        )

    assert transport.async_calls == []
    assert instance._metrics_store.updates == []


def test_fallback_async_updates_metrics_when_transport_rejects_credentials() -> None:
    transport = _Transport(error=AuthenticationError("credentials rejected"))
    instance = _fake_adapter_instance(transport)
    metrics = {"input_tokens": 3}

    with pytest.raises(AuthenticationError):
        asyncio.run(
            completion_adapter._fallback_async(
                instance,
                {"messages": "Return one report.", "metrics": metrics},
                _Report,
            )
        )

    assert len(transport.async_calls) == 1
    assert instance._metrics_store.updates == [metrics]


# ---------------------------------------------------------------------------
# Adapter routing
# ---------------------------------------------------------------------------


def test_adapter_passthrough_keeps_native_transport_for_non_schema_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_calls: list[dict] = []
    sentinel = object()

    def _native(self, **kwargs):
        native_calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(LiteLLMCompletion, "completion", _native)
    transport = _Transport()
    instance = _fake_adapter_instance(transport)

    assert instance.completion(messages="hello") is sentinel

    json_object_format = {"type": "json_object"}
    assert instance.completion(messages="hello", response_format=json_object_format) is sentinel
    assert native_calls[-1]["response_format"] == {"type": "json_object"}
    assert transport.sync_calls == []


def test_adapter_uses_cached_json_object_capability_without_native_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(LiteLLMCompletion, "completion", _fail_native)
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)
    completion_adapter._remember_json_object(instance._model_config)

    response = instance.completion(
        messages="Return one report.",
        response_format=_Report,
        stream=False,
    )

    assert isinstance(response.formatted_response, _Report)
    assert transport.sync_calls[0]["response_format_json_object"] is True


def test_adapter_routes_third_party_anthropic_to_prompt_only_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(LiteLLMCompletion, "completion", _fail_native)
    config = _Config("anthropic", "third-party-model", "https://compatible-provider.example/v1")
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport, config=config)

    response = instance.completion(
        messages="Return one report.",
        response_format=_Report,
        stream=False,
    )

    assert isinstance(response.formatted_response, _Report)
    call = transport.sync_calls[0]
    assert call["response_format_json_object"] is False
    assert "response_format" not in call
    assert "json schema" in call["messages"][-1]["content"].lower()


def test_adapter_falls_back_once_when_provider_rejects_schema_and_remembers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_calls: list[dict] = []

    def _native(self, **kwargs):
        native_calls.append(kwargs)
        raise BadRequestError("This response_format type is not supported now")

    monkeypatch.setattr(LiteLLMCompletion, "completion", _native)
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)

    response = instance.completion(
        messages="Return one report.",
        response_format=_Report,
        stream=False,
    )

    assert isinstance(response.formatted_response, _Report)
    assert len(native_calls) == 1
    assert native_calls[0]["response_format"] is _Report
    assert completion_adapter._uses_json_object(instance._model_config)

    instance.completion(
        messages="Return one report.",
        response_format=_Report,
        stream=False,
    )

    assert len(native_calls) == 1
    assert len(transport.sync_calls) == 2


def test_adapter_does_not_fallback_on_rate_limit_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _native(self, **_kwargs):
        raise RateLimitError("rate limited")

    monkeypatch.setattr(LiteLLMCompletion, "completion", _native)
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)

    with pytest.raises(RateLimitError):
        instance.completion(
            messages="Return one report.",
            response_format=_Report,
            stream=False,
        )

    assert transport.sync_calls == []
    assert not completion_adapter._uses_json_object(instance._model_config)


def test_adapter_does_not_fallback_on_authentication_errors_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _native_async(self, **_kwargs):
        raise AuthenticationError("credentials rejected")

    monkeypatch.setattr(LiteLLMCompletion, "completion_async", _native_async)
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)

    with pytest.raises(AuthenticationError):
        asyncio.run(
            instance.completion_async(
                messages="Return one report.",
                response_format=_Report,
                stream=False,
            )
        )

    assert transport.async_calls == []
    assert not completion_adapter._uses_json_object(instance._model_config)


def test_adapter_async_uses_cached_capability_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(LiteLLMCompletion, "completion_async", _fail_native_async)
    transport = _Transport(response=_response(_report_payload()))
    instance = _fake_adapter_instance(transport)
    completion_adapter._remember_json_object(instance._model_config)

    response = asyncio.run(
        instance.completion_async(
            messages="Return one report.",
            response_format=_Report,
            stream=False,
        )
    )

    assert isinstance(response.formatted_response, _Report)
    assert transport.async_calls[0]["response_format_json_object"] is True


def test_get_adapter_class_is_cached_subclass_of_native_completion() -> None:
    first = completion_adapter._get_adapter_class()
    second = completion_adapter._get_adapter_class()

    assert first is second
    assert issubclass(first, LiteLLMCompletion)
    register_completion_adapter()
