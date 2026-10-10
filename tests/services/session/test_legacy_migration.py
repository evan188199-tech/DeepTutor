from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.services.session.legacy_migration import (
    LegacyChatSessionMigrator,
    LegacyMigrationError,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _write_legacy(path: Path, sessions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "sessions": sessions}), encoding="utf-8")


def _session(session_id: str = "chat_original") -> dict:
    return {
        "session_id": session_id,
        "title": "Original title",
        "created_at": 100.5,
        "updated_at": 103.5,
        "settings": {
            "kb_name": "physics",
            "enable_rag": True,
            "enable_web_search": True,
        },
        "messages": [
            {"role": "user", "content": "hello", "timestamp": 101.5},
            {
                "role": "assistant",
                "content": "answer",
                "timestamp": 102.5,
                "sources": {"rag": [{"title": "source"}], "web": []},
            },
        ],
    }


@pytest.mark.asyncio
async def test_migrates_timestamps_settings_sources_and_archives(tmp_path) -> None:
    source = tmp_path / "workspace" / "chat" / "chat" / "sessions.json"
    archive = tmp_path / "archive" / "legacy-chat"
    _write_legacy(source, [_session()])
    store = SQLiteSessionStore(tmp_path / "chat_history.db")

    report = await LegacyChatSessionMigrator(store, source, archive).migrate()

    assert report.imported == 1
    assert report.messages == 2
    assert report.failed == 0
    assert not source.exists()
    assert Path(report.archived_to).exists()
    detail = await store.get_session_with_messages("chat_original")
    assert detail is not None
    assert detail["title"] == "Original title"
    assert detail["created_at"] == 100.5
    assert detail["updated_at"] == 103.5
    assert detail["preferences"]["knowledge_bases"] == ["physics"]
    assert detail["preferences"]["tools"] == ["web_search"]
    assert [row["created_at"] for row in detail["messages"]] == [101.5, 102.5]
    assert detail["messages"][1]["metadata"]["sources"]["rag"][0]["title"] == "source"


@pytest.mark.asyncio
async def test_existing_session_is_not_overwritten_and_repeat_is_idempotent(
    tmp_path,
) -> None:
    source = tmp_path / "sessions.json"
    archive = tmp_path / "archive"
    payload = _session("chat_collision")
    _write_legacy(source, [payload])
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    await store.create_session("Keep me", "chat_collision")
    migrator = LegacyChatSessionMigrator(store, source, archive)

    first = await migrator.migrate()
    assert first.imported == 0 and first.skipped == 1
    assert (await store.get_session("chat_collision"))["title"] == "Keep me"

    archived = Path(first.archived_to)
    source.write_bytes(archived.read_bytes())
    second = await migrator.migrate()
    assert second.imported == 0 and second.skipped == 1
    assert not source.exists()
    assert len((archive / "migration-ledger.json").read_text().splitlines()) > 1


@pytest.mark.asyncio
async def test_corrupt_or_partial_migration_keeps_source(tmp_path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{bad", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    migrator = LegacyChatSessionMigrator(store, corrupt, tmp_path / "archive")
    with pytest.raises(LegacyMigrationError):
        await migrator.migrate()
    assert corrupt.exists()
    assert list((tmp_path / "archive").glob("pre-migration-*.json"))

    class _PartiallyFailingRepository:
        def __init__(self) -> None:
            self.imported: set[str] = set()
            self.fail_once = True

        async def import_legacy_session(self, **session):
            session_id = session["session_id"]
            if session_id == "chat_b" and self.fail_once:
                self.fail_once = False
                raise RuntimeError("simulated backend error")
            if session_id in self.imported:
                return {"imported": False, "message_count": 0}
            self.imported.add(session_id)
            return {"imported": True, "message_count": len(session["messages"])}

    source = tmp_path / "partial.json"
    _write_legacy(source, [_session("chat_a"), _session("chat_b")])
    repository = _PartiallyFailingRepository()
    partial = LegacyChatSessionMigrator(repository, source, tmp_path / "archive-partial")
    with pytest.raises(LegacyMigrationError):
        await partial.migrate()
    assert source.exists()

    recovered = await partial.migrate()
    assert recovered.imported == 1
    assert recovered.skipped == 1
    assert not source.exists()


@pytest.mark.asyncio
async def test_empty_and_dry_run_are_safe(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    source = tmp_path / "sessions.json"
    _write_legacy(source, [])
    migrator = LegacyChatSessionMigrator(store, source, tmp_path / "archive")

    dry_run = await migrator.migrate(dry_run=True)
    assert dry_run.imported == 0
    assert source.exists()

    applied = await migrator.migrate()
    assert applied.imported == 0
    assert not source.exists()


class _RecordingRepository:
    """Fake SessionRepository that records import payloads verbatim."""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or ())
        self.calls: list[dict] = []

    async def import_legacy_session(self, **session):
        self.calls.append(dict(session))
        if session["session_id"] in self.existing:
            return {"imported": False, "message_count": 0}
        self.existing.add(session["session_id"])
        return {"imported": True, "message_count": len(session["messages"])}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_ledger(archive: Path, runs: list[dict]) -> None:
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "migration-ledger.json").write_text(
        json.dumps({"version": 1, "runs": runs}), encoding="utf-8"
    )


def _read_ledger(archive: Path) -> dict:
    return json.loads((archive / "migration-ledger.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_sparse_session_defaults_are_applied(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(
        source,
        [
            {"session_id": "chat_sparse", "messages": [{"role": "user"}]},
            {
                "session_id": "chat_partial_defaults",
                "created_at": 55.0,
                "settings": "not-a-dict",
                "title": None,
                "messages": [{"role": "assistant", "content": "hi"}],
            },
        ],
    )
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(repository, source, tmp_path / "archive").migrate()

    assert report.imported == 2 and report.failed == 0
    sparse, partial = repository.calls
    assert sparse["title"] == "New conversation"
    assert sparse["created_at"] == 0.0 and sparse["updated_at"] == 0.0
    assert sparse["preferences"] == {
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "legacy_chat_settings": {},
        "legacy_migrated": True,
    }
    assert sparse["messages"][0]["created_at"] == 0.0
    assert sparse["messages"][0]["content"] == ""
    assert sparse["messages"][0]["metadata"] == {"legacy_chat": True}
    assert partial["title"] == "New conversation"
    assert partial["created_at"] == 55.0 and partial["updated_at"] == 55.0
    assert partial["messages"][0]["created_at"] == 55.0
    assert partial["preferences"]["legacy_chat_settings"] == {}


@pytest.mark.asyncio
async def test_settings_flags_drive_preferences_and_legacy_echo(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    settings = {"kb_name": "physics", "enable_rag": True, "enable_web_search": True}
    _write_legacy(
        source,
        [
            {
                "session_id": "chat_full_flags",
                "settings": settings,
                "messages": [],
            },
            {
                "session_id": "chat_rag_off",
                "settings": {"kb_name": "physics", "enable_web_search": False},
                "messages": [],
            },
        ],
    )
    repository = _RecordingRepository()

    await LegacyChatSessionMigrator(repository, source, tmp_path / "archive").migrate()

    full, rag_off = repository.calls
    assert full["preferences"]["knowledge_bases"] == ["physics"]
    assert full["preferences"]["tools"] == ["web_search"]
    assert full["preferences"]["legacy_chat_settings"] == dict(settings)
    assert rag_off["preferences"]["knowledge_bases"] == []
    assert rag_off["preferences"]["tools"] == []


@pytest.mark.asyncio
async def test_long_title_is_truncated_to_100_chars(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(
        source,
        [{"session_id": "chat_long_title", "title": "x" * 150, "messages": []}],
    )
    repository = _RecordingRepository()

    await LegacyChatSessionMigrator(repository, source, tmp_path / "archive").migrate()

    assert len(repository.calls[0]["title"]) == 100


@pytest.mark.asyncio
async def test_message_sources_kept_only_for_dict_or_list(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(
        source,
        [
            {
                "session_id": "chat_sources",
                "messages": [
                    {"role": "user", "content": "q", "sources": "not-a-container"},
                    {"role": "assistant", "content": "a", "sources": [{"title": "doc"}]},
                ],
            }
        ],
    )
    repository = _RecordingRepository()

    await LegacyChatSessionMigrator(repository, source, tmp_path / "archive").migrate()

    user_msg, assistant_msg = repository.calls[0]["messages"]
    assert "sources" not in user_msg["metadata"]
    assert user_msg["metadata"] == {"legacy_chat": True}
    assert assistant_msg["metadata"]["sources"] == [{"title": "doc"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_session",
    [
        "plain-string",
        {"title": "no id"},
        {"session_id": "chat_bad", "messages": "not-a-list"},
        {"session_id": "chat_bad", "messages": ["not-an-object"]},
        {"session_id": "chat_bad", "messages": [{"role": "bot", "content": "x"}]},
    ],
)
async def test_malformed_session_entries_fail_preflight_and_retain_source(
    tmp_path, raw_session
) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [raw_session])
    repository = _RecordingRepository()
    migrator = LegacyChatSessionMigrator(repository, source, tmp_path / "archive")

    with pytest.raises(LegacyMigrationError, match="preflight"):
        await migrator.migrate()

    assert source.exists()
    assert repository.calls == []
    assert not (tmp_path / "archive" / "migration-ledger.json").exists()


@pytest.mark.asyncio
async def test_corrupt_source_can_be_fixed_and_remigrated(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{bad", encoding="utf-8")
    repository = _RecordingRepository()
    migrator = LegacyChatSessionMigrator(repository, source, tmp_path / "archive")

    with pytest.raises(LegacyMigrationError):
        await migrator.migrate()

    _write_legacy(source, [_session("chat_recovered")])
    report = await migrator.migrate()

    assert report.imported == 1
    assert repository.calls[0]["session_id"] == "chat_recovered"
    assert not source.exists()
    ledger = _read_ledger(tmp_path / "archive")
    assert len(ledger["runs"]) == 1
    assert ledger["runs"][0]["source_hash"] == _sha256(Path(report.archived_to))


@pytest.mark.asyncio
async def test_missing_source_file_is_a_noop(tmp_path) -> None:
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(
        repository, tmp_path / "absent" / "sessions.json", tmp_path / "archive"
    ).migrate()

    assert report.imported == 0
    assert report.skipped == 0
    assert report.failed == 0
    assert report.source_hash == ""
    assert report.archived_to == ""
    assert repository.calls == []


@pytest.mark.asyncio
async def test_root_shapes_rejected_or_treated_as_empty(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    source.write_text(json.dumps([1, 2]), encoding="utf-8")
    repository = _RecordingRepository()
    migrator = LegacyChatSessionMigrator(repository, source, tmp_path / "archive")

    with pytest.raises(LegacyMigrationError, match="sessions list"):
        await migrator.migrate()
    assert source.exists()

    source.write_text(json.dumps({"no_sessions_key": True}), encoding="utf-8")
    report = await migrator.migrate()

    assert report.imported == 0
    assert not source.exists()
    assert not repository.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    ["{not json", json.dumps([]), json.dumps({"runs": None}), json.dumps({"version": 2})],
)
async def test_invalid_ledger_payloads_start_fresh(tmp_path, payload: str) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [_session("chat_ledger_reset")])
    archive = tmp_path / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "migration-ledger.json").write_text(payload, encoding="utf-8")
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(repository, source, archive).migrate()

    assert report.imported == 1 and report.skipped == 0
    assert len(_read_ledger(archive)["runs"]) == 1


@pytest.mark.asyncio
async def test_completed_ledger_reentry_restores_counts_without_repo_calls(
    tmp_path,
) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [_session("chat_a"), _session("chat_b")])
    archive = tmp_path / "archive"
    repository = _RecordingRepository()
    first = await LegacyChatSessionMigrator(repository, source, archive).migrate()
    assert first.imported == 2

    fresh_repository = _RecordingRepository()
    source.write_bytes(Path(first.archived_to).read_bytes())
    second = await LegacyChatSessionMigrator(fresh_repository, source, archive).migrate()

    assert second.imported == 0
    assert second.skipped == 2
    assert second.messages == 0
    assert second.failed == 0
    assert fresh_repository.calls == []
    assert source.exists() is False
    assert _read_ledger(archive)["runs"][-1]["source_hash"] == _sha256(Path(second.archived_to))


@pytest.mark.asyncio
async def test_failed_ledger_entry_does_not_block_reimport(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [_session("chat_retry")])
    digest = _sha256(source)
    archive = tmp_path / "archive"
    _write_ledger(archive, [{"source_hash": digest, "failed": True, "imported": 9}])
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(repository, source, archive).migrate()

    assert report.imported == 1 and report.skipped == 0
    runs = _read_ledger(archive)["runs"]
    assert len(runs) == 2
    assert not runs[1].get("failed")


@pytest.mark.asyncio
async def test_seeded_successful_ledger_entry_skips_with_restored_counts(
    tmp_path,
) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [_session("chat_seeded")])
    digest = _sha256(source)
    archive = tmp_path / "archive"
    _write_ledger(
        archive,
        [{"source_hash": digest, "imported": 3, "skipped": 4}],
    )
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(repository, source, archive).migrate()

    assert report.imported == 0
    assert report.skipped == 7
    assert repository.calls == []
    assert not source.exists()
    assert report.archived_to


@pytest.mark.asyncio
async def test_dry_run_reports_counts_without_side_effects(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(
        source,
        [_session("chat_dry_a"), _session("chat_dry_b"), _session("chat_dry_c")],
    )
    archive = tmp_path / "archive"
    repository = _RecordingRepository()

    report = await LegacyChatSessionMigrator(repository, source, archive).migrate(dry_run=True)

    assert report.imported == 3
    assert report.messages == 6
    assert report.failed == 0
    assert repository.calls == []
    assert source.exists()
    assert report.archived_to == ""
    assert not list(archive.glob("pre-migration-*.json"))
    assert not (archive / "migration-ledger.json").exists()


@pytest.mark.asyncio
async def test_dry_run_after_completion_does_not_archive(tmp_path) -> None:
    source = tmp_path / "sessions.json"
    _write_legacy(source, [_session("chat_done")])
    archive = tmp_path / "archive"
    repository = _RecordingRepository()
    first = await LegacyChatSessionMigrator(repository, source, archive).migrate()
    assert first.imported == 1

    source.write_bytes(Path(first.archived_to).read_bytes())
    report = await LegacyChatSessionMigrator(repository, source, archive).migrate(dry_run=True)

    assert report.imported == 0
    assert report.skipped == 1
    assert report.archived_to == ""
    assert source.exists()
    assert len(_read_ledger(archive)["runs"]) == 1
