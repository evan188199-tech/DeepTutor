"""Contract tests for Codex credential storage, corruption fallback, and cold init."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from deeptutor.services.codex_auth.contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
    CodexModel,
)
from deeptutor.services.codex_auth.storage import CodexCredentialStore


def _credentials(generation: int = 0, account_id: str = "account-123") -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id=account_id,
        expires_at=10_000,
        generation=generation,
    )


def _snapshot(generation: int = 1, account_hash: str = "hash") -> CatalogSnapshot:
    model = CodexModel(
        slug="gpt-5.6-sol",
        display_name="Sol",
        priority=1,
        visibility="visible",
        default_reasoning_level="medium",
        supported_reasoning_levels=("low", "medium", "high"),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
    )
    return CatalogSnapshot(
        models=(model,),
        source="live",
        fetched_at=1_000,
        etag=None,
        generation=generation,
        account_hash=account_hash,
    )


def test_commit_and_load_round_trip_bumps_generation(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)

    committed = store.commit_credentials(_credentials(), expected_generation=0)
    loaded = store.load_credentials()

    assert committed.generation == 1
    assert committed.schema_version == 1
    assert loaded is not None
    assert loaded == committed
    assert store.current_generation() == 1
    assert store.credentials_path.name == "credentials.v1.json"
    assert store.state_path.name == "state.v1.json"
    if sys.platform != "win32":
        assert stat.S_IMODE(store.credentials_path.stat().st_mode) == 0o600


def test_commit_rejects_a_stale_expected_generation(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)

    with pytest.raises(CodexAuthError) as exc_info:
        store.commit_credentials(_credentials(), expected_generation=0)

    assert exc_info.value.code == "generation_changed"
    assert store.current_generation() == 1


def test_credentials_from_an_older_generation_fall_back_to_absent(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)
    payload = json.loads(store.credentials_path.read_text(encoding="utf-8"))
    payload["generation"] = 0
    store.credentials_path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.load_credentials() is None


def test_a_newer_generation_than_state_is_also_treated_as_absent(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)
    payload = json.loads(store.credentials_path.read_text(encoding="utf-8"))
    payload["generation"] = 99
    store.credentials_path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.load_credentials() is None


def test_corrupt_credentials_file_raises_credential_corrupt(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)
    store.credentials_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "credential_corrupt"
    assert exc_info.value.http_status == 500


def test_non_object_credentials_payload_raises_credential_corrupt(
    tmp_path: Path,
) -> None:
    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text('["a", "list"]', encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "credential_corrupt"


def test_schema_invalid_credentials_raise_credential_corrupt(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    payload = _credentials().to_dict()
    del payload["account_id"]
    store.credentials_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "credential_corrupt"


@pytest.mark.parametrize("generation", [True, -1, "1", 1.5])
def test_invalid_state_generation_raises_state_corrupt(
    tmp_path: Path,
    generation: object,
) -> None:
    store = CodexCredentialStore(tmp_path)
    store.state_path.parent.mkdir(parents=True)
    store.state_path.write_text(json.dumps({"generation": generation}), encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.current_generation()

    assert exc_info.value.code == "state_corrupt"


def test_corrupt_state_file_raises_state_corrupt(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)
    store.state_path.write_text("garbage{", encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "state_corrupt"


def test_catalog_cache_round_trip(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    snapshot = _snapshot()

    store.save_catalog_cache(snapshot.to_dict())

    loaded = store.load_catalog_cache()
    assert loaded is not None
    assert CatalogSnapshot.from_dict(loaded) == snapshot


def test_corrupt_catalog_cache_raises_but_invalidation_falls_back_to_unlink(
    tmp_path: Path,
) -> None:
    store = CodexCredentialStore(tmp_path)
    store.save_catalog_cache(_snapshot().to_dict())
    store.catalog_cache_path.write_text("<<<corrupt>>>", encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_catalog_cache()
    assert exc_info.value.code == "catalog_corrupt"

    store.invalidate_catalog_models("hash", generation=1)

    assert not store.catalog_cache_path.exists()
    assert store.load_catalog_cache() is None


def test_clear_removes_credentials_and_catalog_cache(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)
    store.save_catalog_cache(_snapshot().to_dict())

    generation = store.clear_credentials()

    assert generation == 2
    assert store.load_credentials() is None
    assert store.load_catalog_cache() is None
    assert store.current_generation() == 2


def test_cold_store_initializes_missing_directories_on_first_use(tmp_path: Path) -> None:
    user_root = tmp_path / "deep" / "nested" / "user"
    store = CodexCredentialStore(user_root)

    assert not user_root.exists()
    assert store.load_credentials() is None
    assert store.current_generation() == 0
    assert store.root.is_dir()
    assert store.root.parent.is_dir()

    store.commit_credentials(_credentials(), expected_generation=0)

    assert store.current_generation() == 1
    assert store.credentials_path.is_file()
    assert store.state_path.is_file()
    if sys.platform != "win32":
        assert stat.S_IMODE(store.root.stat().st_mode) == stat.S_IRWXU


def test_deleted_storage_root_reinitializes_from_scratch(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(), expected_generation=0)

    import shutil

    shutil.rmtree(store.root.parent)

    assert store.load_credentials() is None
    assert store.current_generation() == 0
    assert store.root.is_dir()


def test_store_never_writes_outside_its_user_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    store = CodexCredentialStore(tmp_path / "user")

    store.commit_credentials(_credentials(), expected_generation=0)

    assert list(outside.iterdir()) == []
    assert os.path.commonpath([str(store.root), str(tmp_path / "user")]) == str(tmp_path / "user")
