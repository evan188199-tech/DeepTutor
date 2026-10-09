"""MinerU local lifecycle: no-progress vs max-runtime vs failure, tree cleanup.

Covers the two #1903 findings in the managed local MinerU subprocess:

* the watchdog must distinguish a healthy run (possibly quiet, possibly
  chatty-but-repeating) from a no-progress timeout and from the deliberate
  maximum-runtime cap, and must report honestly which limit fired;
* cancellation/timeout cleanup must settle the whole process tree this
  attempt started (POSIX process group, Windows ``taskkill /T`` scoped to
  the child PID), never unrelated processes.

All scenarios use fake subprocesses with short injectable limits.
"""

from __future__ import annotations

from collections.abc import Iterator
import itertools
from pathlib import Path
import signal
import subprocess
import threading

import pytest

from deeptutor.knowledge import indexing_run
from deeptutor.services.parsing.engines.mineru import local as mineru_local
from deeptutor.services.parsing.engines.mineru.local import (
    LocalParseReason,
    parse_document_with_mineru_result,
)

_NEXT_PID = itertools.count(1000)


class StubRun:
    """Minimal ``IndexingRun`` stand-in so the managed watchdog activates."""

    def __init__(self, exc: BaseException | None = None, raise_after: int = 0) -> None:
        self.exc = exc
        self.raise_after = raise_after
        self.checks = 0

    def check(self) -> None:
        self.checks += 1
        if self.exc is not None and self.checks > self.raise_after:
            raise self.exc


class FakeChild:
    """Fake MinerU CLI child with a stoppable (tree-aware) stdout stream."""

    def __init__(
        self,
        cmd: list[str],
        *,
        returncode: int = 0,
        scenario: str = "quiet",
        artifacts: tuple[str, ...] = ("exam.md",),
    ) -> None:
        self.pid = next(_NEXT_PID)
        self.cmd = cmd
        self.returncode = returncode
        self.scenario = scenario
        self.artifacts = artifacts
        self.stop = threading.Event()
        self.calls: list[str] = []
        self.exited = threading.Event()
        self.stdout = self._stream()

    def _target(self) -> Path:
        return Path(self.cmd[self.cmd.index("-o") + 1])

    def _stream(self) -> Iterator[str]:
        target = self._target()
        if self.scenario == "milestones":
            # Quiet stdout while the parser writes checkpoint files.
            for index in range(8):
                (target / f"chunk-{index}.md").write_text(f"# chunk {index}\n", encoding="utf-8")
                if self.stop.wait(0.15):
                    return
            for name in self.artifacts:
                (target / name).write_text("# parsed", encoding="utf-8")
        elif self.scenario == "repeat":
            while not self.stop.wait(0.1):
                yield "waiting for accelerator"
        elif self.scenario == "distinct":
            index = 0
            while not self.stop.wait(0.1):
                yield f"parsing page {index}"
                index += 1
        elif self.scenario == "one-line":
            yield "starting"
        else:
            # "quiet": no output at all; EOF only once the tree is settled.
            self.stop.wait()
        self.exited.set()

    def poll(self) -> int | None:
        if self.exited.is_set() or self.stop.is_set():
            return self.returncode
        return None

    def terminate(self) -> None:
        self.calls.append("terminate")
        self.stop.set()

    def kill(self) -> None:
        self.calls.append("kill")
        self.stop.set()

    def wait(self, timeout: float | None = None) -> int:
        if not (self.exited.is_set() or self.stop.is_set()):
            if timeout is None:
                self.stop.wait()
            elif not self.stop.wait(timeout):
                raise subprocess.TimeoutExpired(cmd="mineru", timeout=timeout)
        return self.returncode


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"%PDF-1.4")
    return source


def _install(
    monkeypatch: pytest.MonkeyPatch,
    child_holder: dict[FakeChild | None],
    *,
    scenario: str = "quiet",
    returncode: int = 0,
    artifacts: tuple[str, ...] = ("exam.md",),
    run: StubRun | None = StubRun(),
    idle: float = 0.5,
    total: float = 60.0,
) -> None:
    def start(cmd, **_kwargs) -> FakeChild:  # noqa: ANN001, ANN003
        child = FakeChild(cmd, returncode=returncode, scenario=scenario, artifacts=artifacts)
        child_holder["child"] = child
        return child

    monkeypatch.setattr(mineru_local.subprocess, "Popen", start)
    monkeypatch.setattr(mineru_local, "_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS", idle)
    monkeypatch.setattr(mineru_local, "_LOCAL_PARSE_TIMEOUT_SECONDS", total)
    monkeypatch.setattr(indexing_run, "current_run", lambda: run)


def _install_tree_signals(
    monkeypatch: pytest.MonkeyPatch,
    child_holder: dict[FakeChild | None],
    *,
    settle_on: set[int],
) -> list[tuple[int, int]]:
    """Patch the POSIX group-signal helper; record (pid, signal) deliveries."""
    delivered: list[tuple[int, int]] = []

    def fake_signal(pid: int, sig: int) -> bool:
        delivered.append((pid, sig))
        if sig in settle_on and child_holder.get("child") is not None:
            child_holder["child"].stop.set()
        return True

    monkeypatch.setattr(mineru_local, "_signal_process_tree", fake_signal)
    return delivered


# ---------------------------------------------------------------------------
# Watchdog state classification (#1903 part 1)
# ---------------------------------------------------------------------------


def test_quiet_child_with_file_milestones_is_not_interrupted(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent-but-working parser keeps refreshing file milestones."""
    holder: dict[FakeChild | None] = {}
    _install(monkeypatch, holder, scenario="milestones", idle=0.4, total=60.0)
    _install_tree_signals(monkeypatch, holder, settle_on=set())

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.ok is True, result.detail
    child = holder["child"]
    assert child is not None and child.calls == []


def test_silent_child_reports_no_progress_timeout_honestly(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No output and no file growth: bounded stop, indeterminate wording."""
    holder: dict[FakeChild | None] = {}
    _install(monkeypatch, holder, scenario="quiet", idle=0.5, total=60.0)
    signals = _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.ok is False
    assert result.reason is LocalParseReason.IDLE_TIMEOUT
    assert "no observable progress" in result.detail
    assert "not proof of a stall" in result.detail
    child = holder["child"]
    assert child is not None and signals == [(child.pid, signal.SIGTERM)]
    assert child.calls == []


def test_repeated_identical_output_is_not_progress(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh but identical lines must not keep a stuck child alive."""
    holder: dict[FakeChild | None] = {}
    _install(monkeypatch, holder, scenario="repeat", idle=0.6, total=60.0)
    _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.IDLE_TIMEOUT
    assert "not advancing" in result.detail


def test_total_runtime_cap_is_distinguishable_from_no_progress(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct progress lines keep the idle clock fresh; the total cap still bounds."""
    holder: dict[FakeChild | None] = {}
    _install(monkeypatch, holder, scenario="distinct", idle=60.0, total=0.8)
    _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.TIMEOUT
    assert "maximum local parsing runtime" in result.detail
    assert result.reason is not LocalParseReason.IDLE_TIMEOUT


def test_runtime_failure_keeps_its_own_reason(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder: dict[FakeChild | None] = {}
    _install(monkeypatch, holder, scenario="one-line", returncode=7)

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.NONZERO_EXIT


def test_watchdog_states_are_distinguishable(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """running / no-progress / total-limit / failure are four distinct states."""
    states: dict[str, LocalParseReason | None] = {}

    def run_case(scenario: str, **kwargs) -> None:  # noqa: ANN003
        holder: dict[FakeChild | None] = {}
        _install(monkeypatch, holder, scenario=scenario, **kwargs)
        _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})
        outcome = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")
        states[scenario] = outcome.reason

    run_case("milestones", idle=0.4, total=60.0)
    run_case("quiet", idle=0.5, total=60.0)
    run_case("distinct", idle=60.0, total=0.8)
    run_case("one-line", returncode=7)

    assert states["milestones"] is None  # running → success
    assert states["quiet"] is LocalParseReason.IDLE_TIMEOUT
    assert states["distinct"] is LocalParseReason.TIMEOUT
    assert states["one-line"] is LocalParseReason.NONZERO_EXIT
    assert len({str(value) for value in states.values()}) == 4


# ---------------------------------------------------------------------------
# Process-tree settlement (#1903 part 2)
# ---------------------------------------------------------------------------


def test_cancellation_settles_owned_process_tree(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task-scoped cancellation reaches the whole tree via the group signal."""
    holder: dict[FakeChild | None] = {}
    stub = StubRun(indexing_run.IndexingCancelled("cancelled"), raise_after=1)
    _install(monkeypatch, holder, scenario="quiet", run=stub)
    signals = _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.CANCELLED
    child = holder["child"]
    assert child is not None and signals == [(child.pid, signal.SIGTERM)]
    # The group signal settled the tree; the direct-child fallback never ran.
    assert child.calls == []


def test_windows_cleanup_uses_scoped_taskkill(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows the tree is settled by taskkill /T on this child's PID only."""
    holder: dict[FakeChild | None] = {}
    stub = StubRun(indexing_run.IndexingCancelled("cancelled"), raise_after=1)
    _install(monkeypatch, holder, scenario="quiet", run=stub)
    monkeypatch.setattr(mineru_local.sys, "platform", "win32")
    killed: list[int] = []

    def fake_taskkill(pid: int | None) -> None:
        assert pid is not None
        killed.append(pid)
        child = holder.get("child")
        if child is not None:
            child.stop.set()

    monkeypatch.setattr(mineru_local, "_taskkill_tree", fake_taskkill)

    def no_posix_signal(pid: int, sig: int) -> bool:
        raise AssertionError("POSIX group signal must not run on Windows")

    monkeypatch.setattr(mineru_local, "_signal_process_tree", no_posix_signal)

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.CANCELLED
    child = holder["child"]
    assert child is not None and killed == [child.pid]
    assert child.calls == []


def test_tree_stop_escalates_when_terminate_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tree that survives SIGTERM is escalated to SIGKILL, then direct kill."""
    holder: dict[FakeChild | None] = {}
    child = FakeChild(["mineru", "-p", "x", "-o", str(tmp_path)])
    holder["child"] = child
    monkeypatch.setattr(mineru_local, "_TERMINATE_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(mineru_local, "_KILL_GRACE_SECONDS", 0.1)
    # Signals are delivered but ignored; the last-resort direct kill settles.
    signals = _install_tree_signals(monkeypatch, holder, settle_on=set())

    mineru_local._stop_process_tree(child)

    assert [sig for _pid, sig in signals] == [signal.SIGTERM, signal.SIGKILL]
    assert child.calls == ["kill"]  # last-resort direct kill ran


def test_tree_stop_falls_back_to_direct_child_without_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no tree-wide signal is available the direct child still settles."""
    child = FakeChild(["mineru", "-p", "x", "-o", str(tmp_path)])
    monkeypatch.setattr(mineru_local, "_TERMINATE_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(mineru_local, "_KILL_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(mineru_local, "_signal_process_tree", lambda pid, sig: False)

    mineru_local._stop_process_tree(child)

    assert child.calls == ["terminate"]


def test_keyboard_interrupt_settles_tree_in_finally(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The finally path also recycles the whole tree, not just the launcher."""

    class InterruptedChild(FakeChild):
        def _stream(self) -> Iterator[str]:
            yield "parsing page 2"
            self.exited.set()
            raise KeyboardInterrupt

    holder: dict[FakeChild | None] = {}

    def start(cmd, **_kwargs) -> InterruptedChild:  # noqa: ANN001, ANN003
        child = InterruptedChild(cmd)
        holder["child"] = child
        return child

    monkeypatch.setattr(mineru_local.subprocess, "Popen", start)
    signals = _install_tree_signals(monkeypatch, holder, settle_on={signal.SIGTERM})

    with pytest.raises(KeyboardInterrupt):
        parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    child = holder["child"]
    assert child is not None and signals == [(child.pid, signal.SIGTERM)]
    assert child.calls == []
