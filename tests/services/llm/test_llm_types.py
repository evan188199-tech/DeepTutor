"""Contracts of the shared LLM response models.

``services/llm/types.py`` is small on purpose: a truncation table every
caller reads, an outcome object streamed callers fill, and the two pydantic
models that cross provider boundaries. These tests pin those contracts so a
provider adapter cannot quietly change what "the response ended early" or
"the chunk carried usage" means.

Truncation is one of the three silent degradations a reasoning model
produces (with malformed JSON and provider errors) — a cap on hidden plus
visible tokens cuts the body with no exception, which is exactly what
:meth:`StreamOutcome.truncated` and :func:`finish_was_truncated` exist to
make visible (#1545, #1547).
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.services.llm.types import (
    TRUNCATED_FINISH_REASONS,
    AsyncStreamGenerator,
    LLMResponse,
    StreamChunk,
    StreamOutcome,
    TutorResponse,
    TutorStreamChunk,
    finish_was_truncated,
)

# --- finish_was_truncated: the one truncation table ---


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens"])
def test_every_cap_reason_counts_as_truncated(reason: str) -> None:
    assert finish_was_truncated(reason) is True


@pytest.mark.parametrize("reason", [" Length ", "MAX_TOKENS", "\tmax_output_tokens\n"])
def test_cap_reasons_match_case_and_whitespace_insensitive(reason: str) -> None:
    assert finish_was_truncated(reason) is True


@pytest.mark.parametrize(
    "reason", ["stop", "tool_calls", "content_filter", "eos", "", "   ", "lengthened"]
)
def test_normal_finish_reasons_are_not_truncation(reason: str) -> None:
    assert finish_was_truncated(reason) is False


def test_none_finish_reason_is_not_truncation() -> None:
    assert finish_was_truncated(None) is False


def test_non_string_reasons_are_coerced_like_callers_pass_them() -> None:
    assert finish_was_truncated(123) is False
    assert finish_was_truncated("Length") is True


def test_the_truncation_table_is_exactly_the_three_cap_reasons() -> None:
    assert TRUNCATED_FINISH_REASONS == frozenset({"length", "max_tokens", "max_output_tokens"})


# --- StreamOutcome: what a streamed caller learns after the fact ---


def test_stream_outcome_defaults_to_a_complete_unknown_finish() -> None:
    outcome = StreamOutcome()
    assert outcome.finish_reason == ""
    assert outcome.usage == {}
    assert outcome.truncated is False


def test_stream_outcome_default_usage_dicts_are_not_shared() -> None:
    first, second = StreamOutcome(), StreamOutcome()
    first.usage["total_tokens"] = 5
    assert second.usage == {}, "a mutable default would leak tokens between calls"


def test_stream_outcome_truncated_reads_the_finish_reason() -> None:
    assert StreamOutcome(finish_reason="length").truncated is True
    assert StreamOutcome(finish_reason="max_tokens").truncated is True
    assert StreamOutcome(finish_reason="stop").truncated is False


def test_stream_outcome_carries_token_usage() -> None:
    outcome = StreamOutcome(
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    )
    assert outcome.usage["total_tokens"] == 13


# --- TutorResponse / TutorStreamChunk: the wire models ---


def test_tutor_response_defaults_for_every_optional_field() -> None:
    response = TutorResponse(content="hello")
    assert response.raw_response == {}
    assert response.usage == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert response.provider == ""
    assert response.model == ""
    assert response.finish_reason is None
    assert response.cost_estimate == 0.0


def test_tutor_response_without_content_is_invalid() -> None:
    with pytest.raises(ValidationError):
        TutorResponse()  # type: ignore[call-arg]


def test_tutor_response_keeps_what_the_provider_reported() -> None:
    response = TutorResponse(
        content="body",
        raw_response={"id": "resp-1"},
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        provider="openai",
        model="gpt-test",
        finish_reason="length",
        cost_estimate=0.25,
    )
    dumped = response.model_dump()
    assert dumped["finish_reason"] == "length"
    assert dumped["cost_estimate"] == 0.25
    assert dumped["raw_response"] == {"id": "resp-1"}


def test_truncated_tutor_response_is_detectable_through_the_shared_table() -> None:
    response = TutorResponse(content="cut off", finish_reason="max_output_tokens")
    assert finish_was_truncated(response.finish_reason) is True


def test_tutor_stream_chunk_defaults_to_an_incomplete_no_usage_chunk() -> None:
    chunk = TutorStreamChunk(delta="he")
    assert chunk.content == ""
    assert chunk.provider == ""
    assert chunk.model == ""
    assert chunk.is_complete is False
    assert chunk.usage is None


def test_tutor_stream_chunk_final_chunk_reports_completion_and_usage() -> None:
    chunk = TutorStreamChunk(
        delta="",
        content="hello",
        is_complete=True,
        usage={"total_tokens": 7},
    )
    assert chunk.is_complete is True
    assert chunk.usage == {"total_tokens": 7}
    assert chunk.delta == ""


def test_tutor_stream_chunk_without_delta_is_invalid() -> None:
    with pytest.raises(ValidationError):
        TutorStreamChunk()  # type: ignore[call-arg]


# --- Backwards-compatible aliases ---


def test_legacy_aliases_still_point_at_the_current_models() -> None:
    assert LLMResponse is TutorResponse
    assert StreamChunk is TutorStreamChunk


def test_stream_generator_alias_is_bound_to_tutor_stream_chunks() -> None:
    import collections.abc
    import typing

    assert typing.get_origin(AsyncStreamGenerator) is collections.abc.AsyncGenerator
    args = typing.get_args(AsyncStreamGenerator)
    assert args[0] is TutorStreamChunk
    assert args[1] in (type(None), None)
