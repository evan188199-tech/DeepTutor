"""OIDC third-party initiated login (/api/lti/login) validation."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from deeptutor.services.lti import LtiError

from .conftest import (
    AUTH_LOGIN_URL,
    CLIENT_ID,
    ISSUER,
    REDIRECT_URI,
    TARGET_LINK_URI,
)


def _query(url: str) -> dict[str, str]:
    return {k: v[-1] for k, v in parse_qs(urlsplit(url).query).items()}


def test_login_init_redirects_to_platform_auth_url(service, login_result) -> None:
    split = urlsplit(login_result.redirect_url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == AUTH_LOGIN_URL

    query = _query(login_result.redirect_url)
    assert query["scope"] == "openid"
    assert query["response_type"] == "id_token"
    assert query["response_mode"] == "form_post"
    assert query["prompt"] == "none"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["login_hint"] == "lms-user-1"
    assert query["lti_message_hint"] == "course-message-hint"
    assert len(query["state"]) >= 32
    assert len(query["nonce"]) >= 32
    assert query["state"] != query["nonce"]


def test_login_init_states_are_unique_per_request(service) -> None:
    params = {
        "iss": ISSUER,
        "login_hint": "lms-user-1",
        "target_link_uri": TARGET_LINK_URI,
    }
    first = service.begin_login(params, redirect_uri=REDIRECT_URI)
    second = service.begin_login(params, redirect_uri=REDIRECT_URI)
    assert first.state != second.state
    assert _query(first.redirect_url)["nonce"] != _query(second.redirect_url)["nonce"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://unknown-lms.example.edu"},
        {"client_id": "other-client"},
        {"target_link_uri": "https://evil.example.edu/app"},
        {"login_hint": ""},
    ],
)
def test_login_init_rejects_malformed_requests(service, overrides) -> None:
    params = {
        "iss": ISSUER,
        "login_hint": "lms-user-1",
        "target_link_uri": TARGET_LINK_URI,
        "client_id": CLIENT_ID,
    }
    params.update(overrides)
    with pytest.raises(LtiError) as excinfo:
        service.begin_login(params, redirect_uri=REDIRECT_URI)
    assert excinfo.value.status_code == 400


def test_login_init_rejects_unregistered_deployment(service) -> None:
    with pytest.raises(LtiError) as excinfo:
        service.begin_login(
            {
                "iss": ISSUER,
                "login_hint": "lms-user-1",
                "target_link_uri": TARGET_LINK_URI,
                "lti_deployment_id": "deployment-not-registered",
            },
            redirect_uri=REDIRECT_URI,
        )
    assert excinfo.value.code == "unregistered_deployment"


def test_login_init_rejects_non_http_redirect_uri(service) -> None:
    with pytest.raises(LtiError):
        service.begin_login(
            {"iss": ISSUER, "login_hint": "u1", "target_link_uri": TARGET_LINK_URI},
            redirect_uri="javascript:alert(1)",
        )


def test_disabled_service_is_not_enabled() -> None:
    from deeptutor.services.lti import LtiService

    assert LtiService(platforms=[]).enabled is False
