"""Videogen adapter registry, selection, and config defaults.

Covers the registry contract in ``deeptutor/services/videogen/adapters/__init__.py``
(built-in keys, singleton lookup, empty-name fallback to ``async_task``,
unknown-name rejection, plugging in a new adapter), the ``VideogenConfig``
defaults including per-instance mutable headers, and the public facades'
invalid-adapter / empty-prompt guards. Everything is mocked — no HTTP, no
real video renders.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.config import provider_runtime
from deeptutor.services.generation_http import AUTH_BEARER, GenerationProviderError
from deeptutor.services.videogen import generate_video, probe_video
from deeptutor.services.videogen.adapters import (
    VIDEOGEN_ADAPTERS,
    DashScopeVideogenAdapter,
    get_videogen_adapter,
)
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.base import BaseVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


class _StubAdapter(BaseVideogenAdapter):
    """Records the calls it receives so facades can be asserted end-to-end."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.configs: list[VideogenConfig] = []

    async def submit_task(self, prompt: str, config: VideogenConfig) -> str:
        self.prompts.append(prompt)
        self.configs.append(config)
        return "stub-task"

    async def generate(
        self,
        prompt: str,
        config: VideogenConfig,
        *,
        progress: Any = None,
    ) -> tuple[bytes, str]:
        self.prompts.append(prompt)
        self.configs.append(config)
        return (b"stub-bytes", "video/mp4")


# ── registry & selection ────────────────────────────────────────────────────


def test_registry_maps_builtin_adapters() -> None:
    assert set(VIDEOGEN_ADAPTERS) == {"async_task", "dashscope"}
    assert isinstance(VIDEOGEN_ADAPTERS["async_task"], AsyncTaskVideogenAdapter)
    assert isinstance(VIDEOGEN_ADAPTERS["dashscope"], DashScopeVideogenAdapter)
    for adapter in VIDEOGEN_ADAPTERS.values():
        assert isinstance(adapter, BaseVideogenAdapter)


def test_get_videogen_adapter_returns_registered_singletons() -> None:
    for name, adapter in VIDEOGEN_ADAPTERS.items():
        assert get_videogen_adapter(name) is adapter


def test_get_videogen_adapter_empty_name_falls_back_to_async_task() -> None:
    assert get_videogen_adapter("") is VIDEOGEN_ADAPTERS["async_task"]


def test_get_videogen_adapter_blank_name_does_not_fall_back() -> None:
    with pytest.raises(GenerationProviderError, match="Unsupported videogen adapter"):
        get_videogen_adapter("  ")


def test_get_videogen_adapter_unknown_name_raises() -> None:
    with pytest.raises(GenerationProviderError, match="Unsupported videogen adapter: 'nope'"):
        get_videogen_adapter("nope")


def test_base_videogen_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseVideogenAdapter()  # type: ignore[abstract]


def test_new_adapters_hook_in_through_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubAdapter()
    monkeypatch.setitem(VIDEOGEN_ADAPTERS, "stub", stub)
    assert get_videogen_adapter("stub") is stub


# ── config defaults ─────────────────────────────────────────────────────────


def test_videogen_config_defaults() -> None:
    config = VideogenConfig(model="seedance")
    assert config.model == "seedance"
    assert config.provider_name == "volcengine"
    assert config.adapter == "async_task"
    assert config.auth_style == AUTH_BEARER
    assert config.api_key == ""
    assert config.base_url == ""
    assert config.api_version is None
    assert config.extra_headers == {}
    assert config.aspect_ratio == ""
    assert config.duration == ""
    assert config.resolution == ""
    assert config.request_timeout == 60
    assert config.poll_interval == 5.0
    assert config.poll_timeout == 600


def test_videogen_config_extra_headers_are_not_shared_between_instances() -> None:
    first = VideogenConfig(model="a")
    second = VideogenConfig(model="b")
    assert first.extra_headers == {} and second.extra_headers == {}
    first.extra_headers["X-Trace"] = "1"
    assert second.extra_headers == {}


# ── facades: selection, fallback and guards ─────────────────────────────────


@pytest.mark.asyncio
async def test_generate_video_facade_rejects_empty_prompt() -> None:
    with pytest.raises(GenerationProviderError, match="empty prompt"):
        await generate_video("   ")


@pytest.mark.asyncio
async def test_facades_route_through_the_selected_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubAdapter()
    monkeypatch.setitem(VIDEOGEN_ADAPTERS, "stub", stub)

    def fake_resolve(catalog: dict[str, Any] | None = None) -> VideogenConfig:
        return VideogenConfig(model="stub-model", adapter="stub")

    monkeypatch.setattr(provider_runtime, "resolve_videogen_runtime_config", fake_resolve)

    assert await probe_video("") == "stub-task"
    assert stub.prompts == ["A short test clip."]

    video, content_type = await generate_video(
        "a wave", aspect_ratio="16:9", duration="5", resolution="720p"
    )
    assert (video, content_type) == (b"stub-bytes", "video/mp4")
    config = stub.configs[-1]
    assert config.model == "stub-model"
    assert (config.aspect_ratio, config.duration, config.resolution) == ("16:9", "5", "720p")


@pytest.mark.asyncio
async def test_generate_video_facade_rejects_unknown_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(catalog: dict[str, Any] | None = None) -> VideogenConfig:
        return VideogenConfig(model="m", adapter="does-not-exist")

    monkeypatch.setattr(provider_runtime, "resolve_videogen_runtime_config", fake_resolve)
    with pytest.raises(GenerationProviderError, match="Unsupported videogen adapter"):
        await generate_video("a wave")
