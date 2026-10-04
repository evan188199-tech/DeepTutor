"""Failure-behavior pins for ``RAGService.search`` (DT-22 §3, #1678 context).

The DT-22 silent-error scan flagged the L1 memory-trace block near
``deeptutor/services/rag/service.py`` ``search`` (``except Exception: pass``)
as a degradation point that can mask the real cause of retrieval failures
(#1678: "chat history search fails — existing text cannot be matched").

These tests lock in the CURRENT behavior of the three failure branches around
``search`` without changing any product code:

- retrieval exception  -> raised by the pipeline: propagates unchanged to the
  caller; reported by the pipeline as ``error_type``: returned intact with an
  error status event (visible degradation).
- telemetry failure    -> a failing ``event_sink`` propagates its exception; a
  failure after retrieval completes drops an already-successful result, which
  is indistinguishable from a real retrieval failure from the caller's side.
- memory failure       -> the L1 query trace is best-effort: any failure in
  the memory layer (broken import, unavailable store, failed emit) is
  swallowed and the search still returns normally, so a lost trace is
  invisible to the caller.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from deeptutor.services.rag.service import RAGService

# A known provider that is neither embedding-bound nor PageIndex, so the
# ``with_kb_embedding`` decorator short-circuits and these tests exercise
# ``RAGService.search`` itself instead of the binding layer.
PROVIDER = "weknora"


class TelemetryError(RuntimeError):
    """Raised by the fake event sink to simulate a telemetry outage."""


class FakePipeline:
    """Pipeline double that records queries and fails on demand."""

    def __init__(
        self,
        result: Optional[dict] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.result = result if result is not None else {"answer": "grounded context"}
        self.error = error
        self.queries: list[tuple[str, str]] = []

    async def search(self, query: str, kb_name: str, **kwargs) -> dict:
        self.queries.append((query, kb_name))
        if self.error is not None:
            raise self.error
        return dict(self.result)


class RecordingSink:
    """Event sink double that records events and can fail on a status call."""

    def __init__(self, fail_on_status: Optional[int] = None) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_on_status = fail_on_status
        self.status_count = 0

    async def __call__(self, event_type: str, message: str, metadata: dict) -> None:
        self.events.append(
            {"type": event_type, "message": message, "metadata": dict(metadata or {})}
        )
        if event_type == "status":
            self.status_count += 1
            if self.status_count == self.fail_on_status:
                raise TelemetryError("telemetry sink offline")

    def status_events(self) -> list[dict[str, Any]]:
        return [event for event in self.events if event["type"] == "status"]


class FakeMemoryStore:
    """Memory store double that records L1 events or fails on emit."""

    def __init__(self, emit_error: Optional[BaseException] = None) -> None:
        self.emit_error = emit_error
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        if self.emit_error is not None:
            raise self.emit_error
        self.events.append(event)


def _write_kb_entry(root, name: str = "kb") -> None:
    path = root / "kb_config.json"
    payload = json.loads(path.read_text()) if path.exists() else {"knowledge_bases": {}}
    payload["knowledge_bases"][name] = {
        "path": name,
        "rag_provider": PROVIDER,
        "status": "ready",
    }
    path.write_text(json.dumps(payload))


def _service(root, pipeline: FakePipeline) -> RAGService:
    _write_kb_entry(root)
    service = RAGService(kb_base_dir=str(root), provider=PROVIDER)
    service._pipelines[PROVIDER] = pipeline
    return service


# ---------------------------------------------------------------------------
# Branch 1: retrieval exception (pipeline raises / reports an error result)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_pipeline_exception_propagates_unchanged(tmp_path):
    pipeline_error = RuntimeError("vector index unreadable")
    pipeline = FakePipeline(error=pipeline_error)
    service = _service(tmp_path, pipeline)

    with pytest.raises(RuntimeError) as excinfo:
        await service.search("existing text", "kb")

    # The service-level contract is loud: the pipeline's exception reaches the
    # caller unwrapped, so it is not this branch that masks #1678-style
    # failures — retrieval never degrades into a silent empty result here.
    assert excinfo.value is pipeline_error
    assert pipeline.queries == [("existing text", "kb")]


@pytest.mark.asyncio
async def test_search_pipeline_error_result_is_preserved_and_reported(tmp_path):
    sink = RecordingSink()
    pipeline = FakePipeline(
        result={
            "answer": "Index corrupted; rebuild required.",
            "sources": [],
            "error_type": "index_corruption",
            "needs_reindex": True,
        }
    )
    service = _service(tmp_path, pipeline)

    result = await service.search("existing text", "kb", event_sink=sink)

    # A pipeline-reported failure must stay a failure: the error fields are
    # not stripped and the caller can tell the search degraded.
    assert result["error_type"] == "index_corruption"
    assert result["needs_reindex"] is True
    assert result["provider"] == PROVIDER
    assert result["query"] == "existing text"
    error_events = [
        event for event in sink.status_events() if event["metadata"].get("call_state") == "error"
    ]
    assert len(error_events) == 1
    assert error_events[0]["metadata"]["error_type"] == "index_corruption"
    assert error_events[0]["metadata"]["needs_reindex"] is True
    assert "Index corrupted" in error_events[0]["message"]


# ---------------------------------------------------------------------------
# Branch 2: telemetry failure (event_sink raises)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail_on_status", "retrieval_ran"),
    [(1, False), (3, True)],
    ids=["before-retrieval", "after-retrieval"],
)
async def test_search_telemetry_failure_propagates_and_masks_retrieval(
    tmp_path, fail_on_status, retrieval_ran
):
    sink = RecordingSink(fail_on_status=fail_on_status)
    pipeline = FakePipeline(result={"answer": "grounded context", "sources": []})
    service = _service(tmp_path, pipeline)

    with pytest.raises(TelemetryError, match="telemetry sink offline"):
        await service.search("existing text", "kb", event_sink=sink)

    assert bool(pipeline.queries) is retrieval_ran
    # In the after-retrieval stage the pipeline already produced a healthy
    # result, yet the caller only sees the telemetry exception — a telemetry
    # outage is indistinguishable from a retrieval failure (#1678 symptom).
    if retrieval_ran:
        assert pipeline.queries == [("existing text", "kb")]


@pytest.mark.asyncio
async def test_search_healthy_path_emits_expected_status_sequence(tmp_path):
    sink = RecordingSink()
    pipeline = FakePipeline(result={"answer": "grounded context", "sources": []})
    service = _service(tmp_path, pipeline)

    result = await service.search("existing text", "kb", event_sink=sink)

    assert result["answer"] == "grounded context"
    statuses = [event["message"] for event in sink.status_events()]
    assert len(statuses) == 3
    assert statuses[0].startswith("Query: existing text")
    assert "Retrieving from knowledge base 'kb'" in statuses[1]
    assert "Retrieved 16 characters" in statuses[2]


# ---------------------------------------------------------------------------
# Branch 3: memory failure (L1 query trace is best-effort)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_emits_l1_query_trace_on_success(tmp_path, monkeypatch):
    store = FakeMemoryStore()
    monkeypatch.setattr("deeptutor.services.memory.get_memory_store", lambda: store, raising=False)
    pipeline = FakePipeline(result={"answer": "0123456789abcdef", "sources": []})
    service = _service(tmp_path, pipeline)

    result = await service.search("existing text", "kb")

    assert result["answer"] == "0123456789abcdef"
    assert len(store.events) == 1
    event = store.events[0]
    assert (event.surface, event.kind) == ("kb", "query")
    assert event.payload == {
        "query": "existing text",
        "kb_name": "kb",
        "answer_chars": 16,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["import-broken", "store-unavailable", "emit-failed"], ids=str)
async def test_search_memory_failure_is_silently_swallowed(tmp_path, monkeypatch, mode):
    memory_error = RuntimeError("memory layer down")
    if mode == "import-broken":
        # ``from deeptutor.services.memory import get_memory_store`` fails.
        monkeypatch.delattr("deeptutor.services.memory.get_memory_store", raising=False)
    elif mode == "store-unavailable":

        def broken_factory():
            raise memory_error

        monkeypatch.setattr(
            "deeptutor.services.memory.get_memory_store", broken_factory, raising=False
        )
    else:
        store = FakeMemoryStore(emit_error=memory_error)
        monkeypatch.setattr(
            "deeptutor.services.memory.get_memory_store", lambda: store, raising=False
        )

    pipeline = FakePipeline(result={"answer": "grounded context", "sources": [{"id": "doc-1"}]})
    service = _service(tmp_path, pipeline)

    # Current behavior: every memory-layer failure is swallowed by the
    # best-effort block, the search still returns the full result, and the
    # caller has no way to learn that the L1 trace was lost — the exact
    # silent-degradation finding the DT-22 scan flagged near ``search``.
    result = await service.search("existing text", "kb")

    assert result["query"] == "existing text"
    assert result["answer"] == "grounded context"
    assert result["provider"] == PROVIDER
    assert result["sources"] == [{"id": "doc-1"}]
    assert pipeline.queries == [("existing text", "kb")]
