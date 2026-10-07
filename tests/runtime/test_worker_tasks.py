"""Pure-logic contract tests for the fixed isolated-worker task registry.

``deeptutor.runtime.worker_tasks`` is the allowlist of importable tasks the
isolated worker protocol may execute: callers reference tasks only through the
``"package.module:callable"`` paths resolved by
``deeptutor.runtime.worker_process._resolve``. These tests pin that registry
surface — public task names, required limits in task signatures, the naming
separation of the pytest-prefixed allocation helper, unknown-task lookup
behavior, and each task's delegation — without spawning any worker process.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from deeptutor.runtime.worker_process import _resolve
import deeptutor.runtime.worker_tasks as worker_tasks

MODULE_PATH = "deeptutor.runtime.worker_tasks"
PUBLIC_TASKS = ("extract_document_text", "extract_document_to_markdown")
LIMIT_PARAM_NAMES = ("max_bytes", "max_chars")


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------


def test_public_registry_matches_fixed_task_surface() -> None:
    assert tuple(worker_tasks.__all__) == PUBLIC_TASKS
    for name in worker_tasks.__all__:
        task = getattr(worker_tasks, name)
        assert callable(task)
        assert task.__module__ == MODULE_PATH


def test_registry_names_are_unique_public_and_not_reexports() -> None:
    names = list(worker_tasks.__all__)
    assert len(names) == len(set(names))
    for name in names:
        assert not name.startswith("_")
        # The module imports ``Path``; the registry must never re-export it.
        assert name != "Path"


@pytest.mark.parametrize("task_name", PUBLIC_TASKS)
def test_task_signatures_require_explicit_limits(task_name: str) -> None:
    signature = inspect.signature(getattr(worker_tasks, task_name))
    for limit in LIMIT_PARAM_NAMES:
        param = signature.parameters[limit]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty


def test_text_task_accepts_optional_filename_hint() -> None:
    signature = inspect.signature(worker_tasks.extract_document_text)
    hint = signature.parameters["filename_hint"]
    assert hint.kind is inspect.Parameter.KEYWORD_ONLY
    assert hint.default is None
    # The markdown task has no source-name hint: it derives the stem itself.
    assert (
        "filename_hint"
        not in inspect.signature(worker_tasks.extract_document_to_markdown).parameters
    )


@pytest.mark.parametrize(
    ("callable_path", "expected"),
    [
        (f"{MODULE_PATH}:extract_document_text", worker_tasks.extract_document_text),
        (
            f"{MODULE_PATH}:extract_document_to_markdown",
            worker_tasks.extract_document_to_markdown,
        ),
        (f"{MODULE_PATH}:test_allocate_bytes", worker_tasks.test_allocate_bytes),
    ],
)
def test_callable_paths_resolve_to_module_tasks(callable_path: str, expected: object) -> None:
    assert _resolve(callable_path) is expected


# ---------------------------------------------------------------------------
# Naming conflicts
# ---------------------------------------------------------------------------


def test_pytest_prefixed_helper_stays_out_of_public_registry() -> None:
    """``test_allocate_bytes`` looks like a pytest item but is a worker task.

    It must remain importable through the worker protocol while being kept out
    of ``__all__`` so the registry never presents it as a document task.
    """

    assert "test_allocate_bytes" not in worker_tasks.__all__
    task = getattr(worker_tasks, "test_allocate_bytes", None)
    assert callable(task)
    assert task.__module__ == MODULE_PATH


def test_unknown_task_attribute_lookup_fails_closed() -> None:
    """The module registers no dynamic task fallback (PEP 562 ``__getattr__``).

    A misspelled task name must fail at resolution time, not silently return a
    substitute callable.
    """

    assert not hasattr(worker_tasks, "__getattr__")
    sentinel = object()
    assert getattr(worker_tasks, "definitely_not_a_task", sentinel) is sentinel
    with pytest.raises(AttributeError):
        _ = worker_tasks.definitely_not_a_task  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("callable_path", "expected_error"),
    [
        (f"{MODULE_PATH}:definitely_not_a_task", AttributeError),
        (f"{MODULE_PATH}:__doc__", TypeError),
        (MODULE_PATH, ValueError),
        (f":{PUBLIC_TASKS[0]}", ValueError),
        (f"{MODULE_PATH}:", ValueError),
    ],
)
def test_resolver_rejects_unknown_or_malformed_task_paths(
    callable_path: str, expected_error: type[Exception]
) -> None:
    with pytest.raises(expected_error):
        _resolve(callable_path)


def test_module_level_import_is_addressable_through_task_namespace() -> None:
    """Module-level imports leak into the resolvable task namespace.

    ``Path`` is a class, so the callable-only resolver accepts it as a task
    path. The public ``__all__`` registry is therefore the only boundary that
    distinguishes real document tasks from incidental imports — which is why
    the registry tests above pin it exactly.
    """

    assert _resolve(f"{MODULE_PATH}:Path") is Path


# ---------------------------------------------------------------------------
# Task delegation
# ---------------------------------------------------------------------------


def test_extract_document_text_forwards_source_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_extract(source_path: str, **kwargs: object) -> str:
        captured.update(kwargs, source_path=source_path)
        return "extracted text"

    monkeypatch.setattr("deeptutor.utils.document_extractor.extract_text_from_path", fake_extract)
    result = worker_tasks.extract_document_text(
        "/tmp/source.pdf",
        filename_hint="source.pdf",
        max_bytes=1024,
        max_chars=None,
    )
    assert result == "extracted text"
    assert captured == {
        "source_path": "/tmp/source.pdf",
        "filename_hint": "source.pdf",
        "max_bytes": 1024,
        "max_chars": None,
    }


def test_extract_document_to_markdown_writes_extracted_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "deeptutor.utils.document_extractor.extract_text_from_path",
        lambda source_path, **kwargs: "plain body",
    )
    output = tmp_path / "notes.md"

    worker_tasks.extract_document_to_markdown(
        str(tmp_path / "notes.txt"), str(output), max_bytes=1024, max_chars=None
    )

    assert output.read_text(encoding="utf-8") == "plain body"


def test_extract_document_to_markdown_converts_bibtex_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "deeptutor.utils.document_extractor.extract_text_from_path",
        lambda source_path, **kwargs: "@article{key, title={T}}",
    )
    converted: dict[str, object] = {}

    def fake_bibtex_to_markdown(text: str, source_name: str) -> str:
        converted["text"] = text
        converted["source_name"] = source_name
        return f"# {source_name}\n\n{text}"

    monkeypatch.setattr(
        "deeptutor.utils.bibtex_converter.bibtex_to_markdown", fake_bibtex_to_markdown
    )
    output = tmp_path / "refs.md"

    worker_tasks.extract_document_to_markdown(
        str(tmp_path / "refs.bib"), str(output), max_bytes=1024, max_chars=None
    )

    assert converted == {
        "text": "@article{key, title={T}}",
        "source_name": "refs",
    }
    assert output.read_text(encoding="utf-8") == "# refs\n\n@article{key, title={T}}"


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, 0), (1, 1), (4095, 4095), (4096, 4096), (4097, 4097)],
)
def test_allocation_task_returns_requested_size(size: int, expected: int) -> None:
    assert worker_tasks.test_allocate_bytes(size) == expected
