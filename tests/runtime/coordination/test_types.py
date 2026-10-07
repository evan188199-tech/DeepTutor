"""Contract tests for coordination value objects (deeptutor/runtime/coordination/types.py).

The state vocabulary lives here: these tests pin the legal turn states, the
rejection of illegal state strings, and the immutability / defensive-copy
invariants of the command and lease value objects.
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid

import pytest

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
# State vocabulary: legal values
# ---------------------------------------------------------------------------


def test_turn_status_covers_exactly_the_documented_states() -> None:
    assert {status.value for status in TurnStatus} == {
        "queued",
        "running",
        "waiting_input",
        "completed",
        "failed",
        "cancelled",
    }
    assert len(TurnStatus) == 6
    for status in TurnStatus:
        assert isinstance(status, str)
        assert status.value == status


def test_turn_status_str_enum_round_trip_and_serialization() -> None:
    assert TurnStatus("queued") is TurnStatus.QUEUED
    assert TurnStatus.RUNNING == "running"
    lookup = {TurnStatus.COMPLETED: "done"}
    assert lookup["completed"] == "done"
    assert json.loads(json.dumps({"status": TurnStatus.FAILED})) == {"status": "failed"}


def test_failure_and_command_kind_catalogs_are_exact() -> None:
    assert {code.value for code in TurnFailureCode} == {
        "worker_lost",
        "lease_lost",
        "coordination_unavailable",
        "provider_error",
        "internal_error",
        "rejected",
        "server_shutdown",
    }
    assert {kind.value for kind in TurnCommandKind} == {
        "cancel",
        "submit_user_reply",
        "user_input",
    }
    assert {kind.value for kind in BackgroundCommandKind} == {
        "cron_reload",
        "partner_start",
        "partner_stop",
        "partner_reload",
    }


# ---------------------------------------------------------------------------
# State vocabulary: illegal values are rejected at parse time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum", "bogus"),
    [
        (TurnStatus, "parked"),
        (TurnStatus, ""),
        (TurnStatus, "QUEUED"),
        (TurnFailureCode, "worker gone"),
        (TurnCommandKind, "Cancel"),
        (BackgroundCommandKind, "partner_pause"),
    ],
)
def test_illegal_state_and_kind_strings_never_parse(enum: type, bogus: str) -> None:
    with pytest.raises(ValueError):
        enum(bogus)


# ---------------------------------------------------------------------------
# Lease value objects: immutability and equality
# ---------------------------------------------------------------------------


def test_turn_lease_is_frozen_and_hashable() -> None:
    lease = TurnLease(
        turn_id="t1",
        session_id="s1",
        owner_id="w1",
        fencing_token=7,
        expires_at=123.5,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.fencing_token = 99  # type: ignore[misc]

    twin = TurnLease(
        turn_id="t1",
        session_id="s1",
        owner_id="w1",
        fencing_token=7,
        expires_at=123.5,
    )
    other = dataclasses.replace(lease, fencing_token=8)
    assert lease == twin
    assert hash(lease) == hash(twin)
    assert lease != other
    assert len({lease, twin, other}) == 2


def test_leader_lease_is_frozen_with_field_equality() -> None:
    lease = LeaderLease(owner_id="w1", fencing_token=3, expires_at=1.25)
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.owner_id = "w2"  # type: ignore[misc]
    assert lease == LeaderLease(owner_id="w1", fencing_token=3, expires_at=1.25)
    assert lease != LeaderLease(owner_id="w2", fencing_token=3, expires_at=1.25)


# ---------------------------------------------------------------------------
# TurnCommand: create() defaults, uniqueness, defensive payload copy
# ---------------------------------------------------------------------------


def test_turn_command_create_defaults_and_unique_ids() -> None:
    before = time.time()
    first = TurnCommand.create("turn-1", "cancel")
    second = TurnCommand.create("turn-1", "cancel")
    after = time.time()

    assert first.payload == {}
    assert isinstance(first.payload, dict)
    assert before <= first.created_at <= after
    assert first.command_id.startswith("cmd_")
    assert first.command_id != second.command_id
    uuid.UUID(first.command_id[len("cmd_") :])  # auto id is a uuid4 hex


def test_turn_command_create_honors_explicit_id_and_copies_payload() -> None:
    payload = {"reply": "hello"}
    command = TurnCommand.create(
        "turn-2",
        "submit_user_reply",
        payload,
        command_id="cmd_fixed",
    )
    payload["reply"] = "mutated after creation"

    assert command.command_id == "cmd_fixed"
    assert command.turn_id == "turn-2"
    assert command.kind == "submit_user_reply"
    assert command.payload == {"reply": "hello"}
    assert command.payload is not payload


def test_turn_command_tolerates_none_payload_and_enum_kinds() -> None:
    from_none = TurnCommand.create("turn-3", "user_input", None)
    assert from_none.payload == {}

    enum_kind = TurnCommand.create("turn-3", TurnCommandKind.USER_INPUT)
    assert enum_kind.kind is TurnCommandKind.USER_INPUT
    # StrEnum kind compares equal to the raw protocol string.
    assert enum_kind.kind == "user_input"
    assert TurnCommandKind("submit_user_reply") is TurnCommandKind.SUBMIT_USER_REPLY


def test_turn_command_constructor_is_permissive_and_equality_is_value_based() -> None:
    """The dataclass does no runtime validation: malformed fields are stored verbatim."""
    odd = TurnCommand(command_id=1, turn_id=2.5, kind=None, payload=None)  # type: ignore[arg-type]
    assert odd.command_id == 1
    assert odd.payload is None
    assert odd != TurnCommand.create("x", "cancel", {}, command_id="1")


# ---------------------------------------------------------------------------
# BackgroundCommand: same contract on the background side
# ---------------------------------------------------------------------------


def test_background_command_create_defaults_unique_ids_and_copy() -> None:
    first = BackgroundCommand.create("cron_reload")
    second = BackgroundCommand.create("cron_reload")

    assert first.command_id.startswith("bgcmd_")
    assert first.command_id != second.command_id
    assert first.payload == {}
    uuid.UUID(first.command_id[len("bgcmd_") :])

    payload = {"partner": "p1"}
    explicit = BackgroundCommand.create(
        BackgroundCommandKind.PARTNER_START,
        payload,
        command_id="bgcmd_fixed",
    )
    payload["partner"] = "changed"
    assert explicit.command_id == "bgcmd_fixed"
    assert explicit.kind == "partner_start"
    assert explicit.payload == {"partner": "p1"}
    assert explicit.payload is not payload


def test_background_command_freezes_against_mutation() -> None:
    command = BackgroundCommand.create("partner_stop", {"partner": "p1"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        command.kind = "partner_start"  # type: ignore[misc]
