from __future__ import annotations

import json
from pathlib import Path

from deeptutor.multi_user.legacy_kids_learner_migration import LegacyKidsLearnerMigration


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _source(root: Path) -> tuple[Path, Path, Path]:
    immersive = root / "data" / "user" / "workspace" / "immersive_reading"
    kids = immersive / "kids"
    _write(
        kids / "profiles.json",
        [
            {"id": "other", "name": "Other", "birth_date": "2015-01-01"},
            {"id": "baby", "name": "Baby", "birth_date": "2018-01-01"},
        ],
    )
    _write(
        kids / "assignments.json",
        [
            {
                "id": "reading-1",
                "profile_id": "baby",
                "content_type": "reading",
                "document_id": "doc-one",
                "document_title": "One",
                "status": "active",
                "sort_order": 0,
            },
            {
                "id": "book",
                "profile_id": "baby",
                "content_type": "interactive_book",
                "book_id": "bk_book",
                "status": "active",
                "sort_order": 1,
            },
            {
                "id": "reading-2",
                "profile_id": "baby",
                "content_type": "reading",
                "document_id": "doc-two",
                "document_title": "Two",
                "status": "active",
                "sort_order": 2,
            },
            {
                "id": "ignored",
                "profile_id": "other",
                "content_type": "reading",
                "document_id": "doc-three",
                "status": "active",
                "sort_order": 0,
            },
        ],
    )
    for document_id, text, index in (("doc-one", "first", 0), ("doc-two", "second", 0)):
        document = immersive / f"document_{document_id}"
        document.mkdir(parents=True)
        (document / "original.txt").write_text(text, encoding="utf-8")
        _write(document / "manifest.json", {"source_filename": f"{document_id}.txt"})
        sections = document / "sections"
        sections.mkdir()
        for number in range(1, 5):
            (sections / f"section_{number:04d}.txt").write_text(text, encoding="utf-8")
        _write(
            kids / "progress" / f"baby_{document_id}.json",
            {
                "current_section_index": index,
                "scroll_percent": 25,
                "epub_cfi": f"epubcfi({document_id})",
                "completed_section_ids": ["section_0001"],
                "quiz_scores": {"section_0001": 3},
                "updated_at": 123.0,
            },
        )

    book = root / "data" / "user" / "workspace" / "book" / "book_bk_book"
    _write(book / "manifest.json", {"id": "bk_book", "title": "Shared book", "page_count": 2})
    _write(
        book / "spine.json",
        {"book_id": "bk_book", "chapters": [{"id": "ch", "page_ids": ["pg_current", "pg_next"]}]},
    )
    _write(
        kids / "progress" / "ib_baby_bk_book.json",
        {
            "current_page_id": "pg_current",
            "completed_page_ids": [],
            "updated_at": 456.0,
        },
    )
    return immersive, kids, book


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_dry_run_selects_only_baby_and_makes_zero_writes(
    tmp_path, mu_isolated_root, seed_user
) -> None:
    _source(tmp_path)
    seed_user("admin", role="admin")
    seed_user("Baby")
    migration = LegacyKidsLearnerMigration(profile_name="baby")
    before = _tree_snapshot(tmp_path)

    result = migration.plan()

    assert result["writes"] == 0
    assert result["profile"]["id"] == "baby"
    assert result["account"]["username"] == "Baby"
    assert [item["document_id"] for item in result["reading_materials"]] == [
        "doc-one",
        "doc-two",
    ]
    assert [item["book_id"] for item in result["interactive_books"]] == ["bk_book"]
    assert _tree_snapshot(tmp_path) == before


def test_apply_reuses_baby_and_is_idempotent(tmp_path, mu_isolated_root, seed_user) -> None:
    immersive, _kids, book = _source(tmp_path)
    seed_user("admin", role="admin")
    account = seed_user("Baby")
    immersive_before = _tree_snapshot(immersive)
    book_before = _tree_snapshot(book)
    migration = LegacyKidsLearnerMigration(profile_name="Baby")

    result = migration.apply()

    assert result["mode"] == "apply"
    assert result["account"]["id"] == account["id"]
    stored = json.loads(
        (tmp_path / "data" / "system" / "auth" / "users.json").read_text(encoding="utf-8")
    )
    assert stored["Baby"]["id"] == account["id"]
    assert stored["Baby"]["hash"] == account["hash"]
    assert stored["Baby"]["preset"] == "learner"
    assert stored["Baby"]["learner_profile"] == {"schema_version": 1, "age": 8}
    assert stored["Baby"]["book_permission"] == {
        "create": False,
        "default": "none",
        "books": {"bk_book": "read"},
    }

    workspace = tmp_path / "data" / "users" / account["id"] / "user" / "workspace"
    assert not (workspace / "book" / "book_bk_book").exists()
    assert _tree_snapshot(immersive) == immersive_before
    assert _tree_snapshot(book) == book_before

    from deeptutor.book.learning_overlay import BookLearningOverlay
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.reading import ReadingStore
    from deeptutor.services.path_service import PathService

    reading = ReadingStore(workspace / "reading")
    grant = load_grant(str(account["id"]))
    assert grant["exec_enabled"] is False
    assert grant["learning_policy"]["age_band"] == "6-8"
    assert grant["learning_policy"]["reading"]["allow_upload"] is False
    assert grant["learning_policy"]["reading"]["extensions"] == [
        "read_aloud",
        "guided_learning",
        "vocabulary",
        "quiz",
    ]
    assert len(grant["learning_policy"]["reading"]["material_ids"]) == 2
    for item in result["reading_materials"]:
        position = reading.position(str(item["material_id"]))
        assert position.locator == item["locator"]
        assert position.source_anchor == item["source_anchor"]
        assert position.percentage == 0.25
    progress = BookLearningOverlay(
        PathService(workspace_root=workspace.parent.parent)
    ).load_progress("bk_book")
    assert progress is not None
    assert progress.current_page_id == "pg_current"
    assert progress.visited_page_ids == ["pg_current"]
    assert progress.updated_at == 456.0
    journal = json.loads(
        (tmp_path / "data" / "system" / "migrations" / "baby-kids-to-learner.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["reading_progress"]["doc-one"]["completed_section_ids"] == ["section_0001"]
    assert journal["reading_progress"]["doc-one"]["quiz_scores"] == {"section_0001": 3}
    assert journal["interactive_book_progress"]["bk_book"]["current_page_id"] == "pg_current"

    after_apply = _tree_snapshot(tmp_path)
    second = migration.apply()
    assert second["writes"] == 0
    assert _tree_snapshot(tmp_path) == after_apply


def test_migration_rejects_ambiguous_missing_or_unmatched_state(
    tmp_path, mu_isolated_root, seed_user
) -> None:
    _source(tmp_path)
    seed_user("admin", role="admin")
    seed_user("Baby")
    profiles_path = (
        tmp_path / "data" / "user" / "workspace" / "immersive_reading" / "kids" / "profiles.json"
    )
    original = json.loads(profiles_path.read_text(encoding="utf-8"))

    try:
        LegacyKidsLearnerMigration(profile_name="Missing").plan()
    except ValueError:
        pass
    else:
        raise AssertionError("missing profile was accepted")

    duplicate = original + [{**original[1], "id": "baby-duplicate"}]
    profiles_path.write_text(json.dumps(duplicate), encoding="utf-8")
    try:
        LegacyKidsLearnerMigration(profile_name="Baby").plan()
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate profile was accepted")

    profiles_path.write_text(json.dumps(original), encoding="utf-8")
    users_path = tmp_path / "data" / "system" / "auth" / "users.json"
    users = json.loads(users_path.read_text(encoding="utf-8"))
    users.pop("Baby")
    users_path.write_text(json.dumps(users), encoding="utf-8")
    try:
        LegacyKidsLearnerMigration(profile_name="Baby").plan()
    except ValueError:
        pass
    else:
        raise AssertionError("missing account was accepted")


def test_cli_defaults_to_dry_run(tmp_path, mu_isolated_root, seed_user) -> None:
    from typer.testing import CliRunner

    from deeptutor_cli.main import app

    _source(tmp_path)
    seed_user("admin", role="admin")
    seed_user("Baby")
    result = CliRunner().invoke(app, ["migrate", "legacy-kids", "--profile", "Baby"])

    assert result.exit_code == 0
    assert '"mode": "dry-run"' in result.output
    assert '"writes": 0' in result.output
