"""API surface tests for ``/api/capabilities/settings``.

The endpoint is a deliberate transport layer in front of
:mod:`deeptutor.services.config.capabilities_settings`: GET returns the
merged settings state, PUT writes the payload back into the YAML files.
Because a real PUT would rewrite ``agents.yaml`` / ``main.yaml``, every
test stubs the service functions — the router must stay a pure
pass-through, and the production app must keep the routes behind the
learning-surface auth gate.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

SETTINGS_PATH = "/api/capabilities/settings"


@pytest.fixture
def client() -> "TestClient":
    from deeptutor.api.routers import capabilities_settings

    app = FastAPI()
    app.include_router(capabilities_settings.router, prefix="/api/capabilities")
    return TestClient(app)


def test_get_settings_returns_the_service_state(
    client: "TestClient", monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET is a read-only mirror of the service layer's merged state."""
    from deeptutor.services.config import capabilities_settings as service

    sentinel = {"solve": {"temperature": 0.2, "max_tokens": 4096}}
    monkeypatch.setattr(service, "capabilities_settings_dict", lambda: sentinel)

    response = client.get(SETTINGS_PATH)

    assert response.status_code == 200
    assert response.json() == sentinel


def test_put_settings_round_trips_payload_through_the_service(
    client: "TestClient", monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT hands the JSON body to the service untouched and echoes its result."""
    from deeptutor.services.config import capabilities_settings as service

    seen: dict = {}
    sentinel = {"ok": True, "applied": ["solve.temperature"]}

    def fake_save(payload: dict) -> dict:
        seen.update(payload)
        return sentinel

    monkeypatch.setattr(service, "save_capabilities_settings", fake_save)

    payload = {"solve": {"temperature": 0.5, "max_tokens": 8192}}
    response = client.put(SETTINGS_PATH, json=payload)

    assert response.status_code == 200
    assert seen == payload
    assert response.json() == sentinel


def test_put_settings_propagates_service_errors(
    client: "TestClient", monkeypatch: pytest.MonkeyPatch
) -> None:
    """Service-side failures surface instead of being swallowed into a fake 200."""
    from deeptutor.services.config import capabilities_settings as service

    def refusing_save(payload: dict) -> dict:
        raise ValueError("invalid capabilities settings payload")

    monkeypatch.setattr(service, "save_capabilities_settings", refusing_save)

    with pytest.raises(ValueError, match="invalid capabilities settings payload"):
        client.put(SETTINGS_PATH, json={"solve": {"temperature": "not-a-number"}})


def test_put_settings_rejects_non_object_payloads(client: "TestClient") -> None:
    """The route models the body as a JSON object; anything else is a 422."""
    response = client.put(SETTINGS_PATH, json=["not", "an", "object"])

    assert response.status_code == 422


def _effective_route_contexts(app: "FastAPI", path: str) -> Iterator[tuple[set[str], list]]:
    """Yield ``(methods, dependency_lists)`` for routes registered at *path*.

    Handles both flattened ``APIRoute`` releases and FastAPI >= 0.141, where
    included routers stay nested behind ``effective_route_contexts()``.
    """
    for route in app.routes:
        if getattr(route, "path", None) == path:
            yield set(route.methods), route.dependencies
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if not callable(contexts):
            continue
        for context in contexts():
            if getattr(context, "path", None) != path:
                continue
            dependencies = list(getattr(context, "dependencies", []) or [])
            dependencies.extend(getattr(context.original_route, "dependencies", []) or [])
            yield set(context.methods), dependencies


def test_settings_routes_stay_behind_the_learning_surface_gate() -> None:
    """Both methods must inherit the auth dependency from the include call.

    The gate lives on the ``include_router`` call in the production app, not
    on the router object, so this asserts against the real application — if
    the router is ever re-included without ``_auth`` the test fails.
    """
    from deeptutor.api.main import app
    from deeptutor.api.routers.auth import require_learning_surface

    contexts = list(_effective_route_contexts(app, SETTINGS_PATH))
    assert contexts, "expected /api/capabilities/settings to be registered"

    methods_seen: set[str] = set()
    for methods, dependencies in contexts:
        methods_seen |= methods
        gated = {dependency.dependency for dependency in dependencies}
        assert require_learning_surface in gated
    assert {"GET", "PUT"} <= methods_seen
