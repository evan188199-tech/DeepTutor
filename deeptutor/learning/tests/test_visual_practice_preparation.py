"""Table-driven preparation coverage for source-bound visual practice (#1611)."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from deeptutor.learning.visual_practice import prepare_visual, public_visual
from deeptutor.services.rag.source_visuals import VisualEvidence

FIGURE_BYTES = b"png-bytes-for-the-original-source-figure"
FIGURE_SHA = sha256(FIGURE_BYTES).hexdigest()

FIGURE_RECORD = {
    "asset_id": "asset-1",
    "source_path": "raw/anatomy.pdf",
    "page_number": 3,
    "source_document_id": "doc-hash-1",
    "region": [0.0, 0.0, 1.0, 1.0],
    "caption": "Figure 1: heart structures",
    "context": "",
    "text": "The artery lies left of the vein.",
    "page_context": "",
    "table_html": "",
    "notes": "",
}


def found_evidence(record: dict | None = None) -> VisualEvidence:
    return VisualEvidence(
        content="Source evidence located.",
        sources=[
            {
                "visual_asset_url": "/visual-assets/asset-1",
                "url": "/files/raw/anatomy.pdf",
            }
        ],
        images=[(dict(record or FIGURE_RECORD), FIGURE_BYTES)],
    )


def base_request() -> dict:
    return {
        "task": "identification",
        "sources": [
            {
                "kb_name": "anatomy",
                "asset_id": "asset-1",
                "source_path": "raw/anatomy.pdf",
                "page": 3,
                "source_hash": "doc-hash-1",
            }
        ],
        "reference_quote": "The artery lies left of the vein.",
        "accepted_answers": ["artery", "an artery"],
        "key_status": "verified",
        "answer_cues": "none",
    }


def install_rag(monkeypatch, *, evidence: VisualEvidence | None = None, accessible: bool = True):
    from deeptutor.multi_user import knowledge_access
    from deeptutor.services.rag import kb_paths, source_visuals

    monkeypatch.setattr(
        knowledge_access,
        "resolve_for_rag",
        (lambda name: SimpleNamespace(base_dir=Path("/data"), name=name))
        if accessible
        else (lambda name: None),
    )
    monkeypatch.setattr(kb_paths, "resolve_kb_dir", lambda base_dir, name: Path("/data") / name)
    payload = evidence if evidence is not None else found_evidence()
    monkeypatch.setattr(
        source_visuals, "retrieve_visual", lambda kb_dir, kb_name, **selectors: payload
    )


def record_with(overrides: dict | None = None) -> dict:
    merged = {**FIGURE_RECORD, **(overrides or {})}
    return {key: value for key, value in merged.items() if value is not None}


PREPARATION_CASES = [
    pytest.param(
        {},
        {},
        {},
        {"inspected_image_hashes": [FIGURE_SHA]},
        {
            "task": "identification",
            "key_status": "verified",
            "answer_cues": "none",
            "pixels_inspected": True,
            "hints_used": 0,
            "reference_answer": "artery",
        },
        ["artery", "an artery"],
        id="verified-identification-key",
    ),
    pytest.param(
        {},
        {},
        {},
        {"inspected_image_hashes": []},
        {
            "key_status": "unverified",
            "answer_cues": "unverified",
            "pixels_inspected": False,
            "hints_used": 1,
        },
        None,
        id="unverified-when-pixels-not-inspected",
    ),
    pytest.param(
        {"asset_id": None},
        {},
        {},
        {"inspected_image_hashes": [FIGURE_SHA]},
        {
            "key_status": "verified",
            "answer_cues": "visible",
            "pixels_inspected": True,
            "hints_used": 1,
        },
        None,
        id="visible-cues-when-page-text-reveals-answer",
    ),
    pytest.param(
        {},
        {"pixels_inspected": True},
        {},
        {"inspected_image_hashes": None},
        {"key_status": "verified", "answer_cues": "none", "pixels_inspected": True},
        None,
        id="declared-inspection-trusted-when-no-hashes",
    ),
    pytest.param(
        {},
        {"pixels_inspected": False},
        {},
        {"inspected_image_hashes": None},
        {"key_status": "unverified", "answer_cues": "unverified", "pixels_inspected": False},
        None,
        id="declared-uninspected-downgrades-key",
    ),
    pytest.param(
        {},
        {},
        {},
        {"expected_answer": "A", "options": {"A": "the artery"}},
        {"key_status": "verified", "reference_answer": "the artery", "hints_used": 0},
        ["the artery", "artery", "an artery"],
        id="choice-option-body-becomes-reference",
    ),
    pytest.param(
        {"text": "The 动脉 lies left of the vein."},
        {"reference_quote": "The 动脉 lies left of the vein.", "accepted_answers": ["动脉", "the artery"]},
        {},
        {"expected_answer": "动脉"},
        {"key_status": "verified", "reference_answer": "动脉", "hints_used": 0},
        ["动脉", "the artery"],
        id="non-ascii-answer-matches-quote",
    ),
    pytest.param(
        {},
        {},
        {},
        {"expected_answer": ""},
        {"key_status": "unverified", "reference_answer": ""},
        ["", "artery", "an artery"],
        id="empty-reference-answer-cannot-verify",
    ),
]


REJECTION_CASES = [
    pytest.param({"task": "maze"}, {}, {}, "Visual tasks support", id="unsupported-task"),
    pytest.param(
        {"sources": "Figure 1"}, {}, {}, "Select one or two exact source figures",
        id="sources-not-a-list",
    ),
    pytest.param(
        {"task": "comparison"}, {}, {}, "requires both original sources",
        id="comparison-needs-two-sources",
    ),
    pytest.param(
        {"sources": ["Figure 1"]}, {}, {}, "Each visual source must be an object",
        id="source-not-an-object",
    ),
    pytest.param(
        {}, {"attached_kbs": ["biology"]}, {}, "attached to this topic/turn",
        id="kb-outside-attached-set",
    ),
    pytest.param({}, {}, {"accessible": False}, "not accessible", id="kb-not-accessible"),
    pytest.param(
        {},
        {},
        {"evidence": VisualEvidence("ambiguous", error="multiple_references")},
        "Cannot establish original visual evidence",
        id="retrieval-error",
    ),
    pytest.param(
        {},
        {},
        {"evidence": VisualEvidence("No figure matched the request.")},
        "Cannot establish original visual evidence",
        id="retrieval-no-images",
    ),
    pytest.param(
        {"accepted_answers": [f"alias {index}" for index in range(13)]},
        {},
        {},
        "at most 12",
        id="too-many-accepted-answers",
    ),
    pytest.param(
        {"answer_cues": "hidden"}, {}, {}, "answer_cues must be none, visible or unverified",
        id="unsupported-answer-cues",
    ),
]


@pytest.mark.parametrize(
    (
        "record_overrides",
        "request_overrides",
        "rag_kwargs",
        "call_overrides",
        "expected",
        "expected_aliases",
    ),
    PREPARATION_CASES,
)
def test_prepare_visual_paths(
    monkeypatch,
    record_overrides,
    request_overrides,
    rag_kwargs,
    call_overrides,
    expected,
    expected_aliases,
):
    install_rag(monkeypatch, evidence=found_evidence(record_with(record_overrides)), **rag_kwargs)
    kwargs = {
        "expected_answer": "artery",
        "options": {},
        "inspected_image_hashes": [FIGURE_SHA],
        **call_overrides,
    }
    context, aliases = prepare_visual({**base_request(), **request_overrides}, **kwargs)
    for key, value in expected.items():
        assert context[key] == value, key
    quote = request_overrides.get("reference_quote") or base_request()["reference_quote"]
    assert context["reference_quote"] == quote
    if expected_aliases is not None:
        assert aliases == expected_aliases
    if not record_overrides:
        source = context["sources"][0]
        assert source["kb_name"] == "anatomy"
        assert source["asset_id"] == "asset-1"
        assert source["source_path"] == "raw/anatomy.pdf"
        assert source["page"] == 3
        assert source["source_hash"] == "doc-hash-1"
        assert source["image_url"] == "/visual-assets/asset-1"
        assert source["url"] == "/files/raw/anatomy.pdf"
        assert source["image_sha256"] == FIGURE_SHA
        assert public_visual(context) == {
            "task": context["task"],
            "sources": context["sources"],
            "answer_cues": context["answer_cues"],
            "key_status": context["key_status"],
            "hints_used": context["hints_used"],
            "pixels_inspected": context["pixels_inspected"],
        }


@pytest.mark.parametrize(
    ("request_overrides", "call_overrides", "rag_kwargs", "message"),
    REJECTION_CASES,
)
def test_prepare_visual_rejects(monkeypatch, request_overrides, call_overrides, rag_kwargs, message):
    install_rag(monkeypatch, **rag_kwargs)
    kwargs = {"expected_answer": "artery", "options": {}, **call_overrides}
    with pytest.raises(ValueError, match=re.escape(message)):
        prepare_visual({**base_request(), **request_overrides}, **kwargs)
