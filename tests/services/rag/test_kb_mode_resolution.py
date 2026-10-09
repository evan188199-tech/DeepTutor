"""Retrieval-mode resolution for mode-aware pipelines.

Covers :func:`resolve_kb_mode`'s documented resolution order — explicit
override, the KB's own ``search_mode``, the provider's configured default,
then the engine's built-in default — plus case/whitespace normalization,
per-provider scoping, and the defensive fallback for a corrupt config file.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.rag.pipelines.modes import resolve_kb_mode

SUPPORTED = ("hybrid", "local", "global", "naive", "mix")
ENGINE_DEFAULT = "hybrid"


def _write_config(base: Path, config: dict) -> None:
    (base / "kb_config.json").write_text(json.dumps(config), encoding="utf-8")


def test_explicit_override_wins_and_is_normalized(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"kb": {"search_mode": "global"}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit="  Mix ", supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "mix"


def test_invalid_explicit_falls_back_to_kb_search_mode(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"kb": {"search_mode": "Global"}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit="bogus", supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "global"


def test_kb_search_mode_is_normalized(tmp_path: Path) -> None:
    _write_config(tmp_path, {"knowledge_bases": {"kb": {"search_mode": "  HYBRID  "}}})
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default="naive"
    )
    assert resolved == "hybrid"


def test_invalid_kb_mode_falls_back_to_provider_default(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"kb": {"search_mode": "warp-drive"}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "local"


def test_missing_kb_name_uses_provider_default(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"kb": {"search_mode": "global"}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, None, "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "local"


def test_unknown_kb_name_skips_entry(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"other": {"search_mode": "global"}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "local"


def test_provider_default_is_scoped_per_provider(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"knowledge_bases": {}, "defaults": {"provider_modes": {"graphrag": "global"}}},
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == ENGINE_DEFAULT


def test_builtin_default_without_config_file(tmp_path: Path) -> None:
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == ENGINE_DEFAULT


def test_corrupt_config_falls_back_to_engine_default(tmp_path: Path) -> None:
    (tmp_path / "kb_config.json").write_text("{not json", encoding="utf-8")
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit=None, supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == ENGINE_DEFAULT


def test_blank_candidates_are_skipped(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "knowledge_bases": {"kb": {}},
            "defaults": {"provider_modes": {"llamaindex": "local"}},
        },
    )
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit="", supported=SUPPORTED, default=ENGINE_DEFAULT
    )
    assert resolved == "local"


def test_supported_list_is_case_insensitive(tmp_path: Path) -> None:
    resolved = resolve_kb_mode(
        tmp_path, "kb", "llamaindex", explicit="LOCAL", supported=("Local", "Global"), default="naive"
    )
    assert resolved == "local"
