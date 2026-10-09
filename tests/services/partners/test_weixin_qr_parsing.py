"""Pure parsing contract of the personal-WeChat QR login exchange.

``deeptutor/partners/channels/weixin_qr.py`` is deliberately stateless: it
never opens a socket, so everything worth pinning down is what its pure
helpers do with local fixture payloads — the dataclasses the rest of the code
passes around, the unauthenticated header set, host normalisation for
mid-flight redirects, the status-payload reader, and which poll errors are
worth retrying. None of that needs WeChat, a login, or even a mock transport.
"""

from __future__ import annotations

import base64
import dataclasses

import httpx
import pytest

from deeptutor.partners.channels.weixin_qr import (
    QrCode,
    QrOutcome,
    interpret_status,
    is_retryable_poll_error,
    normalize_host,
    qr_headers,
)

# ---- the value objects -------------------------------------------------------


def test_a_qr_code_carries_the_poll_id_and_what_to_draw() -> None:
    code = QrCode(qrcode_id="qr-1", scan_payload="scan-me")

    assert code.qrcode_id == "qr-1"
    assert code.scan_payload == "scan-me"


def test_qr_code_is_immutable() -> None:
    code = QrCode(qrcode_id="qr-1", scan_payload="scan-me")

    with pytest.raises(dataclasses.FrozenInstanceError):
        code.qrcode_id = "qr-2"  # type: ignore[misc]


def test_an_outcome_defaults_to_an_empty_non_answer() -> None:
    outcome = QrOutcome(status="waiting")

    assert outcome.status == "waiting"
    assert outcome.token == ""
    assert outcome.base_url == ""
    assert outcome.poll_base_url == ""
    assert outcome.bot_id == ""
    assert outcome.user_id == ""


def test_an_outcome_is_immutable() -> None:
    outcome = QrOutcome(status="confirmed", token="t")

    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.token = "t2"  # type: ignore[misc]


# ---- the unauthenticated header set ------------------------------------------


def test_qr_headers_carry_the_fixed_ilink_identity() -> None:
    headers = qr_headers(client_version=1068)

    assert headers["Content-Type"] == "application/json"
    assert headers["AuthorizationType"] == "ilink_bot_token"
    assert headers["iLink-App-Id"] == "bot"
    assert headers["iLink-App-ClientVersion"] == "1068"


def test_qr_headers_never_carry_an_authorization_token() -> None:
    """Obtaining the token is the point of these calls."""
    headers = qr_headers(client_version=1)

    assert not any(k.lower() == "authorization" for k in headers)


@pytest.mark.parametrize("uin", [qr_headers(client_version=1)["X-WECHAT-UIN"] for _ in range(5)])
def test_the_wechat_uin_is_base64_of_a_decimal_uint32(uin: str) -> None:
    decoded = base64.b64decode(uin).decode("ascii")

    assert decoded.isdigit()
    assert int(decoded) < 2**32


def test_a_route_tag_is_included_trimmed() -> None:
    headers = qr_headers(client_version=1, route_tag="  edge-7  ")

    assert headers["SKRouteTag"] == "edge-7"


@pytest.mark.parametrize("route_tag", ["", "   "])
def test_a_blank_route_tag_omits_the_header(route_tag: str) -> None:
    headers = qr_headers(client_version=1, route_tag=route_tag)

    assert "SKRouteTag" not in headers


def test_no_route_tag_omits_the_header() -> None:
    assert "SKRouteTag" not in qr_headers(client_version=1)


# ---- redirect host normalisation ---------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", ""),
        ("   ", ""),
        ("host.qq.com", "https://host.qq.com"),
        ("  host.qq.com  ", "https://host.qq.com"),
        ("host.qq.com/edge", "https://host.qq.com/edge"),
        ("https://host.qq.com", "https://host.qq.com"),
        ("http://host.qq.com", "http://host.qq.com"),
        (" https://host.qq.com ", "https://host.qq.com"),
    ],
)
def test_normalize_host(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


# ---- reading one status payload ----------------------------------------------


@pytest.mark.parametrize("payload", [None, 123, "not a dict", ["wait"], True])
def test_a_non_mapping_payload_is_never_a_verdict(payload: object) -> None:
    assert interpret_status(payload) == QrOutcome(status="unknown")


@pytest.mark.parametrize("payload", [{}, {"status": ""}, {"status": None}])
def test_a_missing_or_empty_status_keeps_polling(payload: dict) -> None:
    assert interpret_status(payload) == QrOutcome(status="unknown")


def test_a_status_string_from_the_future_is_unknown_not_expired() -> None:
    """An unrecognised status must not end a login that is still live."""
    assert interpret_status({"status": "something_new"}) == QrOutcome(status="unknown")


def test_the_vocabulary_is_matched_exactly() -> None:
    assert interpret_status({"status": "Wait"}).status == "unknown"
    assert interpret_status({"status": "CONFIRMED"}).status == "unknown"


def test_wait_and_expired_map_one_to_one() -> None:
    assert interpret_status({"status": "wait"}) == QrOutcome(status="waiting")
    assert interpret_status({"status": "expired"}) == QrOutcome(status="expired")


def test_a_confirmed_payload_is_read_in_full() -> None:
    outcome = interpret_status(
        {
            "status": "confirmed",
            "bot_token": "bot-token-1",
            "baseurl": "https://edge.weixin.qq.com",
            "ilink_bot_id": "bot-1",
            "ilink_user_id": "user-1",
            "unrelated": "ignored",
        }
    )

    assert outcome.status == "confirmed"
    assert outcome.token == "bot-token-1"
    assert outcome.base_url == "https://edge.weixin.qq.com"
    assert outcome.bot_id == "bot-1"
    assert outcome.user_id == "user-1"


def test_a_confirmed_payload_without_the_optional_fields_yields_empty_strings() -> None:
    outcome = interpret_status({"status": "confirmed", "bot_token": "t"})

    assert outcome.base_url == ""
    assert outcome.bot_id == ""
    assert outcome.user_id == ""


@pytest.mark.parametrize("token", [None, ""])
def test_a_confirmation_without_a_token_is_a_failure_not_a_success(token: str) -> None:
    """Trusting ``status`` alone would store an empty token and fail later."""
    outcome = interpret_status({"status": "confirmed", "bot_token": token})

    assert outcome.status == "error"
    assert outcome.token == ""


@pytest.mark.parametrize(
    "raw,token",
    [("t", "t"), (12345, "12345"), ("   ", "   ")],
)
def test_any_truthy_token_value_is_accepted_verbatim(raw: object, token: str) -> None:
    outcome = interpret_status({"status": "confirmed", "bot_token": raw})

    assert outcome.status == "confirmed"
    assert outcome.token == token


def test_a_redirect_is_a_scan_in_progress_carrying_a_normalised_host() -> None:
    outcome = interpret_status(
        {"status": "scaned_but_redirect", "redirect_host": "other.weixin.qq.com"}
    )

    assert outcome.status == "scanned"
    assert outcome.poll_base_url == "https://other.weixin.qq.com"


@pytest.mark.parametrize("host", [None, "", "   "])
def test_a_redirect_without_a_usable_host_polls_nowhere_new(host: str) -> None:
    outcome = interpret_status({"status": "scaned_but_redirect", "redirect_host": host})

    assert outcome.status == "scanned"
    assert outcome.poll_base_url == ""


def test_a_redirect_host_with_a_scheme_is_kept_as_is() -> None:
    outcome = interpret_status(
        {"status": "scaned_but_redirect", "redirect_host": "http://other.weixin.qq.com"}
    )

    assert outcome.poll_base_url == "http://other.weixin.qq.com"


# ---- which poll failures are worth another try --------------------------------


def _status_error(code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        f"{code}", request=httpx.Request("GET", "https://x"), response=httpx.Response(code)
    )


@pytest.mark.parametrize(
    "err",
    [
        httpx.ReadTimeout("x"),
        httpx.ConnectTimeout("x"),
        httpx.ConnectError("x"),
        _status_error(500),
        _status_error(503),
    ],
)
def test_transport_hiccups_and_5xx_are_retryable(err: Exception) -> None:
    assert is_retryable_poll_error(err) is True


@pytest.mark.parametrize(
    "err",
    [
        _status_error(400),
        _status_error(403),
        _status_error(429),
        ValueError("not a transport problem at all"),
    ],
)
def test_verdicts_and_unrelated_errors_are_not_retryable(err: Exception) -> None:
    """A 429 is WeChat answering, not the wire failing: it is a verdict."""
    assert is_retryable_poll_error(err) is False


def test_a_status_error_without_a_response_is_not_retryable() -> None:
    err = httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=None)

    assert is_retryable_poll_error(err) is False
