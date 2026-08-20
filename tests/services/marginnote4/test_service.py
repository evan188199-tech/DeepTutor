from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.marginnote4.service import (
    MarginNote4Service,
    OperationConflict,
    UnauthorizedDevice,
)


def _pair(service: MarginNote4Service, user_id: str, library_id: str) -> tuple[str, dict]:
    session, code = service.create_pairing_session(
        user_id=user_id,
        library_id=library_id,
        library_name=f"Library {library_id}",
    )
    claim = service.claim_pairing_session(
        pairing_code=code,
        device_name="Test Mac",
        device_kind="macos",
    )
    service.confirm_pairing_session(user_id=user_id, session_id=session.session_id)
    token, _ = service.complete_pairing(
        device_id=claim["device_id"], claim_secret=claim["claim_secret"]
    )
    return token, claim


def _object(object_id: str, revision: int, content: str) -> dict:
    return {
        "object_id": object_id,
        "object_type": "note",
        "revision": revision,
        "title": object_id,
        "content": content,
        "source_locator": {
            "kind": "marginnote4",
            "note_id": object_id,
            "uri": f"marginnote3app://note/{object_id}",
        },
    }


@pytest.fixture
def service(tmp_path: Path) -> MarginNote4Service:
    return MarginNote4Service(tmp_path / "bridge.sqlite3")


def test_pairing_binds_user_and_library_server_side(service: MarginNote4Service) -> None:
    token, claim = _pair(service, "user-a", "library-a")
    device = service.authenticate_device(token)
    assert (device.user_id, device.library_id) == ("user-a", "library-a")
    assert service.list_devices("user-b") == []

    result = service.push(
        device,
        protocol_version=1,
        operation_id="op-1",
        objects=[_object("note-1", 1, "first")],
        deletions=[],
    )
    assert result.accepted == 1
    assert service.get_object(user_id="user-b", library_id="library-a", object_id="note-1") is None
    assert service.list_pairing_sessions("user-b") == []

    rotated = service.rotate_device_token(user_id="user-a", device_id=claim["device_id"])
    assert service.authenticate_device(rotated).device_id == claim["device_id"]
    with pytest.raises(UnauthorizedDevice):
        service.authenticate_device(token)

    service.revoke_device(user_id="user-a", device_id=claim["device_id"])
    with pytest.raises(UnauthorizedDevice):
        service.authenticate_device(rotated)


def test_push_replay_out_of_order_and_tombstones(service: MarginNote4Service) -> None:
    token, _claim = _pair(service, "user-a", "library-a")
    device = service.authenticate_device(token)

    first = service.push(
        device,
        protocol_version=1,
        operation_id="op-1",
        objects=[_object("note-1", 1, "first")],
        deletions=[],
    )
    assert (first.accepted, first.updated, first.deleted) == (1, 0, 0)

    replay = service.push(
        device,
        protocol_version=1,
        operation_id="op-1",
        objects=[_object("note-1", 1, "first")],
        deletions=[],
    )
    assert replay.replayed is True

    with pytest.raises(OperationConflict):
        service.push(
            device,
            protocol_version=1,
            operation_id="op-1",
            objects=[_object("note-1", 1, "different")],
            deletions=[],
        )

    service.push(
        device,
        protocol_version=1,
        operation_id="op-2",
        objects=[_object("note-1", 2, "second")],
        deletions=[],
    )
    stale = service.push(
        device,
        protocol_version=1,
        operation_id="op-3",
        objects=[_object("note-1", 1, "late first")],
        deletions=[],
    )
    assert stale.ignored_stale == 1
    assert (
        service.get_object(user_id="user-a", library_id="library-a", object_id="note-1").content
        == "second"
    )

    deleted = service.push(
        device,
        protocol_version=1,
        operation_id="op-4",
        objects=[],
        deletions=[{"object_id": "note-1", "revision": 3}],
    )
    assert deleted.deleted == 1
    assert service.get_object(user_id="user-a", library_id="library-a", object_id="note-1") is None

    pulled = service.pull(device, cursor=0)
    assert [change["action"] for change in pulled.changes] == ["upsert", "upsert", "delete"]
    assert pulled.cursor == "3"
    assert pulled.has_more is False


def test_same_revision_conflict_does_not_overwrite(service: MarginNote4Service) -> None:
    token, _claim = _pair(service, "user-a", "library-a")
    device = service.authenticate_device(token)
    service.push(
        device,
        protocol_version=1,
        operation_id="op-1",
        objects=[_object("note-1", 2, "server")],
        deletions=[],
    )
    result = service.push(
        device,
        protocol_version=1,
        operation_id="op-2",
        objects=[_object("note-1", 2, "device")],
        deletions=[],
    )
    assert result.conflicts == [
        {
            "object_id": "note-1",
            "reason": "same_revision_different_content",
            "server_revision": 2,
            "device_revision": 2,
        }
    ]
    assert (
        service.get_object(user_id="user-a", library_id="library-a", object_id="note-1").content
        == "server"
    )
