"""Edge branches of the legacy channel-state rehoming that the main file skips.

Complements ``test_channel_state_migration.py``: the legacy-dir ledger itself,
the owner-detection boundary cases (corrupt state, blank or duplicate tokens,
malformed channel configs), and what happens when the copy itself fails —
the legacy tree must always survive as the fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import types

import pytest

from deeptutor.partners.config import paths as partner_paths
from deeptutor.partners.helpers import ensure_dir
from deeptutor.services.partners import channel_state_migration as migration
from deeptutor.services.partners.channel_state_migration import (
    LEGACY_STATE_DIRS,
    rehome_shared_channel_state,
)


@pytest.fixture
def partners_root(tmp_path, monkeypatch):
    root = ensure_dir(tmp_path / "partners")
    monkeypatch.setattr(partner_paths, "_base_dir", lambda: root)
    return root


def _legacy_account(partners_root: Path, channel: str, payload) -> Path:
    legacy = ensure_dir(partners_root / LEGACY_STATE_DIRS[channel])
    target = legacy / "account.json"
    if isinstance(payload, str):
        target.write_text(payload, encoding="utf-8")
    else:
        target.write_text(json.dumps(payload), encoding="utf-8")
    return legacy


def _adopted(partners_root, partner_id: str, channel: str, name: str = "account.json") -> Path:
    return partners_root / partner_id / "channels" / channel / name


class TestLegacyStateMapping:
    def test_ledger_covers_the_four_shared_channels(self):
        assert LEGACY_STATE_DIRS == {
            "weixin": "weixin",
            "mochat": "mochat",
            "msteams": "msteams",
            "matrix": "matrix-store",
        }

    def test_mochat_and_msteams_rehome_by_their_legacy_dir_name(self, partners_root):
        for channel in ("mochat", "msteams"):
            legacy = ensure_dir(partners_root / LEGACY_STATE_DIRS[channel])
            (legacy / "state.json").write_text(json.dumps({"channel": channel}), encoding="utf-8")

        rehome_shared_channel_state(
            {
                "alice": {"mochat": {"enabled": True}},
                "bob": {"msteams": {"enabled": True}},
            }
        )

        assert (
            json.loads(_adopted(partners_root, "alice", "mochat", "state.json").read_text())[
                "channel"
            ]
            == "mochat"
        )
        assert (
            json.loads(_adopted(partners_root, "bob", "msteams", "state.json").read_text())[
                "channel"
            ]
            == "msteams"
        )

    def test_present_but_empty_legacy_dir_is_skipped(self, partners_root):
        ensure_dir(partners_root / "weixin")

        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})

        assert not _adopted(partners_root, "alice", "weixin").exists()


class TestOwnerDetectionEdges:
    def test_corrupt_legacy_account_json_leaves_ownership_undecided(self, partners_root):
        _legacy_account(partners_root, "weixin", "{not json")

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True, "token": "token-a"}},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert not _adopted(partners_root, "bob", "weixin").exists()
        assert (partners_root / "weixin" / "account.json").exists()

    def test_unreadable_legacy_account_json_is_not_a_claim(self, partners_root):
        legacy = ensure_dir(partners_root / "weixin")
        ensure_dir(legacy / "account.json")  # a directory: read_text() raises OSError

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True, "token": "token-a"}},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert not _adopted(partners_root, "bob", "weixin").exists()

    def test_non_dict_legacy_account_json_is_not_a_claim(self, partners_root):
        _legacy_account(partners_root, "weixin", ["token-a", "token-b"])

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True, "token": "token-a"}},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert not _adopted(partners_root, "bob", "weixin").exists()

    def test_partner_without_a_configured_token_cannot_claim(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "token-b"})

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True}},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert _adopted(partners_root, "bob", "weixin").exists()
        assert not _adopted(partners_root, "alice", "weixin").exists()

    def test_token_comparison_ignores_surrounding_whitespace(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "  token-b  "})

        rehome_shared_channel_state({"bob": {"weixin": {"enabled": True, "token": " token-b "}}})

        assert (
            json.loads(_adopted(partners_root, "bob", "weixin").read_text())["token"]
            == "  token-b  "
        )

    def test_two_partners_configured_with_one_token_are_not_split(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "token-shared"})

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True, "token": "token-shared"}},
                "bob": {"weixin": {"enabled": True, "token": "token-shared"}},
            }
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert not _adopted(partners_root, "bob", "weixin").exists()
        assert (partners_root / "weixin" / "account.json").exists()

    def test_channel_config_that_is_not_a_mapping_is_not_a_candidate(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "token-b"})

        rehome_shared_channel_state(
            {
                "alice": {"weixin": "on"},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert _adopted(partners_root, "bob", "weixin").exists()
        assert not _adopted(partners_root, "alice", "weixin").exists()

    def test_channel_entry_without_enabled_flag_is_not_a_candidate(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "token-legacy"})

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"token": "token-legacy"}},
                "bob": {"weixin": {"enabled": True, "token": "token-other"}},
            }
        )

        assert _adopted(partners_root, "bob", "weixin").exists()
        assert not _adopted(partners_root, "alice", "weixin").exists()

    def test_no_enabled_candidates_leaves_legacy_alone(self, partners_root):
        _legacy_account(partners_root, "weixin", {"token": "token-legacy"})

        rehome_shared_channel_state(
            {"alice": {"weixin": {"enabled": False, "token": "token-legacy"}}}
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert (partners_root / "weixin" / "account.json").exists()


class TestCopyFailureFallback:
    @staticmethod
    def _sqlite_store(path: Path) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE device_keys (user TEXT, key TEXT)")
            conn.execute("INSERT INTO device_keys VALUES ('alice', 'k1')")
            conn.commit()
        finally:
            conn.close()

    def test_failed_copy_leaves_legacy_intact(self, partners_root, monkeypatch):
        legacy = ensure_dir(partners_root / "matrix-store")
        db = legacy / "nio.db"
        self._sqlite_store(db)

        def _broken_copytree(*args, **kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(migration, "shutil", types.SimpleNamespace(copytree=_broken_copytree))

        rehome_shared_channel_state({"alice": {"matrix": {"enabled": True}}})

        assert not _adopted(partners_root, "alice", "matrix", "nio.db").exists()
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT user, key FROM device_keys").fetchall()
        finally:
            conn.close()
        assert rows == [("alice", "k1")]

    def test_rehoming_recovers_after_a_transient_copy_failure(self, partners_root, monkeypatch):
        legacy = ensure_dir(partners_root / "matrix-store")
        db = legacy / "nio.db"
        self._sqlite_store(db)
        real_copytree = migration.shutil.copytree
        attempts = []

        def _flaky_copytree(src, dst, **kwargs):
            attempts.append(src)
            if len(attempts) == 1:
                raise OSError(5, "transient I/O error")
            return real_copytree(src, dst, **kwargs)

        monkeypatch.setattr(migration, "shutil", types.SimpleNamespace(copytree=_flaky_copytree))

        rehome_shared_channel_state({"alice": {"matrix": {"enabled": True}}})
        assert not _adopted(partners_root, "alice", "matrix", "nio.db").exists()

        rehome_shared_channel_state({"alice": {"matrix": {"enabled": True}}})
        assert _adopted(partners_root, "alice", "matrix", "nio.db").exists()
        assert (legacy / "nio.db").exists()

    def test_one_channel_failing_does_not_block_the_others(self, partners_root, monkeypatch):
        _legacy_account(partners_root, "weixin", {"token": "token-a", "cursor": "c1"})
        legacy_store = ensure_dir(partners_root / "matrix-store")
        self._sqlite_store(legacy_store / "nio.db")
        real_copytree = migration.shutil.copytree

        def _weixin_fails(src, dst, **kwargs):
            if Path(src).name == "weixin":
                raise OSError(28, "no space left on device")
            return real_copytree(src, dst, **kwargs)

        monkeypatch.setattr(migration, "shutil", types.SimpleNamespace(copytree=_weixin_fails))

        rehome_shared_channel_state(
            {
                "alice": {
                    "weixin": {"enabled": True, "token": "token-a"},
                    "matrix": {"enabled": True},
                }
            }
        )

        assert not _adopted(partners_root, "alice", "weixin").exists()
        assert (partners_root / "weixin" / "account.json").exists()
        assert _adopted(partners_root, "alice", "matrix", "nio.db").exists()
