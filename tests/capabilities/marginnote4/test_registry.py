"""Tests for owner-scoped MarginNote device registration."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from deeptutor.capabilities.marginnote4.registry import (
    ActiveDeviceError,
    MarginNoteDeviceRegistry,
    PairingCodeError,
)


def _registry(tmp_path: Path) -> MarginNoteDeviceRegistry:
    return MarginNoteDeviceRegistry(tmp_path / "registry.db")


def _code(registry: MarginNoteDeviceRegistry, kb: str = "library") -> str:
    return registry.create_pairing_code(
        owner_id="u_alice",
        kb_name=kb,
        workspace_root="/tmp/alice-workspace",
    ).code


def test_pairing_code_claims_once_and_token_authenticates(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    code = _code(registry)
    device, token = registry.claim(code, device_name="MacBook")
    assert device.owner_id == "u_alice"
    assert device.kb_name == "library"
    assert registry.authenticate(token).device_id == device.device_id

    with pytest.raises(PairingCodeError):
        registry.claim(code)


def test_second_active_device_is_rejected_until_revoked(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first, first_token = registry.claim(_code(registry))
    with pytest.raises(ActiveDeviceError):
        registry.claim(_code(registry))

    revoked = registry.revoke(
        owner_id="u_alice",
        device_id=first.device_id,
        workspace_root="/tmp/alice-workspace",
    )
    assert revoked.active is False
    with pytest.raises(PermissionError):
        registry.authenticate(first_token)

    second, _ = registry.claim(_code(registry))
    assert second.device_id != first.device_id


def test_scoped_listing_does_not_cross_owners(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    alice = registry.claim(_code(registry))
    registry.create_pairing_code(
        owner_id="u_bob", kb_name="library", workspace_root="/tmp/bob-workspace"
    )
    devices = registry.list_devices(
        owner_id="u_alice", kb_name="library", workspace_root="/tmp/alice-workspace"
    )
    assert [device.device_id for device in devices] == [alice[0].device_id]


def test_expired_code_cannot_claim(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    code = registry.create_pairing_code(
        owner_id="u_alice",
        kb_name="library",
        workspace_root="/tmp/alice-workspace",
        ttl_seconds=60,
    ).code
    with sqlite3.connect(registry.db_path) as conn:
        conn.execute("UPDATE mn4_pairing_codes SET expires_at='2000-01-01T00:00:00+00:00'")
    with pytest.raises(PairingCodeError):
        registry.claim(code)
