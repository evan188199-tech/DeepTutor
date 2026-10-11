"""Serialization roundtrip and malformed-input tolerance for the v2 turn protocol."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError
import pytest

from deeptutor.api.contracts.turn_protocol import (
    MINIMUM_WEB_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    ActiveTurnInfo,
    CancelTurnCommand,
    CheckActiveTurnCommand,
    ClientCommand,
    CommandAckEvent,
    ErrorEnvelope,
    PingCommand,
    PongEvent,
    ProtocolErrorEvent,
    RegenerateCommand,
    ResumeTurnCommand,
    RuntimeStatus,
    ServerEvent,
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
    UserInputCommand,
)

_CLIENT_COMMAND_PAYLOADS: list[dict[str, Any]] = [
    {"type": "start_turn", "protocol_version": "2.0", "content": "hi"},
    {"type": "subscribe_turn", "turn_id": "t", "after_seq": 4, "protocol_version": "2.0"},
    {"type": "subscribe_session", "session_id": "s", "protocol_version": "2.0"},
    {"type": "resume_from", "turn_id": "t", "seq": 9, "protocol_version": "2.0"},
    {"type": "unsubscribe", "turn_id": "t", "protocol_version": "2.0"},
    {"type": "cancel_turn", "turn_id": "t", "command_id": "c", "protocol_version": "2.0"},
    {"type": "regenerate", "session_id": "s", "protocol_version": "2.0"},
    {
        "type": "submit_user_reply",
        "turn_id": "t",
        "text": "answer",
        "command_id": "c",
        "protocol_version": "2.0",
    },
    {
        "type": "submit_user_reply",
        "turn_id": "t",
        "answers": [{"questionId": "q1", "text": "B"}],
        "command_id": "c",
        "protocol_version": "2.0",
    },
    {
        "type": "user_input",
        "turn_id": "t",
        "content": "42",
        "command_id": "c",
        "protocol_version": "2.0",
    },
    {"type": "check_active_turn", "session_id": "s", "protocol_version": "2.0"},
    {"type": "ping", "protocol_version": "2.0"},
]

_CLIENT_COMMAND_TYPES: dict[str, type] = {
    "start_turn": StartTurnCommand,
    "subscribe_turn": SubscribeTurnCommand,
    "subscribe_session": SubscribeSessionCommand,
    "resume_from": ResumeTurnCommand,
    "unsubscribe": UnsubscribeCommand,
    "cancel_turn": CancelTurnCommand,
    "regenerate": RegenerateCommand,
    "submit_user_reply": SubmitUserReplyCommand,
    "user_input": UserInputCommand,
    "check_active_turn": CheckActiveTurnCommand,
    "ping": PingCommand,
}


def test_protocol_version_constants_are_locked() -> None:
    assert PROTOCOL_VERSION == "2.0"
    assert MINIMUM_WEB_PROTOCOL_VERSION == "2.0"


@pytest.mark.parametrize("payload", _CLIENT_COMMAND_PAYLOADS)
def test_client_command_roundtrips_through_dict_and_json(payload: dict) -> None:
    adapter = TypeAdapter(ClientCommand)
    parsed = adapter.validate_python(payload)

    assert type(parsed) is _CLIENT_COMMAND_TYPES[payload["type"]]
    assert adapter.validate_python(parsed.model_dump()) == parsed
    assert adapter.validate_json(parsed.model_dump_json()) == parsed


def test_every_discriminated_command_type_is_covered() -> None:
    covered = {payload["type"] for payload in _CLIENT_COMMAND_PAYLOADS}
    assert covered == set(_CLIENT_COMMAND_TYPES)


@pytest.mark.parametrize("command_type", sorted(_CLIENT_COMMAND_TYPES))
def test_client_command_rejects_missing_protocol_version(command_type: str) -> None:
    """No client command accepts a payload without an explicit "2.0" version."""

    payload: dict[str, Any] = {"type": command_type}
    if command_type == "start_turn":
        payload["content"] = "hi"
    identity_fields = {"turn_id": "t", "session_id": "s", "command_id": "c"}
    for field, value in identity_fields.items():
        if field in _CLIENT_COMMAND_TYPES[command_type].model_fields:
            payload[field] = value

    with pytest.raises(ValidationError):
        TypeAdapter(ClientCommand).validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "teleport", "protocol_version": "2.0"},
        {"type": "ping", "protocol_version": "2.0", "surprise": True},
        {"type": "ping"},
        {"type": "ping", "protocol_version": "3.0"},
        {"type": "ping", "protocol_version": "1.0"},
        {"type": "ping", "protocol_version": 2.0},
        {"type": "start_turn", "protocol_version": "2.0"},
        {"type": "subscribe_turn", "turn_id": "", "protocol_version": "2.0"},
        {"type": "subscribe_turn", "turn_id": "t", "after_seq": -1, "protocol_version": "2.0"},
        {"type": "cancel_turn", "turn_id": "t", "protocol_version": "2.0"},
        {"type": "cancel_turn", "turn_id": "t", "command_id": "", "protocol_version": "2.0"},
        {"type": "unsubscribe", "protocol_version": "2.0"},
        {"type": "user_input", "turn_id": "t", "content": "x", "protocol_version": "2.0"},
        {
            "type": "submit_user_reply",
            "turn_id": "t",
            "text": None,
            "answers": None,
            "command_id": "c",
            "protocol_version": "2.0",
        },
        {
            "type": "submit_user_reply",
            "turn_id": "t",
            "answers": [],
            "command_id": "c",
            "protocol_version": "2.0",
        },
    ],
)
def test_malformed_client_commands_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ClientCommand).validate_python(payload)


def test_start_turn_rejects_unknown_fields_like_any_wire_model() -> None:
    with pytest.raises(ValidationError):
        StartTurnCommand.model_validate(
            {"type": "start_turn", "protocol_version": "2.0", "content": "hi", "nonsense": 1}
        )


def test_start_turn_translates_legacy_runtime_config_with_warning() -> None:
    with pytest.warns(DeprecationWarning, match="_persist_user_message"):
        command = StartTurnCommand.model_validate(
            {
                "type": "start_turn",
                "protocol_version": "2.0",
                "content": "hi",
                "config": {"_persist_user_message": False},
            }
        )

    assert command.persist_user_message is False
    assert command.config == {}
    restored = StartTurnCommand.model_validate(command.model_dump())
    assert restored.persist_user_message is False


def test_server_event_roundtrip_preserves_every_field() -> None:
    event = StreamEvent(
        type=StreamEventType.CONTENT,
        source="chat",
        stage="responding",
        content="answer text",
        metadata={"call_kind": "llm_final_response"},
        session_id="sess-1",
        turn_id="turn-1",
        seq=12,
        timestamp=1234.5,
    )

    assert StreamEvent.model_validate(event.model_dump()) == event
    assert StreamEvent.model_validate_json(event.model_dump_json()) == event
    assert event.protocol_version == "2.0"
    assert event.model_dump(mode="json")["type"] == "content"


def test_server_events_default_to_the_current_protocol_version() -> None:
    assert StreamEvent(type=StreamEventType.DONE, timestamp=1.0).protocol_version == "2.0"
    assert ActiveTurnInfo().protocol_version == "2.0"
    assert PongEvent().protocol_version == "2.0"
    ack = CommandAckEvent(command_id="c", command_type="user_input", accepted=True)
    assert ack.protocol_version == "2.0"
    failure = ProtocolErrorEvent(error_code="internal_error", message="boom")
    assert failure.protocol_version == "2.0"


def test_server_event_union_roundtrip_and_json_tagging() -> None:
    events: list[ServerEvent] = [
        StreamEvent(type=StreamEventType.DONE, seq=1, timestamp=1.0),
        ActiveTurnInfo(turn_id="t", status=TurnQueryState.RUNNING, owner_id="w1"),
        PongEvent(),
        CommandAckEvent(
            command_id="c",
            command_type="user_input",
            accepted=False,
            error_code="rejected",
            turn_id="t",
        ),
        ProtocolErrorEvent(
            error_code="unsupported_protocol_version",
            message="expected 2.0",
            retryable=True,
            session_id="s",
            turn_id="t",
        ),
    ]
    for event in events:
        adapter = TypeAdapter(ServerEvent)
        assert type(adapter.validate_python(event.model_dump())) is type(event)
        assert adapter.validate_json(event.model_dump_json()) == event


def test_stream_event_rejects_invalid_fields() -> None:
    with pytest.raises(ValidationError):
        StreamEvent.model_validate({"type": "teleport", "timestamp": 1.0})
    with pytest.raises(ValidationError):
        StreamEvent.model_validate({"type": "content", "timestamp": 1.0, "seq": -1})
    with pytest.raises(ValidationError):
        StreamEvent.model_validate({"type": "content"})


def test_ack_and_protocol_error_events_are_strict() -> None:
    with pytest.raises(ValidationError):
        CommandAckEvent.model_validate(
            {"command_id": "c", "command_type": "teleport", "accepted": True}
        )
    with pytest.raises(ValidationError):
        CommandAckEvent.model_validate(
            {"command_id": "", "command_type": "cancel_turn", "accepted": True}
        )
    with pytest.raises(ValidationError):
        ProtocolErrorEvent.model_validate({"error_code": "", "message": "m"})


def test_turn_summary_roundtrip_with_enums_and_nested_session() -> None:
    summary = TurnSummary(
        id="turn-1",
        session_id="sess-1",
        status=TurnStatus.FAILED,
        query_state=TurnQueryState.RECOVERING,
        capability="chat",
        owner_id="worker-1",
        last_seq=8,
        error="provider down",
        error_code=TurnFailureCode.PROVIDER_ERROR,
        retryable=True,
        created_at=100.0,
        updated_at=200.0,
    )
    assert TurnSummary.model_validate(summary.model_dump()) == summary
    assert summary.model_dump(mode="json")["status"] == "failed"

    detail = SessionDetail(
        id="sess-1",
        title="Calculus",
        active_turn=summary,
        messages=[{"role": "user", "content": "hi"}],
        preferences={"reply_language": "en"},
    )
    restored = SessionDetail.model_validate_json(detail.model_dump_json())
    assert restored == detail
    assert restored.active_turn is not None
    assert restored.active_turn.error_code is TurnFailureCode.PROVIDER_ERROR

    without_turn = SessionSummary(id="s", title="t")
    assert without_turn.active_turn is None
    assert SessionSummary.model_validate(without_turn.model_dump()) == without_turn


def test_error_envelope_roundtrip_with_and_without_correlation() -> None:
    envelope = ErrorEnvelope(
        error_code="internal_error", message="boom", retryable=False, correlation_id="corr-9"
    )
    assert ErrorEnvelope.model_validate(envelope.model_dump()) == envelope
    assert envelope.model_dump(mode="json")["correlation_id"] == "corr-9"

    minimal = ErrorEnvelope(error_code="not_found", message="missing")
    assert minimal.correlation_id is None
    assert minimal.retryable is False
    assert ErrorEnvelope.model_validate_json(minimal.model_dump_json()) == minimal


def _runtime_status(**overrides: Any) -> RuntimeStatus:
    base: dict[str, Any] = {
        "worker_id": "host:1:abcd1234",
        "worker_count": 1,
        "coordination_mode": "memory",
        "redis_configured": False,
        "redis_status": "not_configured",
        "lease_ttl_seconds": 30,
        "renew_interval_seconds": 10,
        "recovery_interval_seconds": 10,
    }
    base.update(overrides)
    return RuntimeStatus.model_validate(base)


def test_runtime_status_roundtrip_and_version_defaults() -> None:
    status = _runtime_status(
        leader_id="host:2",
        leader_healthy=True,
        owner_turn_count=3,
        recovery_backlog=1,
    )
    restored = RuntimeStatus.model_validate_json(status.model_dump_json())
    assert restored == status
    assert restored.protocol_version == "2.0"
    assert restored.minimum_web_protocol_version == "2.0"


@pytest.mark.parametrize(
    "overrides",
    [
        {"worker_count": 0},
        {"coordination_mode": "kafka"},
        {"redis_status": "meh"},
        {"lease_ttl_seconds": 0},
        {"owner_turn_count": -1},
        {"recovery_backlog": -5},
    ],
)
def test_runtime_status_rejects_out_of_range_fields(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        _runtime_status(**overrides)


def test_turn_protocol_document_roundtrips_the_canonical_surface() -> None:
    document = TurnProtocolDocument(
        client_command={"type": "ping", "protocol_version": "2.0"},
        server_event=StreamEvent(type=StreamEventType.SESSION, session_id="sess-1", timestamp=9.0),
        runtime_status=_runtime_status(),
        session_summary=SessionSummary(id="sess-1", title="Algebra"),
        session_detail=SessionDetail(id="sess-1", title="Algebra", messages=[]),
        error=ErrorEnvelope(error_code="none", message="ok"),
    )

    assert document.protocol_version == "2.0"
    assert document.minimum_web_protocol_version == "2.0"

    restored = TurnProtocolDocument.model_validate_json(document.model_dump_json())
    assert restored == document
    assert isinstance(restored.client_command, PingCommand)
    assert isinstance(restored.server_event, StreamEvent)
