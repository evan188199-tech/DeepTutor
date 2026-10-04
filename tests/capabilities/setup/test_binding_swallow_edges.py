"""Swallowed-failure regression edges for the setup capability binding.

The 2026-10-03 silent-exception scan flags two advisory writes in
``deeptutor/capabilities/setup/binding.py`` that swallow every exception:

- ``setup_gaps`` (:135): a ``document_parsing.engine`` spec row whose
  ``read``/``choices`` call blows up silently drops the parsing gap.
- ``mark_intro_shown`` (:207): a failed ``set_ui_setting`` write disappears.

The shape contracts below pin what must keep holding across a fix, so the
advisory "never raise" behaviour cannot regress. The ``logger.warning``
contracts pin the observability the module logger
(``deeptutor.capabilities.setup.binding``) now provides: every swallowed
advisory read or write leaves a warning naming the row or key it lost.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.setup.binding import (
    INTRO_SHOWN_KEY,
    SetupGap,
    mark_intro_shown,
    setup_gaps,
)

SETTINGS_SPEC = "deeptutor.services.config.settings_spec"
INTERFACE_SETTINGS = "deeptutor.services.settings.interface_settings"
BINDING_LOGGER = "deeptutor.capabilities.setup.binding"


def _choice(value: str, available: bool = True) -> SimpleNamespace:
    return SimpleNamespace(value=value, available=available)


def _spec(read, choices=lambda: ()):
    """A stand-in for a SettingSpec row, covering what ``setup_gaps`` touches."""
    return SimpleNamespace(read=read, choices=choices)


def _configured(value: str):
    return _spec(lambda: value, lambda: (_choice(value),))


def _write_specs(monkeypatch: pytest.MonkeyPatch, **rows) -> None:
    """Install a spec table covering only the rows a test cares about."""

    def fake_setting_specs():
        return rows

    monkeypatch.setattr(f"{SETTINGS_SPEC}.setting_specs", fake_setting_specs)


# ---------------------------------------------------------------------------
# Shape contracts: advisory reads must never raise
# ---------------------------------------------------------------------------


def test_unreadable_spec_table_returns_empty_tuple(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``setup_gaps`` returns an empty tuple when the whole table is gone."""

    def boom() -> None:
        raise RuntimeError("settings table unreadable")

    monkeypatch.setattr(f"{SETTINGS_SPEC}.setting_specs", boom)

    with caplog.at_level(logging.WARNING, logger=BINDING_LOGGER):
        assert setup_gaps() == ()

    records = [record for record in caplog.records if record.name == BINDING_LOGGER]
    assert records, "the swallowed spec-table failure must be logged"


def test_unreadable_catalog_row_treated_as_configured_and_logged(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An unreadable catalog row counts as configured, and says so in the log."""

    def boom() -> None:
        raise RuntimeError("embedding row unreadable")

    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _spec(boom),
            "catalog.search": _configured("tavily"),
        },
    )

    with caplog.at_level(logging.WARNING, logger=BINDING_LOGGER):
        assert setup_gaps() == ()

    records = [record for record in caplog.records if record.name == BINDING_LOGGER]
    assert records, "the swallowed catalog-row failure must be logged"
    assert any("catalog.embedding" in record.getMessage() for record in records)


def test_unreadable_parsing_row_keeps_shape_and_other_gaps(monkeypatch) -> None:
    """A malformed parsing row must not break the report's shape.

    Locked current contract: the result stays a tuple of :class:`SetupGap`,
    gaps computed before the malformed row survive, and no exception escapes.
    """

    def boom() -> None:
        raise RuntimeError("parsing row unreadable")

    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _spec(lambda: ""),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": _spec(boom),
        },
    )

    gaps = setup_gaps()

    assert isinstance(gaps, tuple)
    assert all(isinstance(gap, SetupGap) for gap in gaps)
    assert [gap.key for gap in gaps] == ["catalog.embedding"]
    assert gaps[0].blocking is True


def test_missing_parsing_row_reports_no_parsing_gap(monkeypatch) -> None:
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _configured("openai/text-embedding-3-small"),
            "catalog.search": _configured("tavily"),
        },
    )

    assert setup_gaps() == ()


# ---------------------------------------------------------------------------
# Normal paths: the report must not regress
# ---------------------------------------------------------------------------


def test_missing_embedding_selection_reports_blocking_gap(monkeypatch) -> None:
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _spec(lambda: ""),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": _configured("minerva"),
        },
    )

    gaps = setup_gaps()

    assert [gap.key for gap in gaps] == ["catalog.embedding"]
    assert gaps[0].area == "models"
    assert gaps[0].blocking is True


def test_text_only_parser_with_installed_alternatives_reports_count(
    monkeypatch,
) -> None:
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _configured("openai/text-embedding-3-small"),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": _spec(
                lambda: "text_only",
                lambda: (
                    _choice("text_only"),
                    _choice("minerva"),
                    _choice("docling", available=False),
                ),
            ),
        },
    )

    gaps = setup_gaps()

    assert [gap.key for gap in gaps] == ["document_parsing.engine"]
    assert gaps[0].area == "parsing"
    assert gaps[0].blocking is False
    assert "1 better engine" in gaps[0].remedy


def test_text_only_parser_without_alternatives_suggests_install(monkeypatch) -> None:
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _configured("openai/text-embedding-3-small"),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": _spec(
                lambda: "text_only",
                lambda: (_choice("text_only"),),
            ),
        },
    )

    gaps = setup_gaps()

    assert [gap.key for gap in gaps] == ["document_parsing.engine"]
    assert "installed in one step" in gaps[0].remedy


def test_strong_parser_selected_reports_no_gap(monkeypatch) -> None:
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _configured("openai/text-embedding-3-small"),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": _configured("minerva"),
        },
    )

    assert setup_gaps() == ()


# ---------------------------------------------------------------------------
# mark_intro_shown: write-through and never-raise contracts
# ---------------------------------------------------------------------------


def test_mark_intro_shown_writes_true_once(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        f"{INTERFACE_SETTINGS}.set_ui_setting",
        lambda key, value: calls.append((key, value)),
    )

    mark_intro_shown()

    assert calls == [(INTRO_SHOWN_KEY, True)]


def test_mark_intro_shown_never_raises(monkeypatch) -> None:
    def boom(key, value) -> None:
        raise OSError("interface.json unwritable")

    monkeypatch.setattr(f"{INTERFACE_SETTINGS}.set_ui_setting", boom)

    mark_intro_shown()


# ---------------------------------------------------------------------------
# Observability contracts: fail until the swallow sites log
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broken", ["read", "choices"])
def test_unreadable_parsing_row_is_logged(
    monkeypatch, caplog: pytest.LogCaptureFixture, broken: str
) -> None:
    """A failing parsing row must leave a warning naming the row."""

    def boom() -> None:
        raise RuntimeError(f"parsing row {broken} failed")

    row = _spec(boom) if broken == "read" else _spec(lambda: "text_only", boom)
    _write_specs(
        monkeypatch,
        **{
            "catalog.embedding": _configured("openai/text-embedding-3-small"),
            "catalog.search": _configured("tavily"),
            "document_parsing.engine": row,
        },
    )

    with caplog.at_level(logging.WARNING, logger=BINDING_LOGGER):
        gaps = setup_gaps()

    assert gaps == ()
    records = [record for record in caplog.records if record.name == BINDING_LOGGER]
    assert records, "the swallowed parsing-row failure must be logged"
    assert any("document_parsing.engine" in record.getMessage() for record in records)


def test_failed_intro_write_is_logged(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    """A failing intro-marker write must leave a warning naming the key."""

    def boom(key, value) -> None:
        raise OSError("interface.json unwritable")

    monkeypatch.setattr(f"{INTERFACE_SETTINGS}.set_ui_setting", boom)

    with caplog.at_level(logging.WARNING, logger=BINDING_LOGGER):
        mark_intro_shown()

    records = [record for record in caplog.records if record.name == BINDING_LOGGER]
    assert records, "the swallowed intro write failure must be logged"
    assert any(INTRO_SHOWN_KEY in record.getMessage() for record in records)
