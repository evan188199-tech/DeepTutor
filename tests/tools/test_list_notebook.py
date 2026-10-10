"""Unit tests for the ``list_notebook`` tool's pure rendering logic."""

from __future__ import annotations

import datetime as _dt

import pytest

from deeptutor.tools.list_notebook import (
    MAX_NOTEBOOKS_RENDERED,
    MAX_RECORDS_RENDERED,
    MAX_SUMMARY_PREVIEW,
    MAX_TITLE_PREVIEW,
    list_notebooks_or_records,
)


class _FakeManager:
    """Minimal NotebookManager stand-in for unit tests."""

    def __init__(self, notebooks=(), records_by_nb=None):
        self._notebooks = list(notebooks)
        self._records = dict(records_by_nb or {})

    def list_notebooks(self):
        return list(self._notebooks)

    def get_records(self, notebook_id):
        return list(self._records.get(notebook_id, []))


# ---------------------------------------------------------------------------
# Index mode (no notebook_id)
# ---------------------------------------------------------------------------


def test_index_returns_empty_message_when_user_has_no_notebooks() -> None:
    outcome = list_notebooks_or_records(notebook_manager=_FakeManager())
    assert outcome.ok is True
    assert "no notebooks" in outcome.text.lower()
    assert outcome.summary == {"mode": "index", "count": 0}


def test_index_renders_id_name_count_for_each_notebook() -> None:
    manager = _FakeManager(
        notebooks=[
            {
                "id": "nb-1",
                "name": "Math",
                "description": "Calculus + linear algebra",
                "record_count": 12,
                "updated_at": 1_700_000_000.0,
            },
            {
                "id": "nb-2",
                "name": "Physics",
                "record_count": 3,
                "updated_at": 1_700_000_010.0,
            },
        ],
    )
    outcome = list_notebooks_or_records(notebook_manager=manager)
    assert outcome.ok is True
    assert "`nb-1`" in outcome.text
    assert "**Math**" in outcome.text
    assert "12 records" in outcome.text
    assert "Calculus + linear algebra" in outcome.text
    assert "`nb-2`" in outcome.text
    assert "Physics" in outcome.text
    assert outcome.summary == {"mode": "index", "count": 2}


def test_index_caps_huge_notebook_lists() -> None:
    manager = _FakeManager(
        notebooks=[
            {"id": f"nb-{i}", "name": f"NB {i}", "record_count": i}
            for i in range(MAX_NOTEBOOKS_RENDERED + 10)
        ],
    )
    outcome = list_notebooks_or_records(notebook_manager=manager)
    assert outcome.ok is True
    assert "showing" in outcome.text.lower()
    assert outcome.summary["count"] == MAX_NOTEBOOKS_RENDERED + 10


# ---------------------------------------------------------------------------
# Drill-down mode (notebook_id given)
# ---------------------------------------------------------------------------


def test_drilldown_rejects_unknown_notebook_id() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
    )
    outcome = list_notebooks_or_records(notebook_id="bogus", notebook_manager=manager)
    assert outcome.ok is False
    assert "Unknown notebook_id" in outcome.error
    assert "`nb-1`" in outcome.error  # tells the LLM the right id to use


def test_drilldown_empty_records() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": []},
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert "no records" in outcome.text.lower()
    assert outcome.summary == {"mode": "records", "notebook_id": "nb-1", "count": 0}


def test_drilldown_renders_records_newest_first() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={
            "nb-1": [
                {
                    "id": "r-old",
                    "title": "Old",
                    "summary": "old summary",
                    "type": "chat",
                    "created_at": 1_700_000_000.0,
                },
                {
                    "id": "r-new",
                    "title": "New",
                    "summary": "new summary",
                    "type": "chat",
                    "created_at": 1_700_001_000.0,
                },
            ]
        },
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    # Newest first — "r-new" appears before "r-old" in the rendered text.
    assert outcome.text.index("`r-new`") < outcome.text.index("`r-old`")
    assert "new summary" in outcome.text


def test_drilldown_caps_huge_record_lists() -> None:
    big_records = [
        {"id": f"r-{i}", "title": f"R{i}", "summary": "", "created_at": float(i)}
        for i in range(MAX_RECORDS_RENDERED + 20)
    ]
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": big_records},
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert "showing" in outcome.text.lower()
    assert outcome.summary["count"] == MAX_RECORDS_RENDERED + 20


# ---------------------------------------------------------------------------
# Mode selection & id normalization (filter/pagination inputs)
# ---------------------------------------------------------------------------


def test_whitespace_only_notebook_id_falls_back_to_index_mode() -> None:
    manager = _FakeManager(notebooks=[{"id": "nb-1", "name": "Math"}])
    outcome = list_notebooks_or_records(notebook_id="   ", notebook_manager=manager)
    assert outcome.ok is True
    assert outcome.summary["mode"] == "index"


def test_drilldown_matches_notebook_id_after_stripping() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": [{"id": "r-1", "title": "T"}]},
    )
    outcome = list_notebooks_or_records(
        notebook_id="  nb-1\t", notebook_manager=manager
    )
    assert outcome.ok is True
    assert outcome.summary["count"] == 1


def test_drilldown_clips_long_title_and_summary() -> None:
    long_title = "T" * (MAX_TITLE_PREVIEW + 40)
    long_summary = "S" * (MAX_SUMMARY_PREVIEW + 40)
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": [{"id": "r-1", "title": long_title, "summary": long_summary}]},
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert long_title[:MAX_TITLE_PREVIEW] + "…" in outcome.text
    assert long_summary[:MAX_SUMMARY_PREVIEW] + "…" in outcome.text
    assert long_title not in outcome.text


# ---------------------------------------------------------------------------
# Empty sets & malformed entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_return", [None, {}, "nb-1", 42])
def test_index_treats_non_list_notebook_listing_as_empty(bad_return) -> None:
    class _BrokenManager:
        def list_notebooks(self):
            return bad_return

    outcome = list_notebooks_or_records(notebook_manager=_BrokenManager())
    assert outcome.ok is True
    assert "no notebooks" in outcome.text.lower()
    assert outcome.summary == {"mode": "index", "count": 0}


def test_index_tolerates_malformed_entries() -> None:
    manager = _FakeManager(
        notebooks=[
            {"name": "NoId"},
            {"id": "  ", "title": "Titled", "record_count": "7"},
            {
                "id": "nb-3",
                "name": "WeirdCounts",
                "record_count": "not-a-number",
                "updated_at": "soon",
            },
            {"id": "nb-4", "record_count": None},
        ],
    )
    outcome = list_notebooks_or_records(notebook_manager=manager)
    assert outcome.ok is True
    assert "NoId" in outcome.text
    assert "Titled" in outcome.text
    assert "7 records" in outcome.text
    assert "WeirdCounts" in outcome.text
    assert "0 records" in outcome.text
    assert "updated" not in outcome.text
    assert outcome.summary["count"] == 4


def test_drilldown_tolerates_malformed_records() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={
            "nb-1": [
                {"summary": "no id, no title", "created_at": None},
                {"id": "r-2", "created_at": -5},
                {"id": "r-3", "title": "Ok", "summary": "fine", "created_at": 1_700_000_000.0},
            ]
        },
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert "(untitled)" in outcome.text
    assert "r-3" in outcome.text
    expected_date = _dt.datetime.fromtimestamp(1_700_000_000.0).strftime("%Y-%m-%d")
    assert expected_date in outcome.text
    assert outcome.summary["count"] == 3


# ---------------------------------------------------------------------------
# Storage unavailable / degraded paths (fixture-injected, no real storage)
# ---------------------------------------------------------------------------


def test_without_injected_manager_uses_service_default(monkeypatch) -> None:
    fake = _FakeManager(notebooks=[{"id": "nb-9", "name": "FromService"}])
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager", lambda: fake
    )
    outcome = list_notebooks_or_records()
    assert outcome.ok is True
    assert "`nb-9`" in outcome.text
    assert "FromService" in outcome.text


def test_drilldown_reports_get_records_failure_as_outcome() -> None:
    class _FailingManager:
        def list_notebooks(self):
            return [{"id": "nb-1", "name": "Math"}]

        def get_records(self, notebook_id):
            raise RuntimeError("storage unavailable")

    outcome = list_notebooks_or_records(
        notebook_id="nb-1", notebook_manager=_FailingManager()
    )
    assert outcome.ok is False
    assert "Failed to load records" in outcome.error
    assert outcome.text == ""
    assert outcome.summary is None
