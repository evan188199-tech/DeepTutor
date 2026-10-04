"""Counter restore must stay correct and visible when citation IDs are malformed."""

from __future__ import annotations

import json
import logging

from deeptutor.agents.research.utils.citation_manager import CitationManager

_LOGGER_NAME = "deeptutor.agents.research.utils.citation_manager"


def _write_citations_file(cache_dir, citations: dict, counters: dict | None = None) -> None:
    data = {"research_id": "restore-check", "citations": citations}
    if counters is not None:
        data["counters"] = counters
    (cache_dir / "citations.json").write_text(json.dumps(data), encoding="utf-8")


def test_restore_logs_and_skips_malformed_plan_ids(tmp_path, caplog) -> None:
    _write_citations_file(tmp_path, {"PLAN-03": {"title": "valid"}, "PLAN-oops": {}})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        manager = CitationManager("restore-plan", cache_dir=tmp_path)

    assert manager._plan_counter == 3
    assert manager.generate_plan_citation_id() == "PLAN-04"
    assert any("PLAN-oops" in record.message for record in caplog.records)


def test_restore_logs_and_skips_malformed_cit_ids(tmp_path, caplog) -> None:
    _write_citations_file(
        tmp_path,
        {"CIT-2-05": {"title": "valid"}, "CIT-2-oops": {}, "CIT-9-oops": {}},
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        manager = CitationManager("restore-cit", cache_dir=tmp_path)

    assert manager._block_counters == {"2": 5}
    assert manager.generate_research_citation_id("block_2") == "CIT-2-06"
    malformed_warnings = [
        record.message
        for record in caplog.records
        if "CIT-2-oops" in record.message or "CIT-9-oops" in record.message
    ]
    assert len(malformed_warnings) == 2


def test_restore_stays_silent_for_parseable_ids(tmp_path, caplog) -> None:
    _write_citations_file(tmp_path, {"PLAN-07": {}, "CIT-3-04": {}})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        CitationManager("restore-clean", cache_dir=tmp_path)

    assert not caplog.records


def test_saved_counters_take_precedence_over_restore(tmp_path, caplog) -> None:
    _write_citations_file(
        tmp_path,
        {"PLAN-03": {}, "CIT-2-05": {}},
        counters={"plan_counter": 11, "block_counters": {"2": 9}},
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        manager = CitationManager("restore-counters", cache_dir=tmp_path)

    assert manager._plan_counter == 11
    assert manager._block_counters == {"2": 9}
    assert not caplog.records
