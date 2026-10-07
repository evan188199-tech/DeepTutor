"""Contract tests for the Codex token refresh flow over a mocked HTTP transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from deeptutor.services.codex_auth.constants import CODEX_OAUTH_CLIENT_ID, CODEX_TOKEN_URL
from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexCredentials
from deeptutor.services.codex_auth.oauth import CodexOAuthClient
from deeptutor.services.codex_auth.service import CodexOAuthService
from deeptutor.services.codex_auth.storage import CodexCredentialStore
from deeptutor.services.config.model_catalog import ModelCatalogService

SECRET = "stored-refresh-secret"


def _credentials(expires_at: int = 1_200, generation: int = 0) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="stored-access",
        refresh_token=SECRET,
        id_token="stored-id",
        account_id="account-123",
        expires_at=expires_at,
        generation=generation,
    )


class FakeCatalog:
    async def get(self, credentials: CodexCredentials, force: bool) -> None:
        del credentials, force
        return None

    async def invalidate(self) -> None:
        return None


def _refresh_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "access_token": "fresh-access",
        "refresh_token": "fresh-refresh",
        "id_token": "fresh-id",
        "account_id": "account-123",
        "expires_in": 3_600,
    }
    payload.update(overrides)
    return payload


def _mock_client(
    requests: list[httpx.Request],
    handler: Any,
) -> tuple[httpx.AsyncClient, CodexOAuthClient]:
    def route(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return http, CodexOAuthClient(http)


@pytest.mark.asyncio
async def test_refresh_sends_json_grant_request_to_the_audited_token_url() -> None:
    requests: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_refresh_payload())

    http, client = _mock_client(requests, handler)
    async with http:
        payload = await client.refresh(SECRET)

    assert payload["access_token"] == "fresh-access"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == CODEX_TOKEN_URL
    assert request.method == "POST"
    assert request.headers["content-type"].startswith("application/json")
    assert json.loads(request.content) == {
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": SECRET,
    }


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "expected_status"),
    [
        (400, {"error": "invalid_grant"}, "token_refresh_rejected", 401),
        (401, {"error": "invalid_token"}, "token_refresh_rejected", 401),
        (400, {"error": "slow_down"}, "token_refresh_failed", 502),
        (401, {"error": "server_wants_you_back_later"}, "token_refresh_failed", 502),
        (401, "not-a-json-body", "token_refresh_failed", 502),
        (500, {"error": "backend_error"}, "token_refresh_failed", 502),
        (200, ["not", "a", "dict"], "token_refresh_failed", 502),
    ],
)
@pytest.mark.asyncio
async def test_refresh_response_classification(
    status: int,
    body: Any,
    expected_code: str,
    expected_status: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    http, client = _mock_client([], handler)
    async with http:
        with pytest.raises(CodexAuthError) as exc_info:
            await client.refresh(SECRET)

    assert exc_info.value.code == expected_code
    assert exc_info.value.http_status == expected_status


@pytest.mark.asyncio
async def test_transport_failure_maps_to_transient_refresh_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    http, client = _mock_client([], handler)
    async with http:
        with pytest.raises(CodexAuthError) as exc_info:
            await client.refresh(SECRET)

    assert exc_info.value.code == "token_refresh_failed"
    assert exc_info.value.http_status == 502


@pytest.mark.asyncio
async def test_refresh_errors_never_expose_the_stored_grant() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=SECRET)

    http, client = _mock_client([], handler)
    async with http:
        with pytest.raises(CodexAuthError) as exc_info:
            await client.refresh(SECRET)

    assert SECRET not in str(exc_info.value)
    assert SECRET not in exc_info.value.public_message


@pytest.mark.asyncio
async def test_service_refresh_commits_mocked_http_payload_and_throttles(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    responses: list[dict[str, Any]] = [_refresh_payload()]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[-1])

    http, client = _mock_client(requests, handler)
    clock = [1_000.0]
    store = CodexCredentialStore(tmp_path)
    committed = store.commit_credentials(_credentials(), expected_generation=0)
    service = CodexOAuthService(
        store,
        FakeCatalog(),
        ModelCatalogService(tmp_path / "model_catalog.json"),
        oauth_client=client,
        clock=lambda: clock[0],
    )

    async with http:
        token = await service.get_token()

    assert len(requests) == 1
    assert token.access_token == "fresh-access"
    assert token.generation == committed.generation + 1
    stored = store.load_credentials()
    assert stored is not None
    assert stored.access_token == "fresh-access"
    assert stored.refresh_token == "fresh-refresh"
    assert stored.expires_at == 1_000 + 3_600

    second = await service.get_token()

    assert len(requests) == 1
    assert second.access_token == "fresh-access"
    assert urlsplit(CODEX_TOKEN_URL).hostname == "auth.openai.com"
