"""Prompt manager path resolution tests."""

from __future__ import annotations

import logging

from deeptutor.services.prompt import get_prompt_manager


def test_prompt_manager_loads_prompts_from_deeptutor_tree() -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts(
        module_name="question",
        agent_name="idea_agent",
        language="en",
    )

    assert "generate_ideas" in prompts


def test_missing_prompt_warning_goes_to_logger_not_stdout(capsys, caplog) -> None:
    manager = get_prompt_manager()

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.prompt.manager"):
        prompts = manager._load_with_fallback("research", "no_such_agent", "en", None)

    assert prompts == {}
    assert any("No prompt file found" in record.getMessage() for record in caplog.records)
    assert capsys.readouterr().out == ""
