"""Offline parsing behaviour of the MinerU exam-paper question extractor."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from deeptutor.tools.question import question_extractor as qe


def _make_auto(paper: Path, *, name: str = "auto") -> Path:
    auto = paper / name
    auto.mkdir(parents=True)
    (auto / "paper.md").write_text("# Exam\n\n1. What is ATP?\n", encoding="utf-8")
    (auto / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. What is ATP?"}]), encoding="utf-8"
    )
    (auto / "images").mkdir()
    (auto / "images" / "img_001.jpg").write_bytes(b"fake")
    return auto


def test_find_parsed_content_dir_prefers_auto(tmp_path: Path) -> None:
    auto = _make_auto(tmp_path)
    (tmp_path / "mineru_backup").mkdir()
    assert qe._find_parsed_content_dir(tmp_path) == auto


def test_find_parsed_content_dir_falls_back_to_hybrid_auto(tmp_path: Path) -> None:
    hybrid = _make_auto(tmp_path, name="hybrid_auto")
    assert qe._find_parsed_content_dir(tmp_path) == hybrid


def test_find_parsed_content_dir_uses_first_sorted_dir_with_markdown(tmp_path: Path) -> None:
    (tmp_path / "b_output").mkdir()
    (tmp_path / "a_output").mkdir()
    (tmp_path / "a_output" / "x.md").write_text("md", encoding="utf-8")
    assert qe._find_parsed_content_dir(tmp_path) == tmp_path / "a_output"


def test_find_parsed_content_dir_discovers_nested_artifacts(tmp_path: Path) -> None:
    (tmp_path / "v2" / "deep").mkdir(parents=True)
    (tmp_path / "v2" / "deep" / "paper.md").write_text("md", encoding="utf-8")
    (tmp_path / "v2" / "deep" / "paper_content_list.json").write_text("[]", encoding="utf-8")
    nested = tmp_path / "v2" / "deep"
    assert qe._find_parsed_content_dir(tmp_path) == nested


def test_find_parsed_content_dir_returns_paper_dir_when_empty(tmp_path: Path) -> None:
    assert qe._find_parsed_content_dir(tmp_path) == tmp_path


def test_load_parsed_paper_reads_markdown_and_content_list(tmp_path: Path) -> None:
    auto = _make_auto(tmp_path)
    markdown, content_list, images_dir = qe.load_parsed_paper(tmp_path)

    assert markdown == "# Exam\n\n1. What is ATP?\n"
    assert content_list == [{"type": "text", "text": "1. What is ATP?"}]
    assert images_dir == auto / "images"


def test_load_parsed_paper_without_content_list(tmp_path: Path) -> None:
    auto = tmp_path / "auto"
    auto.mkdir()
    (auto / "paper.md").write_text("# Exam", encoding="utf-8")
    markdown, content_list, _ = qe.load_parsed_paper(tmp_path)

    assert markdown == "# Exam"
    assert content_list is None


def test_load_parsed_paper_without_markdown(tmp_path: Path) -> None:
    markdown, content_list, images_dir = qe.load_parsed_paper(tmp_path)

    assert markdown is None
    assert content_list is None
    assert images_dir == tmp_path / "images"


def test_save_questions_json_writes_roundtrippable_report(tmp_path: Path) -> None:
    questions = [
        {"question_number": "1", "question_text": "What is ATP?", "images": ["img.jpg"]},
        {"question_number": "2", "question_text": "Define osmosis.", "images": []},
    ]
    output = qe.save_questions_json(questions, tmp_path / "nested", "exam_2024")

    assert output.parent == tmp_path / "nested"
    assert re.fullmatch(r"exam_2024_\d{8}_\d{6}_questions\.json", output.name)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["paper_name"] == "exam_2024"
    assert payload["total_questions"] == 2
    assert payload["questions"] == questions


def test_extract_questions_filters_image_candidates(monkeypatch, tmp_path: Path) -> None:
    images = tmp_path / "auto" / "images"
    images.mkdir(parents=True)
    for name in ("a.jpg", "b.PNG", "c.webp", "d.txt", "e.jpeg", "notes.md"):
        (images / name).write_bytes(b"x")

    captured: dict = {}

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return '```json\n{"questions": [{"question_number": "1"}]}\n```'

    monkeypatch.setattr(qe, "llm_complete", fake_complete)
    monkeypatch.setattr(
        qe,
        "get_agent_params",
        lambda agent: (
            captured.__setitem__("agent", agent) or {"temperature": 0.2, "max_tokens": 777}
        ),
    )
    monkeypatch.setattr(qe, "supports_response_format", lambda binding, model: True)

    questions = qe.extract_questions_with_llm(
        markdown_content="A" * 16000 + "END_MARKER",
        content_list=None,
        images_dir=images,
        api_key="key",
        base_url="https://example.test/v1",
        model="gpt-test",
        binding="openai",
    )

    assert questions == [{"question_number": "1"}]
    assert captured["agent"] == "question"
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 777
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == "gpt-test"
    assert captured["api_key"] == "key"
    assert "END_MARKER" not in captured["prompt"]
    assert "A" * 15000 in captured["prompt"]
    assert "A" * 15001 not in captured["prompt"]
    assert '"a.jpg"' in captured["prompt"]
    assert '"b.PNG"' in captured["prompt"]
    assert '"e.jpeg"' in captured["prompt"]
    assert "d.txt" not in captured["prompt"]
    assert "notes.md" not in captured["prompt"]


def test_extract_questions_omits_response_format_when_unsupported(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict = {}

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return '{"questions": []}'

    monkeypatch.setattr(qe, "llm_complete", fake_complete)
    monkeypatch.setattr(qe, "get_agent_params", lambda agent: {"temperature": 0, "max_tokens": 1})
    monkeypatch.setattr(qe, "supports_response_format", lambda binding, model: False)
    questions = qe.extract_questions_with_llm(
        markdown_content="md",
        content_list=None,
        images_dir=tmp_path,
        api_key="key",
        base_url="https://example.test/v1",
        model="gpt-test",
    )

    assert questions == []
    assert "response_format" not in captured


def test_extract_questions_rejects_empty_llm_response(monkeypatch, tmp_path: Path) -> None:
    async def fake_complete(**kwargs):
        return ""

    monkeypatch.setattr(qe, "llm_complete", fake_complete)
    monkeypatch.setattr(qe, "get_agent_params", lambda agent: {"temperature": 0, "max_tokens": 1})
    monkeypatch.setattr(qe, "supports_response_format", lambda binding, model: False)
    with pytest.raises(ValueError, match="Failed to parse LLM JSON response"):
        qe.extract_questions_with_llm(
            markdown_content="md",
            content_list=None,
            images_dir=tmp_path,
            api_key="key",
            base_url="https://example.test/v1",
            model="gpt-test",
        )


def test_extract_questions_falls_back_to_empty_on_unparseable_response(
    monkeypatch, tmp_path: Path
) -> None:
    async def fake_complete(**kwargs):
        return "not json at all"

    monkeypatch.setattr(qe, "llm_complete", fake_complete)
    monkeypatch.setattr(qe, "get_agent_params", lambda agent: {"temperature": 0, "max_tokens": 1})
    monkeypatch.setattr(qe, "supports_response_format", lambda binding, model: False)
    assert (
        qe.extract_questions_with_llm(
            markdown_content="md",
            content_list=None,
            images_dir=tmp_path,
            api_key="key",
            base_url="https://example.test/v1",
            model="gpt-test",
        )
        == []
    )
