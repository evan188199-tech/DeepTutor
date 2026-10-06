"""Contract tests for deeptutor.partners.network.validate_url_target.

Locks the channel-shared SSRF guard: scheme/host gating, DNS-failure and
timeout semantics, blocked-address matrix, and loopback exceptions. All DNS
resolution is faked — no real network requests are ever made.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from deeptutor.partners.network import validate_url_target

_ADDR_INFOS = [
    ("0.0.0.1", "0.0.0.0/8"),
    ("10.1.2.3", "10.0.0.0/8"),
    ("100.64.0.1", "100.64.0.0/10"),
    ("127.0.0.1", "127.0.0.0/8"),
    ("169.254.169.254", "169.254.0.0/16"),
    ("172.16.0.1", "172.16.0.0/12"),
    ("192.168.1.1", "192.168.0.0/16"),
    ("::1", "::1/128"),
    ("fc00::1", "fc00::/7"),
    ("fe80::1", "fe80::/10"),
]


def _fake_resolve(monkeypatch, addresses):
    """Stub socket.getaddrinfo to return the given address strings."""
    calls: list[str] = []

    def fake_getaddrinfo(host, *args, **kwargs):
        calls.append(host)
        return [
            (
                (socket.AF_INET6 if ":" in addr else socket.AF_INET),
                socket.SOCK_STREAM,
                6,
                "",
                (addr, 0),
            )
            for addr in addresses
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return calls


def test_public_hostname_resolving_to_public_ip_is_allowed(monkeypatch) -> None:
    calls = _fake_resolve(monkeypatch, ["93.184.216.34"])
    ok, err = validate_url_target("https://example.com/media/img.png")
    assert ok is True
    assert err == ""
    assert calls == ["example.com"]


def test_dns_resolution_failure_maps_to_failed_result(monkeypatch) -> None:
    def failing_getaddrinfo(*args, **kwargs):
        raise socket.gaierror(8, "nodename nor servname provided")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    ok, err = validate_url_target("http://example.invalid/media.jpg")
    assert ok is False
    assert err == "Cannot resolve hostname: example.invalid"


def test_dns_failure_is_attempted_exactly_once(monkeypatch) -> None:
    attempts = 0

    def failing_getaddrinfo(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    ok, err = validate_url_target("http://down.example/media.jpg")
    assert ok is False
    assert attempts == 1


def test_dns_timeout_is_not_swallowed_into_failed_result(monkeypatch) -> None:
    attempts = 0

    def timing_out_getaddrinfo(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise socket.timeout("resolution timed out")

    monkeypatch.setattr(socket, "getaddrinfo", timing_out_getaddrinfo)
    with pytest.raises(socket.timeout):
        validate_url_target("http://slow.example/media.jpg")
    assert attempts == 1


def test_unparseable_url_wraps_parser_error() -> None:
    ok, err = validate_url_target("http://[::1/media.jpg")
    assert ok is False
    assert err == "Invalid IPv6 URL"


def test_non_http_scheme_rejected_before_dns(monkeypatch) -> None:
    calls = _fake_resolve(monkeypatch, ["93.184.216.34"])
    ok, err = validate_url_target("ftp://example.com/file")
    assert ok is False
    assert err == "Only http/https allowed, got 'ftp'"
    assert calls == []


def test_missing_domain_rejected_before_dns(monkeypatch) -> None:
    calls = _fake_resolve(monkeypatch, ["93.184.216.34"])
    ok, err = validate_url_target("http:///media.jpg")
    assert ok is False
    assert err == "Missing domain"
    assert calls == []


def test_missing_hostname_rejected_before_dns(monkeypatch) -> None:
    calls = _fake_resolve(monkeypatch, ["93.184.216.34"])
    ok, err = validate_url_target("http://:8080/media.jpg")
    assert ok is False
    assert err == "Missing hostname"
    assert calls == []


@pytest.mark.parametrize(
    ("resolved", "blocked_net"),
    _ADDR_INFOS,
    ids=[addr for addr, _ in _ADDR_INFOS],
)
def test_private_and_internal_targets_are_blocked(
    monkeypatch, resolved: str, blocked_net: str
) -> None:
    _fake_resolve(monkeypatch, [resolved])
    ok, err = validate_url_target("http://host.example/media.jpg")
    assert ipaddress.ip_address(resolved) in ipaddress.ip_network(blocked_net)
    assert ok is False
    assert "private/internal address" in err
    assert resolved in err


def test_ipv6_mapped_ipv4_private_target_is_blocked(monkeypatch) -> None:
    _fake_resolve(monkeypatch, ["::ffff:192.168.0.9"])
    ok, err = validate_url_target("http://host.example/media.jpg")
    assert ok is False
    assert "192.168.0.9" in err


def test_allow_loopback_permits_localhost_when_all_addrs_loopback(
    monkeypatch,
) -> None:
    _fake_resolve(monkeypatch, ["127.0.0.1"])
    ok, err = validate_url_target("http://localhost/media.jpg", allow_loopback=True)
    assert ok is True
    assert err == ""


def test_allow_loopback_blocks_mixed_loopback_and_private(monkeypatch) -> None:
    _fake_resolve(monkeypatch, ["127.0.0.1", "10.0.0.5"])
    ok, err = validate_url_target("http://localhost/media.jpg", allow_loopback=True)
    assert ok is False
    assert "private/internal address" in err


def test_allow_loopback_rejects_public_names_resolving_to_loopback(
    monkeypatch,
) -> None:
    _fake_resolve(monkeypatch, ["127.0.0.1"])
    ok, err = validate_url_target("http://internal.example/media.jpg", allow_loopback=True)
    assert ok is False
    assert "private/internal address" in err


def test_unparseable_dns_entries_are_skipped_not_fatal(monkeypatch) -> None:
    calls = _fake_resolve(monkeypatch, ["not-an-ip-addr", "2001:4860:4860::8888"])
    ok, err = validate_url_target("http://host.example/media.jpg")
    assert len(calls) == 1
    assert ok is True
    assert err == ""


def test_unparseable_dns_entries_do_not_mask_private_blocks(monkeypatch) -> None:
    _fake_resolve(monkeypatch, ["not-an-ip-addr", "10.9.9.9"])
    ok, err = validate_url_target("http://host.example/media.jpg")
    assert ok is False
    assert "10.9.9.9" in err
