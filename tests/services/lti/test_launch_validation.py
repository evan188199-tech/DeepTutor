"""Resource link launch (/api/lti/launch) validation."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from deeptutor.services.lti import LtiError, LtiService

from .conftest import (
    CLIENT_ID,
    DEPLOYMENT_ID,
    ISSUER,
    LEARNER_ROLE,
    REDIRECT_URI,
    TARGET_LINK_URI,
    make_id_token,
)


def _pending(service) -> tuple[str, str]:
    """Run a login init and return (state, nonce) issued for it."""
    result = service.begin_login(
        {"iss": ISSUER, "login_hint": "u1", "target_link_uri": TARGET_LINK_URI},
        redirect_uri=REDIRECT_URI,
    )
    query = {k: v[-1] for k, v in parse_qs(urlsplit(result.redirect_url).query).items()}
    return result.state, query["nonce"]


async def _launch(service, idp_key, **token_kwargs) -> None:
    state, nonce = _pending(service)
    token = make_id_token(idp_key, nonce=nonce, **token_kwargs)
    await service.complete_launch({"state": state, "id_token": token})


@pytest.mark.asyncio
async def test_launch_happy_path_returns_verified_claims(service, idp_key) -> None:
    state, nonce = _pending(service)
    token = make_id_token(idp_key, nonce=nonce, sub="student-42", roles=[LEARNER_ROLE])
    result = await service.complete_launch({"state": state, "id_token": token})

    assert result.platform.issuer == ISSUER
    assert result.sub == "student-42"
    assert result.claims["aud"] == CLIENT_ID
    assert result.roles == (LEARNER_ROLE,)


@pytest.mark.asyncio
async def test_launch_rejects_unknown_state(service, idp_key) -> None:
    token = make_id_token(idp_key, nonce="any")
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": "forged-state", "id_token": token})
    assert excinfo.value.code == "invalid_state"


@pytest.mark.asyncio
async def test_launch_state_is_single_use(service, idp_key) -> None:
    state, nonce = _pending(service)
    token = make_id_token(idp_key, nonce=nonce)
    first = await service.complete_launch({"state": state, "id_token": token})
    assert first.sub

    replay = make_id_token(idp_key, nonce=nonce)
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": state, "id_token": replay})
    assert excinfo.value.code == "invalid_state"


@pytest.mark.asyncio
async def test_launch_rejects_expired_state(idp_key) -> None:
    now = {"t": 1000.0}
    from deeptutor.services.lti import LtiPlatform

    from .conftest import AUTH_LOGIN_URL, jwk_for_key

    service = LtiService(
        platforms=[
            LtiPlatform(
                issuer=ISSUER,
                client_id=CLIENT_ID,
                deployment_ids=frozenset({DEPLOYMENT_ID}),
                auth_login_url=AUTH_LOGIN_URL,
                target_link_uri=TARGET_LINK_URI,
                key_set={"keys": [jwk_for_key(idp_key)]},
            )
        ],
        state_ttl_seconds=60,
        clock=lambda: now["t"],
    )
    state, nonce = _pending(service)
    now["t"] += 61

    token = make_id_token(idp_key, nonce=nonce)
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": state, "id_token": token})
    assert excinfo.value.code == "invalid_state"


@pytest.mark.asyncio
async def test_launch_rejects_signature_forged_with_known_kid(service, idp_key) -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    state, nonce = _pending(service)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # Same kid as the registered platform key, different private key.
    token = make_id_token(attacker_key, nonce=nonce)
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": state, "id_token": token})
    assert excinfo.value.code == "invalid_id_token"


@pytest.mark.asyncio
async def test_launch_rejects_unknown_signing_key(service, idp_key) -> None:
    state, nonce = _pending(service)
    token = make_id_token(idp_key, nonce=nonce, kid="key-never-registered")
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": state, "id_token": token})
    assert excinfo.value.code == "unknown_signing_key"


@pytest.mark.asyncio
async def test_launch_rejects_wrong_issuer_claim(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, iss="https://other-lms.example.edu")
    assert excinfo.value.code == "invalid_id_token"


@pytest.mark.asyncio
async def test_launch_rejects_wrong_audience_claim(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, aud="someone-elses-client")
    assert excinfo.value.code == "invalid_id_token"


@pytest.mark.asyncio
async def test_launch_rejects_expired_token(service, idp_key) -> None:
    import time

    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, exp=int(time.time()) - 3600)
    assert excinfo.value.code == "invalid_id_token"


@pytest.mark.asyncio
async def test_launch_rejects_nonce_mismatch(service, idp_key) -> None:
    state, _ = _pending(service)
    token = make_id_token(idp_key, nonce="not-the-issued-nonce")
    with pytest.raises(LtiError) as excinfo:
        await service.complete_launch({"state": state, "id_token": token})
    assert excinfo.value.code == "nonce_mismatch"


@pytest.mark.asyncio
async def test_launch_rejects_unregistered_deployment(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, deployment_id="deployment-not-registered")
    assert excinfo.value.code == "unregistered_deployment"


@pytest.mark.asyncio
async def test_launch_rejects_deep_linking_message(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, message_type="LtiDeepLinkingRequest")
    assert excinfo.value.code == "unsupported_message"


@pytest.mark.asyncio
async def test_launch_requires_resource_link_claim(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, resource_link={})
    assert excinfo.value.code == "unsupported_message"


@pytest.mark.asyncio
async def test_launch_rejects_target_link_uri_mismatch(service, idp_key) -> None:
    with pytest.raises(LtiError) as excinfo:
        await _launch(service, idp_key, target_link_uri="https://evil.example.edu/app")
    assert excinfo.value.code == "target_link_uri_mismatch"
