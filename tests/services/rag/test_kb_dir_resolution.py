"""On-disk directory resolution for a knowledge base.

Extends the linked-KB coverage in ``test_linked_kb.py`` with the remaining
:func:`resolve_kb_dir` branches: the ``vault_path`` fallback, field
precedence, ``~`` expansion, and the conventional-layout fallbacks when the
config file is missing, corrupt, or carries unusable entries.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.rag.kb_paths import resolve_kb_dir


def _write_config(base: Path, config: dict) -> None:
    (base / "kb_config.json").write_text(json.dumps(config), encoding="utf-8")


def test_vault_path_fallback(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    vault = tmp_path / "my-vault"
    vault.mkdir()
    _write_config(base, {"knowledge_bases": {"notes": {"type": "obsidian", "vault_path": str(vault)}}})
    assert resolve_kb_dir(base, "notes") == vault


def test_external_path_takes_precedence_over_vault_path(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    external = tmp_path / "engine-index"
    vault = tmp_path / "my-vault"
    external.mkdir()
    vault.mkdir()
    _write_config(
        base,
        {
            "knowledge_bases": {
                "notes": {"external_path": str(external), "vault_path": str(vault)}
            }
        },
    )
    assert resolve_kb_dir(base, "notes") == external


def test_blank_pointer_falls_back_to_conventional(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    _write_config(base, {"knowledge_bases": {"notes": {"external_path": ""}}})
    assert resolve_kb_dir(base, "notes") == base / "notes"


def test_external_path_is_user_expanded(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(base, {"knowledge_bases": {"notes": {"external_path": "~/vaults/notebook"}}})
    assert resolve_kb_dir(base, "notes") == tmp_path / "vaults" / "notebook"


def test_corrupt_config_falls_back_to_conventional(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    (base / "kb_config.json").write_text("{not json", encoding="utf-8")
    assert resolve_kb_dir(base, "notes") == base / "notes"


def test_config_without_knowledge_bases_key(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    _write_config(base, {"defaults": {"provider_modes": {"llamaindex": "local"}}})
    assert resolve_kb_dir(base, "notes") == base / "notes"


def test_non_dict_entry_is_ignored(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    _write_config(base, {"knowledge_bases": {"notes": 42}})
    assert resolve_kb_dir(base, "notes") == base / "notes"


def test_missing_config_file_conventional_layout(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    assert resolve_kb_dir(base, "notes") == base / "notes"


def test_accepts_path_or_str_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    assert resolve_kb_dir(Path(base), "notes") == base / "notes"
    assert resolve_kb_dir(str(base), "notes") == base / "notes"
