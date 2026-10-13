from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
import sys
import types

_UNDER_TEST = "question_extractor_under_test"


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


def test_load_parsed_paper_progress_goes_to_logger_not_stdout(
    tmp_path: Path, caplog, capsys
) -> None:
    question_extractor = _load_question_extractor_module()
    parsed_dir = tmp_path / "mimic_exam" / "auto"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "exam.md").write_text("# Exam content", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger=_UNDER_TEST):
        markdown_content, _content_list, _images_dir = question_extractor.load_parsed_paper(
            tmp_path / "mimic_exam"
        )

    assert markdown_content == "# Exam content"
    messages = [record.getMessage() for record in caplog.records]
    assert any("Using parsed content directory" in message for message in messages)
    assert any("Found markdown file" in message for message in messages)
    assert capsys.readouterr().out == ""


def test_extract_questions_from_paper_missing_dir_logs_via_logger(
    tmp_path: Path, caplog, capsys
) -> None:
    question_extractor = _load_question_extractor_module()

    with caplog.at_level(logging.ERROR, logger=_UNDER_TEST):
        success = question_extractor.extract_questions_from_paper(str(tmp_path / "missing"))

    assert success is False
    assert any("Directory does not exist" in record.getMessage() for record in caplog.records)
    assert capsys.readouterr().out == ""


def test_extract_questions_from_paper_no_markdown_logs_via_logger(
    tmp_path: Path, caplog, capsys
) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "empty_paper"
    paper_dir.mkdir()

    with caplog.at_level(logging.ERROR, logger=_UNDER_TEST):
        success = question_extractor.extract_questions_from_paper(str(paper_dir))

    assert success is False
    assert any("Unable to load paper content" in record.getMessage() for record in caplog.records)
    assert any("No markdown file found" in record.getMessage() for record in caplog.records)
    assert capsys.readouterr().out == ""


def test_extract_questions_from_paper_llm_config_error_logs_via_logger(
    tmp_path: Path, caplog, capsys, monkeypatch
) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "exam.md").write_text("# Exam content", encoding="utf-8")

    def _raise_value_error() -> None:
        raise ValueError("no active LLM profile")

    monkeypatch.setattr(question_extractor, "get_llm_config", _raise_value_error)

    with caplog.at_level(logging.INFO, logger=_UNDER_TEST):
        success = question_extractor.extract_questions_from_paper(str(paper_dir))

    assert success is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("no active LLM profile" in message for message in messages)
    assert any("Configure an active LLM profile" in message for message in messages)
    assert capsys.readouterr().out == ""


def test_cli_logging_keeps_stdout_output(tmp_path: Path, capsys, monkeypatch) -> None:
    question_extractor = _load_question_extractor_module()
    monkeypatch.setattr(sys, "argv", ["question_extractor.py", str(tmp_path / "missing_paper")])

    try:
        question_extractor.main()
    except SystemExit as exit_code:
        assert exit_code.code == 1
    else:
        raise AssertionError("main() should exit with status 1 on failure")

    assert "Directory does not exist" in capsys.readouterr().out
