from __future__ import annotations

import pytest

from deeptutor.book.learning_overlay import BookLearningOverlay
from deeptutor.book.models import Book, BookStatus, Progress
from deeptutor.book.storage import BookStorage, get_book_storage
from deeptutor.multi_user import book_access
from deeptutor.multi_user.book_permission import BookPermission
from deeptutor.multi_user.identity import set_book_permission
from deeptutor.multi_user.paths import (
    get_admin_path_service,
    get_path_service_for_scope,
)


@pytest.fixture
def auth_on(monkeypatch):
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)


@pytest.fixture
def auth_off(monkeypatch):
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", False)


@pytest.fixture
def book_caches():
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module

    storage_module._storages.clear()
    engine_module._engines.clear()
    yield
    storage_module._storages.clear()
    engine_module._engines.clear()


def _seed_book(
    path_service,
    book_id: str,
    *,
    title: str = "T",
    updated_at: float | None = None,
    page_count: int = 0,
) -> Book:
    book = Book(id=book_id, title=title, page_count=page_count)
    if updated_at is not None:
        book.updated_at = updated_at
    BookStorage(path_service=path_service).save_book(book)
    return book


def test_can_create_book_without_auth_is_open(
    mu_isolated_root, seed_user, as_user, auth_off
) -> None:
    alice = seed_user("alice", role="user")
    set_book_permission("alice", BookPermission(create=False))
    with as_user(alice["id"], username="alice"):
        assert book_access.can_create_book() is True


def test_can_create_book_admin_and_permitted_user(
    mu_isolated_root, seed_user, as_user, auth_on
) -> None:
    alice = seed_user("alice", role="user")
    with as_user("admin-1", role="admin", username="root"):
        assert book_access.can_create_book() is True
    with as_user(alice["id"], username="alice"):
        assert book_access.can_create_book() is True


def test_can_create_book_denied_by_create_false(
    mu_isolated_root, seed_user, as_user, auth_on
) -> None:
    alice = seed_user("alice", role="user")
    set_book_permission("alice", BookPermission(create=False))
    with as_user(alice["id"], username="alice"):
        assert book_access.can_create_book() is False


def test_resolve_book_own_grants_full_edit(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    alice = seed_user("alice", role="user")
    user = make_user(alice["id"], username="alice")
    _seed_book(get_path_service_for_scope(user.scope), "bk_own", title="Own")
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_own")
        assert resolved is not None
        assert resolved.source == "own"
        assert resolved.permission == "edit"
        assert resolved.can_edit is True
        assert resolved.can_delete is True
        assert resolved.is_shared is False
        assert resolved.capabilities() == {
            "source": "own",
            "permission": "edit",
            "can_edit": True,
            "can_delete": True,
        }
        assert resolved.learning is get_book_storage()


def test_resolve_book_without_auth_never_sees_shared(
    mu_isolated_root, seed_user, as_user, auth_off, book_caches
) -> None:
    _seed_book(get_admin_path_service(), "bk_shared", title="Shared")
    alice = seed_user("alice", role="user")
    with as_user(alice["id"], username="alice"):
        assert book_access.resolve_book("bk_shared") is None


def test_resolve_book_admin_uses_own_workspace_not_shared_path(
    mu_isolated_root, seed_user, as_user, auth_on, book_caches
) -> None:
    _seed_book(get_admin_path_service(), "bk_shared", title="Shared")
    with as_user("admin-1", role="admin", username="root"):
        resolved = book_access.resolve_book("bk_shared")
        assert resolved is not None
        assert resolved.source == "own"
        assert resolved.can_delete is True
        assert book_access.resolve_book("bk_unknown") is None


def test_resolve_book_shared_levels_and_explicit_none(
    mu_isolated_root, seed_user, as_user, auth_on, book_caches
) -> None:
    admin = get_admin_path_service()
    _seed_book(admin, "bk_read", title="Read")
    _seed_book(admin, "bk_edit", title="Edit")
    _seed_book(admin, "bk_none", title="None")
    alice = seed_user("alice", role="user")
    set_book_permission(
        "alice",
        BookPermission(books=(("bk_read", "read"), ("bk_edit", "edit"), ("bk_none", "none"))),
    )
    with as_user(alice["id"], username="alice"):
        read = book_access.resolve_book("bk_read")
        assert read is not None
        assert read.is_shared is True
        assert read.permission == "read"
        assert read.can_edit is False
        assert read.can_delete is False
        assert read.capabilities() == {
            "source": "shared",
            "permission": "read",
            "can_edit": False,
            "can_delete": False,
        }
        edit = book_access.resolve_book("bk_edit")
        assert edit is not None
        assert edit.permission == "edit"
        assert edit.can_edit is True
        assert edit.can_delete is False
        assert book_access.resolve_book("bk_none") is None


def test_resolve_book_default_read_grants_shared_and_unknown_denied(
    mu_isolated_root, seed_user, as_user, auth_on, book_caches
) -> None:
    _seed_book(get_admin_path_service(), "bk_shared", title="Shared")
    alice = seed_user("alice", role="user")
    set_book_permission("alice", BookPermission(default="read"))
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_shared")
        assert resolved is not None
        assert resolved.source == "shared"
        assert resolved.permission == "read"
        assert resolved.can_edit is False
        assert book_access.resolve_book("bk_unknown") is None


def test_resolve_book_own_wins_over_shared_same_id(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    admin = get_admin_path_service()
    _seed_book(admin, "bk_both", title="Admin copy")
    alice = seed_user("alice", role="user")
    set_book_permission("alice", BookPermission(books=(("bk_both", "read"),)))
    user = make_user(alice["id"], username="alice")
    _seed_book(get_path_service_for_scope(user.scope), "bk_both", title="Own copy")
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_both")
        assert resolved is not None
        assert resolved.source == "own"
        assert resolved.can_delete is True


def test_accessible_books_merges_own_and_shared_sorted(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    admin = get_admin_path_service()
    _seed_book(admin, "bk_both", title="Admin", updated_at=500.0)
    _seed_book(admin, "bk_edit", title="Edit", updated_at=200.0)
    _seed_book(admin, "bk_read", title="Read", updated_at=100.0)
    _seed_book(admin, "bk_secret", title="Secret", updated_at=400.0)
    alice = seed_user("alice", role="user")
    set_book_permission(
        "alice",
        BookPermission(books=(("bk_edit", "edit"), ("bk_read", "read"))),
    )
    user = make_user(alice["id"], username="alice")
    own = get_path_service_for_scope(user.scope)
    _seed_book(own, "bk_own", title="Own", updated_at=300.0)
    _seed_book(own, "bk_both", title="Own copy", updated_at=500.0)
    with as_user(alice["id"], username="alice"):
        entries = book_access.accessible_books()
    ids = [book.id for book, _ in entries]
    assert ids == ["bk_both", "bk_own", "bk_edit", "bk_read"]
    by_id = {book.id: resolved for book, resolved in entries}
    assert by_id["bk_both"].source == "own"
    assert by_id["bk_edit"].can_edit is True
    assert by_id["bk_edit"].can_delete is False
    assert by_id["bk_read"].can_edit is False
    assert by_id["bk_read"].is_shared is True
    assert "bk_secret" not in by_id


def test_accessible_books_without_surface_lists_own_only(
    mu_isolated_root, seed_user, make_user, as_user, monkeypatch, book_caches
) -> None:
    from deeptutor.services import auth as auth_service

    _seed_book(get_admin_path_service(), "bk_shared", title="Shared")
    alice = seed_user("alice", role="user")
    user = make_user(alice["id"], username="alice")
    own = get_path_service_for_scope(user.scope)
    _seed_book(own, "bk_own", title="Own")
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    with as_user(alice["id"], username="alice"):
        assert [book.id for book, _ in book_access.accessible_books()] == ["bk_own"]
    set_book_permission("alice", BookPermission(books=(("bk_shared", "read"),)))
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", False)
    with as_user(alice["id"], username="alice"):
        assert [book.id for book, _ in book_access.accessible_books()] == ["bk_own"]


def test_shared_book_exists_and_admin_catalog_shape(mu_isolated_root, seed_user, auth_on) -> None:
    _seed_book(get_admin_path_service(), "bk_shared", title="Shared", updated_at=42.0)
    assert book_access.shared_book_exists("bk_shared") is True
    assert book_access.shared_book_exists("bk_nope") is False
    assert book_access.admin_book_catalog() == [
        {
            "book_id": "bk_shared",
            "title": "Shared",
            "status": BookStatus.DRAFT.value,
            "updated_at": 42.0,
        }
    ]


def test_load_progress_defaults_for_fresh_book(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    alice = seed_user("alice", role="user")
    user = make_user(alice["id"], username="alice")
    _seed_book(get_path_service_for_scope(user.scope), "bk_own", title="Own")
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_own")
        assert resolved is not None
        progress = resolved.load_progress("bk_own")
        assert progress.book_id == "bk_own"
        assert progress.visited_page_ids == []
        assert progress.current_page_id == ""


def test_load_progress_round_trip_through_own_store(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    alice = seed_user("alice", role="user")
    user = make_user(alice["id"], username="alice")
    _seed_book(get_path_service_for_scope(user.scope), "bk_own", title="Own")
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_own")
        assert resolved is not None
        resolved.learning.save_progress(
            Progress(
                book_id="bk_own",
                current_page_id="p9",
                visited_page_ids=["p1", "p9"],
            )
        )
        progress = resolved.load_progress("bk_own")
        assert progress.current_page_id == "p9"
        assert progress.visited_page_ids == ["p1", "p9"]


def test_shared_learning_overlay_is_per_reader(
    mu_isolated_root, seed_user, as_user, auth_on, book_caches
) -> None:
    _seed_book(get_admin_path_service(), "bk_shared", title="Shared")
    alice = seed_user("alice", role="user")
    bob = seed_user("bob", role="user")
    set_book_permission("alice", BookPermission(books=(("bk_shared", "read"),)))
    set_book_permission("bob", BookPermission(books=(("bk_shared", "read"),)))
    with as_user(alice["id"], username="alice"):
        resolved = book_access.resolve_book("bk_shared")
        assert resolved is not None
        assert isinstance(resolved.learning, BookLearningOverlay)
        resolved.learning.save_progress(
            Progress(book_id="bk_shared", current_page_id="p1", visited_page_ids=["p1"])
        )
        admin_progress = get_admin_path_service().get_book_root("bk_shared") / "progress.json"
        assert not admin_progress.exists()
    with as_user(bob["id"], username="bob"):
        resolved_bob = book_access.resolve_book("bk_shared")
        assert resolved_bob is not None
        progress = resolved_bob.load_progress("bk_shared")
        assert progress.visited_page_ids == []
        assert progress.current_page_id == ""


def test_reading_summary_zero_and_percent(
    mu_isolated_root, seed_user, make_user, as_user, auth_on, book_caches
) -> None:
    alice = seed_user("alice", role="user")
    user = make_user(alice["id"], username="alice")
    own = get_path_service_for_scope(user.scope)
    _seed_book(own, "bk_empty", title="Empty", page_count=0)
    _seed_book(own, "bk_full", title="Full", page_count=4)
    with as_user(alice["id"], username="alice"):
        empty = book_access.resolve_book("bk_empty")
        assert empty is not None
        empty_book = empty.engine.load_book("bk_empty")
        assert empty_book is not None
        assert empty.reading_summary(empty_book) == {
            "current_page_id": "",
            "visited_pages": 0,
            "total_pages": 0,
            "percent": 0,
        }
        empty.learning.save_progress(Progress(book_id="bk_empty", visited_page_ids=["p1"]))
        assert empty.reading_summary(empty_book)["percent"] == 0
        full = book_access.resolve_book("bk_full")
        assert full is not None
        full.learning.save_progress(
            Progress(
                book_id="bk_full",
                current_page_id="p2",
                visited_page_ids=["p2", "p1", "p2"],
            )
        )
        full_book = full.engine.load_book("bk_full")
        assert full_book is not None
        assert full.reading_summary(full_book) == {
            "current_page_id": "p2",
            "visited_pages": 2,
            "total_pages": 4,
            "percent": 50,
        }
