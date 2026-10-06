"""Timeout teardown baselines for the two parsing-path HIGH subprocess gaps.

Scope: the scan report ``evidence/subprocess-timeouts-20261005/report.md``
(baseline ``origin/main`` ``f07029cfc``) grades four HIGH spawn sites without
timeout or kill coverage. This module baselines two of them — the pair that
the report's fix-card proposal B groups together:

- H2 ``deeptutor/services/parsing/engines/docling/local_worker.py:52``
  (``Popen``, line-read stdout; kill machinery ``_stop_worker`` exists at
  ``:85`` but is reachable only via exceptions, so a stalled worker blocks
  ``for raw_line in process.stdout`` forever).
- H3 ``deeptutor/services/parsing/engines/mineru/local.py:216``
  (``Popen``, line-read stdout; no watchdog — the exception-reachable
  ``finally`` teardown at ``:311`` cannot run while the stdout iteration is
  blocked on a silent child, so a stalled MinerU CLI blocks the parse
  forever).

The tests never spawn a real process: ``Popen`` is monkeypatched and the fake
child lives entirely in memory (no ``os.exec``, no real pipe, no real wait).
Each "hang" test bounds its own stall with a give-up timer, so the suite stays
fast whether or not the fix has landed.

Red/green ratchet: the hang tests assert the *desired* watchdog behaviour
(stall -> terminate -> wait grace -> kill) and are marked
``xfail(strict=True)`` until fix card B lands. When the fix arrives they
XPASS, which fails the suite on purpose: remove the marker in the same PR and
patch the newly configurable watchdog threshold below
``_STALL_GIVE_UP_SECONDS`` so the kill is observable here.

The three green tests lock the teardown machinery the fix must keep reusing:
docling's ``_stop_worker`` terminate -> wait(5) -> kill escalation
(``local_worker.py:85``) and mineru's ``finally`` terminate -> wait(3) -> kill
escalation (``local.py:311``) — and must not bypass a graceful terminate with
a bare ``kill`` when the child cooperates.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import time

import pytest

from deeptutor.services.parsing.engines.docling import local_worker as docling_local_worker
from deeptutor.services.parsing.engines.docling.config import DoclingConfig
from deeptutor.services.parsing.engines.mineru import local as mineru_local

# Upper bound on how long a fake worker may stay stalled before the test
# unblocks it. Every hang test finishes in about this many seconds; once fix
# card B lands, the configured watchdog threshold must be patched below this
# window so the terminate->kill is observed before the give-up fires.
_STALL_GIVE_UP_SECONDS = 3.0


class _FakeWorkerProcess:
    """In-memory stand-in for the parsing subprocess.

    The fake queues a few stdout lines, then stalls as if the worker went
    silent mid-run. ``terminate()`` only records the flag unless the process
    is cooperative; ``kill()`` always finishes it (exit code ``-9``). A test
    can hand in a ``release`` event that ends the stall, after which the fake
    behaves as if the worker had exited on its own with code ``0``.
    """

    def __init__(
        self,
        lines: tuple[str, ...] = (),
        *,
        release: threading.Event | None = None,
        stubborn: bool = True,
        explode: BaseException | None = None,
    ) -> None:
        self._lines = list(lines)
        self._cursor = 0
        self._lock = threading.Lock()
        self._stubborn = stubborn
        self.explode = explode
        self.stdout = _StallingStdout(self)
        self.terminated = threading.Event()
        self.killed = threading.Event()
        self._finished = threading.Event()
        self._exit_code = 0
        self._release = release if release is not None else threading.Event()

    # -- stdout feed -------------------------------------------------------
    def next_line(self) -> str | None:
        with self._lock:
            if self._cursor < len(self._lines):
                line = self._lines[self._cursor]
                self._cursor += 1
                return line
        return None

    @property
    def released(self) -> bool:
        return self._release.is_set()

    # -- Popen-compatible surface -------------------------------------------
    def poll(self) -> int | None:
        if self._finished.is_set():
            return self._exit_code
        if self.released:
            return 0
        return None

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._finished.wait(0.02):
                return self._exit_code
            if self.released:
                return 0
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd="fake-parsing-worker", timeout=timeout)

    def terminate(self) -> None:
        self.terminated.set()
        if not self._stubborn:
            self._exit_code = -15
            self._finished.set()

    def kill(self) -> None:
        self.killed.set()
        self._exit_code = -9
        self._finished.set()


class _StallingStdout:
    """Line iterator that stalls once the queued lines are consumed."""

    def __init__(self, process: _FakeWorkerProcess) -> None:
        self._process = process

    def __iter__(self) -> _StallingStdout:
        return self

    def __next__(self) -> str:
        process = self._process
        line = process.next_line()
        if line is not None:
            return line
        if process.explode is not None:
            raise process.explode
        while True:
            # A killed worker closes its pipe; a released stall ends the test.
            if process.killed.wait(0.02) or process.released:
                raise StopIteration


def _give_up_timer(release: threading.Event) -> threading.Timer:
    return threading.Timer(_STALL_GIVE_UP_SECONDS, release.set)


# ---------------------------------------------------------------------------
# H2 docling local worker — report row H2, local_worker.py:52
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "Report H2: parse_local has no parse-level watchdog; a stalled worker "
        "blocks the stdout iteration forever and _stop_worker (terminate->kill) "
        "is reachable only via exceptions. xfail(strict) until fix card B adds "
        "the watchdog; patch its threshold below _STALL_GIVE_UP_SECONDS then."
    ),
    strict=True,
)
def test_docling_stalled_worker_is_terminated_then_killed(tmp_path, monkeypatch) -> None:
    """A silent docling worker must be torn down within the parse timeout."""
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    release = threading.Event()
    fake = _FakeWorkerProcess(("worker: loading model\n",), release=release)
    monkeypatch.setattr(docling_local_worker.subprocess, "Popen", lambda *_a, **_k: fake)

    give_up = _give_up_timer(release)
    give_up.start()
    try:
        with contextlib.suppress(Exception):
            docling_local_worker.parse_local(
                source,
                workdir,
                config=DoclingConfig(mode="local"),
            )
    finally:
        give_up.cancel()

    assert fake.killed.is_set(), (
        "stalled docling worker was never terminated and killed "
        f"within {_STALL_GIVE_UP_SECONDS}s"
    )


def test_docling_stream_failure_stops_worker_cooperatively(tmp_path, monkeypatch) -> None:
    """Report H2: the exception-reachable kill path must keep working.

    Green baseline for the machinery fix card B reuses: a broken stdout
    triggers ``_stop_worker`` and a cooperative terminate is enough (no kill).
    """
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    boom = RuntimeError("docling worker stream exploded")
    fake = _FakeWorkerProcess(("worker: starting\n",), stubborn=False, explode=boom)
    monkeypatch.setattr(docling_local_worker.subprocess, "Popen", lambda *_a, **_k: fake)

    with pytest.raises(RuntimeError):
        docling_local_worker.parse_local(
            source,
            workdir,
            config=DoclingConfig(mode="local"),
        )

    assert fake.terminated.is_set()
    assert not fake.killed.is_set()


def test_docling_stop_worker_escalates_to_kill_when_terminate_is_ignored(
    tmp_path,
    monkeypatch,
) -> None:
    """Report H2: a worker that ignores SIGTERM is escalated to kill."""
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    boom = RuntimeError("docling worker stream exploded")
    fake = _FakeWorkerProcess(("worker: starting\n",), stubborn=True, explode=boom)
    monkeypatch.setattr(docling_local_worker.subprocess, "Popen", lambda *_a, **_k: fake)

    with pytest.raises(RuntimeError):
        docling_local_worker.parse_local(
            source,
            workdir,
            config=DoclingConfig(mode="local"),
        )

    assert fake.terminated.is_set()
    assert fake.killed.is_set()


# ---------------------------------------------------------------------------
# H3 mineru local CLI — report row H3, local.py:216
# ---------------------------------------------------------------------------


def _mineru_inputs(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    out_base = tmp_path / "parsed"
    out_base.mkdir()
    return str(source), str(out_base)


@pytest.mark.xfail(
    reason=(
        "Report H3: parse_document_with_mineru has no parse-level watchdog; a "
        "stalled MinerU CLI blocks the stdout iteration forever, so the "
        "finally teardown at local.py:311 never runs. xfail(strict) until fix "
        "card B adds the watchdog; patch its threshold below "
        "_STALL_GIVE_UP_SECONDS then."
    ),
    strict=True,
)
def test_mineru_stalled_cli_is_terminated_then_killed(tmp_path, monkeypatch) -> None:
    """A silent MinerU CLI must be torn down within the parse timeout."""
    source, out_base = _mineru_inputs(tmp_path)

    release = threading.Event()
    fake = _FakeWorkerProcess(("parsing page 1\n",), release=release)
    monkeypatch.setattr(mineru_local.subprocess, "Popen", lambda *_a, **_k: fake)

    give_up = _give_up_timer(release)
    give_up.start()
    try:
        with contextlib.suppress(Exception):
            mineru_local.parse_document_with_mineru(
                source,
                out_base,
                cli_command="fake-mineru-cli",
            )
    finally:
        give_up.cancel()

    assert fake.killed.is_set(), (
        "stalled MinerU CLI was never terminated and killed "
        f"within {_STALL_GIVE_UP_SECONDS}s"
    )


def test_mineru_stream_failure_stops_cli_process(tmp_path, monkeypatch) -> None:
    """Report H3: a broken MinerU stdout must not leak the CLI process.

    Green baseline for the machinery fix card B reuses: the ``finally``
    teardown (``local.py:311``) escalates terminate -> wait(3) -> kill for a
    stubborn child, and the parse still reports failure instead of raising.
    """
    source, out_base = _mineru_inputs(tmp_path)

    boom = RuntimeError("mineru stream exploded")
    fake = _FakeWorkerProcess(("parsing page 1\n",), stubborn=True, explode=boom)
    monkeypatch.setattr(mineru_local.subprocess, "Popen", lambda *_a, **_k: fake)

    result = mineru_local.parse_document_with_mineru(
        source,
        out_base,
        cli_command="fake-mineru-cli",
    )

    assert result is False
    assert fake.terminated.is_set()
    assert fake.killed.is_set()
