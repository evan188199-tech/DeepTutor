"""Probe contract of ``check_mineru_installed`` (local MinerU engine).

Three probe paths are locked here so a fix cannot silently regress them:

1. binary missing — an absent candidate falls through to the next one and
   nothing usable on PATH means ``None``. Sibling launch failures
   (``PermissionError`` for a non-executable file, ``NotADirectoryError``
   for a file sitting where a PATH entry should be) must degrade the same
   way instead of crashing the caller.
2. non-zero exit — a CLI whose ``--version`` probe fails is unhealthy but
   still installed: reporting it as "not installed" distorts the
   availability conclusion this probe exists to produce and contradicts
   the backend message contract ("a runtime failure must not be reported
   as a missing installation", see ``backend._LOCAL_FAILURE_MESSAGES``).
   A healthy fallback CLI is still preferred over a broken first choice.
3. malformed version output — exit code 0 is the only acceptance signal;
   version text is never parsed, whatever the probe printed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import shutil
import subprocess

import pytest

from deeptutor.services.parsing.engines.mineru import local as mineru_local
from deeptutor.services.parsing.engines.mineru.local import check_mineru_installed


@dataclass(frozen=True)
class ProbeOutcome:
    """One candidate's simulated ``--version`` result.

    ``error`` simulates a spawn failure (the probe never reaches a
    returncode); ``returncode``/``stdout``/``stderr`` simulate a launched
    probe. An unlisted candidate behaves as absent.
    """

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    error: BaseException | None = None


ABSENT = ProbeOutcome(error=FileNotFoundError(2, "No such file or directory"))


class FakeProbes:
    """Simulated PATH for the ``mineru``/``magic-pdf`` version probes.

    Patches both ``subprocess.run`` and ``shutil.which`` consistently, so
    the contract holds no matter whether a fix probes via exec (today) or
    resolves presence via ``shutil.which`` first: a candidate is visible
    to ``which`` exactly when its outcome models a launchable file (no
    ``error``), and its ``subprocess.run`` then yields the configured
    result. Calls are recorded for debugging, but tests pin only the
    observable return contract.
    """

    def __init__(self, outcomes: dict[str, ProbeOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        self.calls.append(command)
        assert command[1:] == ("--version",), "the probe must ask for --version"
        assert kwargs.get("capture_output") is True, "probe output must be captured"
        assert kwargs.get("check") is False, "a failed probe must not raise"
        assert kwargs.get("shell") is False, "the probe must not use a shell"
        outcome = self.outcomes.get(command[0], ABSENT)
        if outcome.error is not None:
            raise outcome.error
        return subprocess.CompletedProcess(
            list(argv), outcome.returncode, outcome.stdout, outcome.stderr
        )

    def which(self, cmd: str, mode: int = 0o111, path: object = None) -> str | None:
        outcome = self.outcomes.get(cmd)
        if outcome is None or outcome.error is not None:
            return None
        return f"/usr/local/bin/{cmd}"


@pytest.fixture()
def probes(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, ProbeOutcome]], FakeProbes]:
    """Install a :class:`FakeProbes` as the probe's entire PATH view."""

    def _install(outcomes: dict[str, ProbeOutcome]) -> FakeProbes:
        fake = FakeProbes(outcomes)
        monkeypatch.setattr(mineru_local.subprocess, "run", fake.run)
        monkeypatch.setattr(shutil, "which", fake.which)
        return fake

    return _install


# ---------------------------------------------------------------------------
# Path 1 — binary missing
# ---------------------------------------------------------------------------


def test_both_candidates_absent_returns_none(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """Nothing usable on PATH means ``None`` — and never an exception."""
    probes({})

    assert check_mineru_installed() is None


def test_first_candidate_absent_falls_through_to_second(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """An absent ``mineru`` must not hide a healthy ``magic-pdf``."""
    probes(
        {
            "mineru": ABSENT,
            "magic-pdf": ProbeOutcome(returncode=0, stdout="magic-pdf 1.2.3"),
        }
    )

    assert check_mineru_installed() == "magic-pdf"


def test_unlaunchable_binary_degrades_to_none(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """A present-but-not-executable binary (``PermissionError`` on exec) is
    a launch failure: the probe must degrade exactly like a missing binary
    instead of crashing the caller (baseline raises ``PermissionError``)."""
    probes({"mineru": ProbeOutcome(error=PermissionError(13, "Permission denied"))})

    assert check_mineru_installed() is None


def test_broken_path_entry_degrades_to_none(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """A file sitting where a PATH directory should be (``NotADirectoryError``
    on exec) must degrade to "unavailable", never propagate (baseline raises
    ``NotADirectoryError``)."""
    probes({"mineru": ProbeOutcome(error=NotADirectoryError(20, "Not a directory"))})

    assert check_mineru_installed() is None


# ---------------------------------------------------------------------------
# Path 2 — subprocess non-zero exit
# ---------------------------------------------------------------------------


def test_healthy_fallback_preferred_over_broken_first(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """A working ``magic-pdf`` beats a ``mineru`` whose probe fails."""
    probes(
        {
            "mineru": ProbeOutcome(returncode=1, stderr="ModuleNotFoundError: pypdfium2"),
            "magic-pdf": ProbeOutcome(returncode=0, stdout="magic-pdf 1.2.3"),
        }
    )

    assert check_mineru_installed() == "magic-pdf"


def test_broken_install_is_not_reported_missing(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """``mineru`` exists but its version probe fails: it is installed but
    unhealthy. Answering ``None`` makes callers print "please pip install"
    for a CLI already on PATH and hides the real error (baseline returns
    ``None`` here — the availability distortion this suite exists for)."""
    probes({"mineru": ProbeOutcome(returncode=1, stderr="ModuleNotFoundError: pypdfium2")})

    assert check_mineru_installed() == "mineru"


# ---------------------------------------------------------------------------
# Path 3 — malformed version output
# ---------------------------------------------------------------------------


def test_garbage_version_output_still_counts_installed(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """Exit code 0 is the acceptance signal; version text is never parsed."""
    probes({"mineru": ProbeOutcome(returncode=0, stdout="💥 definitely not a version\n")})

    assert check_mineru_installed() == "mineru"


def test_empty_version_output_still_counts_installed(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """A silent-but-successful probe still proves the CLI launches."""
    probes({"mineru": ProbeOutcome(returncode=0, stdout="", stderr="")})

    assert check_mineru_installed() == "mineru"


def test_stderr_only_version_output_still_counts_installed(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """CLIs that print their version to stderr still count as installed."""
    probes({"mineru": ProbeOutcome(returncode=0, stdout="", stderr="mineru 2.1.0")})

    assert check_mineru_installed() == "mineru"


def test_malformed_output_does_not_change_preference_order(
    probes: Callable[[dict[str, ProbeOutcome]], FakeProbes],
) -> None:
    """A malformed-but-successful ``mineru`` still wins over ``magic-pdf``."""
    probes(
        {
            "mineru": ProbeOutcome(returncode=0, stdout=""),
            "magic-pdf": ProbeOutcome(returncode=0, stdout="magic-pdf 1.2.3"),
        }
    )

    assert check_mineru_installed() == "mineru"
