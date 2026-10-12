"""Route contract for the workspace journal overview API.

``tests/api/test_learning_journal.py`` mounts the router bare and covers the
store-facing behaviour (workspace scoping, corruption handling, snapshot
shape). This module pins the wiring ``main.py`` adds in front of the same
router:

* the production auth stack — ``require_learning_surface`` over
  ``require_auth`` with ``AUTH_ENABLED=true`` — including the learner-policy
  default-deny for the unmapped journal surface,
* the unparameterised overview contract: no pagination or filter parameters,
  one GET route, and nothing else,
* the read-only method surface across every write verb,
* the boundary of the 409 error mapping (only ``OSError``/``ValueError``).

Everything runs offline against ``TestClient`` with isolated multi-user
roots; no server is started.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload
from deeptutor.services.learning_journal.store import LearningJournalStore

OVERVIEW_URL = "/api/learning-journal"

#: Bearer token → (username, user_id). Unknown tokens must decode to None so
#: ``require_auth`` answers 401 instead of admitting the request.
_TOKENS: dict[str, tuple[str, str]] = {
    "token-alice": ("alice", "u_alice"),
    "token-bob": ("bob", "u_bob"),
}


def _acting_payload(user_id: str) -> TokenPayload:
    username = next(name for name, uid in _TOKENS.values() if uid == user_id)
    return TokenPayload(username=username, role="user", user_id=user_id)


@pytest.fixture
def journal_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The journal router behind the exact dependency stack ``main.py`` mounts.

    Isolates the multi-user roots under ``tmp_path`` (same approach as
    ``tests/api/routers/test_learning_records_access.py``) so the request →
    ``require_auth`` → user ContextVar → per-account path service chain runs
    for real, without touching developer data.
    """
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import learning_journal
    from deeptutor.api.routers.auth import require_learning_surface
    from deeptutor.multi_user import grants, identity
    from deeptutor.multi_user import paths as mu_paths
    from deeptutor.services import auth as auth_service

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)

    def _decode(token: str) -> TokenPayload | None:
        pair = _TOKENS.get(token)
        if pair is None:
            return None
        username, user_id = pair
        return TokenPayload(username=username, role="user", user_id=user_id)

    monkeypatch.setattr(auth_router, "decode_token", _decode)

    monkeypatch.setattr(mu_paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mu_paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(mu_paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(mu_paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(mu_paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(mu_paths, "_path_services", {})

    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "legacy-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "legacy-secret")

    grants_dir = system_root / "grants"
    monkeypatch.setattr(grants, "GRANTS_DIR", grants_dir)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")

    app = FastAPI()
    app.include_router(
        learning_journal.router,
        prefix=OVERVIEW_URL,
        dependencies=[Depends(require_learning_surface)],
    )
    return SimpleNamespace(
        client=TestClient(app),
        grants_dir=grants_dir,
        users_root=admin_root / "users",
    )


def _seed_journal(user_id: str, *, topic: str, records: int = 0) -> None:
    """Persist a journal for an account outside the HTTP request cycle."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.multi_user.context import reset_current_user

    token = _install_current_user(_acting_payload(user_id))
    try:
        store = LearningJournalStore()
        store.set_mission(topic=topic)
        for index in range(records):
            result = store.add_record(title=f"Insight {index}", insight=f"Recorded {index}")
            assert result.accepted, result.message
    finally:
        reset_current_user(token)


def test_overview_rejects_missing_and_unknown_tokens(journal_client) -> None:
    """401 branches: an unauthenticated or unrecognisable caller is rejected
    before any journal file is created for any account."""
    missing = journal_client.client.get(OVERVIEW_URL)
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"

    unknown = journal_client.client.get(
        OVERVIEW_URL, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert unknown.status_code == 401
    assert unknown.headers["WWW-Authenticate"] == "Bearer"

    created = [p for p in journal_client.users_root.rglob("learning_journal") if p.is_dir()]
    assert created == []


def test_overview_serves_only_the_callers_journal(journal_client) -> None:
    """With the production auth stack, each authenticated account is served
    its own workspace journal and never another account's entries."""
    _seed_journal("u_alice", topic="Alice mission")
    _seed_journal("u_bob", topic="Bob mission")

    alice = journal_client.client.get(OVERVIEW_URL, headers={"Authorization": "Bearer token-alice"})
    assert alice.status_code == 200
    alice_body = alice.json()
    assert alice_body["mission"]["topic"] == "Alice mission"
    assert "Bob mission" not in json.dumps(alice_body)

    bob = journal_client.client.get(OVERVIEW_URL, headers={"Authorization": "Bearer token-bob"})
    assert bob.status_code == 200
    bob_body = bob.json()
    assert bob_body["mission"]["topic"] == "Bob mission"
    assert "Alice mission" not in json.dumps(bob_body)


def test_learner_policy_without_journal_surface_is_denied(journal_client) -> None:
    """A configured learning account is default-denied on the unmapped journal
    surface: the guard answers 403 and the stored journal stays untouched."""
    journal_client.grants_dir.mkdir(parents=True, exist_ok=True)
    (journal_client.grants_dir / "u_alice.json").write_text(
        json.dumps(
            {
                "learning_policy": {
                    "age_band": "9-12",
                    "locked_persona": "teacher",
                    "allowed_capabilities": ["chat", "immersive_reading"],
                    "default_capability": "chat",
                    "allowed_surfaces": ["chat", "reading"],
                }
            }
        ),
        encoding="utf-8",
    )
    _seed_journal("u_alice", topic="Learner mission")

    denied = journal_client.client.get(
        OVERVIEW_URL, headers={"Authorization": "Bearer token-alice"}
    )
    assert denied.status_code == 403
    assert "requested server surface" in denied.json()["detail"]

    journal_file = next(journal_client.users_root.rglob("journal.json"))
    stored = json.loads(journal_file.read_text(encoding="utf-8"))
    assert stored["mission"]["topic"] == "Learner mission"


def test_overview_takes_no_pagination_or_filter_parameters(journal_client) -> None:
    """The overview is an unpaged, unfiltered full snapshot: query parameters
    are ignored (never 422, never narrowing), and the router registers exactly
    one GET route with no parameter sub-endpoints."""
    _seed_journal("u_alice", topic="Mission", records=3)

    headers = {"Authorization": "Bearer token-alice"}
    plain = journal_client.client.get(OVERVIEW_URL, headers=headers)
    assert plain.status_code == 200

    filtered = journal_client.client.get(
        OVERVIEW_URL,
        headers=headers,
        params={"limit": "0", "offset": "5", "topic": "Mission", "since": "2020-01-01"},
    )
    assert filtered.status_code == 200
    assert filtered.json() == plain.json()

    from deeptutor.api.routers import learning_journal

    routes = [
        (route.path, tuple(sorted(route.methods))) for route in learning_journal.router.routes
    ]
    assert routes == [("", ("GET",))]


def test_overview_refuses_every_mutation_method() -> None:
    """The read-only surface covers every write verb, not just POST."""
    from deeptutor.api.routers import learning_journal

    app = FastAPI()
    app.include_router(learning_journal.router, prefix=OVERVIEW_URL)
    client = TestClient(app)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, OVERVIEW_URL, json={})
        assert response.status_code == 405, method


def test_unexpected_store_error_is_not_mapped_to_conflict(monkeypatch) -> None:
    """Only ``OSError``/``ValueError`` map to 409; any other store failure
    stays a server error instead of being disguised as a conflict."""
    from deeptutor.api.routers import learning_journal

    class _ExplodingStore:
        def overview(self) -> dict:
            raise RuntimeError("unexpected backend failure")

    monkeypatch.setattr(learning_journal, "get_learning_journal_store", lambda: _ExplodingStore())
    app = FastAPI()
    app.include_router(learning_journal.router, prefix=OVERVIEW_URL)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(OVERVIEW_URL)
    assert response.status_code == 500
