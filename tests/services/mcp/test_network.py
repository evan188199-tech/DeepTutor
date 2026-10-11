"""MCP network guard: what a remote-server URL may resolve to, and when.

Remote transports point the app process at a URL a configuration supplies, so
the guard is the one place a bad target must die before a socket is opened.
These tests pin the verdicts with a fake resolver — no DNS is ever queried —
covering the deployment vs self-service postures, the admin-approved private
origin exception, and the origin strings the approval compares.
"""

from __future__ import annotations

import asyncio
import socket as socket_module

import pytest

from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
import deeptutor.services.mcp.network as network
from deeptutor.services.mcp.network import (
    approved_private_origin,
    mcp_origin,
    validate_mcp_url,
    validate_mcp_url_async,
)

FAKE_ADDRESSES = {
    "public.test": "93.184.216.34",
    "metadata.test": "169.254.169.254",
    "mapped-metadata.test": "::ffff:169.254.169.254",
    "linklocal-v6.test": "fe80::1",
    "thisnet.test": "0.0.0.1",
    "ec2-v6.test": "fd00:ec2::254",
    "alibaba.test": "100.100.100.200",
    "loopback.test": "127.0.0.1",
    "rfc1918a.test": "10.1.2.3",
    "rfc1918b.test": "172.16.5.4",
    "rfc1918c.test": "192.168.1.1",
    "cgnat.test": "100.64.0.1",
    "ula.test": "fd00::1",
    "loopback-v6.test": "::1",
}


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Serve canned answers instead of touching a real resolver."""

    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        addr = FAKE_ADDRESSES.get(host)
        if addr is None:
            raise socket_module.gaierror(socket_module.EAI_NONAME, "Name or service not known")
        return [(socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", (addr, 0))]

    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    return FAKE_ADDRESSES


@pytest.fixture
def resolver_with_records(monkeypatch: pytest.MonkeyPatch):
    """Let a test supply raw getaddrinfo entries per host."""

    def install(table: dict[str, list[tuple]]) -> None:
        def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
            if host not in table:
                raise socket_module.gaierror(socket_module.EAI_NONAME, "Name or service not known")
            return table[host]

        monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)

    return install


# ── URL structure: what can never be a remote MCP server ─────────────────


def test_only_http_and_https_schemes_are_accepted() -> None:
    ok, error = validate_mcp_url("ftp://public.test/mcp")
    assert not ok and "Only http/https" in error
    ok, error = validate_mcp_url("file:///etc/hosts")
    assert not ok and "Only http/https" in error
    ok, error = validate_mcp_url("public.test/mcp")
    assert not ok and "Only http/https" in error


def test_an_invalid_port_is_rejected() -> None:
    ok, error = validate_mcp_url("http://public.test:notaport/mcp")
    assert not ok and error


def test_a_url_without_hostname_is_rejected() -> None:
    ok, error = validate_mcp_url("http:///path")
    assert not ok and "Missing hostname" in error


def test_embedded_credentials_and_fragments_are_rejected() -> None:
    for url in (
        "http://user:secret@public.test/mcp",
        "http://user@public.test/mcp",
        "http://public.test/mcp#section",
    ):
        ok, error = validate_mcp_url(url)
        assert not ok and "credentials or fragments" in error, url


# ── DNS resolution failures and unusable records ──────────────────────────


def test_an_unresolvable_hostname_is_rejected(resolver: dict[str, str]) -> None:
    ok, error = validate_mcp_url("https://nowhere.test/mcp")
    assert not ok and "Cannot resolve hostname" in error


def test_records_without_addresses_leave_nothing_usable(
    resolver_with_records,
) -> None:
    resolver_with_records({"odd.test": [(2, 1, 6, "", ("not-an-address", 0))]})
    ok, error = validate_mcp_url("http://odd.test/mcp")
    assert not ok and "No usable address" in error


def test_unparseable_records_are_skipped_and_good_ones_still_count(
    resolver_with_records,
) -> None:
    resolver_with_records(
        {
            "mixed.test": [
                (2, 1, 6, "", ("still-not-an-address", 0)),
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
        }
    )
    ok, error = validate_mcp_url("http://mixed.test/mcp", strict=True)
    assert ok and not error


# ── deployment posture: accidental damage only ────────────────────────────


def test_deployment_servers_may_sit_on_loopback_or_the_lan(
    resolver: dict[str, str],
) -> None:
    for host in ("loopback.test", "rfc1918a.test", "rfc1918b.test", "rfc1918c.test"):
        ok, error = validate_mcp_url(f"http://{host}:8080/mcp")
        assert ok and not error, host


@pytest.mark.parametrize(
    "host",
    ["metadata.test", "mapped-metadata.test", "linklocal-v6.test", "thisnet.test"],
)
def test_deployment_guard_still_blocks_metadata_and_this_network(
    resolver: dict[str, str], host: str
) -> None:
    ok, error = validate_mcp_url(f"http://{host}/mcp")
    assert not ok and "link-local/metadata" in error, host


def test_vendor_metadata_ranges_are_blocked_in_both_stacks(
    resolver: dict[str, str],
) -> None:
    for host, port in (("ec2-v6.test", 8080), ("alibaba.test", 8080)):
        ok, error = validate_mcp_url(f"http://{host}:{port}/mcp")
        assert not ok and "link-local/metadata" in error, host


def test_ipv6_mapped_ipv4_addresses_are_judged_as_ipv4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ::ffff:10.0.0.1 is a LAN address in disguise; strict must still refuse it.
    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        return [(socket_module.AF_INET6, socket_module.SOCK_STREAM, 6, "", ("::ffff:10.0.0.1", 0))]

    monkeypatch.setattr(network.socket, "getaddrinfo", fake_getaddrinfo)
    ok, error = validate_mcp_url("http://mapped-lan.test/mcp", strict=True)
    assert not ok and "public internet" in error


# ── self-service posture: nothing may point inward ────────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "loopback.test",
        "rfc1918a.test",
        "rfc1918b.test",
        "rfc1918c.test",
        "cgnat.test",
        "ula.test",
        "loopback-v6.test",
    ],
)
def test_self_service_rejects_loopback_and_private_ranges(
    resolver: dict[str, str], host: str
) -> None:
    ok, error = validate_mcp_url(f"http://{host}:8080/mcp", strict=True)
    assert not ok and "public internet" in error, host


def test_strict_posture_keeps_every_deployment_block(
    resolver: dict[str, str],
) -> None:
    ok, error = validate_mcp_url("http://metadata.test/mcp", strict=True)
    assert not ok and "public internet" in error


# ── the admin-approved private-origin exception ───────────────────────────


def test_approval_grants_rfc1918_only_for_the_exact_approved_origin(
    resolver: dict[str, str],
) -> None:
    url = "http://rfc1918a.test:8080/mcp"
    ok, error = validate_mcp_url(url, strict=True)
    assert not ok
    trusted = mcp_origin(url)
    ok, error = validate_mcp_url(url, strict=True, trusted_origin=trusted)
    assert ok and not error


@pytest.mark.parametrize("host", ["metadata.test", "loopback.test", "cgnat.test"])
def test_approval_never_unlocks_metadata_loopback_or_cgnat(
    resolver: dict[str, str], host: str
) -> None:
    url = f"http://{host}:8080/mcp"
    ok, _ = validate_mcp_url(url, strict=True, trusted_origin=mcp_origin(url))
    assert not ok


def test_a_trusted_origin_does_not_transfer_to_another_host_or_port(
    resolver: dict[str, str],
) -> None:
    trusted = mcp_origin("http://rfc1918a.test:8080/mcp")
    for url in ("http://rfc1918b.test:8080/mcp", "http://rfc1918a.test:9090/mcp"):
        ok, error = validate_mcp_url(url, strict=True, trusted_origin=trusted)
        assert not ok and "public internet" in error, url


def test_embedded_credentials_are_refused_before_origin_matching_is_consulted(
    resolver: dict[str, str],
) -> None:
    url = "http://user:secret@rfc1918a.test:8080/mcp"
    trusted = "http://rfc1918a.test:8080"
    ok, error = validate_mcp_url(url, strict=True, trusted_origin=trusted)
    assert not ok and "credentials or fragments" in error


# ── origin strings the approval compares ──────────────────────────────────


def test_origins_default_to_the_scheme_port() -> None:
    assert mcp_origin("http://public.test/mcp") == "http://public.test:80"
    assert mcp_origin("https://public.test/mcp") == "https://public.test:443"


def test_explicit_ports_are_kept_in_the_origin() -> None:
    assert mcp_origin("https://public.test:8443/mcp") == "https://public.test:8443"


def test_origin_host_is_casefolded_and_trailing_dots_stripped() -> None:
    assert mcp_origin("http://Example.COM./mcp") == "http://example.com:80"


def test_ipv6_hosts_are_bracketed_in_the_origin() -> None:
    assert mcp_origin("http://[2001:db8::1]:8080/mcp") == "http://[2001:db8::1]:8080"


def test_non_server_urls_cannot_form_an_origin() -> None:
    for url in (
        "ftp://public.test/mcp",
        "not a url",
        "http://user:secret@public.test/mcp",
    ):
        with pytest.raises(ValueError):
            mcp_origin(url)


# ── the registry of approved private origins ──────────────────────────────


def _config(*servers: MCPServerConfig) -> MCPConfig:
    return MCPConfig(servers={f"srv{i}": server for i, server in enumerate(servers)})


def test_approval_matches_a_flagged_remote_server_on_its_exact_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = MCPServerConfig(url="http://rfc1918a.test:8080/mcp", allow_private_network=True)
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: _config(cfg))
    assert approved_private_origin("http://rfc1918a.test:8080/other") == (
        "http://rfc1918a.test:8080"
    )


def test_approval_ignores_servers_without_the_private_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = MCPServerConfig(url="http://rfc1918a.test:8080/mcp")
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: _config(cfg))
    assert approved_private_origin("http://rfc1918a.test:8080/mcp") is None


def test_approval_ignores_non_http_transports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = MCPServerConfig(command="some-mcp", allow_private_network=True)
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: _config(cfg))
    assert approved_private_origin("http://rfc1918a.test:8080/mcp") is None


def test_approval_requires_the_same_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = MCPServerConfig(url="http://rfc1918a.test:8080/mcp", allow_private_network=True)
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: _config(cfg))
    assert approved_private_origin("http://rfc1918a.test:9090/mcp") is None


def test_approval_skips_registry_entries_with_unusable_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = MCPServerConfig(url="", type="sse", allow_private_network=True)
    good = MCPServerConfig(url="http://rfc1918a.test:8080/mcp", allow_private_network=True)
    monkeypatch.setattr(
        "deeptutor.services.mcp.config.load_mcp_config", lambda: _config(broken, good)
    )
    assert approved_private_origin("http://rfc1918a.test:8080/mcp") == ("http://rfc1918a.test:8080")


def test_an_empty_registry_approves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: _config())
    assert approved_private_origin("http://rfc1918a.test:8080/mcp") is None


# ── the async wrapper ─────────────────────────────────────────────────────


def test_async_validation_matches_the_sync_verdict(resolver: dict[str, str]) -> None:
    ok, error = asyncio.run(validate_mcp_url_async("http://public.test/mcp", strict=True))
    assert ok and not error
    ok, error = asyncio.run(validate_mcp_url_async("http://metadata.test/mcp", strict=True))
    assert not ok and "public internet" in error


def test_async_validation_reports_resolution_failures(
    resolver: dict[str, str],
) -> None:
    ok, error = asyncio.run(validate_mcp_url_async("https://nowhere.test/mcp"))
    assert not ok and "Cannot resolve hostname" in error
