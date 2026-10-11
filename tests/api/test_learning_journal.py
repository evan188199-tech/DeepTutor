from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import learning_journal
from deeptutor.services.learning_journal.store import LearningJournalStore
from deeptutor.services.path_service import PathService
from deeptutor.services.workspace.context import WorkspacePathService, WorkspaceScope


def test_read_only_overview_is_scoped_and_preserves_corruption(tmp_path, monkeypatch):
    account = PathService(workspace_root=tmp_path / "account")
    a = WorkspacePathService(account, WorkspaceScope("a", account.workspace_root, tmp_path / "a"))
    b = WorkspacePathService(account, WorkspaceScope("b", account.workspace_root, tmp_path / "b"))
    active = [a]
    store = LearningJournalStore()
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service", lambda: active[0]
    )
    monkeypatch.setattr(learning_journal, "get_learning_journal_store", lambda: store)
    app = FastAPI()
    app.include_router(learning_journal.router, prefix="/api/learning-journal")
    client = TestClient(app)
    store.set_mission(topic="Workspace A")
    assert client.get("/api/learning-journal").json()["mission"]["topic"] == "Workspace A"
    active[0] = b
    assert client.get("/api/learning-journal").json()["mission"]["topic"] == ""
    assert not b.get_learning_journal_dir().exists()
    assert (
        client.post("/api/learning-journal", json={"mission": {"topic": "overwrite"}}).status_code
        == 405
    )
    b.get_learning_journal_dir().mkdir(parents=True)
    b.get_learning_journal_file().write_bytes(b"{corrupt")
    assert client.get("/api/learning-journal").status_code == 409
    assert b.get_learning_journal_file().read_bytes() == b"{corrupt"
    active[0] = a
    assert store.load().mission.topic == "Workspace A"


def _journal_app(monkeypatch, store, active):
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service", lambda: active[0]
    )
    monkeypatch.setattr(learning_journal, "get_learning_journal_store", lambda: store)
    app = FastAPI()
    app.include_router(learning_journal.router, prefix="/api/learning-journal")
    return TestClient(app)


def _scoped_active(tmp_path):
    account = PathService(workspace_root=tmp_path / "account")
    return [
        WorkspacePathService(account, WorkspaceScope("a", account.workspace_root, tmp_path / "a"))
    ]


def test_overview_on_empty_workspace_has_full_shape_and_creates_nothing(tmp_path, monkeypatch):
    active = _scoped_active(tmp_path)
    client = _journal_app(monkeypatch, LearningJournalStore(), active)

    snapshot = client.get("/api/learning-journal")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert set(body) == {
        "version",
        "updated_at",
        "mission",
        "last_session",
        "records",
        "injected_context",
    }
    assert body["version"] == 1
    assert body["records"] == []
    assert body["injected_context"] == ""
    assert body["mission"]["topic"] == ""
    assert not active[0].get_learning_journal_dir().exists()


def test_unsupported_version_maps_to_409_and_preserves_bytes(tmp_path, monkeypatch):
    active = _scoped_active(tmp_path)
    client = _journal_app(monkeypatch, LearningJournalStore(), active)

    journal_file = active[0].get_learning_journal_file()
    journal_file.parent.mkdir(parents=True)
    journal_file.write_bytes(b'{"version": 99}')

    response = client.get("/api/learning-journal")
    assert response.status_code == 409
    assert "preserved" in response.json()["detail"]
    assert journal_file.read_bytes() == b'{"version": 99}'


def test_overview_maps_oserror_to_409(tmp_path, monkeypatch):
    active = _scoped_active(tmp_path)
    store = LearningJournalStore()

    def raise_oserror():
        raise OSError("disk gone")

    monkeypatch.setattr(store, "overview", raise_oserror)
    client = _journal_app(monkeypatch, store, active)

    response = client.get("/api/learning-journal")
    assert response.status_code == 409
    assert "could not be read" in response.json()["detail"]
