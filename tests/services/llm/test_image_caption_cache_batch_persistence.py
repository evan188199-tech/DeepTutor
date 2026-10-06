"""Batch-cache expiry, write-failure, and duplicate-write semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.llm import image_caption_cache as cache
from deeptutor.services.llm.config import LLMConfig


class Client:
    def __init__(self) -> None:
        self.config = LLMConfig(
            model="vision-test", api_key="test-secret", base_url="https://example.test/v1"
        )


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "parse_cache"
    monkeypatch.setattr(
        cache, "get_path_service", lambda: SimpleNamespace(get_parse_cache_root=lambda: root)
    )
    return root


def images(count: int) -> list[dict[str, str]]:
    return [
        {"base64": f"data{i}", "mimetype": "image/png", "filename": f"{i}.png"}
        for i in range(count)
    ]


async def cached_batch(client: Client, generate) -> list[str]:
    return await cache.complete_image_caption_batch(
        client,
        images(2),
        prompt="Describe each figure",
        system_prompt="Be factual",
        generate=generate,
    )


@pytest.mark.asyncio
async def test_expired_batch_entry_is_regenerated_and_rewritten(cache_root):
    generate_calls = []

    async def generate() -> list[str]:
        generate_calls.append(1)
        return ["alpha", "beta"]

    client = Client()
    assert await cached_batch(client, generate) == ["alpha", "beta"]
    entry = next(cache_root.rglob("*.json"))
    stale = json.loads(entry.read_text())
    stale["version"] = cache._CACHE_VERSION + 1
    entry.write_text(json.dumps(stale))
    assert await cached_batch(client, generate) == ["alpha", "beta"]
    assert len(generate_calls) == 2
    assert json.loads(entry.read_text()) == {"version": 1, "captions": ["alpha", "beta"]}


@pytest.mark.asyncio
async def test_batch_write_failure_keeps_generated_captions(cache_root, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(cache, "atomic_write_json", fail)
    generate_calls = []

    async def generate() -> list[str]:
        generate_calls.append(1)
        return ["alpha", "beta"]

    client = Client()
    assert await cached_batch(client, generate) == ["alpha", "beta"]
    assert not list(cache_root.rglob("*.json"))
    assert await cached_batch(client, generate) == ["alpha", "beta"]
    assert len(generate_calls) == 2


@pytest.mark.asyncio
async def test_concurrent_batch_writes_leave_single_complete_entry(cache_root):
    async def generate() -> list[str]:
        await asyncio.sleep(0)
        return ["alpha", "beta"]

    client = Client()
    results = await asyncio.gather(*(cached_batch(client, generate) for _ in range(8)))
    assert results == [["alpha", "beta"]] * 8
    entries = list(cache_root.rglob("*.json"))
    assert len(entries) == 1
    assert json.loads(entries[0].read_text()) == {"version": 1, "captions": ["alpha", "beta"]}
    assert len(list(entries[0].parent.iterdir())) == 1
