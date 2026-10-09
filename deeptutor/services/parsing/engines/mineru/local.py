#!/usr/bin/env python
"""Run MinerU's local CLI for supported documents and images."""

import argparse
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.parsing.cache import load_ir

from .formats import MINERU_SUPPORTED_FORMATS

# Minimum seconds between on_output callbacks. MinerU's CLI emits tqdm-style
# progress that universal-newline decoding turns into many lines per second;
# without a floor the trace panel gets flooded during model downloads.
_ON_OUTPUT_MIN_INTERVAL = 0.5
# Watchdog bounds for one managed local parse (#1903): the no-progress limit
# bounds the time without an observable milestone (new output files in the
# attempt tree, or a log line the parser has not printed before); the total
# limit deliberately caps overall runtime. The two outcomes are reported as
# distinct reasons so a caller can tell them apart.
_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS = 600
_LOCAL_PARSE_TIMEOUT_SECONDS = 7200
# How long tree cleanup waits after a polite signal and after a forceful one
# before escalating (then falling back to the direct child).
_TERMINATE_GRACE_SECONDS = 3
_KILL_GRACE_SECONDS = 5

#: Upper bound on the failure excerpt carried back to callers: long enough for
#: a useful stderr tail, short enough to fit inside an error message.
_FAILURE_DETAIL_MAX_CHARS = 400


def _bounded_detail(text: str) -> str:
    """One failure excerpt, trimmed to ``_FAILURE_DETAIL_MAX_CHARS``."""
    clean = str(text or "").strip()
    if len(clean) <= _FAILURE_DETAIL_MAX_CHARS:
        return clean
    return clean[:_FAILURE_DETAIL_MAX_CHARS].rstrip() + "…"


def _signal_process_tree(pid: int, sig: int) -> bool:
    """Deliver ``sig`` to the child's whole process group (POSIX only).

    The parse child is started with ``start_new_session=True``, so ``pid`` is
    also the process-group id and the signal reaches every descendant this
    attempt started — and nothing else. Returns ``False`` when the group is
    gone or group signalling is unavailable.
    """
    if sys.platform == "win32":
        return False
    try:
        os.killpg(pid, sig)
    except OSError:
        return False
    return True


def _taskkill_tree(pid: int | None) -> None:
    """Windows OS-native recursive termination for one attempt's PID only.

    ``taskkill /T /F`` takes down the launcher and its descendants without
    ever matching unrelated processes by name.
    """
    if pid is None:
        return
    subprocess.run(  # nosec B603, B607 — fixed argv, shell=False
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
        shell=False,
    )


def _stop_process_tree(process: subprocess.Popen) -> None:
    """Stop the attempt's process tree and wait for it to settle (#1903).

    Scoped to the child this parse started: the POSIX process group above, or
    ``taskkill /T`` on the child's PID on Windows. When no tree-wide signal
    is available (fake/legacy children), the direct child is still settled.
    Escalates to a forceful signal and finally the direct child if the tree
    ignores each step, so a surviving descendant cannot hold the inherited
    stdout open past cleanup.
    """
    pid = getattr(process, "pid", None)
    if sys.platform == "win32":
        _taskkill_tree(pid)
        tree_signalled = pid is not None
    else:
        tree_signalled = pid is not None and _signal_process_tree(pid, signal.SIGTERM)
    if not tree_signalled:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    if sys.platform == "win32":
        _taskkill_tree(pid)
    elif pid is not None:
        _signal_process_tree(pid, signal.SIGKILL)
    try:
        process.wait(timeout=_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass


def _attempt_progress_snapshot(root: Path) -> tuple[int, int]:
    """Count files and bytes under ``root`` as a log-independent milestone.

    A quiet-but-working parser still grows its output tree, so the watchdog
    polls this between ticks. ``state.json`` only changes outside the
    streaming loop, so it cannot keep a dead attempt alive on its own.
    """
    files = 0
    total_bytes = 0
    try:
        for path in root.rglob("*"):
            try:
                info = path.stat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                files += 1
                total_bytes += info.st_size
    except OSError:
        return (0, 0)
    return (files, total_bytes)


def _format_timeout_detail(
    *, elapsed: float, limit: float, output_age: float, progress_age: float
) -> str:
    """Explain a deliberate maximum-runtime stop, with activity diagnostics."""
    return (
        f"maximum local parsing runtime {limit:.0f}s enforced after {elapsed:.0f}s; "
        f"last output {output_age:.0f}s ago, progress last observed {progress_age:.0f}s ago; "
        "completed checkpoints remain reusable"
    )


def _format_idle_detail(
    *, idle: float, limit: float, output_age: float, files: int, size: int
) -> str:
    """Explain a no-progress stop honestly: indeterminate, not a proven stall."""
    if output_age >= idle:
        output_state = "stdout has been silent"
    else:
        output_state = "output is still arriving but not advancing"
    return (
        f"no observable progress for {idle:.0f}s (no-progress limit {limit:.0f}s); "
        f"{output_state} ({output_age:.0f}s since the last line); "
        f"attempt output holds {files} file(s), {size} bytes; "
        "silence is not proof of a stall — a quiet but working stage is "
        "indistinguishable at this limit; completed checkpoints remain reusable"
    )


class LocalParseReason(StrEnum):
    """Why a local MinerU parse failed.

    The values mirror ``readiness.py``'s pre-flight reasons (``cli_missing``,
    ``models_missing``) so the two failure vocabularies stay aligned.
    """

    CLI_MISSING = "cli_missing"
    INPUT_MISSING = "input_missing"
    UNSUPPORTED_INPUT = "unsupported_input"
    LEGACY_CLI_INPUT = "legacy_cli_input"
    #: The no-progress watchdog fired: no observable milestone within the
    #: idle limit. Distinct from ``TIMEOUT`` (the deliberate runtime cap).
    IDLE_TIMEOUT = "idle_timeout"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    NONZERO_EXIT = "nonzero_exit"
    NO_ARTIFACTS = "no_artifacts"
    EXCEPTION = "exception"


@dataclass(frozen=True, slots=True)
class LocalParseResult:
    """Outcome of one local MinerU parse.

    ``detail`` is a bounded, user-safe excerpt (stderr tail or exception
    text), never the whole process log.
    """

    ok: bool
    reason: LocalParseReason | None = None
    detail: str = ""

    @classmethod
    def success(cls) -> "LocalParseResult":
        """A parse that wrote its artifacts."""
        return cls(ok=True)

    @classmethod
    def failure(cls, reason: LocalParseReason, detail: str = "") -> "LocalParseResult":
        """A failed parse, with the reason and its bounded excerpt."""
        return cls(ok=False, reason=reason, detail=_bounded_detail(detail))


def check_mineru_installed():
    """Check if MinerU is installed"""
    try:
        # Security: Using partial path is intentional here - we need to find
        # the command in user's PATH. These are trusted CLI tools, not user input.
        result = subprocess.run(
            ["mineru", "--version"],  # nosec B607
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            return "mineru"
    except FileNotFoundError:
        pass

    try:
        # Security: Same as above - intentionally using PATH lookup for CLI tool.
        result = subprocess.run(
            ["magic-pdf", "--version"],  # nosec B607
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            return "magic-pdf"
    except FileNotFoundError:
        pass

    return None


def parse_document_with_mineru_result(
    source_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> LocalParseResult:
    """Parse with MinerU and report *why* a failure happened.

    Same inputs as :func:`parse_document_with_mineru`, but the outcome carries
    a :class:`LocalParseReason` and a bounded ``detail`` (stderr tail or
    exception text) instead of a bare ``False``.

    Args:
        source_path: Path to a PDF, image, DOCX, PPTX, or XLSX file
        output_base_dir: Base path for output directory, defaults to reference_papers
        on_output: Optional callback invoked (rate-limited) with each line of
            the CLI's combined stdout/stderr, so callers can surface live
            progress (model downloads, per-page parsing) instead of a silent
            multi-minute subprocess. Called from this thread.
        cli_command: Explicit MinerU executable to run (the validated
            ``local_cli_path`` setting). None = auto-detect from PATH.
        extra_env: Env vars merged over os.environ for the subprocess (e.g.
            MINERU_MODEL_SOURCE / HF_ENDPOINT so a lazy first-parse model
            download honors the configured source and mirror).

    Returns:
        LocalParseResult: Whether parsing succeeded, and why it failed.
    """
    if cli_command:
        mineru_cmd = cli_command
        print(f"✓ Using configured MinerU command: {mineru_cmd}")
    else:
        mineru_cmd = check_mineru_installed()
        if not mineru_cmd:
            print("✗ Error: MinerU installation not detected")
            print("Please install MinerU first:")
            print("  pip install magic-pdf[full]")
            print("or")
            print("  pip install mineru")
            print("or visit: https://github.com/opendatalab/MinerU")
            return LocalParseResult.failure(
                LocalParseReason.CLI_MISSING,
                "neither `mineru` nor `magic-pdf` was found on PATH",
            )
        print(f"✓ Detected MinerU command: {mineru_cmd}")

    source_file = Path(source_path).resolve()
    if not source_file.exists():
        print(f"✗ Error: Input file does not exist: {source_file}")
        return LocalParseResult.failure(LocalParseReason.INPUT_MISSING, str(source_file))

    suffix = source_file.suffix.lower()
    if suffix not in MINERU_SUPPORTED_FORMATS:
        print(f"✗ Error: Unsupported MinerU input format: {source_file}")
        return LocalParseResult.failure(
            LocalParseReason.UNSUPPORTED_INPUT,
            suffix or "(no file extension)",
        )

    if Path(mineru_cmd).name == "magic-pdf" and suffix != ".pdf":
        print("✗ Error: The legacy magic-pdf CLI only accepts PDF files.")
        print("Install the current CLI with `pip install mineru` for images and Office files.")
        return LocalParseResult.failure(
            LocalParseReason.LEGACY_CLI_INPUT,
            f"magic-pdf cannot parse {suffix or '(no file extension)'}",
        )

    # Project root is 3 levels up from deeptutor/tools/question/
    project_root = Path(__file__).parent.parent.parent.parent
    if output_base_dir is None:
        base_dir = project_root / "reference_papers"
    else:
        base_dir = Path(output_base_dir)

    base_dir.mkdir(parents=True, exist_ok=True)

    source_name = source_file.stem
    output_dir = base_dir / source_name

    print(f"📄 Input file: {source_file}")
    print(f"📁 Output directory: {output_dir}")
    print("→ Starting parsing...")

    # Each CLI owns its attempt. Failed/interrupted attempts stay available,
    # while a prior usable output survives until a validated replacement (#1612).
    attempt = Path(tempfile.mkdtemp(prefix=".mineru-attempt-", dir=base_dir))
    temp_output = attempt / "output"
    temp_output.mkdir()
    state_path = attempt / "state.json"
    atomic_write_json(state_path, {"source": source_file.name, "state": "running"})
    process = None
    process_finished = False
    watchdog_stop = threading.Event()
    watchdog = None
    interrupted: list[tuple[LocalParseReason, str]] = []
    result = LocalParseResult.failure(LocalParseReason.EXCEPTION, "parse interrupted")
    try:
        cmd = [mineru_cmd, "-p", str(source_file), "-o", str(temp_output)]

        print(f"🔧 Executing command: {' '.join(cmd)}")

        # Stream combined stdout/stderr line by line. text=True enables
        # universal newlines, so tqdm's \r-rewritten progress bars arrive as
        # individual lines rather than one giant buffered blob at exit.
        # POSIX children lead their own session so cleanup can signal the
        # whole tree this attempt owns without touching unrelated processes.
        process = subprocess.Popen(  # nosec B603 — fixed argv, shell=False
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env={**os.environ, **extra_env} if extra_env else None,
            start_new_session=sys.platform != "win32",
        )
        tail: deque[str] = deque(maxlen=40)
        last_emit = 0.0
        from deeptutor.knowledge.indexing_run import IndexingCancelled, current_run

        run = current_run()
        # Output activity (any line) and meaningful progress (new output
        # files, or a line the parser has not printed before) are tracked
        # separately: repeated identical output must not read as progress,
        # and a silent stage that keeps writing files is not idle (#1903).
        activity = [time.monotonic()]
        progress = [activity[0]]
        if run is not None:
            started = activity[0]
            milestone = _attempt_progress_snapshot(attempt)

            def watch():
                nonlocal milestone
                while not watchdog_stop.wait(0.25):
                    now = time.monotonic()
                    try:
                        run.check()
                    except IndexingCancelled:
                        interrupted.append(
                            (
                                LocalParseReason.CANCELLED,
                                "Cancellation reached a safe boundary; "
                                "completed checkpoints remain reusable.",
                            )
                        )
                    except OSError:
                        interrupted.append(
                            (
                                LocalParseReason.EXCEPTION,
                                "indexing run state became unreadable",
                            )
                        )
                    if not interrupted:
                        snapshot = _attempt_progress_snapshot(attempt)
                        if snapshot != milestone:
                            # The attempt tree grew: trustworthy parser
                            # progress even while stdout stays silent.
                            milestone = snapshot
                            progress[0] = now
                    if not interrupted and now - started > _LOCAL_PARSE_TIMEOUT_SECONDS:
                        interrupted.append(
                            (
                                LocalParseReason.TIMEOUT,
                                _format_timeout_detail(
                                    elapsed=now - started,
                                    limit=_LOCAL_PARSE_TIMEOUT_SECONDS,
                                    output_age=now - activity[0],
                                    progress_age=now - progress[0],
                                ),
                            )
                        )
                    if not interrupted and now - progress[0] > _LOCAL_PARSE_IDLE_TIMEOUT_SECONDS:
                        interrupted.append(
                            (
                                LocalParseReason.IDLE_TIMEOUT,
                                _format_idle_detail(
                                    idle=now - progress[0],
                                    limit=_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS,
                                    output_age=now - activity[0],
                                    files=milestone[0],
                                    size=milestone[1],
                                ),
                            )
                        )
                    if interrupted:
                        # Settle the whole owned tree so no descendant keeps
                        # the inherited stdout open past this attempt.
                        _stop_process_tree(process)
                        return

            watchdog = threading.Thread(target=watch, daemon=True)
            watchdog.start()
        assert process.stdout is not None
        last_line: str | None = None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            seen = time.monotonic()
            activity[0] = seen
            if line != last_line:
                # A message the parser has not printed before is tentative
                # progress; exact repeats are output activity, not milestones.
                progress[0] = seen
                last_line = line
            tail.append(line)
            if on_output is not None:
                now = time.monotonic()
                if now - last_emit >= _ON_OUTPUT_MIN_INTERVAL:
                    last_emit = now
                    try:
                        on_output(line[:300])
                    except Exception:
                        # A broken callback must not kill the parse; stop
                        # reporting and keep going.
                        on_output = None
        returncode = process.wait()
        process_finished = True

        if interrupted:
            reason, detail = interrupted[0]
            result = LocalParseResult.failure(reason, detail)
            return result
        if returncode != 0:
            print("✗ MinerU parsing failed:")
            print("\n".join(tail))
            result = LocalParseResult.failure(
                LocalParseReason.NONZERO_EXIT,
                f"exit code {returncode}\n" + "\n".join(tail),
            )
            return result

        print("✓ MinerU parsing completed!")

        generated_folders = sorted(temp_output.iterdir())

        if not generated_folders:
            print("⚠️ Warning: No generated files found in temp directory")
            result = LocalParseResult.failure(
                LocalParseReason.NO_ARTIFACTS,
                f"no files were produced in {temp_output}",
            )
            return result

        named_folder = temp_output / source_name
        source_folder = named_folder if named_folder.is_dir() else temp_output
        markdown, blocks, _assets = load_ir(source_folder)
        if not markdown.strip() and not blocks:
            result = LocalParseResult.failure(
                LocalParseReason.NO_ARTIFACTS,
                "MinerU produced no usable markdown or content blocks",
            )
            return result

        backup = base_dir / f".{source_name}.previous-{uuid4().hex}"
        had_previous = output_dir.exists()
        if had_previous:
            output_dir.rename(backup)
        try:
            source_folder.rename(output_dir)
        except BaseException:
            if had_previous:
                backup.rename(output_dir)
            raise
        if had_previous:
            shutil.rmtree(backup)
        print(f"📦 Files saved to: {output_dir}")

        print("\n📋 Generated files:")
        for item in output_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(output_dir)
                print(f"  - {rel_path}")

        result = LocalParseResult.success()
        return result

    except Exception as e:
        print(f"✗ Error occurred during parsing: {e!s}")
        import traceback

        traceback.print_exc()
        result = LocalParseResult.failure(
            LocalParseReason.EXCEPTION,
            f"{type(e).__name__}: {e}",
        )
        return result
    finally:
        watchdog_stop.set()
        if watchdog is not None:
            watchdog.join(timeout=4)
        # Settle the whole tree this attempt started before another attempt
        # can publish output (#1903); direct-child termination alone leaves
        # descendants holding the inherited stdout on Windows.
        if process is not None and not process_finished:
            _stop_process_tree(process)
        if result.ok:
            shutil.rmtree(attempt, ignore_errors=True)
        else:
            try:
                atomic_write_json(
                    state_path,
                    {
                        "source": source_file.name,
                        "state": "incomplete",
                        "reason": str(result.reason),
                    },
                )
            except OSError:
                # A diagnostic write must not hide the original failure.
                pass


def parse_document_with_mineru(
    source_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> bool:
    """Parse a supported document or image using MinerU.

    Retained bool contract for existing callers; see
    :func:`parse_document_with_mineru_result` when the failure reason and its
    bounded diagnostic excerpt matter.

    Returns:
        bool: Whether parsing was successful
    """
    return parse_document_with_mineru_result(
        source_path,
        output_base_dir,
        on_output=on_output,
        cli_command=cli_command,
        extra_env=extra_env,
    ).ok


def parse_pdf_with_mineru(
    pdf_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
):
    """Backward-compatible PDF-only wrapper around the generic CLI adapter."""
    pdf_file = Path(pdf_path)
    if pdf_file.suffix.lower() != ".pdf":
        print(f"✗ Error: File is not PDF format: {pdf_file.resolve()}")
        return False
    return parse_document_with_mineru(
        pdf_path,
        output_base_dir,
        on_output=on_output,
        cli_command=cli_command,
        extra_env=extra_env,
    )


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Parse PDF files using MinerU and save results to reference_papers directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse a single PDF file
  python pdf_parser.py /path/to/paper.pdf

  # Parse PDF and specify output directory
  python pdf_parser.py /path/to/paper.pdf -o /custom/output/dir
        """,
    )

    parser.add_argument("pdf_path", type=str, help="Path to PDF file")

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Base path for output directory (default: reference_papers)",
    )

    args = parser.parse_args()

    success = parse_pdf_with_mineru(args.pdf_path, args.output)

    if success:
        print("\n✓ Parsing completed!")
        sys.exit(0)
    else:
        print("\n✗ Parsing failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
