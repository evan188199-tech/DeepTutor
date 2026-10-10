"""Branch coverage for the DeepTutor LightRAG ingress parser bridge.

Focus: input-format branches of
``deeptutor.services.rag.pipelines.lightrag.parser.DeepTutorParser.parse``
(RAW passthrough vs. structured sidecar), malformed/empty-input degradation,
and the persisted full_docs / ParseResult output contract that the
entity-relation extraction consumes.

The optional ``lightrag-hku`` dependency is replaced by a behaviour-faithful
stub of the exact API surface the parser touches (constants, ``ParseResult``,
``strip_control_characters``, ``make_lightrag_doc_content``,
``sidecar_uri_for``), mirroring lightrag-hku 1.5.7. All bundle construction
runs the real ``ingress.freeze_document`` / ``load_verified_bundle`` code.
Pure logic: no LightRAG instance, no network.
"""

from __future__ import annotations

import abc
import dataclasses
import hashlib
import json
from pathlib import Path
import re
import sys
import types
from urllib.parse import quote

import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.pipelines.lightrag import ingress, sidecar
from deeptutor.services.rag.pipelines.lightrag.ingress import IngressError

FULL_DOCS_FORMAT_RAW = "raw"
FULL_DOCS_FORMAT_LIGHTRAG = "lightrag"
LIGHTRAG_DOC_CONTENT_PREFIX = "{{LRdoc}}"

_SURROGATE_PATTERN = re.compile(r"[\ud800-\udfff\ufffe\uffff]")
_CONTROL_CHAR_PATTERN_ALL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Behaviour-faithful lightrag-hku 1.5.7 stubs (only the surface parser.py uses)
# ---------------------------------------------------------------------------


def _strip_control_characters(text: str, replacement_char: str = "") -> str:
    if not text:
        return text
    text = _SURROGATE_PATTERN.sub(replacement_char, text)
    return _CONTROL_CHAR_PATTERN_ALL.sub(replacement_char, text)


def _make_lightrag_doc_content(merged_text: str) -> str:
    return f"{LIGHTRAG_DOC_CONTENT_PREFIX}{merged_text or ''}"


def _sidecar_uri_for(parsed_artifact_dir: Path | str) -> str:
    resolved = Path(parsed_artifact_dir).resolve()
    return f"file://{quote(str(resolved), safe='/')}/"


@dataclasses.dataclass
class _StubParseResult:
    doc_id: str
    file_path: str
    parse_format: str
    content: str
    blocks_path: str = ""
    parse_engine: str | None = None
    parse_stage_skipped: bool = False
    parse_warnings: dict | None = None
    smartheading_llm_cache_ids: list[str] | None = None

    def to_dict(self) -> dict:
        out = {
            "doc_id": self.doc_id,
            "file_path": self.file_path,
            "parse_format": self.parse_format,
            "content": self.content,
            "blocks_path": self.blocks_path,
        }
        if self.parse_engine is not None:
            out["parse_engine"] = self.parse_engine
        return out


class _StubBaseParser(abc.ABC):
    engine_name: str

    @abc.abstractmethod
    async def parse(self, ctx): ...


def _stub_dataclass(name: str, fields: list[str]) -> type:
    return dataclasses.make_dataclass(name, [(field, object, None) for field in fields])


class _WriterState:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.content = "Sidecar merged text"


def _build_stub_modules() -> tuple[dict[str, types.ModuleType], _WriterState]:
    writer_state = _WriterState()

    constants = types.ModuleType("lightrag.constants")
    constants.FULL_DOCS_FORMAT_RAW = FULL_DOCS_FORMAT_RAW
    constants.FULL_DOCS_FORMAT_LIGHTRAG = FULL_DOCS_FORMAT_LIGHTRAG
    constants.LIGHTRAG_DOC_CONTENT_PREFIX = LIGHTRAG_DOC_CONTENT_PREFIX

    utils = types.ModuleType("lightrag.utils")
    utils.strip_control_characters = _strip_control_characters

    utils_pipeline = types.ModuleType("lightrag.utils_pipeline")
    utils_pipeline.make_lightrag_doc_content = _make_lightrag_doc_content
    utils_pipeline.sidecar_uri_for = _sidecar_uri_for

    parser_base = types.ModuleType("lightrag.parser.base")
    parser_base.BaseParser = _StubBaseParser
    parser_base.ParseResult = _StubParseResult
    parser_base.ResolvedSource = _stub_dataclass(
        "ResolvedSource", ["source_path", "document_name", "parsed_dir"]
    )
    parser_base.ParseContext = _stub_dataclass(
        "ParseContext", ["rag", "doc_id", "file_path", "content_data"]
    )

    ir = types.ModuleType("lightrag.sidecar.ir")
    ir.IRPosition = _stub_dataclass("IRPosition", ["type", "anchor", "range"])
    ir.IRTable = _stub_dataclass(
        "IRTable",
        [
            "placeholder_key",
            "rows",
            "html",
            "num_rows",
            "num_cols",
            "caption",
            "footnotes",
            "table_header",
            "self_ref",
        ],
    )
    ir.IRDrawing = _stub_dataclass(
        "IRDrawing",
        ["placeholder_key", "asset_ref", "fmt", "caption", "footnotes", "src", "self_ref"],
    )
    ir.IREquation = _stub_dataclass(
        "IREquation",
        ["placeholder_key", "latex", "is_block", "caption", "footnotes", "self_ref"],
    )
    ir.AssetSpec = _stub_dataclass("AssetSpec", ["ref", "suggested_name", "source"])
    ir.IRBlock = _stub_dataclass(
        "IRBlock",
        [
            "content_template",
            "heading",
            "level",
            "parent_headings",
            "positions",
            "tables",
            "drawings",
            "equations",
        ],
    )
    ir.IRDoc = _stub_dataclass(
        "IRDoc",
        [
            "document_name",
            "document_format",
            "doc_title",
            "split_option",
            "blocks",
            "assets",
            "bbox_attributes",
        ],
    )

    def fake_write_sidecar(ir_doc, *, parsed_dir, doc_id, engine, **_kwargs):
        base_name = Path(ir_doc.document_name).stem or ir_doc.document_name
        blocks_path = str(Path(parsed_dir) / f"{base_name}.blocks.jsonl")
        writer_state.calls.append(
            {
                "engine": engine,
                "doc_id": doc_id,
                "parsed_dir": str(parsed_dir),
                "document_name": ir_doc.document_name,
                "block_count": len(ir_doc.blocks),
                "asset_count": len(ir_doc.assets),
                "doc_title": ir_doc.doc_title,
            }
        )
        return {
            "doc_id": doc_id,
            "file_path": ir_doc.document_name,
            "parse_format": FULL_DOCS_FORMAT_LIGHTRAG,
            "content": writer_state.content,
            "blocks_path": blocks_path,
        }

    writer = types.ModuleType("lightrag.sidecar.writer")
    writer.write_sidecar = fake_write_sidecar

    modules: dict[str, types.ModuleType] = {}
    for name in (
        "lightrag",
        "lightrag.constants",
        "lightrag.utils",
        "lightrag.utils_pipeline",
        "lightrag.parser",
        "lightrag.parser.base",
        "lightrag.sidecar",
        "lightrag.sidecar.ir",
        "lightrag.sidecar.writer",
    ):
        modules[name] = types.ModuleType(name)
    modules["lightrag.constants"] = constants
    modules["lightrag.utils"] = utils
    modules["lightrag.utils_pipeline"] = utils_pipeline
    modules["lightrag.parser.base"] = parser_base
    modules["lightrag.sidecar.ir"] = ir
    modules["lightrag.sidecar.writer"] = writer
    return modules, writer_state


@pytest.fixture()
def lightrag_stub():
    modules, writer_state = _build_stub_modules()
    saved = {name: sys.modules.get(name) for name in modules}
    try:
        sys.modules.update(modules)
        yield types.SimpleNamespace(modules=modules, writer=writer_state)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _import_parser():
    from deeptutor.services.rag.pipelines.lightrag import parser as parser_module

    return parser_module


# ---------------------------------------------------------------------------
# Bundle construction via the real freeze/verify code
# ---------------------------------------------------------------------------


def _structured_blocks() -> list[dict]:
    return [
        {
            "type": "text",
            "text": "Fixture",
            "text_level": 1,
            "page_idx": 0,
            "bbox": [1, 2, 3, 4],
        },
        {"type": "text", "text": "Body", "page_idx": 0},
        {"type": "list", "list_items": ["one", "two"], "page_idx": 0},
        {
            "type": "table",
            "table_body": "<table><tr><td>A</td></tr></table>",
            "table_caption": ["Table caption"],
            "page_idx": 1,
        },
        {
            "type": "image",
            "img_path": "images/chart.png",
            "image_caption": ["Chart caption"],
            "page_idx": 1,
        },
        {"type": "equation", "text": "x^2", "page_idx": 1},
    ]


def _freeze_raw_bundle(working: Path, source: Path, markdown: str) -> ingress.StagedDocument:
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"raw source bytes")
    parsed = ParsedDocument(
        markdown=markdown,
        blocks=None,
        source_hash="raw-source-sha",
        parser_signature="text-signature",
        engine="text",
    )
    return ingress.freeze_document(working, source, parsed)


def _freeze_structured_bundle(tmp_path: Path, working: Path) -> tuple[ingress.StagedDocument, Path]:
    assets = tmp_path / "parser-assets"
    (assets / "images").mkdir(parents=True, exist_ok=True)
    (assets / "images" / "chart.png").write_bytes(b"image-bytes")
    source = tmp_path / "incoming"
    source.mkdir(exist_ok=True)
    source_file = source / "paper.pdf"
    source_file.write_bytes(b"original pdf")
    parsed = ParsedDocument(
        markdown="# Fixture\n\nBody",
        blocks=_structured_blocks(),
        asset_dir=assets,
        source_hash="source-sha",
        parser_signature="mineru-signature",
        engine="mineru",
    )
    return ingress.freeze_document(working, source_file, parsed), assets


def _edit_manifest(bundle: Path, mutate) -> None:
    manifest_path = bundle / ingress.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _rewrite_bundle_file(bundle: Path, relative: str, payload: bytes) -> None:
    target = bundle / relative
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    def _update(manifest: dict) -> None:
        for record in (manifest.get("markdown"), manifest.get("blocks")):
            if isinstance(record, dict) and record.get("path") == relative:
                record["sha256"] = digest

    _edit_manifest(bundle, _update)


class _RecordingRag:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self.persisted: list[tuple[str, dict]] = []

    async def _persist_parsed_full_docs(self, doc_id: str, payload: dict) -> None:
        self.persisted.append((doc_id, dict(payload)))


class _FakeContext:
    def __init__(
        self, rag: _RecordingRag, source_path: Path, document_name: str, parsed_dir: Path
    ) -> None:
        self.rag = rag
        self.doc_id = "doc-0123456789abcdef0123456789abcdef"
        self.file_path = document_name
        self._resolved = types.SimpleNamespace(
            source_path=source_path,
            document_name=document_name,
            parsed_dir=parsed_dir,
        )
        self.archived: list[str] = []

    def resolve(self, engine_name: str):
        assert engine_name == "deeptutor"
        return self._resolved

    async def archive_source(self, source_path: str) -> None:
        self.archived.append(source_path)


def _context_for(
    tmp_path: Path, working: Path, source_path: Path, document_name: str
) -> tuple[_FakeContext, _RecordingRag, Path]:
    rag = _RecordingRag(working)
    parsed_dir = tmp_path / "artifacts" / f"{Path(document_name).stem}.parsed"
    ctx = _FakeContext(rag, source_path, document_name, parsed_dir)
    return ctx, rag, parsed_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_raw_bundle_persists_raw_format_and_strips_control_characters(
    lightrag_stub, tmp_path
) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    markdown = "# Frozen\x00\n\nBody with\x1c control chars"
    staged = _freeze_raw_bundle(working, tmp_path / "incoming.pdf", markdown)
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "incoming.pdf")

    result = await parser_module.DeepTutorParser().parse(ctx)

    expected = _strip_control_characters(markdown)
    assert len(rag.persisted) == 1
    doc_id, payload = rag.persisted[0]
    assert doc_id == ctx.doc_id
    assert payload["content"] == expected
    assert payload["parse_format"] == FULL_DOCS_FORMAT_RAW
    assert payload["parse_engine"] == "deeptutor"
    assert payload["file_path"] == ctx.file_path
    assert isinstance(payload["update_time"], int)
    assert "sidecar_location" not in payload
    assert result.to_dict()["parse_format"] == FULL_DOCS_FORMAT_RAW
    assert result.content == expected
    assert result.parse_engine == "deeptutor"
    assert ctx.archived == [str(staged.source_path)]
    assert lightrag_stub.writer.calls == []


@pytest.mark.asyncio
async def test_parse_structured_bundle_writes_sidecar_and_persists_lightrag_format(
    lightrag_stub, tmp_path
) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged, _assets = _freeze_structured_bundle(tmp_path, working)
    ctx, rag, parsed_dir = _context_for(tmp_path, working, staged.source_path, "paper.pdf")
    lightrag_stub.writer.content = "Extracted entity-relation input body"

    result = await parser_module.DeepTutorParser().parse(ctx)

    assert len(lightrag_stub.writer.calls) == 1
    call = lightrag_stub.writer.calls[0]
    assert call["engine"] == "deeptutor"
    assert call["doc_id"] == ctx.doc_id
    assert call["parsed_dir"] == str(parsed_dir)
    assert call["document_name"] == "paper.pdf"
    assert call["block_count"] >= 1
    assert call["asset_count"] >= 1

    assert len(rag.persisted) == 1
    _doc_id, payload = rag.persisted[0]
    assert payload["parse_format"] == FULL_DOCS_FORMAT_LIGHTRAG
    assert payload["content"] == (LIGHTRAG_DOC_CONTENT_PREFIX + lightrag_stub.writer.content)
    assert payload["sidecar_location"] == _sidecar_uri_for(parsed_dir)
    assert payload["parse_engine"] == "deeptutor"
    assert payload["file_path"] == ctx.file_path
    assert isinstance(payload["update_time"], int)

    assert result.parse_format == FULL_DOCS_FORMAT_LIGHTRAG
    assert result.content == lightrag_stub.writer.content
    assert result.blocks_path == str(parsed_dir / "paper.blocks.jsonl")
    assert result.parse_engine == "deeptutor"
    assert ctx.archived == [str(staged.source_path)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["symlink", "missing"])
async def test_parse_refuses_non_regular_source(lightrag_stub, tmp_path, mode) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    if mode == "symlink":
        target = tmp_path / "elsewhere.pdf"
        target.write_bytes(b"redirect")
        source = tmp_path / "linked.pdf"
        source.symlink_to(target)
        document_name = "linked.pdf"
    else:
        source = tmp_path / "ghost.pdf"
        document_name = "ghost.pdf"
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, source, document_name)

    with pytest.raises(IngressError):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []


@pytest.mark.asyncio
async def test_parse_rejects_tampered_source_digest(lightrag_stub, tmp_path) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged = _freeze_raw_bundle(working, tmp_path / "incoming.pdf", "# Frozen\n\nBody")
    staged.source_path.write_bytes(b"tampered after freeze")
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "incoming.pdf")

    with pytest.raises(IngressError, match="digest mismatch"):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []


@pytest.mark.asyncio
async def test_parse_rejects_non_dict_source_record(lightrag_stub, tmp_path) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged = _freeze_raw_bundle(working, tmp_path / "incoming.pdf", "# Frozen\n\nBody")
    _edit_manifest(staged.bundle_dir, lambda manifest: manifest.__setitem__("source", "tampered"))
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "incoming.pdf")

    with pytest.raises(IngressError, match="digest mismatch"):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []


@pytest.mark.asyncio
async def test_parse_rejects_empty_raw_document(lightrag_stub, tmp_path) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged = _freeze_raw_bundle(working, tmp_path / "incoming.pdf", "# Frozen\n\nBody")
    markdown_record = json.loads(
        (staged.bundle_dir / ingress.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )["markdown"]
    _rewrite_bundle_file(staged.bundle_dir, markdown_record["path"], b"\n \n\t\n")
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "incoming.pdf")

    with pytest.raises(IngressError, match="empty"):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"[]", b"{}"])
async def test_parse_structured_malformed_blocks_payload_degrades(
    lightrag_stub, tmp_path, payload
) -> None:
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged, _assets = _freeze_structured_bundle(tmp_path, working)
    blocks_record = json.loads(
        (staged.bundle_dir / ingress.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )["blocks"]
    _rewrite_bundle_file(staged.bundle_dir, blocks_record["path"], payload)
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "paper.pdf")

    with pytest.raises(sidecar.SidecarMappingError):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []


@pytest.mark.asyncio
async def test_parse_manifest_without_markdown_record_degrades(lightrag_stub, tmp_path) -> None:
    """A manifest whose markdown record is missing must fail closed.

    The current build surfaces KeyError("markdown") because the record is only
    validated when present; degrading this to IngressError is a fix-card
    candidate, so the assertion accepts both the current and the fixed
    behaviour.
    """
    parser_module = _import_parser()
    working = tmp_path / "version-1"
    staged, _assets = _freeze_structured_bundle(tmp_path, working)
    _edit_manifest(staged.bundle_dir, lambda manifest: manifest.pop("markdown"))
    ctx, rag, _parsed_dir = _context_for(tmp_path, working, staged.source_path, "paper.pdf")

    with pytest.raises((IngressError, KeyError)):
        await parser_module.DeepTutorParser().parse(ctx)

    assert rag.persisted == []
    assert ctx.archived == []
