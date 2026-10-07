"""Tests for the ``python -m deeptutor`` entry module."""

from __future__ import annotations

import runpy
from unittest import mock

import deeptutor.__main__ as main_module
from deeptutor_cli.main import main as cli_main


def test_module_reexports_the_cli_entrypoint() -> None:
    assert main_module.main is cli_main
    assert callable(main_module.main)


def test_running_as_main_invokes_the_cli_once() -> None:
    with mock.patch("deeptutor_cli.main.main") as cli_mock:
        runpy.run_module("deeptutor", run_name="__main__")

    cli_mock.assert_called_once_with()


def test_importing_as_a_module_does_not_invoke_the_cli() -> None:
    with mock.patch("deeptutor_cli.main.main") as cli_mock:
        runpy.run_module("deeptutor", run_name="deeptutor.__main__")

    cli_mock.assert_not_called()
