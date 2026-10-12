from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pymupdf
import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag import source_visuals as source_visuals_module
from deeptutor.services.rag.source_visuals import (
    VisualEvidence,
    figure_labels,
    figure_references,
    page_image,
    retrieve_visual,
    source_file,
    source_state,
    source_url,
)
from deeptutor.services.rag.visual_assets import (
    MAX_MODEL_IMAGES,
    VisualAssetStore,
    _sha256_file,
    collect_visual_assets,
)
from deeptutor.services.rag.visual_coverage import coverage_overview, record_coverage


@pytest.fixture
def textbook(tmp_path):
    kb = tmp_path / "kb"
    raw = kb / "raw"
    raw.mkdir(parents=True)
    source = raw / "textbook.pdf"
    pdf = pymupdf.open()
    images = tmp_path / "parse" / "images"
    images.mkdir(parents=True)
    blocks = []
    for i in range(100):
        path = images / f"figure-{i:03d}.png"
        picture = Image.new("RGB", (512, 320), "white")
        draw = ImageDraw.Draw(picture)
        for n in range(20):
            draw.text(
                (20 + (n % 4) * 120, 20 + (n // 4) * 55), f"{i}:{n} / 12 mm", fill=(i, 30, 70)
            )
        picture.save(path)
        page = pdf.new_page()
        page.insert_text((50, 50), f"Figure 1.{i}: Distinct explanation for source {i}")
        page.insert_image(pymupdf.Rect(50, 80, 562, 400), filename=str(path))
        blocks.append(
            {
                "type": "image",
                "img_path": str(path),
                "page_idx": i,
                "image_caption": [f"Figure 1.{i}"],
                "section": f"Chapter {i // 25}",
                "text": f"Distinct explanation for source {i}",
                "group_id": f"panel-{i}",
            }
        )
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 2.5: vector relationship A -> B, distance 12 mm")
    page.draw_line((60, 90), (240, 90))
    page.insert_text((60, 80), "A")
    page.insert_text((240, 80), "B")
    page = pdf.new_page()
    page.insert_text((50, 50), "Table 3.2: measured values")
    page.insert_text((50, 80), "Header: mass (kg) | speed (m/s)")
    page.insert_text((50, 100), "Row A: 2 | 12; note: measured at 20 C")
    table = images / "table.png"
    Image.new("RGB", (14, 11), (80, 120, 60)).save(table)
    page.insert_image(pymupdf.Rect(50, 120, 64, 131), filename=str(table))
    blocks.append(
        {
            "type": "table",
            "img_path": str(table),
            "page_idx": 101,
            "table_caption": ["Table 3.2"],
            "table_body": "<table><tr><th>mass (kg)</th><th>speed (m/s)</th></tr><tr><td>2</td><td>12</td></tr></table>",
            "table_footnote": ["Measured at 20 C"],
        }
    )
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 4.1: (a) first panel; (b) second panel")
    page.draw_rect(pymupdf.Rect(50, 80, 200, 200))
    page.draw_circle(pymupdf.Point(300, 140), 60)
    pdf.save(source, deflate=True)
    pdf.close()
    parsed = ParsedDocument(
        markdown="Textbook",
        blocks=blocks,
        asset_dir=images,
        parser_signature="synthetic-v1",
        engine="synthetic",
    )
    candidates = collect_visual_assets(parsed, source, kb)
    VisualAssetStore(kb).publish(candidates)
    record_coverage(parsed, source, kb, candidates)
    return kb, source, parsed, candidates


def test_complete_retention_exact_early_middle_late_and_cross_language(textbook):
    kb, source, parsed, candidates = textbook
    assert len(candidates) == 101
    for number in (0, 50, 99):
        evidence = retrieve_visual(kb, "kb", source_path=source.name, query=f"请解释图1.{number}")
        assert not evidence.error
        record, pixels = evidence.images[0]
        assert record["asset_id"] == candidates[number].record["asset_id"]
        assert pixels == candidates[number].path.read_bytes()
        assert record["group_id"] == f"panel-{number}"
        assert f"source {number}" in evidence.content
        assert "source_document_id" in evidence.sources[0]
        assert "/files/textbook.pdf" in evidence.sources[0]["url"]
        assert evidence.sources[0]["url"].endswith(f"#page={number + 1}")
    overview = coverage_overview(kb, source_path=source.name, offset=100, limit=20)
    assert overview["total_assets"] == 101
    assert len(overview["assets"]) == 1
    assert overview["documents"][0]["retained_count"] == 101
    assert not overview["documents"][0]["whole_document_verified"]


def test_table_headers_units_notes_and_reference_type_are_preserved(textbook):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="表3.2")
    assert not evidence.error
    assert "<th>mass (kg)</th>" in evidence.content
    assert "<td>12</td>" in evidence.content
    assert "Measured at 20 C" in evidence.content
    assert evidence.images[0][0]["page_number"] == 102
    wrong_kind = retrieve_visual(kb, "kb", source_path=source.name, figure="Figure 3.2")
    assert wrong_kind.error == "not_found"
    assert not wrong_kind.images


def test_multi_panel_group_inspects_the_complete_original_page(textbook):
    kb, source, parsed, _ = textbook
    blocks = []
    for n in (0, 1):
        blocks.append(
            {
                "type": "image",
                "img_path": str(parsed.asset_dir / f"figure-{n:03d}.png"),
                "page_idx": 102,
                "image_caption": [f"Figure 4.1 ({chr(97 + n)})"],
                "group_id": "combined-4.1",
            }
        )
    panels = ParsedDocument(
        markdown="",
        blocks=blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="panels",
        engine="synthetic",
    )
    VisualAssetStore(kb).publish(collect_visual_assets(panels, source, kb))
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="图4.1")
    assert not evidence.error
    assert evidence.sources[0]["page"] == 103
    assert "first panel" in evidence.content and "second panel" in evidence.content
    assert evidence.images[0][0]["kind"] == "source_page"


def test_vector_and_sparse_caption_resolve_original_page_without_cloud(textbook):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="图2.5")
    assert not evidence.error
    assert evidence.images[0][0]["kind"] == "source_page"
    assert evidence.sources[0]["page"] == 101
    assert "distance 12 mm" in evidence.content
    assert evidence.model_message()["content"][1]["type"] == "image_url"
    crop = retrieve_visual(kb, "kb", source_path=source.name, page=101, region=[0, 0, 0.6, 0.3])
    assert not crop.error
    assert crop.images[0][0]["render_scale"] == 4
    assert "A -> B" in crop.content
    assert "region=" in crop.sources[0]["visual_asset_url"]
    assert crop.images[0][1] != evidence.images[0][1]


def test_same_label_in_two_sources_never_silently_substitutes(textbook):
    kb, source, parsed, candidates = textbook
    other = source.with_name("other.pdf")
    other.write_bytes(source.read_bytes())
    second = collect_visual_assets(parsed, other, kb)
    VisualAssetStore(kb).publish(second)
    ambiguous = retrieve_visual(kb, "kb", query="Explain Figure 1.99")
    assert ambiguous.error == "ambiguous_reference"
    assert not ambiguous.images
    assert "other.pdf" in ambiguous.content and "textbook.pdf" in ambiguous.content
    selected = retrieve_visual(kb, "kb", asset_id=candidates[99].record["asset_id"])
    assert not selected.error
    assert selected.images[0][0]["source_path"] == source.name


def test_explicit_page_hash_and_region_are_not_silently_ignored(textbook):
    kb, source, _, candidates = textbook
    wrong_page = retrieve_visual(kb, "kb", source_path=source.name, figure="Figure 1.99", page=1)
    assert wrong_page.error == "not_found"
    wrong_hash = retrieve_visual(
        kb, "kb", asset_id=candidates[99].record["asset_id"], source_hash="other-source"
    )
    assert wrong_hash.error == "source_identity_mismatch"
    region = retrieve_visual(
        kb, "kb", asset_id=candidates[99].record["asset_id"], region=[0, 0, 0.6, 0.3]
    )
    assert not region.error
    assert region.images[0][0]["kind"] == "source_page"
    assert region.images[0][0]["page_number"] == 100


def test_followup_restart_reindex_and_changed_or_missing_source_identity(textbook):
    kb, source, parsed, candidates = textbook
    old = candidates[99].record["asset_id"]
    newer = ParsedDocument(
        markdown=parsed.markdown,
        blocks=parsed.blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="synthetic-v2",
        engine="synthetic",
    )
    VisualAssetStore(kb).publish(collect_visual_assets(newer, source, kb))
    evidence = retrieve_visual(kb, "kb", asset_id=old)
    assert evidence.images[0][0]["asset_id"] == old
    before = source.read_bytes()
    source.write_bytes(before + b"changed")
    assert source_state(kb, candidates[99].record) == "changed"
    failed = retrieve_visual(kb, "kb", asset_id=old)
    assert failed.error == "source_changed" and not failed.images
    with pytest.raises(ValueError, match="changed"):
        page_image(kb, source.name, 1, expected_hash=candidates[0].record["source_document_id"])
    source.unlink()
    assert retrieve_visual(kb, "kb", asset_id=old).error == "source_missing"


def test_coverage_exclusions_unverified_zero_images_and_pure_read(textbook):
    kb, source, parsed, candidates = textbook
    (parsed.asset_dir / "oversize.png").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (parsed.asset_dir / "broken.png").write_bytes(b"not pixels")
    record_coverage(parsed, source, kb, candidates)
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    assert {issue["reason"] for issue in report["issues"]} >= {
        "exceeds_5_mib",
        "unsupported_or_invalid_pixels",
        "table_structure_requires_source_verification",
    }
    report_files = {p: p.read_bytes() for p in (kb / "visual_assets").rglob("*") if p.is_file()}
    coverage_overview(kb, source_path=source.name)
    assert all(p.read_bytes() == data for p, data in report_files.items())
    blank = ParsedDocument(markdown="plain text", engine="text_only")
    record_coverage(blank, source, kb, [])
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    assert report["validated_count"] == 0
    assert not report["whole_document_verified"]
    assert report["page_fallback"]


@pytest.mark.parametrize("region", [[0, 0, 2, 1], [1, 0, 0, 1], [0, 0, float("nan"), 1], [0, 1]])
def test_invalid_regions_are_visible_failures(textbook, region):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, page=1, region=region)
    assert evidence.error == "page_unavailable" and not evidence.images


def test_source_access_is_bounded_to_managed_kb(textbook, tmp_path):
    kb, source, _, _ = textbook
    outside = tmp_path / "private.pdf"
    outside.write_bytes(source.read_bytes())
    (source.parent / "link.pdf").symlink_to(outside)
    for path in ("../private.pdf", str(outside), "link.pdf"):
        with pytest.raises(ValueError):
            page_image(kb, path, 1)


def test_real_rag_tool_exact_grounding_pixels_and_text_only_fallback(textbook, monkeypatch):
    from deeptutor.tools.builtin import RAGTool

    kb, source, _, candidates = textbook
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda _: SimpleNamespace(base_dir=kb.parent, name=kb.name),
    )
    result = asyncio.run(
        RAGTool().execute(
            kb_name=kb.name, query="解释图1.99", source_path=source.name, _vision_supported=True
        )
    )
    assert result.success and result.model_message
    assert result.sources[0]["visual_asset_id"] == candidates[99].record["asset_id"]
    assert "data:image/png;base64," in result.model_message["content"][1]["image_url"]["url"]
    assert "base64" not in json.dumps(result.metadata)
    text_only = asyncio.run(
        RAGTool().execute(kb_name=kb.name, query="Explain Figure 1.99", source_path=source.name)
    )
    assert text_only.success and text_only.model_message is None
    assert "cannot inspect pixels" in text_only.content
    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", lambda _: None)
    denied = asyncio.run(RAGTool().execute(kb_name=kb.name, query="Explain Figure 1.99"))
    assert not denied.success and not denied.sources


def test_coverage_and_page_http_routes_retain_source_guard_and_hash(textbook, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import knowledge

    kb, source, _, candidates = textbook
    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", lambda _: source.parent)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    client = TestClient(app)
    overview = client.get(
        "/api/knowledge-bases/kb/visual-coverage", params={"source_path": source.name}
    )
    assert overview.status_code == 200
    assert overview.json()["total_assets"] == 101
    page = client.get(
        "/api/knowledge-bases/kb/source-page",
        params={
            "source_path": source.name,
            "page": 101,
            "source_hash": candidates[0].record["source_document_id"],
        },
    )
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.headers["x-source-document-id"] == candidates[0].record["source_document_id"]
    invalid = client.get(
        "/api/knowledge-bases/kb/source-page", params={"source_path": "../secret.pdf", "page": 1}
    )
    assert invalid.status_code == 422

    def deny(_):
        raise HTTPException(status_code=403, detail="Access denied")

    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", deny)
    assert client.get("/api/knowledge-bases/kb/visual-coverage").status_code == 403
    assert (
        client.get(
            "/api/knowledge-bases/kb/source-page", params={"source_path": source.name, "page": 1}
        ).status_code
        == 403
    )


@pytest.fixture
def minibook(tmp_path):
    kb = tmp_path / "kb"
    raw = kb / "raw"
    raw.mkdir(parents=True)
    source = raw / "scan.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 9.9 appears here first")
    page.insert_text((50, 80), "Figure 9.8 unique opening marker")
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 9.9 appears here second")
    page.insert_text((50, 80), "Figure 9.7 only closing marker")
    pdf.save(source, deflate=True)
    pdf.close()
    return kb, source


def test_figure_label_extraction_normalizes_and_classifies():
    text = "Fig. 1.2 and Figure 3a vs 图4, Table 5.6 表7-1 and FIG. 1.2 again; p. 12"
    assert figure_labels(text) == ["1.2", "3a", "4", "5.6", "7-1"]
    assert figure_references(text) == [
        "figure:1.2",
        "figure:3a",
        "figure:4",
        "table:5.6",
        "table:7-1",
    ]
    assert figure_labels("no references at all") == []
    assert figure_references("no references at all") == []


def test_retrieve_rejects_missing_or_multiple_exact_references(textbook):
    kb, source, _, _ = textbook
    assert retrieve_visual(kb, "kb").error == "reference_required"
    assert retrieve_visual(kb, "kb", query="nothing specific here").error == "reference_required"
    assert retrieve_visual(kb, "kb", figure="图1.1 图1.2").error == "multiple_references"
    compared = retrieve_visual(kb, "kb", query="compare 图1.1 with 图1.2")
    assert compared.error == "multiple_references"


def test_page_reference_resolves_unique_source_or_asks_for_disambiguation(textbook):
    kb, source, parsed, _ = textbook
    unique = retrieve_visual(kb, "kb", page=1)
    assert not unique.error
    assert unique.images[0][0]["kind"] == "source_page"
    assert unique.images[0][0]["page_number"] == 1
    other = source.with_name("other.pdf")
    other.write_bytes(source.read_bytes())
    VisualAssetStore(kb).publish(collect_visual_assets(parsed, other, kb))
    ambiguous = retrieve_visual(kb, "kb", page=1)
    assert ambiguous.error == "ambiguous_source" and not ambiguous.images
    resolved = retrieve_visual(kb, "kb", page=1, source_path=source.name)
    assert not resolved.error
    assert resolved.images[0][0]["source_path"] == source.name


def test_label_page_scan_prefers_exact_unique_pages_or_reports_choices(minibook):
    kb, source = minibook
    source.with_name("notes.txt").write_text("plain text only", encoding="utf-8")
    ambiguous = retrieve_visual(kb, "kb", source_path=source.name, figure="图9.9")
    assert ambiguous.error == "ambiguous_page"
    assert "pages [1, 2]" in ambiguous.content
    opening = retrieve_visual(kb, "kb", source_path=source.name, figure="图9.8")
    assert not opening.error
    assert opening.images[0][0]["kind"] == "source_page"
    assert opening.images[0][0]["page_number"] == 1
    closing = retrieve_visual(kb, "kb", source_path=source.name, figure="Figure 9.7")
    assert not closing.error
    assert closing.images[0][0]["page_number"] == 2
    non_pdf = retrieve_visual(kb, "kb", source_path="notes.txt", figure="图9.9")
    assert non_pdf.error == "not_found" and not non_pdf.images


def test_missing_asset_bytes_fail_instead_of_claiming_pixels(textbook, monkeypatch):
    kb, source, _, candidates = textbook
    monkeypatch.setattr(VisualAssetStore, "read", lambda self, asset_id: None)
    evidence = retrieve_visual(kb, "kb", asset_id=candidates[50].record["asset_id"])
    assert evidence.error == "pixels_unavailable" and not evidence.images


def test_region_zoom_requires_verified_pdf_page(textbook):
    kb, source, parsed, _ = textbook
    blocks = [
        {"type": "image", "img_path": str(parsed.asset_dir / "figure-000.png"), "page_idx": 0}
    ]
    plain = ParsedDocument(
        markdown="",
        blocks=blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="plain",
        engine="synthetic",
    )
    notes = source.parent / "notes.txt"
    notes.write_text("text only", encoding="utf-8")
    candidates = collect_visual_assets(plain, notes, kb)
    assert candidates
    VisualAssetStore(kb).publish(candidates)
    asset_id = candidates[0].record["asset_id"]
    evidence = retrieve_visual(kb, "kb", asset_id=asset_id)
    assert not evidence.error and evidence.images
    zoom = retrieve_visual(kb, "kb", asset_id=asset_id, region=[0.0, 0.0, 0.5, 0.5])
    assert zoom.error == "region_unavailable" and not zoom.images


def test_model_message_caps_images_and_urls_stay_workspace_scoped():
    assert VisualEvidence(content="text").model_message() is None
    images = [
        (
            {
                "asset_id": f"asset-{n}",
                "source_path": "book.pdf",
                "page_number": n + 1,
                "mime_type": "image/png",
            },
            b"px",
        )
        for n in range(MAX_MODEL_IMAGES + 1)
    ]
    message = VisualEvidence(content="text", images=images).model_message()
    assert message["role"] == "user"
    assert len(message["content"]) == 2 * MAX_MODEL_IMAGES
    assert "asset-2" not in message["content"][0]["text"]
    with_asset = source_url(
        "kb",
        {"asset_id": "a" * 64, "source_path": "book.pdf", "page_number": 1},
        image=True,
    )
    assert f"/api/knowledge-bases/kb/visual-assets/{'a' * 64}" in with_asset
    region_page = source_url(
        "kb",
        {
            "source_path": "book.pdf",
            "page_number": 2,
            "source_document_id": "abc",
            "region": [0.0, 0.0, 0.5, 0.5],
        },
        image=True,
    )
    assert "/source-page?" in region_page
    assert "region=0.0" in region_page
    assert "page=2" in region_page
    assert "source_hash=abc" in region_page
    located = source_url("kb", {"source_path": "book.pdf", "page_number": 3})
    assert located.endswith("#page=3")
    unlocated = source_url("kb", {"source_path": "a b.pdf"})
    assert "files/a%20b.pdf" in unlocated and unlocated.endswith("#page=1")


def test_page_extraction_enforces_encryption_size_decoding_and_identity(minibook, monkeypatch):
    kb, source = minibook
    raw = source.parent
    locked = pymupdf.open()
    locked.new_page().insert_text((50, 50), "sealed page")
    locked.save(
        raw / "locked.pdf",
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="secret",
        user_pw="secret",
    )
    locked.close()
    with pytest.raises(ValueError, match="encrypted"):
        page_image(kb, "locked.pdf", 1)
    huge = raw / "huge.pdf"
    with open(huge, "wb") as handle:
        handle.write(b"%PDF-1.4\n")
        handle.truncate(513 * 1024 * 1024)
    with pytest.raises(ValueError, match="512 MiB"):
        page_image(kb, "huge.pdf", 1)
    huge.unlink()
    (raw / "broken.pdf").write_bytes(b"definitely not a pdf")
    with pytest.raises(ValueError, match="decoded"):
        page_image(kb, "broken.pdf", 1)
    (raw / "notes.txt").write_text("text only", encoding="utf-8")
    with pytest.raises(ValueError, match="PDF sources"):
        page_image(kb, "notes.txt", 1)
    with pytest.raises(ValueError, match="between 1 and"):
        page_image(kb, source.name, 0)
    with pytest.raises(ValueError, match="between 1 and"):
        page_image(kb, source.name, 3)
    real_sha = source_visuals_module._sha256_file
    seen = []

    def shifting(path):
        seen.append(real_sha(path))
        return seen[0] if len(seen) == 1 else "0" * 64

    monkeypatch.setattr(source_visuals_module, "_sha256_file", shifting)
    with pytest.raises(ValueError, match="changed during page inspection"):
        page_image(kb, source.name, 1)
    discovery = retrieve_visual(kb, "kb", source_path="locked.pdf", figure="图9.8")
    assert discovery.error == "page_discovery_limit"


def test_page_image_byte_budget_falls_back_to_jpeg_then_fails(minibook, tmp_path, monkeypatch):
    import random

    kb, source = minibook
    rng = random.Random(7)
    noisy = Image.new("RGB", (800, 600), "white")
    pixels = noisy.load()
    for y in range(600):
        for x in range(800):
            pixels[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    noisy_path = tmp_path / "noisy.png"
    noisy.save(noisy_path)
    budget_pdf = source.parent / "budget.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 545, 792), filename=str(noisy_path))
    doc.save(budget_pdf, deflate=False)
    doc.close()
    record, png = page_image(kb, budget_pdf.name, 1)
    assert record["mime_type"] == "image/png"
    budget = len(png) - 1
    monkeypatch.setattr(source_visuals_module, "MAX_IMAGE_BYTES", budget)
    record, jpeg = page_image(kb, budget_pdf.name, 1)
    assert record["mime_type"] == "image/jpeg"
    assert len(jpeg) <= budget
    monkeypatch.setattr(source_visuals_module, "MAX_IMAGE_BYTES", 512)
    with pytest.raises(ValueError, match="byte budget"):
        page_image(kb, budget_pdf.name, 1)


@pytest.mark.parametrize(
    "region",
    [
        [0.5, 0.0, 0.5, 1.0],
        [0.0, 0.5, 1.0, 0.5],
        [-0.01, 0.0, 0.5, 1.0],
        [0.0, 0.0, 0.5, 1.01],
        [0.0, 0.0, float("inf"), 1.0],
    ],
)
def test_region_boundaries_outside_unit_square_fail_closed(textbook, region):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, page=1, region=region)
    assert evidence.error == "page_unavailable" and not evidence.images


def test_region_boundaries_inside_unit_square_render(minibook):
    kb, source = minibook
    full = page_image(kb, source.name, 1, region=[0.0, 0.0, 1.0, 1.0])
    assert full[0]["region"] == [0.0, 0.0, 1.0, 1.0]
    assert 2 < full[0]["render_scale"] <= 4
    assert "Figure 9.9" in full[0]["text"]
    assert full[1][:4] == b"\x89PNG"
    edge = page_image(kb, source.name, 1, region=[0.75, 0.75, 1.0, 1.0])
    assert edge[0]["region"] == [0.75, 0.75, 1.0, 1.0]
    assert edge[1][:4] == b"\x89PNG"


def test_source_state_and_file_guard_reject_unmanaged_and_escapes(minibook, tmp_path):
    kb, source = minibook
    assert source_state(kb, {"source_path": source.name}) == "unmanaged"
    digest = _sha256_file(source)
    current = {
        "managed_source": True,
        "source_path": source.name,
        "source_document_id": digest,
    }
    assert source_state(kb, current) == "current"
    moved = source.with_name("moved.pdf")
    source.rename(moved)
    assert source_state(kb, current) == "missing"
    moved.rename(source)
    for bad in ("", str(source), "../scan.pdf", "missing.pdf"):
        with pytest.raises(ValueError):
            source_file(kb, bad)
    (source.parent / "sub").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        source_file(kb, "sub/x.pdf")
    assert source_file(kb, source.name) == source


def test_record_coverage_skips_outside_and_unsafe_locations(textbook, tmp_path):
    kb, source, parsed, _ = textbook
    before = {p.name for p in (kb / "visual_assets" / "coverage").iterdir()}
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(source.read_bytes())
    record_coverage(parsed, outside, kb, [])
    assert {p.name for p in (kb / "visual_assets" / "coverage").iterdir()} == before
    escapee = tmp_path / "linked-assets"
    escapee.mkdir()
    rogue = tmp_path / "rogue"
    (rogue / "raw").mkdir(parents=True)
    (rogue / "visual_assets").symlink_to(escapee, target_is_directory=True)
    rogue_copy = rogue / "raw" / "copy.pdf"
    rogue_copy.write_bytes(source.read_bytes())
    with pytest.raises(OSError, match="unsafe"):
        record_coverage(parsed, rogue_copy, rogue, [])
    third = tmp_path / "third"
    (third / "raw").mkdir(parents=True)
    third_copy = third / "raw" / "copy.pdf"
    third_copy.write_bytes(source.read_bytes())
    (third / "visual_assets").mkdir()
    (third / "visual_assets" / "coverage").symlink_to(escapee, target_is_directory=True)
    with pytest.raises(OSError, match="unsafe"):
        record_coverage(parsed, third_copy, third, [])


def test_coverage_records_per_asset_extraction_failures(textbook):
    kb, source, parsed, candidates = textbook
    assets = parsed.asset_dir
    (assets / "linked.png").symlink_to(assets / "figure-000.png")
    (assets / "unreadable.png").write_bytes((assets / "figure-001.png").read_bytes())
    (assets / "unreadable.png").chmod(0o000)
    (assets / "folder.png").mkdir()
    (assets / "ignored.txt").write_text("skip", encoding="utf-8")
    try:
        record_coverage(parsed, source, kb, candidates)
    finally:
        (assets / "unreadable.png").chmod(0o644)
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    flagged = {issue["asset"]: issue for issue in report["issues"] if issue.get("asset")}
    assert flagged["linked.png"]["reason"] == "symbolic_link"
    assert flagged["unreadable.png"]["reason"] == "asset_read_failed"
    assert flagged["unreadable.png"]["status"] == "failed"
    assert flagged["folder.png"]["reason"] == "unsupported_or_invalid_pixels"
    assert "ignored.txt" not in flagged


def test_coverage_flags_unretained_references_and_table_verification(textbook):
    kb, source, parsed, candidates = textbook
    blocks = [
        {"type": "table", "page": "7"},
        {"type": "image", "img_path": str(parsed.asset_dir / "ghost.png")},
        "not-a-dict",
    ]
    custom = ParsedDocument(
        markdown="",
        blocks=blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="audit",
        engine="synthetic",
    )
    record_coverage(custom, source, kb, [])
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    reasons = {issue["reason"]: issue for issue in report["issues"]}
    table_issue = reasons["table_structure_requires_source_verification"]
    assert table_issue["structured_table_available"] is False
    assert table_issue["page"] == "7"
    ghost = reasons["referenced_image_not_retained"]
    assert ghost["page"] is None and ghost["locator"] == "blocks.json#/1"
    assert len(report["issues"]) == 2
    assert report["validated_count"] == 0


def test_coverage_overview_falls_back_when_report_missing_stale_or_unsafe(textbook):
    from hashlib import sha256

    kb, source, *_ = textbook
    stale = source.read_bytes() + b"rewritten after extraction"
    source.write_bytes(stale)
    stale_report = coverage_overview(kb, source_path=source.name)["documents"][0]
    assert stale_report["issues"][0]["reason"] == "extraction_coverage_unknown"
    assert stale_report["retained_count"] == 0
    fresh = source.with_name("fresh.pdf")
    fresh.write_bytes(source.read_bytes())
    unknown = coverage_overview(kb, source_path="fresh.pdf")["documents"][0]
    assert unknown["issues"] == [
        {"status": "unverified", "reason": "extraction_coverage_unknown"}
    ]
    assert unknown["page_fallback"] is True
    notes = source.parent / "notes.txt"
    notes.write_text("text only", encoding="utf-8")
    notes_report = coverage_overview(kb, source_path="notes.txt")["documents"][0]
    assert notes_report["page_fallback"] is False
    overview = coverage_overview(kb, offset=10_000, limit=10)
    assert overview["assets"] == []
    assert overview["total_assets"] == 101
    report_file = (
        kb
        / "visual_assets"
        / "coverage"
        / (sha256(b"fresh.pdf").hexdigest() + ".json")
    )
    report_file.symlink_to(report_file.with_suffix(".absent"))
    unsafe = coverage_overview(kb, source_path="fresh.pdf")["documents"][0]
    assert unsafe["issues"][0]["reason"] == "extraction_coverage_unknown"


def test_coverage_overview_refuses_symlinked_raw_directory(textbook):
    kb, source, *_ = textbook
    real = kb / "raw-real"
    (kb / "raw").rename(real)
    (kb / "raw").symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError, match="unsafe"):
        coverage_overview(kb)
