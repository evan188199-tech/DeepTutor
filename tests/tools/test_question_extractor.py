from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import re
import sys
import types

import pytest

CANONICAL_QUESTION_TYPES = (
    "choice",
    "concept",
    "fill_in_blank",
    "short_answer",
    "written",
    "coding",
)


def _load_question_extractor_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "deeptutor"
        / "tools"
        / "question"
        / "question_extractor.py"
    )

    stubbed_modules = {
        "deeptutor.services.config": {"get_agent_params": lambda *_args, **_kwargs: {}},
        "deeptutor.services.llm": {"complete": lambda *_args, **_kwargs: None},
        "deeptutor.services.llm.capabilities": {
            "supports_response_format": lambda *_args, **_kwargs: False
        },
        "deeptutor.services.llm.config": {"get_llm_config": lambda: None},
        "deeptutor.utils.json_parser": {"parse_json_response": lambda *_args, **_kwargs: {}},
    }

    original_modules: dict[str, types.ModuleType | None] = {}
    for module_name, attributes in stubbed_modules.items():
        original_modules[module_name] = sys.modules.get(module_name)
        module = types.ModuleType(module_name)
        for attr_name, value in attributes.items():
            setattr(module, attr_name, value)
        sys.modules[module_name] = module

    try:
        spec = importlib.util.spec_from_file_location("question_extractor_under_test", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_load_parsed_paper_supports_nested_hybrid_auto_output(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "mimic_exam"
    parsed_dir = paper_dir / "hybrid_auto"
    images_dir = parsed_dir / "images"
    images_dir.mkdir(parents=True)

    markdown_path = parsed_dir / "exam.md"
    markdown_path.write_text("# Exam content", encoding="utf-8")

    content_list_path = parsed_dir / "exam_content_list.json"
    content_list_path.write_text(
        json.dumps([{"type": "text", "text": "Question 1"}], ensure_ascii=False),
        encoding="utf-8",
    )

    (images_dir / "figure.png").write_text("image-bytes", encoding="utf-8")

    markdown_content, content_list, discovered_images_dir = question_extractor.load_parsed_paper(
        paper_dir
    )

    assert markdown_content == "# Exam content"
    assert content_list == [{"type": "text", "text": "Question 1"}]
    assert discovered_images_dir == images_dir


def _stub_llm(
    question_extractor,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict],
    *,
    response_text: str,
    parse=None,
    supports_json: bool = False,
) -> None:
    async def fake_complete(**kwargs):
        calls.append(kwargs)
        return response_text

    monkeypatch.setattr(question_extractor, "llm_complete", fake_complete)
    monkeypatch.setattr(
        question_extractor, "supports_response_format", lambda _binding, _model: supports_json
    )
    monkeypatch.setattr(
        question_extractor,
        "get_agent_params",
        lambda *_args, **_kwargs: {"temperature": 0.2, "max_tokens": 512},
    )
    if parse is not None:
        monkeypatch.setattr(question_extractor, "parse_json_response", parse)


def _stub_llm_config(question_extractor, monkeypatch: pytest.MonkeyPatch, binding: str = "openai"):
    monkeypatch.setattr(
        question_extractor,
        "get_llm_config",
        lambda: types.SimpleNamespace(
            api_key="test-key",
            base_url="http://llm.test",
            model="test-model",
            api_version=None,
            binding=binding,
        ),
    )


def _make_images_dir(tmp_path: Path, names: tuple[str, ...]) -> Path:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for name in names:
        (images_dir / name).write_bytes(b"image-bytes")
    return images_dir


def _sample_questions_payload() -> dict:
    return {
        "questions": [
            {
                "question_number": "1",
                "question_text": "Which option is correct?\nA. one\nB. two",
                "question_type": "choice",
                "difficulty": "easy",
                "answer": "A",
                "images": ["a.jpg"],
            },
            {
                "question_number": "2",
                "question_text": "The sky is blue.",
                "question_type": "concept",
                "difficulty": "easy",
                "answer": "",
                "images": [],
            },
            {
                "question_number": "3",
                "question_text": "The capital of France is ____.",
                "question_type": "fill_in_blank",
                "difficulty": "medium",
                "answer": "Paris",
                "images": [],
            },
            {
                "question_number": "4",
                "question_text": "Explain photosynthesis.",
                "question_type": "short_answer",
                "difficulty": "medium",
                "answer": "",
                "images": [],
            },
            {
                "question_number": "5",
                "question_text": "Discuss the causes of WWI.",
                "question_type": "written",
                "difficulty": "hard",
                "answer": "",
                "images": [],
            },
            {
                "question_number": "6",
                "question_text": "Implement binary search.",
                "question_type": "coding",
                "difficulty": "hard",
                "answer": "",
                "images": [],
            },
        ]
    }


def test_find_parsed_content_dir_prefers_auto_over_hybrid_auto_and_siblings(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    (paper_dir / "aaa_sibling").mkdir(parents=True)
    hybrid_dir = paper_dir / "hybrid_auto"
    hybrid_dir.mkdir(parents=True)
    auto_dir = paper_dir / "auto"
    auto_dir.mkdir(parents=True)
    (auto_dir / "exam.md").write_text("auto", encoding="utf-8")

    assert question_extractor._find_parsed_content_dir(paper_dir) == auto_dir


def test_find_parsed_content_dir_returns_first_sorted_child_with_markdown(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    (paper_dir / "a_dir").mkdir(parents=True)
    (paper_dir / "b_dir").mkdir(parents=True)
    (paper_dir / "c_dir").mkdir(parents=True)
    (paper_dir / "b_dir" / "exam.md").write_text("b", encoding="utf-8")
    (paper_dir / "c_dir" / "exam.md").write_text("c", encoding="utf-8")

    assert question_extractor._find_parsed_content_dir(paper_dir) == paper_dir / "b_dir"


def test_find_parsed_content_dir_discovers_nested_artifact_dirs(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    nested_dir = paper_dir / "nested" / "deep"
    nested_dir.mkdir(parents=True)
    (nested_dir / "exam.md").write_text("nested", encoding="utf-8")
    content_list_dir = paper_dir / "cl_dir"
    content_list_dir.mkdir(parents=True)
    (content_list_dir / "exam_content_list.json").write_text("[]", encoding="utf-8")

    assert question_extractor._find_parsed_content_dir(paper_dir) == nested_dir


def test_find_parsed_content_dir_returns_paper_dir_when_no_candidates(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()

    assert question_extractor._find_parsed_content_dir(paper_dir) == paper_dir


def test_load_parsed_paper_reads_markdown_at_paper_root(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "exam.md").write_text("# Root exam", encoding="utf-8")

    markdown_content, content_list, images_dir = question_extractor.load_parsed_paper(paper_dir)

    assert markdown_content == "# Root exam"
    assert content_list is None
    assert images_dir == paper_dir / "images"


def test_load_parsed_paper_missing_markdown_returns_none(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()

    markdown_content, content_list, images_dir = question_extractor.load_parsed_paper(paper_dir)

    assert markdown_content is None
    assert content_list is None
    assert images_dir == paper_dir / "images"
    assert not images_dir.exists()


def test_load_parsed_paper_without_content_list_returns_none_list(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "exam.md").write_text("# Exam", encoding="utf-8")

    markdown_content, content_list, images_dir = question_extractor.load_parsed_paper(paper_dir)

    assert markdown_content == "# Exam"
    assert content_list is None
    assert images_dir == paper_dir / "images"


def test_load_parsed_paper_malformed_content_list_json_raises(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "exam.md").write_text("# Exam", encoding="utf-8")
    (paper_dir / "exam_content_list.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        question_extractor.load_parsed_paper(paper_dir)


def test_extract_questions_with_llm_passes_all_canonical_question_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps(_sample_questions_payload()),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )
    images_dir = _make_images_dir(
        tmp_path, ("a.jpg", "b.jpeg", "c.png", "d.gif", "e.webp", "f.bmp", "notes.txt")
    )

    result = question_extractor.extract_questions_with_llm(
        markdown_content="# Exam paper",
        content_list=None,
        images_dir=images_dir,
        api_key="test-key",
        base_url="http://llm.test",
        model="test-model",
        binding="openai",
    )

    assert [question["question_type"] for question in result] == list(CANONICAL_QUESTION_TYPES)
    assert result[0]["question_text"] == "Which option is correct?\nA. one\nB. two"

    call_kwargs = calls[0]
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 512
    assert call_kwargs["api_key"] == "test-key"
    assert call_kwargs["base_url"] == "http://llm.test"
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["binding"] == "openai"
    assert call_kwargs.get("response_format") is None
    for question_type in CANONICAL_QUESTION_TYPES:
        assert f'"{question_type}"' in call_kwargs["system_prompt"]
    assert '"a.jpg"' in call_kwargs["prompt"]
    assert '"f.bmp"' not in call_kwargs["prompt"]
    assert '"notes.txt"' not in call_kwargs["prompt"]


def test_extract_questions_with_llm_adds_response_format_when_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps({"questions": []}),
        parse=lambda _text, **_kwargs: json.loads(_text),
        supports_json=True,
    )

    question_extractor.extract_questions_with_llm(
        markdown_content="# Exam",
        content_list=None,
        images_dir=tmp_path / "missing-images",
        api_key="test-key",
        base_url="http://llm.test",
        model="test-model",
        binding="openai",
    )

    assert calls[0]["response_format"] == {"type": "json_object"}


def test_extract_questions_with_llm_resolves_binding_from_config_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps({"questions": []}),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )
    monkeypatch.setattr(
        question_extractor,
        "get_llm_config",
        lambda: types.SimpleNamespace(binding="azure"),
    )

    question_extractor.extract_questions_with_llm(
        markdown_content="# Exam",
        content_list=None,
        images_dir=tmp_path / "missing-images",
        api_key="test-key",
        base_url="http://llm.test",
        model="test-model",
        binding=None,
    )

    assert calls[0]["binding"] == "azure"


def test_extract_questions_with_llm_raises_on_empty_llm_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(question_extractor, monkeypatch, calls, response_text="")

    with pytest.raises(ValueError, match="Failed to parse LLM JSON response"):
        question_extractor.extract_questions_with_llm(
            markdown_content="# Exam",
            content_list=None,
            images_dir=tmp_path / "missing-images",
            api_key="test-key",
            base_url="http://llm.test",
            model="test-model",
            binding="openai",
        )


def test_extract_questions_with_llm_raises_on_malformed_llm_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []

    def broken_parser(_text, **_kwargs):
        raise ValueError("invalid JSON payload")

    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text="this is not json",
        parse=broken_parser,
    )

    with pytest.raises(ValueError, match="Failed to parse LLM JSON response") as exc_info:
        question_extractor.extract_questions_with_llm(
            markdown_content="# Exam",
            content_list=None,
            images_dir=tmp_path / "missing-images",
            api_key="test-key",
            base_url="http://llm.test",
            model="test-model",
            binding="openai",
        )

    assert exc_info.value.__cause__ is not None


def test_extract_questions_with_llm_raises_when_parser_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text="{}",
        parse=lambda _text, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="Failed to parse LLM JSON response"):
        question_extractor.extract_questions_with_llm(
            markdown_content="# Exam",
            content_list=None,
            images_dir=tmp_path / "missing-images",
            api_key="test-key",
            base_url="http://llm.test",
            model="test-model",
            binding="openai",
        )


def test_extract_questions_with_llm_defaults_to_empty_list_without_questions_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(question_extractor, monkeypatch, calls, response_text='{"other": 1}')

    result = question_extractor.extract_questions_with_llm(
        markdown_content="# Exam",
        content_list=None,
        images_dir=tmp_path / "missing-images",
        api_key="test-key",
        base_url="http://llm.test",
        model="test-model",
        binding="openai",
    )

    assert result == []


def test_extract_questions_with_llm_passes_through_malformed_question_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    payload = {"questions": ["junk", 42, None, {"question_number": "1"}]}
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps(payload),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )

    result = question_extractor.extract_questions_with_llm(
        markdown_content="# Exam",
        content_list=None,
        images_dir=tmp_path / "missing-images",
        api_key="test-key",
        base_url="http://llm.test",
        model="test-model",
        binding="openai",
    )

    assert result == payload["questions"]


def test_extract_questions_with_llm_runs_inside_active_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps(_sample_questions_payload()),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )

    async def call_within_loop():
        return question_extractor.extract_questions_with_llm(
            markdown_content="# Exam",
            content_list=None,
            images_dir=tmp_path / "missing-images",
            api_key="test-key",
            base_url="http://llm.test",
            model="test-model",
            binding="openai",
        )

    result = asyncio.run(call_within_loop())

    assert [question["question_type"] for question in result] == list(CANONICAL_QUESTION_TYPES)


def test_save_questions_json_writes_timestamped_output_with_stats(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    output_dir = tmp_path / "out"
    questions = [
        {"question_number": "1", "images": ["a.jpg"]},
        {"question_number": "2", "images": []},
    ]

    output_file = question_extractor.save_questions_json(questions, output_dir, "demo_paper")

    assert output_file.parent == output_dir
    assert re.fullmatch(r"demo_paper_\d{8}_\d{6}_questions\.json", output_file.name)
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["paper_name"] == "demo_paper"
    assert data["total_questions"] == 2
    assert data["questions"] == questions

    empty_file = question_extractor.save_questions_json([], output_dir, "empty_paper")
    assert json.loads(empty_file.read_text(encoding="utf-8"))["total_questions"] == 0


def test_extract_questions_from_paper_returns_false_for_missing_dir(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()

    assert question_extractor.extract_questions_from_paper(str(tmp_path / "does-not-exist")) is False


def test_extract_questions_from_paper_returns_false_without_markdown(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()

    assert question_extractor.extract_questions_from_paper(str(paper_dir)) is False


def test_extract_questions_from_paper_returns_false_when_no_questions_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "auto").mkdir()
    (paper_dir / "auto" / "exam.md").write_text("# Exam", encoding="utf-8")
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps({"questions": []}),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )
    _stub_llm_config(question_extractor, monkeypatch)

    assert question_extractor.extract_questions_from_paper(str(paper_dir)) is False
    assert list(paper_dir.glob("*_questions.json")) == []


def test_extract_questions_from_paper_writes_output_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "auto").mkdir()
    (paper_dir / "auto" / "exam.md").write_text("# Exam", encoding="utf-8")
    output_dir = tmp_path / "output"
    calls: list[dict] = []
    _stub_llm(
        question_extractor,
        monkeypatch,
        calls,
        response_text=json.dumps(
            {
                "questions": [
                    {
                        "question_number": "1",
                        "question_text": "Stem",
                        "question_type": "short_answer",
                        "difficulty": "easy",
                        "answer": "",
                        "images": [],
                    }
                ]
            }
        ),
        parse=lambda _text, **_kwargs: json.loads(_text),
    )
    _stub_llm_config(question_extractor, monkeypatch)

    success = question_extractor.extract_questions_from_paper(str(paper_dir), str(output_dir))
    assert success is True

    output_files = list(output_dir.glob("paper_*_questions.json"))
    assert len(output_files) == 1
    data = json.loads(output_files[0].read_text(encoding="utf-8"))
    assert data["total_questions"] == 1
    assert data["questions"][0]["question_type"] == "short_answer"


def test_main_exits_nonzero_when_extraction_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_extractor = _load_question_extractor_module()
    monkeypatch.setattr(sys, "argv", ["question_extractor.py", str(tmp_path / "missing-dir")])

    with pytest.raises(SystemExit) as exc_info:
        question_extractor.main()

    assert exc_info.value.code == 1
