"""HTTP surface for personal API-key providers (bring your own key, #1927).

The endpoints are self-service for ordinary users: they write only the
caller's own catalog and secret store. Asserted here over real HTTP, with the
deployment switch driven through the admin endpoint itself:

* the switch is off by default — a user who tries to add a provider gets a
  clear refusal, and the admin endpoint that flips it is admin-gated;
* once allowed, a saved provider comes back redacted: whether a key is
  stored, never the key;
* a partner is refused (it would act inside its owner's scope) and an
  administrator is refused (their providers live in the shared catalog);
* deleting stays possible after the switch is turned off again.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import settings as settings_router
from deeptutor.services.auth import TokenPayload
from deeptutor.services.partners.scope import PARTNER_USER_PREFIX

PROVIDERS_URL = "/api/settings/personal-providers"
POLICY_URL = "/api/settings/personal-providers/policy"

PROVIDER_PAYLOAD: dict[str, Any] = {
    "name": "My OpenRouter",
    "binding": "openrouter",
    "api_key": "sk-or-v1-test",
    "models": [{"id": "m-or", "name": "OpenRouter model", "model": "openai/gpt-4o"}],
}


@pytest.fixture
def client(tmp_path, monkeypatch) -> tuple[TestClient, dict[str, TokenPayload]]:
    from deeptutor.multi_user import paths as mu_paths

    monkeypatch.setattr(mu_paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mu_paths, "ADMIN_WORKSPACE_ROOT", tmp_path / "data")
    monkeypatch.setattr(mu_paths, "USERS_ROOT", tmp_path / "data" / "users")
    monkeypatch.setattr(mu_paths, "SYSTEM_ROOT", tmp_path / "data" / "system")
    monkeypatch.setattr(mu_paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(mu_paths, "_path_services", {})

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    payloads: dict[str, TokenPayload] = {
        "current": TokenPayload(username="alice", role="user", user_id="u_alice")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda _token: payloads["current"])

    app = FastAPI()
    app.include_router(
        settings_router.router,
        prefix="/api/settings",
        dependencies=[Depends(auth_router.require_auth)],
    )
    test_client = TestClient(app)
    test_client.headers.update({"Authorization": "Bearer test-token"})
    return test_client, payloads


def _as(payloads: dict[str, TokenPayload], payload: TokenPayload) -> None:
    payloads["current"] = payload


def _alice() -> TokenPayload:
    return TokenPayload(username="alice", role="user", user_id="u_alice")


def _admin() -> TokenPayload:
    return TokenPayload(username="root", role="admin", user_id="u_root")


def _partner() -> TokenPayload:
    return TokenPayload(username="ada", role="user", user_id=f"{PARTNER_USER_PREFIX}ada")


def test_default_view_reports_the_feature_off(client) -> None:
    test_client, _ = client
    response = test_client.get(PROVIDERS_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["providers"] == []
    assert "openrouter" in body["bindings"]
    assert "custom" not in body["bindings"]


def test_a_user_cannot_add_a_provider_while_the_policy_is_off(client) -> None:
    test_client, _ = client
    response = test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD)
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_the_policy_switch_is_admin_gated(client) -> None:
    test_client, payloads = client
    _as(payloads, _alice())
    response = test_client.put(POLICY_URL, json={"allow_personal_providers": True})
    assert response.status_code == 403


def test_user_saves_uses_and_deletes_their_own_provider(client) -> None:
    test_client, payloads = client
    _as(payloads, _admin())
    assert test_client.put(POLICY_URL, json={"allow_personal_providers": True}).status_code == 200

    _as(payloads, _alice())
    response = test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD)
    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["id"] == "personal-openrouter"
    assert provider["has_api_key"] is True
    assert "api_key" not in provider
    assert "sk-or" not in response.text

    listing = test_client.get(PROVIDERS_URL).json()
    assert listing["allowed"] is True
    assert listing["providers"] == [provider]

    # The provider reaches this user's llm-options and nobody else's view.
    options = test_client.get("/api/settings/llm-options").json()
    assert [(o["model_id"], o["source"]) for o in options["options"]] == [("m-or", "personal")]

    response = test_client.delete(f"{PROVIDERS_URL}/personal-openrouter")
    assert response.status_code == 200
    assert test_client.get(PROVIDERS_URL).json()["providers"] == []
    # Idempotent refusal for a second delete of the same id.
    assert test_client.delete(f"{PROVIDERS_URL}/personal-openrouter").status_code == 404


def test_policy_off_again_keeps_delete_available(client) -> None:
    test_client, payloads = client
    _as(payloads, _admin())
    test_client.put(POLICY_URL, json={"allow_personal_providers": True})
    _as(payloads, _alice())
    assert test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD).status_code == 200

    _as(payloads, _admin())
    test_client.put(POLICY_URL, json={"allow_personal_providers": False})

    _as(payloads, _alice())
    assert test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD).status_code == 403
    listing = test_client.get(PROVIDERS_URL).json()
    assert listing["allowed"] is False
    assert [p["id"] for p in listing["providers"]] == ["personal-openrouter"]
    assert test_client.delete(f"{PROVIDERS_URL}/personal-openrouter").status_code == 200


def test_a_partner_is_refused(client) -> None:
    test_client, payloads = client
    _as(payloads, _admin())
    test_client.put(POLICY_URL, json={"allow_personal_providers": True})
    _as(payloads, _partner())
    response = test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD)
    assert response.status_code == 403
    assert test_client.delete(f"{PROVIDERS_URL}/personal-openrouter").status_code == 403


def test_an_administrator_is_redirected_to_the_shared_catalog(client) -> None:
    test_client, payloads = client
    _as(payloads, _admin())
    test_client.put(POLICY_URL, json={"allow_personal_providers": True})
    response = test_client.put(PROVIDERS_URL, json=PROVIDER_PAYLOAD)
    assert response.status_code == 400
    assert "shared model catalog" in response.json()["detail"]


def test_out_of_allowlist_bindings_and_bad_payloads_are_rejected(client) -> None:
    test_client, payloads = client
    _as(payloads, _admin())
    test_client.put(POLICY_URL, json={"allow_personal_providers": True})
    _as(payloads, _alice())
    for binding in ("custom", "openai_codex", "ollama"):
        response = test_client.put(PROVIDERS_URL, json={**PROVIDER_PAYLOAD, "binding": binding})
        assert response.status_code == 400, binding
    # No key on create, and no models, are both refused.
    no_key = {k: v for k, v in PROVIDER_PAYLOAD.items() if k != "api_key"}
    assert test_client.put(PROVIDERS_URL, json=no_key).status_code == 400
    no_models = {**PROVIDER_PAYLOAD, "models": []}
    assert test_client.put(PROVIDERS_URL, json=no_models).status_code == 400
