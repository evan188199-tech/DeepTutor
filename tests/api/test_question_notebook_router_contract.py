"""Contract tests for the question-notebook router (CRUD + 4xx mapping).

The dependency layer (session store, attachment store, course service) is
faked so these tests pin the router's request/response contract — status
codes, response-model fields, and error structures — without any real
storage or services. Store-backed behaviour of the same surface is covered
by ``tests/api/test_question_bank_api.py``.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

router_module = importlib.import_module("deeptutor.api.routers.question_notebook")
notebook_router = router_module.router
CourseNotFoundError = importlib.import_module("deeptutor.services.courses").CourseNotFoundError

PREFIX = "/api/question-notebook"


class FakeStore:
    """Minimal stand-in for SQLiteSessionStore used by the router."""

    def __init__(self) -> None:
        self.entries: dict[int, dict[str, Any]] = {}
        self.next_entry_id = 1
        self.categories: dict[int, dict[str, Any]] = {}
        self.next_category_id = 1
        self.links: set[tuple[int, int]] = set()
        self.sessions: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []
        # Behaviour switches for error-path tests.
        self.upsert_error: ValueError | None = None
        self.drop_found_entry = False
        self.update_result: dict[str, Any] | None = None
        self.delete_entry_result = True
        self.add_link_result = True
        self.remove_link_result = True
        self.create_category_error: ValueError | None = None
        self.rename_error: ValueError | None = None
        self.rename_result: dict[str, Any] | None = None
        self.delete_category_result = True
        self.stats = {"total": 0, "wrong": 0, "unresolved": 0, "bookmarked": 0, "uncategorized": 0}
        self.materials: list[dict[str, Any]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, kwargs if kwargs else args))

    def last_kwargs(self, name: str) -> dict[str, Any]:
        for call_name, args in reversed(self.calls):
            if call_name == name and isinstance(args, dict):
                return args
        return {}

    # -- entries -----------------------------------------------------

    async def find_notebook_entry_by_origin(
        self,
        origin_type: str,
        origin_ref: str,
        question_id: str,
        turn_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._record("find_notebook_entry_by_origin")
        if self.drop_found_entry:
            return None
        for entry in self.entries.values():
            if (
                entry["origin_type"] == origin_type
                and entry["origin_ref"] == origin_ref
                and entry["question_id"] == question_id
                and (turn_id is None or entry.get("turn_id") == turn_id)
            ):
                return entry
        return None

    async def upsert_notebook_entries(
        self, session_id: str | None, items: list[dict[str, Any]]
    ) -> None:
        self._record("upsert_notebook_entries", session_id=session_id)
        if self.upsert_error is not None:
            raise self.upsert_error
        for item in items:
            existing_id = None
            for entry_id, entry in self.entries.items():
                if (
                    entry["origin_type"] == item.get("origin_type", "conversation")
                    and entry["origin_ref"] == item.get("origin_ref", "")
                    and entry["question_id"] == item.get("question_id")
                    and entry.get("turn_id") == item.get("turn_id")
                ):
                    existing_id = entry_id
                    break
            if existing_id is not None:
                merged = dict(self.entries[existing_id])
                merged.update(item)
                merged["updated_at"] = 2000.0
                self.entries[existing_id] = merged
                continue
            requested_id = int(item.get("id") or 0)
            entry_id = requested_id or self.next_entry_id
            if not requested_id:
                self.next_entry_id += 1
            self.entries[entry_id] = {
                **item,
                "id": entry_id,
                "session_id": session_id or "",
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }

    async def get_notebook_entry(self, entry_id: int) -> dict[str, Any] | None:
        return self.entries.get(entry_id)

    async def update_notebook_entry(
        self, entry_id: int, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        self._record("update_notebook_entry", updates=dict(updates))
        if entry_id not in self.entries:
            return None
        if self.update_result is None:
            self.entries[entry_id].update(updates)
            return self.entries[entry_id]
        return self.update_result

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        self._record("delete_notebook_entry")
        if not self.delete_entry_result:
            return False
        return self.entries.pop(entry_id, None) is not None

    async def list_notebook_entries(self, **kwargs: Any) -> dict[str, Any]:
        self._record("list_notebook_entries", **kwargs)
        items = [dict(entry) for entry in self.entries.values()]
        return {"items": items, "total": len(items)}

    # -- entry ↔ category links ---------------------------------------

    async def link_entries_to_category(
        self, entry_ids: list[int], category_id: int, link: bool = True
    ) -> int:
        self._record("link_entries_to_category", entry_ids=list(entry_ids))
        changed = 0
        for entry_id in entry_ids:
            membership = (entry_id, category_id) in self.links
            if link and not membership:
                self.links.add((entry_id, category_id))
                changed += 1
            elif not link and membership:
                self.links.discard((entry_id, category_id))
                changed += 1
        return changed

    async def add_entry_to_category(self, entry_id: int, category_id: int) -> bool:
        self._record("add_entry_to_category")
        if not self.add_link_result:
            return False
        self.links.add((entry_id, category_id))
        return True

    async def remove_entry_from_category(self, entry_id: int, category_id: int) -> bool:
        self._record("remove_entry_from_category")
        if not self.remove_link_result:
            return False
        return True

    # -- overview ------------------------------------------------------

    async def question_bank_stats(self, session_ids: list[str] | None) -> dict[str, Any]:
        self._record("question_bank_stats", session_ids=session_ids)
        return dict(self.stats)

    async def list_question_bank_materials(
        self, session_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        self._record("list_question_bank_materials", session_ids=session_ids)
        return [dict(item) for item in self.materials]

    # -- categories ----------------------------------------------------

    async def list_categories(self, session_ids: list[str] | None) -> list[dict[str, Any]]:
        self._record("list_categories", session_ids=session_ids)
        return [dict(cat) for cat in self.categories.values()]

    async def create_category(self, name: str) -> dict[str, Any]:
        if self.create_category_error is not None:
            raise self.create_category_error
        category_id = self.next_category_id
        self.next_category_id += 1
        category = {"id": category_id, "name": name, "created_at": 1.0, "entry_count": 0}
        self.categories[category_id] = category
        return dict(category)

    async def rename_category(self, category_id: int, name: str) -> dict[str, Any] | None:
        if self.rename_error is not None:
            raise self.rename_error
        if self.rename_result is not None:
            return self.rename_result
        if category_id not in self.categories:
            return None
        self.categories[category_id]["name"] = name
        return self.categories[category_id]

    async def delete_category(self, category_id: int) -> bool:
        if not self.delete_category_result:
            return False
        return self.categories.pop(category_id, None) is not None

    # -- session listing (used by the course-scope helper) ---------------

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.sessions[offset : offset + limit]


class FakeAttachmentStore:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.deleted: list[tuple[str, str]] = []

    async def put(
        self,
        session_id: str,
        attachment_id: str,
        filename: str,
        data: bytes,
        mime_type: str,
    ) -> str:
        self.put_calls.append(
            {
                "session_id": session_id,
                "attachment_id": attachment_id,
                "filename": filename,
                "data": data,
                "mime_type": mime_type,
            }
        )
        return f"att://{session_id}/{attachment_id}"

    async def delete_attachment(self, session_id: str, attachment_id: str) -> None:
        self.deleted.append((session_id, attachment_id))


class FakeCourseService:
    def __init__(self, known: set[str]) -> None:
        self.known = known

    def get(self, course_id: str) -> dict[str, Any]:
        if course_id not in self.known:
            raise CourseNotFoundError(course_id)
        return {"id": course_id}


@pytest.fixture
def deps(monkeypatch):
    store = FakeStore()
    attachments = FakeAttachmentStore()
    courses = FakeCourseService(known={"course-1"})
    monkeypatch.setattr(router_module, "get_sqlite_session_store", lambda: store)
    monkeypatch.setattr(router_module, "get_attachment_store", lambda: attachments)
    monkeypatch.setattr(
        importlib.import_module("deeptutor.services.courses"),
        "get_course_service",
        lambda: courses,
    )
    store.sessions = [
        {"session_id": "sess-course", "preferences": {"course_id": "course-1"}},
        {"session_id": "sess-free", "preferences": {}},
        {"session_id": "sess-other", "preferences": {"course_id": "course-2"}},
    ]
    return {"store": store, "attachments": attachments, "courses": courses}


@pytest.fixture
def client(deps):
    app = FastAPI()
    app.include_router(notebook_router, prefix=PREFIX)
    with TestClient(app) as test_client:
        test_client.deps = deps  # type: ignore[attr-defined]
        yield test_client


def _seed_entry(
    store: FakeStore,
    *,
    session_id: str = "sess-1",
    images: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": store.next_entry_id,
        "session_id": session_id,
        "origin_type": "conversation",
        "origin_ref": session_id,
        "turn_id": "t1",
        "question_id": "q1",
        "question": "What is 2+2?",
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    if images is not None:
        entry["user_answer_images"] = images
    entry.update(overrides)
    store.entries[entry["id"]] = entry
    store.next_entry_id += 1
    return entry


# ── POST /entries/upsert ────────────────────────────────────────────


def test_upsert_conversation_entry_returns_persisted_entry(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-9",
            "question_id": "q9",
            "question": "Capitol of France?",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["session_id"] == "sess-9"
    assert body["origin_type"] == "conversation"
    assert body["origin_ref"] == "sess-9"
    assert body["question_id"] == "q9"
    assert isinstance(body["created_at"], float)
    assert isinstance(body["updated_at"], float)


def test_upsert_conversation_entry_requires_session_id(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={"question_id": "q1", "question": "No session?"},
    )
    assert response.status_code == 422
    assert "conversation entries require session_id" in str(response.json())


def test_upsert_conversation_origin_ref_must_match_session(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "origin_ref": "sess-other",
            "question_id": "q1",
            "question": "Mismatch?",
        },
    )
    assert response.status_code == 422
    assert "origin_ref must match session_id" in str(response.json())


def test_upsert_store_value_error_maps_to_404(client):
    client.deps["store"].upsert_error = ValueError("unknown session")
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "ghost",
            "question_id": "q1",
            "question": "Ghost session?",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown session"


def test_upsert_entry_missing_after_write_maps_to_500(client):
    client.deps["store"].drop_found_entry = True
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "question_id": "q1",
            "question": "Vanishing?",
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Upsert failed"


def test_upsert_persists_base64_answer_images_via_attachment_store(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "question_id": "q1",
            "question": "Sketch?",
            "user_answer_images": [
                {"id": "img-1", "base64": "aGVsbG8=", "filename": "a.png"},
            ],
        },
    )
    assert response.status_code == 200
    attachments = client.deps["attachments"]
    assert len(attachments.put_calls) == 1
    call = attachments.put_calls[0]
    assert call["session_id"] == "sess-1"
    assert call["attachment_id"] == "img-1"
    assert call["data"] == b"hello"
    stored = response.json()["user_answer_images"]
    assert stored == [
        {
            "id": "img-1",
            "url": "att://sess-1/img-1",
            "filename": "a.png",
            "mime_type": "image/png",
        }
    ]


def test_upsert_reuses_submitted_url_without_reupload(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "question_id": "q1",
            "question": "Already stored?",
            "user_answer_images": [{"id": "img-2", "url": "att://sess-1/img-2"}],
        },
    )
    assert response.status_code == 200
    assert client.deps["attachments"].put_calls == []
    assert response.json()["user_answer_images"][0]["url"] == "att://sess-1/img-2"


def test_upsert_drops_unusable_answer_images(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "question_id": "q1",
            "question": "Broken image?",
            "user_answer_images": [
                {"id": "bad-b64", "base64": "abc"},
                {"id": "empty", "base64": "", "url": ""},
            ],
        },
    )
    assert response.status_code == 200
    assert client.deps["attachments"].put_calls == []
    assert response.json()["user_answer_images"] == []


def test_upsert_without_images_leaves_stored_images_untouched(client):
    store = client.deps["store"]
    _seed_entry(store, images=[{"id": "keep", "url": "att://sess-1/keep"}])
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "turn_id": "t1",
            "question_id": "q1",
            "question": "Updated text",
        },
    )
    assert response.status_code == 200
    assert response.json()["question"] == "Updated text"
    assert response.json()["user_answer_images"] == [{"id": "keep", "url": "att://sess-1/keep"}]
    assert client.deps["attachments"].deleted == []


def test_upsert_removes_unretained_images_of_the_previous_entry(client):
    store = client.deps["store"]
    _seed_entry(store, images=[{"id": "old", "url": "att://sess-1/old"}])
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "session_id": "sess-1",
            "turn_id": "t1",
            "question_id": "q1",
            "question": "New attempt",
            "user_answer_images": [{"id": "new", "url": "att://sess-1/new"}],
        },
    )
    assert response.status_code == 200
    assert client.deps["attachments"].deleted == [("sess-1", "old")]


def test_upsert_images_of_independent_entry_use_hashed_owner(client):
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json={
            "origin_type": "external_import",
            "origin_ref": "bank:42",
            "question_id": "q1",
            "question": "Imported?",
            "user_answer_images": [{"id": "img-x", "base64": "aGVsbG8="}],
        },
    )
    assert response.status_code == 200
    call = client.deps["attachments"].put_calls[0]
    assert call["session_id"].startswith("question-notebook-")
    assert call["session_id"] not in ("", "bank:42")


# ── GET /entries/lookup/by-question ────────────────────────────────


def test_lookup_returns_the_matching_entry(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    response = client.get(
        f"{PREFIX}/entries/lookup/by-question",
        params={"session_id": "sess-1", "question_id": "q1", "turn_id": "t1"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == entry["id"]


def test_lookup_without_scope_is_rejected(client):
    response = client.get(
        f"{PREFIX}/entries/lookup/by-question",
        params={"origin_type": "external_import", "question_id": "q1"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "session_id or origin_ref is required"


def test_lookup_conversation_ref_mismatch_is_rejected(client):
    response = client.get(
        f"{PREFIX}/entries/lookup/by-question",
        params={
            "session_id": "sess-1",
            "origin_ref": "sess-2",
            "question_id": "q1",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "conversation origin_ref must match session_id"


def test_lookup_missing_entry_is_404_by_default(client):
    response = client.get(
        f"{PREFIX}/entries/lookup/by-question",
        params={"session_id": "sess-1", "question_id": "missing"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


def test_lookup_missing_entry_can_report_204(client):
    response = client.get(
        f"{PREFIX}/entries/lookup/by-question",
        params={
            "session_id": "sess-1",
            "question_id": "missing",
            "missing_ok": "true",
        },
    )
    assert response.status_code == 204
    assert response.content == b""


# ── GET /entries/{entry_id} ────────────────────────────────────────


def test_get_entry_returns_entry_item_model(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    response = client.get(f"{PREFIX}/entries/{entry['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == entry["id"]
    assert body["question"] == "What is 2+2?"
    assert body["origin_type"] == "conversation"
    assert body["options"] == {}
    assert body["user_answer_images"] == []
    assert body["categories"] is None
    assert body["bookmarked"] is False
    assert body["resolved"] is False


def test_get_missing_entry_is_404(client):
    response = client.get(f"{PREFIX}/entries/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


# ── PATCH /entries/{entry_id} ──────────────────────────────────────


def test_patch_entry_updates_fields_and_confirms(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    response = client.patch(
        f"{PREFIX}/entries/{entry['id']}", json={"bookmarked": True, "ai_judgment": "ok"}
    )
    assert response.status_code == 200
    assert response.json() == {"updated": True, "id": entry["id"]}
    assert store.last_kwargs("update_notebook_entry") == {
        "updates": {"bookmarked": True, "ai_judgment": "ok"}
    }
    assert store.entries[entry["id"]]["bookmarked"] is True


def test_patch_entry_ignores_null_fields(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    response = client.patch(
        f"{PREFIX}/entries/{entry['id']}", json={"bookmarked": True, "resolved": None}
    )
    assert response.status_code == 200
    assert store.last_kwargs("update_notebook_entry") == {"updates": {"bookmarked": True}}


def test_patch_entry_without_fields_is_rejected(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    response = client.patch(f"{PREFIX}/entries/{entry['id']}", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "No fields to update"


def test_patch_missing_entry_is_404(client):
    response = client.patch(f"{PREFIX}/entries/9999", json={"bookmarked": True})
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


# ── DELETE /entries/{entry_id} ─────────────────────────────────────


def test_delete_entry_removes_its_answer_images(client):
    store = client.deps["store"]
    entry = _seed_entry(
        store,
        images=[{"id": "img-a", "url": "u"}, {"id": "img-b", "url": "v"}],
    )
    response = client.delete(f"{PREFIX}/entries/{entry['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": entry["id"]}
    assert entry["id"] not in store.entries
    assert client.deps["attachments"].deleted == [
        ("sess-1", "img-a"),
        ("sess-1", "img-b"),
    ]


def test_delete_independent_entry_uses_hashed_owner(client):
    store = client.deps["store"]
    entry = _seed_entry(
        store,
        session_id="",
        origin_type="external_import",
        origin_ref="bank:7",
        images=[{"id": "img-x", "url": "u"}],
    )
    response = client.delete(f"{PREFIX}/entries/{entry['id']}")
    assert response.status_code == 200
    owner, image_id = client.deps["attachments"].deleted[0]
    assert owner.startswith("question-notebook-")
    assert image_id == "img-x"


def test_delete_missing_entry_is_404(client):
    response = client.delete(f"{PREFIX}/entries/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


def test_delete_failed_store_removal_is_404(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    store.delete_entry_result = False
    response = client.delete(f"{PREFIX}/entries/{entry['id']}")
    assert response.status_code == 404


# ── GET /entries listing contract ──────────────────────────────────


def test_list_entries_returns_items_and_total_with_defaults(client):
    store = client.deps["store"]
    _seed_entry(store)
    response = client.get(f"{PREFIX}/entries")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 1
    assert body["items"][0]["question"] == "What is 2+2?"
    forwarded = store.last_kwargs("list_notebook_entries")
    assert forwarded["sort"] == "recent"
    assert forwarded["limit"] == 50
    assert forwarded["offset"] == 0
    assert forwarded["mistakes_only"] is False
    assert forwarded["session_ids"] is None


def test_list_entries_forwards_filters_and_course_scope(client):
    store = client.deps["store"]
    response = client.get(
        f"{PREFIX}/entries",
        params={
            "course_id": "course-1",
            "mistakes_only": "true",
            "bookmarked": "false",
            "is_correct": "false",
            "resolved": "false",
            "search": "rank",
            "assessment_type": "quiz",
            "result": "incorrect",
            "score_trend": "improved",
            "limit": 10,
            "offset": 5,
        },
    )
    assert response.status_code == 200
    forwarded = store.last_kwargs("list_notebook_entries")
    assert forwarded["session_ids"] == ["sess-course"]
    assert forwarded["mistakes_only"] is True
    assert forwarded["bookmarked"] is False
    assert forwarded["is_correct"] is False
    assert forwarded["resolved"] is False
    assert forwarded["search"] == "rank"
    assert forwarded["assessment_type"] == "quiz"
    assert forwarded["result"] == "incorrect"
    assert forwarded["score_trend"] == "improved"
    assert forwarded["limit"] == 10
    assert forwarded["offset"] == 5


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"assessment_type": "bogus"},
        {"result": "bogus"},
        {"score_trend": "bogus"},
        {"sort": "sideways"},
    ],
)
def test_list_entries_rejects_out_of_contract_queries(client, params):
    assert client.get(f"{PREFIX}/entries", params=params).status_code == 422


# ── entry ↔ category link routes ───────────────────────────────────


def test_add_entry_to_category_confirms(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    category = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()
    response = client.post(
        f"{PREFIX}/entries/{entry['id']}/categories", json={"category_id": category["id"]}
    )
    assert response.status_code == 200
    assert response.json() == {
        "added": True,
        "entry_id": entry["id"],
        "category_id": category["id"],
    }


def test_add_entry_to_category_requires_existing_entry(client):
    response = client.post(f"{PREFIX}/entries/9999/categories", json={"category_id": 1})
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"


def test_add_entry_to_category_refusal_maps_to_400(client):
    store = client.deps["store"]
    entry = _seed_entry(store)
    store.add_link_result = False
    response = client.post(f"{PREFIX}/entries/{entry['id']}/categories", json={"category_id": 3})
    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to add to category"


def test_remove_entry_from_category_confirms(client):
    response = client.delete(f"{PREFIX}/entries/5/categories/7")
    assert response.status_code == 200
    assert response.json() == {"removed": True, "entry_id": 5, "category_id": 7}


def test_remove_missing_link_is_404(client):
    store = client.deps["store"]
    store.remove_link_result = False
    response = client.delete(f"{PREFIX}/entries/5/categories/7")
    assert response.status_code == 404
    assert response.json()["detail"] == "Link not found"


def test_bulk_link_reports_requested_and_changed(client):
    store = client.deps["store"]
    ids = [_seed_entry(store)["id"] for _ in range(2)]
    category = client.post(f"{PREFIX}/categories", json={"name": "Set B"}).json()
    response = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category["id"]},
    )
    assert response.status_code == 200
    assert response.json() == {
        "changed": 2,
        "requested": 2,
        "category_id": category["id"],
        "link": True,
    }
    unlink = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category["id"], "link": False},
    )
    assert unlink.json()["link"] is False
    assert unlink.json()["changed"] == 2


# ── overview routes ─────────────────────────────────────────────────


def test_stats_returns_the_question_bank_counters(client):
    client.deps["store"].stats = {
        "total": 3,
        "wrong": 2,
        "unresolved": 1,
        "bookmarked": 1,
        "uncategorized": 2,
    }
    body = client.get(f"{PREFIX}/stats").json()
    assert body == {
        "total": 3,
        "wrong": 2,
        "unresolved": 1,
        "bookmarked": 1,
        "uncategorized": 2,
    }
    assert client.deps["store"].last_kwargs("question_bank_stats")["session_ids"] is None


def test_stats_scopes_counts_to_the_course_sessions(client):
    response = client.get(f"{PREFIX}/stats", params={"course_id": "course-1"})
    assert response.status_code == 200
    assert client.deps["store"].last_kwargs("question_bank_stats")["session_ids"] == ["sess-course"]


def test_materials_returns_material_summaries(client):
    client.deps["store"].materials = [
        {
            "source": "mastery_path",
            "material_id": "path-1",
            "material_title": "Algebra",
            "entry_count": 4,
            "unresolved_count": 2,
        }
    ]
    response = client.get(f"{PREFIX}/materials")
    assert response.status_code == 200
    assert response.json() == [
        {
            "source": "mastery_path",
            "material_id": "path-1",
            "material_title": "Algebra",
            "entry_count": 4,
            "unresolved_count": 2,
        }
    ]


@pytest.mark.parametrize(
    "path",
    ["/entries", "/stats", "/materials", "/categories"],
)
def test_unknown_course_scopes_to_404(client, path):
    response = client.get(f"{PREFIX}{path}", params={"course_id": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Course not found"


# ── category CRUD ───────────────────────────────────────────────────


def test_create_category_returns_model_with_201(client):
    response = client.post(f"{PREFIX}/categories", json={"name": "Kinematics"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Kinematics"
    assert body["entry_count"] == 0
    assert isinstance(body["id"], int)


def test_create_category_rejects_blank_and_oversized_names(client):
    assert client.post(f"{PREFIX}/categories", json={"name": ""}).status_code == 422
    assert client.post(f"{PREFIX}/categories", json={"name": "x" * 101}).status_code == 422


def test_create_category_conflict_maps_to_409(client):
    client.deps["store"].create_category_error = ValueError("already exists")
    response = client.post(f"{PREFIX}/categories", json={"name": "Math"})
    assert response.status_code == 409
    assert response.json()["detail"] == "already exists"


def test_rename_category_confirms(client):
    category = client.post(f"{PREFIX}/categories", json={"name": "Old"}).json()
    response = client.patch(f"{PREFIX}/categories/{category['id']}", json={"name": "New"})
    assert response.status_code == 200
    assert response.json() == {"updated": True, "id": category["id"], "name": "New"}


def test_rename_missing_category_is_404(client):
    response = client.patch(f"{PREFIX}/categories/9999", json={"name": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


def test_rename_conflict_maps_to_409(client):
    client.deps["store"].rename_error = ValueError("already exists")
    response = client.patch(f"{PREFIX}/categories/1", json={"name": "Clash"})
    assert response.status_code == 409
    assert response.json()["detail"] == "already exists"


def test_delete_category_confirms(client):
    category = client.post(f"{PREFIX}/categories", json={"name": "Doomed"}).json()
    response = client.delete(f"{PREFIX}/categories/{category['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "id": category["id"]}
    assert client.get(f"{PREFIX}/categories").json() == []


def test_delete_missing_category_is_404(client):
    response = client.delete(f"{PREFIX}/categories/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"
