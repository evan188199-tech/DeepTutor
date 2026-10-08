"""Contract tests for the browser turn protocol v2 wire models.

Locks the frontend/backend contract for ``deeptutor.api.contracts.turn_protocol``:
serialization roundtrips, the unknown-field rejection policy, and the explicit
errors produced for malformed payloads.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from deeptutor.api.contracts.turn_protocol import (
    MINIMUM_WEB_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    ActiveTurnInfo,
    CancelTurnCommand,
    ClientCommand,
    CommandAckEvent,
    ErrorEnvelope,
    PingCommand,
    ProtocolErrorEvent,
    PongEvent,
    RuntimeStatus,
    SessionDetail,
    SessionSummary,
    StartTurnCommand,
    StreamEvent,
    StreamEventType,
    SubmitUserReplyCommand,
    SubscribeSessionCommand,
    SubscribeTurnCommand,
    TurnFailureCode,
    TurnProtocolDocument,
    TurnQueryState,
    TurnStatus,
    TurnSummary,
    UnsubscribeCommand,
    UserAnswer,
)

_CLIENT_ADAPTER = TypeAdapter(ClientCommand)


def _error_types(exc: ValidationError) -> set[str]:
    return {error["type"] for error in exc.errors()}


def _runtime_status(**overrides: Any) -> RuntimeStatus:
    payload: dict[str, Any] = {
        "worker_id": "worker-1",
        "worker_count": 2,
        "coordination_mode": "memory",
        "redis_configured": False,
        "redis_status": "not_configured",
        "lease_ttl_seconds": 30,
        "renew_interval_seconds": 10,
        "recovery_interval_seconds": 10,
    }
    payload.update(overrides)
    return RuntimeStatus.model_validate(payload)


def test_protocol_version_constants_are_v2() -> None:
    assert PROTOCOL_VERSION == "2.0"
    assert MINIMUM_WEB_PROTOCOL_VERSION == "2.0"


def test_start_turn_command_json_roundtrip_preserves_defaults() -> None:
    command = StartTurnCommand.model_validate(
        {"content": "hello", "protocol_version": "2.0"}
    )

    assert command.type == "start_turn"
    restored = StartTurnCommand.model_validate_json(command.model_dump_json())
    assert restored == command
    wire = command.model_dump(mode="json")
    assert wire["type"] == "start_turn"
    assert wire["protocol_version"] == "2.0"
    assert wire["content"] == "hello"


def test_client_command_adapter_dispatches_by_discriminator() -> None:
    payloads = [
        {"type": "subscribe_turn", "turn_id": "t1", "protocol_version": "2.0"},
        {"type": "subscribe_session", "session_id": "s1", "protocol_version": "2.0"},
        {"type": "cancel_turn", "turn_id": "t1", "command_id": "c1", "protocol_version": "2.0"},
        {"type": "ping", "protocol_version": "2.0"},
    ]

    dispatched = [_CLIENT_ADAPTER.validate_python(payload) for payload in payloads]

    assert isinstance(dispatched[0], SubscribeTurnCommand)
    assert isinstance(dispatched[1], SubscribeSessionCommand)
    assert isinstance(dispatched[2], CancelTurnCommand)
    assert isinstance(dispatched[3], PingCommand)


def test_stream_event_json_roundtrip_preserves_wire_values() -> None:
    event = StreamEvent.model_validate(
        {
            "type": "content",
            "source": "agent",
            "stage": "answer",
            "content": "partial answer",
            "metadata": {"token": 3},
            "session_id": "s1",
            "turn_id": "t1",
            "seq": 7,
            "timestamp": 12.5,
        }
    )

    restored = StreamEvent.model_validate_json(event.model_dump_json())
    assert restored == event
    wire = event.model_dump(mode="json")
    assert wire["type"] == "content"
    assert wire["metadata"] == {"token": 3}
    assert StreamEventType("content") is StreamEventType.CONTENT


def test_command_events_json_roundtrip() -> None:
    ack = CommandAckEvent.model_validate(
        {
            "command_id": "c1",
            "command_type": "cancel_turn",
            "accepted": True,
            "turn_id": "t1",
        }
    )
    error = ProtocolErrorEvent.model_validate(
        {
            "error_code": "invalid_command",
            "message": "Command does not match the turn protocol.",
            "retryable": False,
            "turn_id": "t1",
        }
    )

    assert CommandAckEvent.model_validate_json(ack.model_dump_json()) == ack
    assert ProtocolErrorEvent.model_validate_json(error.model_dump_json()) == error
    assert ack.type == "command_ack"
    assert error.type == "protocol_error"


def test_turn_summary_nested_in_session_models_roundtrip() -> None:
    summary = TurnSummary.model_validate(
        {
            "id": "t1",
            "session_id": "s1",
            "status": "failed",
            "query_state": "recovering",
            "last_seq": 4,
            "error": "worker disappeared",
            "error_code": "worker_lost",
            "retryable": True,
            "created_at": 1.0,
            "updated_at": 2.0,
        }
    )
    session = SessionSummary.model_validate(
        {"id": "s1", "title": "Demo", "active_turn": summary.model_dump(mode="json")}
    )
    detail = SessionDetail.model_validate(
        {
            "id": "s1",
            "title": "Demo",
            "messages": [{"role": "user", "content": "hi"}],
            "preferences": {"language": "en"},
        }
    )

    assert summary.status is TurnStatus.FAILED
    assert summary.error_code is TurnFailureCode.WORKER_LOST
    assert summary.query_state is TurnQueryState.RECOVERING
    assert SessionSummary.model_validate_json(session.model_dump_json()) == session
    assert SessionDetail.model_validate_json(detail.model_dump_json()) == detail
    assert session.active_turn is not None and session.active_turn.id == "t1"


def test_runtime_status_and_error_envelope_roundtrip() -> None:
    status = _runtime_status(
        leader_id="w1",
        leader_healthy=True,
        owner_turn_count=3,
        recovery_backlog=1,
    )
    envelope = ErrorEnvelope.model_validate(
        {"error_code": "worker_lost", "message": "retry later", "correlation_id": "corr-9"}
    )

    assert RuntimeStatus.model_validate_json(status.model_dump_json()) == status
    assert ErrorEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    wire = status.model_dump(mode="json")
    assert wire["protocol_version"] == "2.0"
    assert wire["minimum_web_protocol_version"] == "2.0"


def test_protocol_document_roundtrip_locks_full_wire_surface() -> None:
    document = TurnProtocolDocument.model_validate(
        {
            "client_command": {"type": "ping", "protocol_version": "2.0"},
            "server_event": {"type": "pong", "protocol_version": "2.0"},
            "runtime_status": _runtime_status().model_dump(mode="json"),
            "session_summary": {"id": "s1", "title": "Demo"},
            "session_detail": {"id": "s1", "title": "Demo"},
            "error": {"error_code": "internal_error", "message": "boom"},
        }
    )

    restored = TurnProtocolDocument.model_validate_json(document.model_dump_json())
    assert restored == document
    assert isinstance(document.client_command, PingCommand)
    assert isinstance(document.server_event, PongEvent)


@pytest.mark.parametrize(
    ("model_cls", "payload"),
    [
        (SubscribeTurnCommand, {"turn_id": "t1", "protocol_version": "2.0", "bogus": 1}),
        (StreamEvent, {"type": "content", "timestamp": 1.0, "bogus": True}),
        (PingCommand, {"protocol_version": "2.0", "bogus": None}),
        (ErrorEnvelope, {"error_code": "x", "message": "y", "bogus": "z"}),
    ],
)
def test_wire_models_reject_unknown_fields(model_cls: type, payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        model_cls.model_validate(payload)

    assert "extra_forbidden" in _error_types(exc_info.value)


def test_start_turn_command_rejects_unknown_fields_inherited_from_turn_request() -> None:
    with pytest.raises(ValidationError) as exc_info:
        StartTurnCommand.model_validate(
            {"content": "hello", "protocol_version": "2.0", "nonsense_field": 1}
        )

    assert "extra_forbidden" in _error_types(exc_info.value)


def test_omitted_optional_fields_take_contract_defaults() -> None:
    subscribe = SubscribeTurnCommand.model_validate(
        {"turn_id": "t1", "protocol_version": "2.0"}
    )
    event = StreamEvent.model_validate({"type": "done", "timestamp": 0.0})
    info = ActiveTurnInfo.model_validate({"protocol_version": "2.0"})

    assert subscribe.after_seq == 0
    assert event.source == ""
    assert event.stage == ""
    assert event.content == ""
    assert event.metadata == {}
    assert event.seq == 0
    assert event.protocol_version == "2.0"
    assert info.status == "none"
    assert info.turn_id == ""


def test_unknown_discriminator_type_is_rejected_by_client_adapter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _CLIENT_ADAPTER.validate_python({"type": "mystery_command", "protocol_version": "2.0"})

    assert "union_tag_invalid" in _error_types(exc_info.value)


def test_wrong_protocol_version_literal_is_rejected() -> None:
    with pytest.raises(ValidationError) as subscribe_error:
        SubscribeTurnCommand.model_validate({"turn_id": "t1", "protocol_version": "1.0"})
    with pytest.raises(ValidationError) as ping_error:
        PingCommand.model_validate({"type": "ping", "protocol_version": "2.1"})

    assert "literal_error" in _error_types(subscribe_error.value)
    assert "literal_error" in _error_types(ping_error.value)


def test_negative_seq_and_empty_identifiers_are_rejected() -> None:
    with pytest.raises(ValidationError) as negative_seq:
        SubscribeTurnCommand.model_validate(
            {"turn_id": "t1", "after_seq": -1, "protocol_version": "2.0"}
        )
    with pytest.raises(ValidationError) as empty_turn_id:
        SubscribeTurnCommand.model_validate({"turn_id": "", "protocol_version": "2.0"})
    with pytest.raises(ValidationError) as empty_command_id:
        CancelTurnCommand.model_validate(
            {"type": "cancel_turn", "turn_id": "t1", "command_id": "", "protocol_version": "2.0"}
        )

    assert "greater_than_equal" in _error_types(negative_seq.value)
    assert "string_too_short" in _error_types(empty_turn_id.value)
    assert "string_too_short" in _error_types(empty_command_id.value)


def test_unsubscribe_requires_a_target() -> None:
    with pytest.raises(ValidationError, match="unsubscribe requires turn_id or session_id"):
        UnsubscribeCommand.model_validate({"type": "unsubscribe", "protocol_version": "2.0"})

    restored = UnsubscribeCommand.model_validate(
        {"type": "unsubscribe", "session_id": "s1", "protocol_version": "2.0"}
    )
    assert restored.session_id == "s1"
    assert restored.turn_id is None


def test_submit_user_reply_requires_text_or_answers() -> None:
    with pytest.raises(ValidationError, match="submit_user_reply requires text or answers"):
        SubmitUserReplyCommand.model_validate(
            {
                "type": "submit_user_reply",
                "turn_id": "t1",
                "command_id": "c1",
                "protocol_version": "2.0",
            }
        )
    with pytest.raises(ValidationError, match="submit_user_reply requires text or answers"):
        SubmitUserReplyCommand.model_validate(
            {
                "type": "submit_user_reply",
                "turn_id": "t1",
                "answers": [],
                "command_id": "c1",
                "protocol_version": "2.0",
            }
        )


def test_user_answer_keeps_camel_case_wire_key() -> None:
    reply = SubmitUserReplyCommand.model_validate(
        {
            "type": "submit_user_reply",
            "turn_id": "t1",
            "command_id": "c1",
            "protocol_version": "2.0",
            "answers": [{"questionId": "q1", "text": "42"}],
        }
    )

    assert reply.answers is not None
    assert reply.answers[0].questionId == "q1"
    restored = SubmitUserReplyCommand.model_validate_json(reply.model_dump_json())
    assert restored == reply
    wire = restored.model_dump(mode="json")
    assert wire["answers"][0]["questionId"] == "q1"
    assert UserAnswer.model_validate(wire["answers"][0]).text == "42"


def test_runtime_status_rejects_invalid_literals_and_bounds() -> None:
    with pytest.raises(ValidationError) as bad_mode:
        _runtime_status(coordination_mode="kafka")
    with pytest.raises(ValidationError) as bad_redis:
        _runtime_status(redis_status="degraded")
    with pytest.raises(ValidationError) as zero_workers:
        _runtime_status(worker_count=0)
    with pytest.raises(ValidationError) as zero_lease:
        _runtime_status(lease_ttl_seconds=0)

    assert "literal_error" in _error_types(bad_mode.value)
    assert "literal_error" in _error_types(bad_redis.value)
    assert "greater_than_equal" in _error_types(zero_workers.value)
    assert "greater_than_equal" in _error_types(zero_lease.value)


def test_malformed_json_is_rejected_with_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        PingCommand.model_validate_json("{not-json")

    assert "json_invalid" in _error_types(exc_info.value)
