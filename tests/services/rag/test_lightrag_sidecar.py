"""The sidecar mapper must round-trip frozen blocks or reject lossy payloads."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
from typing import Any

import pytest

from deeptutor.services.rag.pipelines.lightrag import sidecar as sidecar_module
from deeptutor.services.rag.pipelines.lightrag.sidecar import (
    SidecarMappingError,
    build_ir,
)

_IR_CLASS_NAMES = (
    "AssetSpec",
    "IRBlock",
    "IRDoc",
    "IRDrawing",
    "IREquation",
    "IRPosition",
    "IRTable",
)


class _FakeIR:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


@pytest.fixture
def fake_ir(monkeypatch: pytest.MonkeyPatch) -> dict[str, type]:
    classes = {name: type(name, (_FakeIR,), {}) for name in _IR_CLASS_NAMES}
    package = types.ModuleType("lightrag")
    sidecar = types.ModuleType("lightrag.sidecar")
    ir = types.ModuleType("lightrag.sidecar.ir")
    for name, cls in classes.items():
        setattr(ir, name, cls)
    package.sidecar = sidecar
    sidecar.ir = ir
    monkeypatch.setitem(sys.modules, "lightrag", package)
    monkeypatch.setitem(sys.modules, "lightrag.sidecar", sidecar)
    monkeypatch.setitem(sys.modules, "lightrag.sidecar.ir", ir)
    return classes


def _bundle(
    tmp_path: Path, blocks: list[Any], manifest: dict[str, Any] | None = None
) -> tuple[dict[str, Any], Path]:
    (tmp_path / "blocks.json").write_text(json.dumps(blocks), encoding="utf-8")
    resolved = dict(manifest or {})
    resolved.setdefault("blocks", {"path": "blocks.json"})
    return resolved, tmp_path


@pytest.mark.parametrize("blocks_record", [None, "blocks.json"])
def test_blocks_record_must_be_a_mapping(
    fake_ir: dict[str, type], tmp_path: Path, blocks_record: Any
) -> None:
    (tmp_path / "blocks.json").write_text("[]", encoding="utf-8")
    manifest: dict[str, Any] = {}
    if blocks_record is not None:
        manifest["blocks"] = blocks_record
    with pytest.raises(SidecarMappingError, match="requires a blocks payload"):
        build_ir(manifest, tmp_path)


def test_non_array_blocks_payload_is_rejected(fake_ir: dict[str, type], tmp_path: Path) -> None:
    (tmp_path / "blocks.json").write_text(json.dumps({"blocks": []}), encoding="utf-8")
    with pytest.raises(SidecarMappingError, match="not an array"):
        build_ir({"blocks": {"path": "blocks.json"}}, tmp_path)


@pytest.mark.parametrize(
    "blocks",
    [
        ["not-an-object"],
        [{"text": "   "}],
    ],
)
def test_malformed_blocks_are_rejected(
    fake_ir: dict[str, type], tmp_path: Path, blocks: list[Any]
) -> None:
    manifest, bundle = _bundle(tmp_path, blocks)
    with pytest.raises(SidecarMappingError):
        build_ir(manifest, bundle)


def test_unknown_block_type_with_text_is_preserved(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "watermark", "text": "DRAFT"}])
    doc = build_ir(manifest, bundle)
    assert doc.blocks[0].content_template == "DRAFT"


@pytest.mark.parametrize("block", [{"type": "watermark"}, {"label": " "}])
def test_unknown_block_without_text_is_rejected(
    fake_ir: dict[str, type], tmp_path: Path, block: dict[str, Any]
) -> None:
    manifest, bundle = _bundle(tmp_path, [block])
    with pytest.raises(SidecarMappingError, match="no preservable text"):
        build_ir(manifest, bundle)


def test_headings_build_hierarchy_and_capture_document_title(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {"type": "title", "text": "## Deep Guide", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "intro body"},
            {"type": "section_header", "text": "Details", "text_level": 2, "page_idx": 1},
            {"type": "aside_text", "text": "note"},
        ],
    )
    doc = build_ir(manifest, bundle)
    assert doc.doc_title == "Deep Guide"
    first, second = doc.blocks
    assert first.heading == "Deep Guide"
    assert first.level == 1
    assert first.parent_headings == []
    assert first.content_template == "# Deep Guide\nintro body"
    assert [position.anchor for position in first.positions] == ["1"]
    assert second.heading == "Details"
    assert second.level == 2
    assert second.parent_headings == ["Deep Guide"]
    assert second.content_template == "## Details\nnote"
    assert [position.anchor for position in second.positions] == ["2"]


def test_text_with_level_becomes_heading_and_plain_stays_body(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {"type": "text", "text": "Section", "text_level": "3"},
            {"type": "text", "text": "body"},
            {"type": "page_footnote", "text": "fn"},
        ],
    )
    doc = build_ir(manifest, bundle)
    assert len(doc.blocks) == 1
    block = doc.blocks[0]
    assert block.heading == "Section"
    assert block.level == 3
    assert block.content_template == "### Section\nbody\nfn"


def test_list_block_joins_items_and_falls_back_to_text(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {"type": "list", "list_items": ["one", 2, "  "]},
            {"type": "list", "text": "fallback"},
        ],
    )
    doc = build_ir(manifest, bundle)
    assert len(doc.blocks) == 1
    assert doc.blocks[0].content_template == "one\n2\nfallback"


def test_code_block_collects_caption_body_and_footnotes(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {
                "type": "code",
                "code_body": "print(1)",
                "code_caption": "listing",
                "code_footnote": ["note"],
            }
        ],
    )
    doc = build_ir(manifest, bundle)
    assert doc.blocks[0].content_template == "listing\nprint(1)\nnote"


def test_table_block_maps_rows_header_and_caption(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {
                "type": "table",
                "rows": [[{"text": " a "}, "b"], ["c", "d"]],
                "header": [["H1", "H2"]],
                "caption": "cap",
                "table_footnote": ["fn"],
                "page": 2,
            }
        ],
    )
    doc = build_ir(manifest, bundle)
    block = doc.blocks[0]
    table = block.tables[0]
    assert table.rows == [["a", "b"], ["c", "d"]]
    assert table.num_rows == 2
    assert table.num_cols == 2
    assert table.html is None
    assert table.caption == "cap"
    assert table.footnotes == ["fn"]
    assert table.table_header == [["H1", "H2"]]
    assert table.self_ref == "blocks.json#/0"
    assert "{{TBL:tb1}}" in block.content_template
    assert block.positions[0].anchor == "3"


def test_table_html_body_is_kept_without_rows(fake_ir: dict[str, type], tmp_path: Path) -> None:
    html = "<table><tr><td>x</td></tr></table>"
    manifest, bundle = _bundle(
        tmp_path, [{"type": "table", "table_body": html, "num_rows": 1, "num_cols": 1}]
    )
    table = build_ir(manifest, bundle).blocks[0].tables[0]
    assert table.rows is None
    assert table.html == html
    assert table.num_rows == 1
    assert table.num_cols == 1


@pytest.mark.parametrize("body", ["[not json", '{"a": 1}', "plain text", "[]", ["scalar"]])
def test_table_with_unusable_body_is_rejected(
    fake_ir: dict[str, type], tmp_path: Path, body: Any
) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "table", "rows": body}])
    with pytest.raises(SidecarMappingError, match="no usable body"):
        build_ir(manifest, bundle)


def test_table_non_string_rows_are_skipped(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(
        tmp_path, [{"type": "table", "rows": ["not-a-list", ["a", "b"]], "num_rows": 9}]
    )
    table = build_ir(manifest, bundle).blocks[0].tables[0]
    assert table.rows == [["a", "b"]]
    assert table.num_rows == 9


def test_image_blocks_share_one_asset_via_direct_and_manifest_match(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fig.png").write_bytes(b"png")
    manifest, bundle = _bundle(
        tmp_path,
        [
            {"type": "image", "img_path": "assets/fig.png", "caption": "direct"},
            {"type": "chart", "img_path": "fig.png", "captions": ["from captions"]},
        ],
        manifest={"assets": [{"path": "assets/fig.png"}]},
    )
    doc = build_ir(manifest, bundle)
    assert len(doc.assets) == 1
    assert doc.assets[0].ref == "asset-1"
    assert doc.assets[0].suggested_name == "fig.png"
    first, second = doc.blocks[0].drawings
    assert first.asset_ref == second.asset_ref == "asset-1"
    assert first.caption == "direct"
    assert second.caption == "from captions"
    assert first.self_ref == "blocks.json#/0"
    assert second.self_ref == "blocks.json#/1"
    assert "{{IMG:im1}}" in doc.blocks[0].content_template
    assert "{{IMG:im2}}" in doc.blocks[0].content_template


def test_absolute_asset_path_is_rejected(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "image", "img_path": "/elsewhere/pic.png"}])
    with pytest.raises(SidecarMappingError, match="escapes the frozen bundle"):
        build_ir(manifest, bundle)


def test_asset_path_pointing_above_bundle_is_rejected(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "image", "img_path": "../outside.png"}])
    with pytest.raises(SidecarMappingError, match="escapes the frozen bundle"):
        build_ir(manifest, bundle)


def test_ambiguous_asset_basename_is_rejected(fake_ir: dict[str, type], tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "dup.png").write_bytes(b"png")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "dup.png").write_bytes(b"png")
    manifest, bundle = _bundle(
        tmp_path,
        [{"type": "picture", "img_path": "dup.png"}],
        manifest={"assets": [{"path": "extra/dup.png"}]},
    )
    with pytest.raises(SidecarMappingError, match="ambiguous"):
        build_ir(manifest, bundle)


def test_image_without_verified_bundle_asset_is_rejected(
    fake_ir: dict[str, type], tmp_path: Path
) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "image", "img_path": "missing.png"}])
    with pytest.raises(SidecarMappingError, match="no verified bundle asset"):
        build_ir(manifest, bundle)


def test_equation_block_and_inline_variants(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [
            {"type": "equation", "text": "E = mc^2"},
            {"type": "formula", "text": "x_t", "text_format": "inline"},
        ],
    )
    doc = build_ir(manifest, bundle)
    block_eq, inline_eq = doc.blocks[0].equations
    assert block_eq.is_block is True
    assert block_eq.self_ref == "blocks.json#/0"
    assert inline_eq.is_block is False
    assert inline_eq.self_ref == ""
    assert "{{EQ:eq1}}" in doc.blocks[0].content_template
    assert "{{EQI:eq2}}" in doc.blocks[0].content_template


def test_equation_without_latex_is_rejected(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(tmp_path, [{"type": "equation", "text": "   "}])
    with pytest.raises(SidecarMappingError, match="no LaTeX"):
        build_ir(manifest, bundle)


@pytest.mark.parametrize(
    ("item", "expected_anchor", "expected_range"),
    [
        ({"page_idx": 0}, "1", None),
        ({"page_idx": -2}, "-2", None),
        ({"page_idx": True}, None, None),
        ({"page": " 3 "}, "3", None),
        ({"page": "   "}, None, None),
        ({"bbox": [1, "2", 3.5, 4], "page_idx": 4}, "5", [1.0, 2.0, 3.5, 4.0]),
        ({"bbox": [1, 2, 3, "not-a-number"], "page": "7"}, "7", None),
        ({"bbox": [1, 2]}, None, None),
    ],
)
def test_position_mapping_variants(
    fake_ir: dict[str, type],
    item: dict[str, Any],
    expected_anchor: str | None,
    expected_range: list[float] | None,
) -> None:
    position = sidecar_module._position(item)
    if expected_anchor is None and expected_range is None:
        assert position is None
        return
    assert position is not None
    assert position.type == "bbox"
    assert position.anchor == expected_anchor
    if expected_range is None:
        assert getattr(position, "range", None) is None
    else:
        assert position.range == expected_range


def test_document_metadata_from_manifest(fake_ir: dict[str, type], tmp_path: Path) -> None:
    manifest, bundle = _bundle(
        tmp_path,
        [{"type": "text", "text": "hi"}],
        manifest={
            "canonical_filename": "report.PDF",
            "parser": {"engine": "mineru", "parser_signature": "sig-1"},
        },
    )
    doc = build_ir(manifest, bundle)
    assert isinstance(doc, fake_ir["IRDoc"])
    assert doc.document_name == "report.PDF"
    assert doc.document_format == "pdf"
    assert doc.doc_title == "report"
    assert doc.split_option == {"parser": "mineru", "parser_signature": "sig-1"}
    assert doc.bbox_attributes == {"origin": "LEFTTOP", "max": 1000}
