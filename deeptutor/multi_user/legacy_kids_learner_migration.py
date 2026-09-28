"""One-profile migration from the retired Kids workspace to learner accounts."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from deeptutor.book.learning_overlay import BookLearningOverlay
from deeptutor.book.models import Progress
from deeptutor.book.storage import BookStorage
from deeptutor.multi_user.book_permission import (
    BookPermission,
    normalize_book_permission,
)
from deeptutor.multi_user.grants import save_grant
from deeptutor.multi_user.identity import (
    get_user,
    set_book_permission,
    set_learner_profile,
    set_preset,
)
from deeptutor.multi_user.paths import (
    ensure_user_workspace,
    get_admin_path_service,
)
from deeptutor.reading import ReadingPosition, ReadingStore
from deeptutor.reading.store import content_hash
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import PathService

_READING_EXTENSIONS = ("read_aloud", "guided_learning", "vocabulary", "quiz")


def _read_json(path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _clean_id(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"Legacy Kids {label} is missing")
    return result


def _age_and_band(profile: dict[str, Any]) -> tuple[int, str]:
    try:
        born = date.fromisoformat(str(profile.get("birth_date") or ""))
    except ValueError as exc:
        raise ValueError("Legacy Kids profile has an invalid birth_date") from exc
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if 6 <= age <= 8:
        band = "6-8"
    elif 9 <= age <= 12:
        band = "9-12"
    elif 13 <= age <= 15:
        band = "13-15"
    else:
        raise ValueError(f"Legacy Kids profile age {age} has no supported learner age band")
    return age, band


def _number(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Legacy Kids {label} is invalid") from exc


class LegacyKidsLearnerMigration:
    """Migrate exactly one named legacy Kids profile into an existing account."""

    def __init__(
        self,
        *,
        profile_name: str,
        kids_root: Path | None = None,
        immersive_root: Path | None = None,
        journal_path: Path | None = None,
    ) -> None:
        from deeptutor.multi_user import paths

        self.profile_name = str(profile_name or "").strip()
        if not self.profile_name:
            raise ValueError("A legacy Kids profile name is required")
        if self.profile_name.casefold() != "baby":
            raise ValueError("This one-time migration is limited to the Baby profile")
        admin_workspace = get_admin_path_service().get_workspace_dir()
        self.immersive_root = immersive_root or admin_workspace / "immersive_reading"
        self.kids_root = kids_root or self.immersive_root / "kids"
        self.journal_path = journal_path or (
            paths.SYSTEM_ROOT / "migrations" / "baby-kids-to-learner.json"
        )

    def plan(self) -> dict[str, Any]:
        profile, profile_id = self._select_profile()
        assignments = self._assignments(profile_id)
        account_username, account = self._select_account()
        age, age_band = _age_and_band(profile)

        reading_items: list[dict[str, Any]] = []
        book_items: list[dict[str, Any]] = []
        for assignment in assignments:
            content_type = str(assignment.get("content_type") or "")
            if content_type == "reading":
                reading_items.append(self._reading_item(assignment, profile_id))
            elif content_type == "interactive_book":
                book_items.append(self._book_item(assignment, profile_id))
            else:
                raise ValueError(
                    "Unsupported legacy Kids assignment type for "
                    f"{self.profile_name}: {content_type!r}"
                )

        if len({item["document_id"] for item in reading_items}) != len(reading_items):
            raise ValueError("Legacy Kids profile has duplicate reading assignments")
        if len({item["book_id"] for item in book_items}) != len(book_items):
            raise ValueError("Legacy Kids profile has duplicate interactive book assignments")

        journal = _read_json(self.journal_path, {})
        if journal != {}:
            if not isinstance(journal, dict) or journal.get("version") != 1:
                raise ValueError("The Baby migration journal is invalid")
            if journal.get("profile_id") != profile_id:
                raise ValueError("The Baby migration journal belongs to another profile")
        fingerprint_payload = {
            "profile_id": profile_id,
            "account_id": str(account.get("id") or ""),
            "profile": profile,
            "reading": reading_items,
            "books": book_items,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False, default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        journal_matches = (
            isinstance(journal, dict)
            and journal.get("status") == "complete"
            and journal.get("profile_id") == profile_id
            and journal.get("username") == account_username
            and journal.get("user_id") == str(account.get("id") or "")
        )
        if journal_matches and journal.get("source_fingerprint") != fingerprint:
            raise ValueError("Legacy Kids source changed after the completed Baby migration")

        return {
            "mode": "dry-run",
            "writes": 0,
            "profile": {
                "id": profile_id,
                "name": str(profile.get("name") or ""),
                "age": age,
            },
            "account": {
                "username": account_username,
                "id": str(account.get("id") or ""),
                "preset": str(account.get("preset") or "standard"),
            },
            "age_band": age_band,
            "reading_materials": reading_items,
            "interactive_books": book_items,
            "already_migrated": journal_matches,
            "source_fingerprint": fingerprint,
        }

    def apply(self) -> dict[str, Any]:
        result = self.plan()
        if result["already_migrated"]:
            return {**result, "mode": "apply", "writes": 0}

        username = str(result["account"]["username"])
        user_id = str(result["account"]["id"])
        if not set_preset(username, "learner"):
            raise ValueError(f"Could not convert existing account {username!r} to a learner")
        profile = {"age": int(result["profile"]["age"])}
        if set_learner_profile(username, profile) is None:
            raise ValueError(f"Could not set the learner profile for {username!r}")

        workspace_root = ensure_user_workspace(user_id)
        reading_store = ReadingStore(workspace_root / "user" / "workspace" / "reading")
        migrated_materials: dict[str, str] = {}
        for item in result["reading_materials"]:
            manifest = reading_store.ingest(item["source_path"], filename=str(item["filename"]))
            migrated_materials[str(item["document_id"])] = manifest.material_id
            reading_store.save_position(
                manifest.material_id,
                ReadingPosition(
                    locator=int(item["locator"]),
                    source_anchor=str(item["source_anchor"]),
                    percentage=float(item["percentage"]),
                ),
            )

        permission = normalize_book_permission(get_user(username).get("book_permission"))
        books = permission.books_dict()
        path_service = PathService(workspace_root=workspace_root)
        for item in result["interactive_books"]:
            book_id = str(item["book_id"])
            books[book_id] = "read"
            if item.get("progress_path") is not None:
                visited: list[str] = []
                for page_id in [*item.get("completed_page_ids", []), item["current_page_id"]]:
                    if page_id not in visited:
                        visited.append(page_id)
                BookLearningOverlay(path_service).save_progress(
                    Progress(
                        book_id=book_id,
                        current_page_id=str(item["current_page_id"]),
                        visited_page_ids=visited,
                        updated_at=float(item["updated_at"]),
                    )
                )
        if not set_book_permission(
            username,
            BookPermission(create=False, default="none", books=tuple(books.items())),
        ):
            raise ValueError(f"Could not set book permissions for {username!r}")

        save_grant(
            user_id,
            {
                "models": {"llm": []},
                "enabled_tools": [],
                "mcp_tools": [],
                "cli_apps": [],
                "exec_enabled": False,
                "learning_policy": {
                    "age_band": str(result["age_band"]),
                    "locked_persona": "teacher",
                    "allowed_capabilities": ["chat", "immersive_reading"],
                    "default_capability": "immersive_reading",
                    "allowed_surfaces": ["chat", "reading"],
                    "reading": {
                        "allow_upload": False,
                        "material_ids": sorted(set(migrated_materials.values())),
                        "extensions": list(_READING_EXTENSIONS),
                    },
                },
            },
        )

        journal = {
            "version": 1,
            "status": "complete",
            "profile_id": str(result["profile"]["id"]),
            "username": username,
            "user_id": user_id,
            "materials": migrated_materials,
            "reading_progress": {
                str(item["document_id"]): {
                    "material_id": migrated_materials[str(item["document_id"])],
                    "locator": int(item["locator"]),
                    "source_anchor": str(item["source_anchor"]),
                    "percentage": float(item["percentage"]),
                    "completed_section_ids": list(item["completed_section_ids"]),
                    "quiz_scores": dict(item["quiz_scores"]),
                }
                for item in result["reading_materials"]
            },
            "interactive_books": [str(item["book_id"]) for item in result["interactive_books"]],
            "interactive_book_progress": {
                str(item["book_id"]): {
                    "current_page_id": str(item["current_page_id"]),
                    "completed_page_ids": list(item["completed_page_ids"]),
                }
                for item in result["interactive_books"]
            },
            "source_fingerprint": str(result["source_fingerprint"]),
            "completed_at": time.time(),
        }
        atomic_write_json(self.journal_path, journal)
        write_count = 2 + len(migrated_materials)
        write_count += len(result["interactive_books"]) * 2 + 1
        return {**result, "mode": "apply", "writes": write_count}

    def _select_profile(self) -> tuple[dict[str, Any], str]:
        profiles = _read_json(self.kids_root / "profiles.json", [])
        if not isinstance(profiles, list):
            raise ValueError("Legacy Kids profiles.json is invalid")
        wanted = self.profile_name.casefold()
        matches = [
            row
            for row in profiles
            if isinstance(row, dict) and str(row.get("name") or "").strip().casefold() == wanted
        ]
        if not matches:
            raise ValueError(f"No unique legacy Kids profile named {self.profile_name!r}")
        if len(matches) != 1:
            raise ValueError(
                f"Legacy Kids profile name {self.profile_name!r} is ambiguous; refusing to migrate"
            )
        profile = matches[0]
        return profile, _clean_id(profile.get("id"), "profile id")

    def _select_account(self) -> tuple[str, dict[str, Any]]:
        from deeptutor.multi_user import identity

        users = _read_json(identity.USERS_FILE, {})
        if not isinstance(users, dict):
            raise ValueError("The account store is invalid")
        wanted = self.profile_name.casefold()
        matches = [
            (str(username), row)
            for username, row in users.items()
            if isinstance(row, dict) and str(username).strip().casefold() == wanted
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Exactly one existing account named {self.profile_name!r} is required"
            )
        username, account = matches[0]
        if str(account.get("role") or "user") != "user":
            raise ValueError(f"Account {username!r} must remain a non-admin user")
        if bool(account.get("disabled", False)):
            raise ValueError(f"Account {username!r} is disabled")
        return username, account

    def _assignments(self, profile_id: str) -> list[dict[str, Any]]:
        assignments = _read_json(self.kids_root / "assignments.json", [])
        if not isinstance(assignments, list):
            raise ValueError("Legacy Kids assignments.json is invalid")
        rows = [
            dict(row)
            for row in assignments
            if isinstance(row, dict)
            and row.get("profile_id") == profile_id
            and row.get("status", "active") == "active"
        ]
        return sorted(
            rows,
            key=lambda row: (
                _number(row.get("sort_order"), "assignment sort order"),
                str(row.get("id") or ""),
            ),
        )

    def _reading_item(self, assignment: dict[str, Any], profile_id: str) -> dict[str, Any]:
        document_id = _clean_id(assignment.get("document_id"), "document id")
        source_root = self.immersive_root / f"document_{document_id}"
        originals = sorted(source_root.glob("original.*")) if source_root.is_dir() else []
        if len(originals) != 1:
            raise ValueError(f"Expected exactly one source file for legacy document {document_id}")
        source = originals[0]
        manifest = _read_json(source_root / "manifest.json", {})
        filename = str(
            (manifest.get("source_filename") if isinstance(manifest, dict) else None)
            or assignment.get("document_title")
            or source.name
        )
        progress_path = self.kids_root / "progress" / f"{profile_id}_{document_id}.json"
        progress = _read_json(progress_path, {})
        if not isinstance(progress, dict):
            raise ValueError(f"Legacy reading progress is missing for document {document_id}")
        locator = int(_number(progress.get("current_section_index"), "section index")) + 1
        section_files = sorted((source_root / "sections").glob("section_*.txt"))
        if locator < 1 or (section_files and locator > len(section_files)):
            raise ValueError(f"Legacy reading position is out of range for document {document_id}")
        percentage = min(1.0, max(0.0, _number(progress.get("scroll_percent"), "scroll") / 100))
        return {
            "assignment_id": _clean_id(assignment.get("id"), "assignment id"),
            "document_id": document_id,
            "filename": filename,
            "material_id": content_hash(source.read_bytes()),
            "source_path": source,
            "locator": locator,
            "source_anchor": str(progress.get("epub_cfi") or "")[:4096],
            "percentage": percentage,
            "completed_section_count": len(progress.get("completed_section_ids") or []),
            "completed_section_ids": [
                str(section_id) for section_id in progress.get("completed_section_ids") or []
            ],
            "quiz_score_count": len(progress.get("quiz_scores") or {}),
            "quiz_scores": {
                str(section_id): score
                for section_id, score in (progress.get("quiz_scores") or {}).items()
            },
            "progress_path": progress_path,
        }

    def _book_item(self, assignment: dict[str, Any], profile_id: str) -> dict[str, Any]:
        book_id = _clean_id(assignment.get("book_id"), "book id")
        storage = BookStorage(path_service=get_admin_path_service())
        book = storage.load_book(book_id)
        spine = storage.load_spine(book_id)
        if book is None or spine is None:
            raise ValueError(f"Shared interactive book {book_id} is missing or invalid")
        page_ids = {page_id for chapter in spine.chapters for page_id in chapter.page_ids}
        progress_path = self.kids_root / "progress" / f"ib_{profile_id}_{book_id}.json"
        progress = _read_json(progress_path, {})
        if not isinstance(progress, dict):
            raise ValueError(f"Legacy book progress is missing for book {book_id}")
        current_page_id = _clean_id(progress.get("current_page_id"), "current page id")
        if current_page_id not in page_ids:
            raise ValueError(f"Legacy current page does not belong to shared book {book_id}")
        completed_page_ids = [
            _clean_id(page_id, "completed page id")
            for page_id in progress.get("completed_page_ids") or []
        ]
        return {
            "assignment_id": _clean_id(assignment.get("id"), "assignment id"),
            "book_id": book_id,
            "current_page_id": current_page_id,
            "completed_page_ids": completed_page_ids,
            "updated_at": _number(
                progress.get("updated_at") or progress.get("last_read_at") or time.time(),
                "book updated_at",
            ),
            "progress_path": progress_path,
        }


__all__ = ["LegacyKidsLearnerMigration"]
