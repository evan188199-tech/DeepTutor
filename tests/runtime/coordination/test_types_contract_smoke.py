"""Contract smoke tests for the coordination message value objects.

Pins the module's export surface (``__all__``), the JSON
serialization/deserialization round trip of every cross-process message
object, the frozen/slots invariants of the dataclasses, and the rejection
of illegal enum inputs.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import deeptutor.runtime.coordination.types as types_module
from deeptutor.runtime.coordination.types import (
    BackgroundCommand,
    BackgroundCommandKind,
    LeaderLease,
    TurnCommand,
    TurnCommandKind,
    TurnFailureCode,
    TurnLease,
    TurnStatus,
)


# ---------------------------------------------------------------------------
# Export contract: __all__ is exact and every name is importable
# ---------------------------------------------------------------------------


def test_all_exports_the_full_value_object_contract() -> None:
    assert set(types_module.__all__) == {
        "BackgroundCommand",
        "BackgroundCommandKind",
        "LeaderLease",
        "TurnCommand",
        "TurnCommandKind",
        "TurnFailureCode",
        "TurnLease",
        "TurnStatus",
    }


def test_every_public_export_is_resolvable_from_the_module() -> None:
    for name in types_module.__all__:
        obj = getattr(types_module, name)
        assert obj.__module__ == types_module.__name__


def test_str_enums_are_reachable_through_the_package_init() -> None:
    from deeptutor.runtime.coordination import types as reloaded

    assert reloaded.TurnStatus is TurnStatus
    assert reloaded.TurnCommand is TurnCommand
    assert reloaded.BackgroundCommand is BackgroundCommand


# ---------------------------------------------------------------------------
# Serialization round trips: asdict -> JSON -> reconstruct
# ---------------------------------------------------------------------------


def test_turn_command_json_round_trip_preserves_all_fields() -> None:
    command = TurnCommand.create(
        "turn-1",
        TurnCommandKind.SUBMIT_USER_REPLY,
        {"reply": "hello", "meta": {"attempt": 2, "tags": ["a", "b"]}},
        command_id="cmd_fixed",
    )

    restored = TurnCommand(**json.loads(json.dumps(dataclasses.asdict(command))))

    assert restored == command
    assert restored.payload == {"reply": "hello", "meta": {"attempt": 2, "tags": ["a", "b"]}}
    assert restored.created_at == command.created_at


def test_turn_command_enum_fields_round_trip_through_their_string_values() -> None:
    command = TurnCommand.create("turn-2", TurnCommandKind.CANCEL)

    encoded = json.dumps(dataclasses.asdict(command))
    restored = TurnCommand(**json.loads(encoded))

    assert restored.kind == TurnCommandKind.CANCEL
    assert restored.kind == "cancel"
    assert TurnCommandKind(restored.kind) is TurnCommandKind.CANCEL


def test_background_command_json_round_trip_preserves_all_fields() -> None:
    command = BackgroundCommand.create(
        BackgroundCommandKind.PARTNER_START,
        {"partner": "p1", "options": {"autorun": True, "retries": 3}},
        command_id="bgcmd_fixed",
    )

    restored = BackgroundCommand(**json.loads(json.dumps(dataclasses.asdict(command))))

    assert restored == command
    assert restored.kind == "partner_start"
    assert restored.payload["options"]["autorun"] is True


def test_lease_value_objects_json_round_trip() -> None:
    turn_lease = TurnLease(
        turn_id="t-1",
        session_id="s-1",
        owner_id="w-1",
        fencing_token=42,
        expires_at=1234.5678,
    )
    leader_lease = LeaderLease(owner_id="w-1", fencing_token=7, expires_at=99.5)

    turn_restored = TurnLease(**json.loads(json.dumps(dataclasses.asdict(turn_lease))))
    leader_restored = LeaderLease(**json.loads(json.dumps(dataclasses.asdict(leader_lease))))

    assert turn_restored == turn_lease
    assert leader_restored == leader_lease


def test_status_and_failure_vocabularies_survive_json_encoding() -> None:
    encoded = json.dumps(
        {
            "status": TurnStatus.WAITING_INPUT,
            "failure": TurnFailureCode.LEASE_LOST,
        }
    )

    decoded = json.loads(encoded)

    assert decoded == {"status": "waiting_input", "failure": "lease_lost"}
    assert TurnStatus(decoded["status"]) is TurnStatus.WAITING_INPUT
    assert TurnFailureCode(decoded["failure"]) is TurnFailureCode.LEASE_LOST


# ---------------------------------------------------------------------------
# Frozen / slots invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutator",
    [
        lambda cmd: setattr(cmd, "command_id", "cmd_other"),
        lambda cmd: setattr(cmd, "kind", "cancel"),
        lambda cmd: setattr(cmd, "payload", {}),
    ],
)
def test_command_dataclasses_reject_attribute_mutation(mutator) -> None:
    turn_command = TurnCommand.create("turn-3", "cancel")
    background_command = BackgroundCommand.create("cron_reload")

    with pytest.raises(dataclasses.FrozenInstanceError):
        mutator(turn_command)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mutator(background_command)


@pytest.mark.parametrize(
    ("factory", "fields"),
    [
        (TurnLease, {"turn_id", "session_id", "owner_id", "fencing_token", "expires_at"}),
        (LeaderLease, {"owner_id", "fencing_token", "expires_at"}),
    ],
)
def test_leases_use_slots_and_reject_mutation(factory, fields) -> None:
    if factory is TurnLease:
        lease = factory(
            turn_id="t",
            session_id="s",
            owner_id="w",
            fencing_token=1,
            expires_at=1.0,
        )
    else:
        lease = factory(owner_id="w", fencing_token=1, expires_at=1.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.expires_at = 2.0

    assert not hasattr(lease, "__dict__")
    assert set(lease.__slots__) == fields


# ---------------------------------------------------------------------------
# Illegal input rejection at the parse surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum", "bogus"),
    [
        (TurnStatus, "queued "),
        (TurnStatus, "done"),
        (TurnFailureCode, "worker_lost "),
        (TurnFailureCode, "unknown_failure"),
        (TurnCommandKind, "submit-user-reply"),
        (BackgroundCommandKind, "partner_restart"),
        (BackgroundCommandKind, ""),
    ],
)
def test_illegal_enum_inputs_are_rejected(enum: type, bogus: str) -> None:
    with pytest.raises(ValueError):
        enum(bogus)


def test_illegal_kind_is_not_silently_normalized_by_lookup_helpers() -> None:
    with pytest.raises(ValueError):
        TurnCommandKind("CANCEL")
    with pytest.raises(ValueError):
        BackgroundCommandKind("CRON_RELOAD")
