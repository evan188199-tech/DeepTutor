"""KnowledgeBaseInitializer orchestration: steps, idempotency, failure states."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.initializer import (
    KnowledgeBaseInitializer,
    initialize_knowledge_base,
)
from deeptutor.knowledge.manager import KnowledgeBaseManager


def _fake_rag_service(monkeypatch, *, succeed=True, error=None, on_initialize=None):
    """Replace initializer.RAGService with an offline recording double."""
    created: list = []

    class FakeRagService:
        def __init__(self, *, kb_base_dir: str, provider: str):
            self.kb_base_dir = kb_base_dir
            self.provider = provider
            self.initialize_kwargs: dict | None = None
            created.append(self)

        async def initialize(self, **kwargs):
            self.initialize_kwargs = kwargs
            if on_initialize is not None:
                on_initialize(kwargs)
            if error is not None:
                raise error
            return succeed

    monkeypatch.setattr("deeptutor.knowledge.initializer.RAGService", FakeRagService)
    return created


def _write_source_doc(directory: Path, name: str, payload: str = "hello") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(payload, encoding="utf-8")
    return path


def test_create_directory_structure_writes_layout_metadata_and_registration(
    tmp_path: Path,
) -> None:
    initializer = KnowledgeBaseInitializer(
        kb_name="orchestration-kb",
        base_dir=str(tmp_path),
        rag_provider="graphrag",
    )

    initializer.create_directory_structure()

    kb_dir = tmp_path / "orchestration-kb"
    assert (kb_dir / "raw").is_dir()

    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "orchestration-kb"
    assert metadata["rag_provider"] == "graphrag"
    assert metadata["needs_reindex"] is False

    entry = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_entry("orchestration-kb")
    assert entry is not None
    assert entry["status"] == "initializing"
    assert entry["progress"]["stage"] == "initializing"
    assert entry["rag_provider"] == "graphrag"


def test_copy_documents_copies_sources_and_skips_missing(tmp_path: Path) -> None:
    initializer = KnowledgeBaseInitializer(kb_name="copy-kb", base_dir=str(tmp_path))
    initializer.create_directory_structure()
    source_dir = tmp_path / "sources"
    first = _write_source_doc(source_dir, "a.txt")
    second = _write_source_doc(source_dir, "notes.md", "notes body")

    copied = initializer.copy_documents([str(first), str(source_dir / "missing.txt"), str(second)])

    raw_dir = tmp_path / "copy-kb" / "raw"
    assert len(copied) == 2
    assert all(Path(path).parent == raw_dir for path in copied)
    assert (raw_dir / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (raw_dir / "notes.md").read_text(encoding="utf-8") == "notes body"


def test_repeated_directory_setup_keeps_existing_registration(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="re-kb",
        status="ready",
        progress={"stage": "completed", "message": "already done", "percent": 100},
    )
    config_file = tmp_path / "kb_config.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    config["knowledge_bases"]["re-kb"]["rag_provider"] = "lightrag"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    initializer = KnowledgeBaseInitializer(
        kb_name="re-kb",
        base_dir=str(tmp_path),
        rag_provider="graphrag",
    )
    initializer.create_directory_structure()
    initializer.create_directory_structure()

    entry = manager.get_kb_entry("re-kb")
    assert entry["status"] == "ready"
    assert entry.get("progress") is None
    reloaded = json.loads(config_file.read_text(encoding="utf-8"))
    assert reloaded["knowledge_bases"]["re-kb"]["rag_provider"] == "lightrag"
    assert list(reloaded["knowledge_bases"]) == ["re-kb"]

    metadata = json.loads((tmp_path / "re-kb" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "re-kb"


@pytest.mark.asyncio
async def test_process_documents_without_documents_marks_error_state(
    tmp_path: Path,
) -> None:
    initializer = KnowledgeBaseInitializer(kb_name="empty-kb", base_dir=str(tmp_path))
    initializer.create_directory_structure()

    with pytest.raises(ValueError, match="No documents found"):
        await initializer.process_documents()

    payload = json.loads((tmp_path / "empty-kb" / ".progress.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "error"
    assert payload["error"] == "No documents found"

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("empty-kb")
    assert status["status"] == "error"


@pytest.mark.asyncio
async def test_process_documents_rag_failure_marks_error_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initializer = KnowledgeBaseInitializer(
        kb_name="fail-kb",
        base_dir=str(tmp_path),
        rag_provider="lightrag",
    )
    initializer.create_directory_structure()
    _write_source_doc(initializer.raw_dir, "doc.md")
    created = _fake_rag_service(monkeypatch, succeed=False)

    with pytest.raises(RuntimeError, match="RAG pipeline returned failure"):
        await initializer.process_documents()

    assert len(created) == 1
    assert created[0].provider == "lightrag"
    assert created[0].kb_base_dir == str(tmp_path)

    payload = json.loads((tmp_path / "fail-kb" / ".progress.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "error"
    assert payload["error"] == "RAG pipeline returned failure"

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("fail-kb")
    assert status["status"] == "error"
    assert status["progress"]["error"] == "RAG pipeline returned failure"


@pytest.mark.asyncio
async def test_process_documents_rag_exception_records_error_and_reraises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initializer = KnowledgeBaseInitializer(
        kb_name="raise-kb",
        base_dir=str(tmp_path),
        rag_provider="llamaindex",
    )
    initializer.create_directory_structure()
    _write_source_doc(initializer.raw_dir, "doc.md")
    _fake_rag_service(monkeypatch, error=RuntimeError("embedding endpoint down"))

    with pytest.raises(RuntimeError, match="embedding endpoint down"):
        await initializer.process_documents()

    payload = json.loads((tmp_path / "raise-kb" / ".progress.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "error"
    assert payload["error"] == "embedding endpoint down"

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("raise-kb")
    assert status["status"] == "error"


@pytest.mark.asyncio
async def test_initialize_knowledge_base_marks_error_and_reraises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_source_doc(tmp_path / "sources", "doc.md")
    _fake_rag_service(monkeypatch, error=ValueError("bad provider binding"))

    with pytest.raises(ValueError, match="bad provider binding"):
        await initialize_knowledge_base(
            kb_name="wrap-err",
            source_files=[str(source)],
            base_dir=str(tmp_path),
            rag_provider="llamaindex",
        )

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("wrap-err")
    assert status["status"] == "error"
    assert status["progress"]["error"] == "bad provider binding"
    assert status["progress"]["percent"] == 0


@pytest.mark.asyncio
async def test_initialize_knowledge_base_success_marks_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_source_doc(tmp_path / "sources", "doc.md")
    created = _fake_rag_service(monkeypatch, succeed=True)

    ok = await initialize_knowledge_base(
        kb_name="wrap-ok",
        source_files=[str(source)],
        base_dir=str(tmp_path),
        rag_provider="llamaindex",
    )

    assert ok is True
    assert len(created) == 1
    assert created[0].provider == "llamaindex"

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("wrap-ok")
    assert status["status"] == "ready"
    assert status["progress"] is None

    entry = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_entry("wrap-ok")
    assert entry["last_indexed_count"] == 1
    assert entry["last_indexed_action"] == "create"
    assert entry["last_completed_at"]

    metadata = json.loads((tmp_path / "wrap-ok" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["rag_provider"] == "llamaindex"
    assert metadata["last_indexed_action"] == "create"
    assert metadata["last_indexed_count"] == 1


@pytest.mark.asyncio
async def test_repeated_full_initialization_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_source_doc(tmp_path / "sources", "doc.md")
    created = _fake_rag_service(monkeypatch, succeed=True)

    for _ in range(2):
        ok = await initialize_knowledge_base(
            kb_name="idem-kb",
            source_files=[str(source)],
            base_dir=str(tmp_path),
            rag_provider="llamaindex",
        )
        assert ok is True

    assert len(created) == 2

    config_file = tmp_path / "kb_config.json"
    reloaded = json.loads(config_file.read_text(encoding="utf-8"))
    assert list(reloaded["knowledge_bases"]) == ["idem-kb"]

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("idem-kb")
    assert status["status"] == "ready"

    raw_dir = tmp_path / "idem-kb" / "raw"
    assert [path.name for path in raw_dir.iterdir()] == ["doc.md"]
