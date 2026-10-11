"""Neutral-log regression tests for shared exception logging helpers."""

from __future__ import annotations

from deeptutor.utils.error_utils import exc_type_name, redacted_error_summary


def test_exc_type_name_returns_class_name_only() -> None:
    assert exc_type_name(ValueError("boom")) == "ValueError"


def test_redacted_error_summary_masks_labelled_credentials() -> None:
    exc = RuntimeError("upload failed for api_key=abcdef0123456789abcdef0123 on host")
    summary = redacted_error_summary(exc)
    assert "abcdef0123456789" not in summary
    assert "upload failed" in summary


def test_redacted_error_summary_masks_bearer_tokens() -> None:
    exc = RuntimeError("request rejected: Bearer abcdef0123456789abcdef012345")
    summary = redacted_error_summary(exc)
    assert "abcdef0123456789" not in summary
    assert "Bearer" in summary


def test_redacted_error_summary_truncates_long_messages() -> None:
    exc = RuntimeError("word " * 200)
    summary = redacted_error_summary(exc)
    assert len(summary) <= 120
    assert summary.endswith("...")


def test_redacted_error_summary_collapses_whitespace() -> None:
    exc = RuntimeError("line one\n\tline two   end")
    summary = redacted_error_summary(exc)
    assert "\n" not in summary
    assert "line one line two end" in summary


def test_redacted_error_summary_empty_message_falls_back_to_type_name() -> None:
    class _Empty(RuntimeError):
        def __str__(self) -> str:
            return ""

    assert redacted_error_summary(_Empty()) == "_Empty"
