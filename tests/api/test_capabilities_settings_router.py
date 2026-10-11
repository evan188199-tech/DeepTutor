"""Capabilities settings router contract tests (deeptutor/api/routers/capabilities_settings.py).

The router is a thin transport layer over
:mod:`deeptutor.services.config.capabilities_settings`: GET returns the
schema dict, PUT forwards the payload and returns the saved state. These
tests pin that transport contract without touching any real YAML — the
service functions are resolved lazily at request time, so monkeypatching
them on the service module is enough to keep every request hermetic.

Covered groups:

1. GET contract — service schema dict is returned as-is.
2. PUT contract — payload reaches the service unmodified, response is the
   service's returned new state, and a GET afterwards reads the state back.
3. 4xx surfaces — non-dict and missing JSON bodies are rejected with
   FastAPI's ``{"detail": [...]}`` envelope before the service is called;
   unsupported methods return 405.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

router_mod = importlib.import_module("deeptutor.api.routers.capabilities_settings")
service_mod = importlib.import_module("deeptutor.services.config.capabilities_settings")

PREFIX = "/api/capabilities"


def _fake_schema(marker: str = "schema") -> dict:
    """A dict shaped like the real schema but with sentinel values."""
    return {
        "chat": {"temperature": 0.42, "max_rounds": 9, "stage_budgets": {}},
        "solve": {"temperature": 0.11, "max_tokens": 111, "max_rounds": 3, "max_replans": 1},
        marker: True,
    }


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router_mod.router, prefix=PREFIX)
    return TestClient(app)


# ── ① GET contract ───────────────────────────────────────────────────────


def test_get_returns_service_schema(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = _fake_schema()
    calls: list[bool] = []
    monkeypatch.setattr(
        service_mod,
        "capabilities_settings_dict",
        lambda: (calls.append(True), schema)[1],
    )

    res = client.get(f"{PREFIX}/settings")
    assert res.status_code == 200
    assert res.json() == schema
    assert calls == [True]


def test_get_resolves_service_at_request_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lazy per-request import means a patched service function wins."""
    monkeypatch.setattr(
        service_mod,
        "capabilities_settings_dict",
        lambda: {"from": "patched"},
    )

    res = client.get(f"{PREFIX}/settings")
    assert res.status_code == 200
    assert res.json() == {"from": "patched"}


# ── ② PUT contract ───────────────────────────────────────────────────────


def test_put_forwards_payload_and_returns_saved_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "chat": {"temperature": 0.2, "max_rounds": 30, "stage_budgets": {"exploring": 4096}},
        "solve": {"temperature": 0.5, "max_tokens": 9000, "max_rounds": 20, "max_replans": 4},
    }
    saved_state = _fake_schema("saved")
    seen: list[dict] = []
    monkeypatch.setattr(
        service_mod,
        "save_capabilities_settings",
        lambda p: (seen.append(p), saved_state)[1],
    )

    res = client.put(f"{PREFIX}/settings", json=payload)
    assert res.status_code == 200
    assert res.json() == saved_state
    # The transport layer forwards the parsed body untouched.
    assert len(seen) == 1
    assert seen[0] == payload
    assert seen[0] is not payload  # decode creates a fresh dict; content equal


def test_put_then_get_reads_saved_state_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read/write round-trip through one stateful fake service."""
    state = {"chat": {"temperature": 0.3}, "solve": {"max_rounds": 12}}

    def fake_save(payload: dict) -> dict:
        state.update(payload)
        return dict(state)

    monkeypatch.setattr(service_mod, "capabilities_settings_dict", lambda: dict(state))
    monkeypatch.setattr(service_mod, "save_capabilities_settings", fake_save)

    res = client.put(f"{PREFIX}/settings", json={"chat": {"temperature": 0.77}})
    assert res.status_code == 200
    assert res.json()["chat"] == {"temperature": 0.77}

    follow_up = client.get(f"{PREFIX}/settings")
    assert follow_up.status_code == 200
    assert follow_up.json()["chat"] == {"temperature": 0.77}


# ── ③ 4xx surfaces ───────────────────────────────────────────────────────


def test_put_non_dict_body_rejected_422_without_saving(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        service_mod,
        "save_capabilities_settings",
        lambda p: calls.append(p) or {},
    )

    res = client.put(f"{PREFIX}/settings", json=[1, 2, 3])
    assert res.status_code == 422
    body = res.json()
    assert isinstance(body["detail"], list)
    assert calls == []  # validation rejects before the service runs


def test_put_missing_body_rejected_422_without_saving(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        service_mod,
        "save_capabilities_settings",
        lambda p: calls.append(p) or {},
    )

    res = client.put(f"{PREFIX}/settings")
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)
    assert calls == []


def test_unsupported_methods_on_settings_route_405(client: TestClient) -> None:
    for method in ("post", "delete", "patch"):
        res = getattr(client, method)(f"{PREFIX}/settings")
        assert res.status_code == 405, method
