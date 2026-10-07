"""Behavior tests for the lightweight Book error surface."""

from __future__ import annotations

import pytest

import deeptutor.book as book_package
from deeptutor.book.errors import BookPausedError


def test_book_paused_error_extends_runtime_error() -> None:
    assert issubclass(BookPausedError, RuntimeError)


@pytest.mark.parametrize(
    "message",
    ["book paused by user", "", "paused: another compile is running"],
)
def test_raised_error_keeps_the_message_and_is_caught_as_runtime_error(message: str) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        raise BookPausedError(message)

    assert isinstance(excinfo.value, BookPausedError)
    assert str(excinfo.value) == message


def test_package_level_export_resolves_to_the_errors_module() -> None:
    assert book_package.BookPausedError is BookPausedError
    assert "BookPausedError" in book_package.__all__


def test_package_level_export_is_cached_across_accesses() -> None:
    assert book_package.BookPausedError is book_package.BookPausedError
