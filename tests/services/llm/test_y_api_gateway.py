"""Focused regression tests for the Y-API OpenAI-compatible gateway (#1791).

Y-API is one ``ProviderSpec`` row like the other gateways; the behaviors
these tests lock are the ones its spec alone controls: the Anthropic-format
base override, base/key assembly onto the OpenAI SDK client, chat
completion / stream parsing of its vendor-slashed model ids, and gateway
errors landing in the unified LLM error envelope as ``provider="y_api"``.
"""

from types import SimpleNamespace

from deeptutor.services.llm.error_mapping import map_error
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMRateLimitError,
)
from deeptutor.services.llm.openai_http_client import openai_sdk_client_kwargs
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name

Y_API_DEFAULT_BASE = "https://api.y-api.bestvirtualgoods.com/v1"
Y_API_ANTHROPIC_BASE = "https://api.y-api.bestvirtualgoods.com"


class _GatewayHTTPError(Exception):
    """An OpenAI-SDK-shaped status error, as a gateway relay raises it."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _y_api_completion():
    message = SimpleNamespace(
        content="Review plan ready.",
        reasoning_content=None,
        reasoning=None,
        tool_calls=None,
    )
    return SimpleNamespace(
        model="deepseek/deepseek-v4-flash",
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46),
    )


def _y_api_chunk(content=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(
        content=content,
        reasoning_content=None,
        reasoning=None,
        tool_calls=[],
    )
    return SimpleNamespace(
        model="deepseek/deepseek-v4-flash",
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=usage,
    )


def test_y_api_sdk_client_kwargs_assemble_default_base_and_key() -> None:
    spec = find_by_name("y_api")

    kwargs = openai_sdk_client_kwargs(
        api_key="y-api-key",
        base_url=spec.default_api_base,
        spec=spec,
        sdk_max_retries=0,
    )

    assert kwargs["api_key"] == "y-api-key"
    assert kwargs["base_url"] == Y_API_DEFAULT_BASE
    assert kwargs["max_retries"] == 0
    headers = kwargs["default_headers"]
    assert "x-session-affinity" in headers
    # Y-API is not OpenRouter: no attribution headers leak onto its requests.
    assert "HTTP-Referer" not in headers
    assert "X-OpenRouter-Title" not in headers


def test_y_api_provider_falls_back_to_spec_default_base_and_key() -> None:
    spec = find_by_name("y_api")

    provider = OpenAICompatProvider(
        api_key="y-api-key",
        api_base="",
        spec=spec,
        provider_name="y_api",
        configure_env=False,
    )

    assert provider._effective_base == Y_API_DEFAULT_BASE
    assert str(provider._client.base_url).rstrip("/") == Y_API_DEFAULT_BASE
    assert provider._client.api_key == "y-api-key"


def test_y_api_chat_completion_parse_keeps_content_usage_and_finish() -> None:
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)

    response = provider._parse(_y_api_completion())

    assert response.content == "Review plan ready."
    assert response.finish_reason == "stop"
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }
    assert response.tool_calls == []


def test_y_api_stream_parse_accumulates_content_and_final_usage() -> None:
    final_usage = SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46)
    chunks = [
        _y_api_chunk(content="Review "),
        _y_api_chunk(content="plan ready."),
        # A gateway echoing a zero-filled usage frame on every delta must not
        # overwrite counts; only the real final report counts.
        _y_api_chunk(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)),
        _y_api_chunk(finish_reason="stop"),
        SimpleNamespace(
            model="deepseek/deepseek-v4-flash", choices=[], usage=final_usage
        ),
    ]

    response = OpenAICompatProvider._parse_chunks(chunks)

    assert response.content == "Review plan ready."
    assert response.finish_reason == "stop"
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }


def test_y_api_401_maps_to_unified_authentication_error() -> None:
    mapped = map_error(_GatewayHTTPError("invalid api key", status_code=401), provider="y_api")

    assert isinstance(mapped, LLMAuthenticationError)
    assert mapped.provider == "y_api"
    assert mapped.status_code == 401
    assert str(mapped).startswith("[y_api] ")


def test_y_api_429_maps_to_unified_rate_limit_with_retry_after() -> None:
    error = _GatewayHTTPError("rate limited", status_code=429)
    error.response = type("Response", (), {"headers": {"Retry-After": "7"}})()

    mapped = map_error(error, provider="y_api")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.provider == "y_api"
    assert mapped.status_code == 429
    assert mapped.retry_after == 7.0


def test_y_api_500_maps_to_unified_api_error() -> None:
    mapped = map_error(_GatewayHTTPError("upstream exploded", status_code=500), provider="y_api")

    assert isinstance(mapped, LLMAPIError)
    assert not isinstance(mapped, (LLMAuthenticationError, LLMRateLimitError))
    assert mapped.provider == "y_api"
    assert mapped.status_code == 500
    assert str(mapped).startswith("[y_api] HTTP 500 ")
