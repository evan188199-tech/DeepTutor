"""A truncation failure must reach the reader as "fix the settings", not "retry".

The math animator already names the output cap in its error (#1545), but that
message also contains the word "JSON", so the block classifier filed it as a
retryable ``json_parse`` and the compiler re-ran the whole generation on the
same capped request (#1914).
"""

from __future__ import annotations

from deeptutor.agents.math_animator.utils import describe_unusable_output
from deeptutor.book.blocks.base import GenerationFailure, _classify_failure, _failure_metadata
from deeptutor.services.llm.types import StreamOutcome


def _truncation_failure_message() -> str:
    outcome = StreamOutcome()
    outcome.finish_reason = "length"
    outcome.usage = {"completion_tokens": 12000, "reasoning_tokens": 12000}
    detail = describe_unusable_output(
        error=ValueError("No JSON object found: line 1 column 1 (char 0)"),
        raw_response="<think>planning the whole scene first</think>",
        outcome=outcome,
        max_tokens=12000,
    )
    return f"animation generation failed: Math animator code_generation returned no usable code after 2 attempts. Last attempt: {detail}"


def test_truncated_generation_is_not_classified_as_retryable_json_damage() -> None:
    message = _truncation_failure_message()

    assert "json" in message.lower()  # the trap the old ordering fell into
    assert _classify_failure(message) == "truncated_output"


def test_truncated_generation_failure_metadata_tells_the_user_what_to_change() -> None:
    metadata = _failure_metadata(
        GenerationFailure(_truncation_failure_message()), "AnimationGenerator"
    )

    assert metadata["kind"] == "truncated_output"
    assert metadata["retryable"] is False
    # The actionable hint travels with the error the frontend displays.
    assert "raise the math animator's max tokens" in metadata["message"]
    assert "pick a model that reasons less" in metadata["message"]
