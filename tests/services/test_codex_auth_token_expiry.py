"""Contract tests for Codex token expiry determination and the reauth cooldown."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.codex_auth.contracts import (
    CodexAuthError,
    CodexCredentials,
    decode_codex_jwt,
)
from deeptutor.services.codex_auth.service import (
    CODE_AUTH_FAILURE_COOLDOWN_S,
    CodexOAuthService,
)
from deeptutor.services.codex_auth.storage import CodexCredentialStore
from deeptutor.services.config.model_catalog import ModelCatalogService


def _jwt_payload(payload: dict[str, Any]) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
    return f"header.{raw.decode('ascii').rstrip('=')}.signature"


def _credentials(expires_at: int, generation: int = 0) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id="account-123",
        expires_at=expires_at,
        generation=generation,
    )


class FakeOAuth:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.payload: dict[str, Any] = {
            "access_token": "refreshed-access",
            "refresh_token": "refreshed-refresh",
            "id_token": "refreshed-id",
            "account_id": "account-123",
            "expires_in": 3_600,
        }
        self.error: CodexAuthError | None = None

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        del refresh_token
        self.refresh_calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.payload)


class FakeCatalog:
    async def get(self, credentials: CodexCredentials, force: bool) -> None:
        del credentials, force
        return None

    async def invalidate(self) -> None:
        return None


def _service(
    tmp_path: Path,
    oauth: FakeOAuth,
    clock: list[float],
) -> CodexOAuthService:
    return CodexOAuthService(
        CodexCredentialStore(tmp_path),
        FakeCatalog(),
        ModelCatalogService(tmp_path / "model_catalog.json"),
        oauth_client=oauth,
        clock=lambda: clock[0],
    )


@pytest.mark.parametrize(
    ("payload", "expected_expires_at", "expected_account"),
    [
        ({"exp": 1_700_000_000}, 1_700_000_000, None),
        (
            {
                "exp": 1_700_000_000,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acc-77"},
            },
            1_700_000_000,
            "acc-77",
        ),
        ({"exp": True}, None, None),
        ({"exp": "1700000000"}, None, None),
        ({}, None, None),
        (
            {"https://api.openai.com/auth": {"chatgpt_account_id": 42}},
            None,
            None,
        ),
    ],
)
def test_decode_jwt_extracts_expiry_and_account_claims_only(
    payload: dict[str, Any],
    expected_expires_at: int | None,
    expected_account: str | None,
) -> None:
    claims = decode_codex_jwt(_jwt_payload(payload))

    assert claims.expires_at == expected_expires_at
    assert claims.account_id == expected_account


@pytest.mark.parametrize("token", ["", "no-dots", "a.b", "h.not-base64!.$"])
def test_decode_jwt_rejects_malformed_tokens_as_invalid(token: str) -> None:
    with pytest.raises(CodexAuthError) as exc_info:
        decode_codex_jwt(token)

    assert exc_info.value.code == "invalid_token"
    assert exc_info.value.http_status == 401
    if token:
        assert token not in str(exc_info.value)


@pytest.mark.asyncio
async def test_token_well_before_expiry_window_is_returned_without_refresh(
    tmp_path: Path,
) -> None:
    oauth = FakeOAuth()
    clock = [1_000.0]
    service = _service(tmp_path, oauth, clock)
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(expires_at=1_301), expected_generation=0)

    token = await service.get_token()

    assert oauth.refresh_calls == 0
    assert token.access_token == "access-secret"
    assert token.generation == 1


@pytest.mark.asyncio
async def test_token_at_exact_300_second_boundary_is_refreshed(tmp_path: Path) -> None:
    oauth = FakeOAuth()
    clock = [1_000.0]
    service = _service(tmp_path, oauth, clock)
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(expires_at=1_300), expected_generation=0)

    token = await service.get_token()

    assert oauth.refresh_calls == 1
    assert token.access_token == "refreshed-access"


@pytest.mark.asyncio
async def test_expired_token_is_refreshed(tmp_path: Path) -> None:
    oauth = FakeOAuth()
    clock = [1_000.0]
    service = _service(tmp_path, oauth, clock)
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(expires_at=999), expected_generation=0)

    token = await service.get_token()

    assert oauth.refresh_calls == 1
    assert token.access_token == "refreshed-access"
    assert token.expires_at == 1_000 + 3_600
    assert store.load_credentials() is not None
    assert store.current_generation() == 2


@pytest.mark.asyncio
async def test_missing_credentials_require_authentication(tmp_path: Path) -> None:
    oauth = FakeOAuth()
    service = _service(tmp_path, oauth, [1_000.0])

    with pytest.raises(CodexAuthError) as exc_info:
        await service.get_token()

    assert exc_info.value.code == "authentication_required"
    assert exc_info.value.http_status == 401
    assert oauth.refresh_calls == 0


@pytest.mark.asyncio
async def test_rejected_refresh_fails_fast_until_cooldown_elapses(tmp_path: Path) -> None:
    oauth = FakeOAuth()
    clock = [1_000.0]
    service = _service(tmp_path, oauth, clock)
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials(expires_at=1_200), expected_generation=0)
    oauth.error = CodexAuthError(
        "token_refresh_rejected",
        "Codex sign-in could not be renewed. Sign in to Codex again.",
        401,
    )

    with pytest.raises(CodexAuthError) as first:
        await service.get_token()
    assert first.value.code == "token_refresh_rejected"

    with pytest.raises(CodexAuthError) as second:
        await service.get_token()
    assert second.value.code == "authentication_required"
    assert oauth.refresh_calls == 1

    clock[0] = 1_000.0 + CODE_AUTH_FAILURE_COOLDOWN_S + 1
    oauth.error = None
    token = await service.get_token()

    assert oauth.refresh_calls == 2
    assert token.access_token == "refreshed-access"
