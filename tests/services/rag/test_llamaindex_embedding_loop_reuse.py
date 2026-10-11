"""Tests for per-thread event loop reuse in the LlamaIndex sync embedding path."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

import pytest


def _patch_fake_client(monkeypatch: pytest.MonkeyPatch, client) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    monkeypatch.setattr(embedding_module, "get_embedding_client", lambda config=None: client)


class _RecordingClient:
    """Fake embedding transport: records the running loop, never touches network."""

    def __init__(self, vectors: list[float] | None = None) -> None:
        self.config = SimpleNamespace(
            binding="openai",
            model="test-embed",
            dim=None,
            effective_url="https://example.test/v1/embeddings",
            base_url="https://example.test/v1/embeddings",
            api_version=None,
            send_dimensions=None,
        )
        self.vectors = vectors or [1.0]
        self.calls: list[list[str]] = []
        self.loop_ids: list[int] = []
        self.thread_ids: list[int] = []

    async def embed(self, texts, progress_callback=None, *, input_type=None):
        del progress_callback, input_type
        self.calls.append(list(texts))
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.thread_ids.append(threading.get_ident())
        await asyncio.sleep(0)
        return [list(self.vectors) for _ in texts]


def test_sync_embedding_reuses_one_loop_per_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    client = _RecordingClient()
    _patch_fake_client(monkeypatch, client)
    embedding = embedding_module.CustomEmbedding()

    embedding._get_query_embedding("question")
    embedding._get_text_embedding("document")
    embedding._get_text_embeddings(["one", "two"])

    assert len(client.loop_ids) == 3
    assert len(set(client.loop_ids)) == 1


def test_sync_embedding_loops_are_isolated_per_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    client = _RecordingClient()
    _patch_fake_client(monkeypatch, client)
    embedding = embedding_module.CustomEmbedding()

    def worker() -> None:
        embedding._get_text_embedding("first")
        embedding._get_text_embedding("second")

    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in [executor.submit(worker) for _ in range(2)]:
            future.result(timeout=10)

    assert len(client.loop_ids) == 4
    # Each executor thread reused one loop across both of its calls...
    for thread_id in set(client.thread_ids):
        loops = {
            loop_id
            for loop_id, seen_in in zip(client.loop_ids, client.thread_ids)
            if seen_in == thread_id
        }
        assert len(loops) == 1
    # ...and the two threads ran on two different loops.
    assert len(set(client.loop_ids)) == 2


def test_sync_embedding_error_keeps_thread_loop_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    class _FailingFirstClient(_RecordingClient):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def embed(self, texts, progress_callback=None, *, input_type=None):
            if not self.failed:
                self.failed = True
                self.loop_ids.append(id(asyncio.get_running_loop()))
                raise RuntimeError("provider unavailable")
            return await super().embed(texts, progress_callback, input_type=input_type)

    client = _FailingFirstClient()
    _patch_fake_client(monkeypatch, client)
    embedding = embedding_module.CustomEmbedding()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        embedding._get_text_embedding("boom")

    assert embedding._get_text_embedding("recovered") == [1.0]
    assert len(client.loop_ids) == 2
    assert client.loop_ids[0] == client.loop_ids[1]


def test_thread_sync_loop_recreates_after_close() -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    first = embedding_module._thread_sync_loop()
    first.close()
    assert first.is_closed()

    second = embedding_module._thread_sync_loop()
    assert second is not first
    assert not second.is_closed()
    second.close()

    third = embedding_module._thread_sync_loop()
    try:
        assert third.run_until_complete(_noop_coro()) is None
    finally:
        third.close()


async def _noop_coro():
    return None


def test_concurrent_multithreaded_embedding_results_stay_correct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    thread_count = 4
    texts_per_thread = 3

    class _MappingClient(_RecordingClient):
        def __init__(self) -> None:
            super().__init__()
            self.in_flight = 0
            self.max_in_flight = 0
            self._guard = threading.Lock()

        async def embed(self, texts, progress_callback=None, *, input_type=None):
            del progress_callback, input_type
            self.calls.append(list(texts))
            self.loop_ids.append(id(asyncio.get_running_loop()))
            self.thread_ids.append(threading.get_ident())
            with self._guard:
                self.in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0.01)
                return [[float(text.rsplit("-", 1)[1])] for text in texts]
            finally:
                with self._guard:
                    self.in_flight -= 1

    client = _MappingClient()
    _patch_fake_client(monkeypatch, client)
    embedding = embedding_module.CustomEmbedding()

    def worker(index: int) -> list[list[float]]:
        texts = [f"thread-{index}-chunk-{n}" for n in range(texts_per_thread)]
        return embedding._get_text_embeddings(texts)

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(worker, i) for i in range(thread_count)]
        results = [future.result(timeout=30) for future in futures]

    for index, vectors in enumerate(results):
        assert vectors == [[float(n)] for n in range(texts_per_thread)]

    assert len(client.calls) == thread_count
    assert all(len(call) == texts_per_thread for call in client.calls)
    # Thread loops must actually run concurrently, not serialize each other.
    assert client.max_in_flight >= 2
