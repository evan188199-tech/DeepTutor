"""Contract complement to ``tests/api/test_space_cli_apps.py``.

That file pins the auth split and the grant rules. This module pins the
branches it leaves open: the install success answer, the tolerant uninstall,
the localized error texts the router hands to ``t()``, the request-validation
refusals, catalog pagination and filtering, and the row shape for an install
the catalog no longer knows about.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import space_cli_apps
from deeptutor.services.cli_apps.installer import InstallOutcome
from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import abi_stamp
from deeptutor.services.cli_apps.state import InstalledApp, record_install
from deeptutor.services.i18n import t

REAL_APP = "blender"


@pytest.fixture(autouse=True)
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture
def caller(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"owner": "u_ada", "granted": set(), "exec": None}
    monkeypatch.setattr(space_cli_apps, "current_owner_id", lambda: state["owner"])
    monkeypatch.setattr(space_cli_apps, "allowed_cli_apps", lambda: state["granted"])
    monkeypatch.setattr(space_cli_apps, "exec_override", lambda: state["exec"])
    return state


@pytest.fixture
def client(caller: dict[str, Any]) -> TestClient:
    app = FastAPI()
    app.include_router(space_cli_apps.router, prefix="/api/space/cli-apps")
    return TestClient(app)


def _install(app_id: str = REAL_APP) -> None:
    record_install(
        InstalledApp(
            id=app_id,
            entry_point=f"cli-anything-{app_id}",
            runtime=AppRuntime.PYTHON,
            kind=InstallKind.PINNED_HARNESS,
            target="git+https://example.invalid/x.git@abc",
            pin="abc",
            abi=abi_stamp(),
            installed_at="2026-10-06T00:00:00+00:00",
        )
    )


# ── installing ────────────────────────────────────────────────────────────


def test_a_successful_install_answers_with_the_fresh_list_and_the_log(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A success is not an empty 200: the admin gets the new state and the
    installer output, whose warnings are worth reading even then."""

    async def _succeed(entry: Any) -> InstallOutcome:
        _install(entry.id)
        return InstallOutcome(
            ok=True,
            app_id=entry.id,
            log="$ pip install ...\nInstalled cli-anything",
        )

    monkeypatch.setattr("deeptutor.services.cli_apps.installer.install_app", _succeed)
    response = client.post(f"/api/space/cli-apps/catalog/{REAL_APP}/install")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["apps"]] == [REAL_APP]
    assert body["log"] == "$ pip install ...\nInstalled cli-anything"
    assert body["access"]["unrestricted"] is False


def test_uninstalling_an_app_that_was_never_installed_still_answers_with_the_list(
    client: TestClient,
) -> None:
    """Removal is tolerant by design: a half-finished install must not leave a
    row an administrator is unable to clear, so an unknown id is not a 404."""
    response = client.delete("/api/space/cli-apps/apps/never-installed")

    assert response.status_code == 200
    assert response.json()["apps"] == []


def test_installing_an_unknown_id_names_it_in_the_localized_404(client: TestClient) -> None:
    response = client.post("/api/space/cli-apps/catalog/no-such-app-xyz/install")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "no-such-app-xyz" in detail
    assert "cli_apps." not in detail, "the raw message key must never reach the client"


# ── choosing ──────────────────────────────────────────────────────────────


def test_toggling_an_unknown_app_names_it_in_the_localized_404(
    client: TestClient,
) -> None:
    response = client.put("/api/space/cli-apps/apps/ghost-app/enabled", json={"enabled": True})

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "ghost-app" in detail
    assert "cli_apps." not in detail


def test_the_grant_refusal_message_is_the_localized_sentence(
    client: TestClient,
) -> None:
    _install()
    response = client.put(f"/api/space/cli-apps/apps/{REAL_APP}/enabled", json={"enabled": True})

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "cli.not_granted"
    assert detail["message"] == t("cli_apps.entry_admin_only")
    assert detail["message"]


def test_an_uninstalled_app_answers_404_before_the_grant_is_even_consulted(
    client: TestClient,
) -> None:
    """The 404 for a missing install wins over the 403 for a missing grant,
    whatever the caller's grants are."""
    response = client.put(
        "/api/space/cli-apps/apps/never-installed/enabled", json={"enabled": True}
    )

    assert response.status_code == 404
    assert response.status_code != 403


def test_an_enabled_write_with_a_missing_field_is_refused_and_writes_nothing(
    client: TestClient,
) -> None:
    _install()

    response = client.put(f"/api/space/cli-apps/apps/{REAL_APP}/enabled", json={})

    assert response.status_code == 422
    assert client.get("/api/space/cli-apps/apps").json()["apps"][0]["enabled"] is False


def test_an_enabled_write_with_a_non_boolean_is_refused_and_writes_nothing(
    client: TestClient,
) -> None:
    _install()

    response = client.put(f"/api/space/cli-apps/apps/{REAL_APP}/enabled", json={"enabled": "maybe"})

    assert response.status_code == 422
    assert client.get("/api/space/cli-apps/apps").json()["apps"][0]["enabled"] is False


# ── reading ───────────────────────────────────────────────────────────────


def test_a_non_boolean_installable_only_filter_is_a_422(client: TestClient) -> None:
    response = client.get("/api/space/cli-apps/catalog", params={"installable_only": "maybe"})

    assert response.status_code == 422


def test_catalog_pagination_walks_every_entry_exactly_once(client: TestClient) -> None:
    """Each page is bounded by the limit, cursors never repeat an entry, and
    the walk ends on an empty cursor with the total accounted for."""
    first = client.get(
        "/api/space/cli-apps/catalog",
        params={"installable_only": "false", "limit": 5},
    ).json()
    total = first["total"]
    assert total > 5, "the pinned catalog should span more than one page"

    seen: list[str] = [row["id"] for row in first["entries"]]
    cursor = first["next_cursor"]
    pages = 1
    while cursor:
        page = client.get(
            "/api/space/cli-apps/catalog",
            params={"installable_only": "false", "limit": 5, "cursor": cursor},
        ).json()
        assert len(page["entries"]) <= 5
        seen.extend(row["id"] for row in page["entries"])
        cursor = page["next_cursor"]
        pages += 1
        assert pages < 100, "pagination did not terminate"

    assert len(seen) == len(set(seen)) == total


def test_the_category_filter_narrows_the_rows_but_not_the_reported_counts(
    client: TestClient,
) -> None:
    """The tab counts stay whole-store so the page can render every tab; only
    ``entries`` narrows to the chosen category."""
    everything = client.get(
        "/api/space/cli-apps/catalog",
        params={"installable_only": "false", "limit": 100},
    ).json()
    target = next(row["category"] for row in everything["entries"] if row["category"])

    page = client.get(
        "/api/space/cli-apps/catalog",
        params={"category": target, "installable_only": "false", "limit": 100},
    ).json()

    assert page["entries"]
    assert all(row["category"] == target for row in page["entries"])
    assert sum(page["categories"].values()) == everything["total"]
    assert page["categories"][target] >= len(page["entries"])


def test_an_app_installed_but_gone_from_the_catalog_reports_itself_as_orphaned(
    client: TestClient,
) -> None:
    """The row falls back to what the install record itself knows, and says so
    via ``in_catalog`` instead of pretending the store still lists it."""
    _install("ghost-app")

    body = client.get("/api/space/cli-apps/apps").json()
    row = body["apps"][0]

    assert row["id"] == "ghost-app"
    assert row["in_catalog"] is False
    assert row["display_name"] == "ghost-app"
    assert row["description"] == ""
    assert row["trust"] == "third-party"
