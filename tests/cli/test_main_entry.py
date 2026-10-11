"""Contracts for the ``python -m deeptutor`` module entry (``deeptutor/__main__.py``).

The module entry is a thin forwarder: it must re-export the CLI ``main`` and,
when executed as ``__main__``, delegate the whole invocation (argv parsing and
exit-code surface) to it. These tests stub ``main`` entirely — no real CLI run,
no network, no service processes.
"""

from __future__ import annotations

import importlib
import runpy
import sys
from types import ModuleType

import pytest


def _cli_main_module() -> ModuleType:
    return importlib.import_module("deeptutor_cli.main")


def test_main_module_reexports_cli_main() -> None:
    """``deeptutor.__main__.main`` is the CLI entry, not a private copy."""
    entry = importlib.import_module("deeptutor.__main__")
    cli_main = _cli_main_module()

    assert entry.main is cli_main.main


def test_python_m_deeptutor_invokes_cli_main_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running the package as ``__main__`` calls ``main`` exactly once, with no args.

    The entry must not consume or rewrite ``sys.argv`` — argv handling stays
    downstream in the typer app (argument pass-through contract).
    """
    cli_main = _cli_main_module()
    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(cli_main, "main", lambda *args, **kwargs: calls.append((args, kwargs)))

    argv = sys.argv
    sys.argv = ["deeptutor", "kb", "list"]
    try:
        runpy.run_module("deeptutor", run_name="__main__", alter_sys=True)
    finally:
        sys.argv = argv

    assert calls == [((), {})]


def test_python_m_deeptutor_propagates_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``SystemExit`` raised by the CLI main propagates out of the module run."""
    cli_main = _cli_main_module()

    def _failing_main(*args: object, **kwargs: object) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(cli_main, "main", _failing_main)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("deeptutor", run_name="__main__", alter_sys=True)

    assert excinfo.value.code == 7


def test_python_m_deeptutor_normal_completion_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful CLI main returns cleanly from the module run (exit code 0 path)."""
    cli_main = _cli_main_module()
    monkeypatch.setattr(cli_main, "main", lambda *args, **kwargs: None)

    runpy.run_module("deeptutor", run_name="__main__", alter_sys=True)
