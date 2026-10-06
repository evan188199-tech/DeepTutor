"""Contract tests for the isolated Docling local worker.

The worker runs Docling in a fresh interpreter (``python -m``) so its PyTorch
runtime never shares a process with FAISS. These tests exercise both sides of
that boundary against a stub ``docling`` package placed on ``PYTHONPATH``:

- parent side: :func:`parse_local` task startup, streamed progress events, and
  failure reporting;
- worker side: ``main`` exit codes, the ``TypeName: message`` stderr contract,
  and the markdown artifact written into the workdir.

No real Docling installation (or download) is required.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from deeptutor.services.parsing.engines.docling import local_worker
from deeptutor.services.parsing.engines.docling.config import DoclingConfig
from deeptutor.services.parsing.types import ParserError

_PROGRESS_READY = "stub docling: engine ready"
_PROGRESS_PAGES = "stub docling: pages 1-3 parsed"
_FAILURE_MESSAGE = "stub engine exploded mid-conversion"
_STUB_MARKDOWN = "# stub markdown"

_REPO_ROOT = Path(local_worker.__file__).resolve().parents[5]


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 stub")
    return source


def _write_stub_engine(stub_root: Path) -> None:
    """A fake ``docling`` package whose converter prints progress, fails on
    request via ``DOCLING_STUB_FAIL=1`` and yields a fixed markdown payload."""
    package = stub_root / "docling"
    datamodel = package / "datamodel"
    datamodel.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "document_converter.py").write_text(
        "\n".join(
            [
                "import os",
                "",
                "",
                "class PdfFormatOption:",
                "    def __init__(self, pipeline_options=None):",
                "        self.pipeline_options = pipeline_options",
                "",
                "",
                "class DocumentConverter:",
                "    def __init__(self, format_options=None):",
                "        self.format_options = format_options",
                "",
                "    def convert(self, source):",
                f"        print({_PROGRESS_READY!r}, flush=True)",
                "        if os.environ.get('DOCLING_STUB_FAIL') == '1':",
                f"            raise RuntimeError({_FAILURE_MESSAGE!r})",
                f"        print({_PROGRESS_PAGES!r}, flush=True)",
                "",
                "        class _Document:",
                "            def export_to_markdown(self):",
                f"                return {_STUB_MARKDOWN!r}",
                "",
                "        class _Result:",
                "            document = _Document()",
                "",
                "        return _Result()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (datamodel / "__init__.py").write_text("", encoding="utf-8")
    (datamodel / "base_models.py").write_text(
        "class InputFormat:\n    PDF = 'pdf'\n", encoding="utf-8"
    )
    (datamodel / "pipeline_options.py").write_text(
        "class PdfPipelineOptions:\n"
        "    def __init__(self):\n"
        "        self.do_ocr = False\n"
        "        self.do_table_structure = False\n",
        encoding="utf-8",
    )


def _write_missing_engine_stub(stub_root: Path) -> None:
    package = stub_root / "docling"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "raise ImportError('docling stub: package intentionally unavailable')\n",
        encoding="utf-8",
    )


def _point_pythonpath(monkeypatch: pytest.MonkeyPatch, stub_root: Path) -> None:
    parts = [str(stub_root), str(_REPO_ROOT)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(parts))


class _FakeStreamProcess:
    def __init__(self, lines, returncode: int, poll_return: int | None = None) -> None:
        self.stdout = iter(lines)
        self._returncode = returncode
        self._poll_return = poll_return
        self.waits: list[int | None] = []
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self._returncode

    def poll(self):
        return self._poll_return

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_parse_local_success_streams_progress_and_writes_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_root = tmp_path / "stub-engine"
    _write_stub_engine(stub_root)
    _point_pythonpath(monkeypatch, stub_root)
    source = _source(tmp_path)
    workdir = tmp_path / "parsed"
    events: list[str] = []

    local_worker.parse_local(
        source,
        workdir,
        config=DoclingConfig(mode="local", do_ocr=True, do_table_structure=False),
        on_output=events.append,
    )

    assert events == [
        _PROGRESS_READY,
        _PROGRESS_PAGES,
        "Converted lesson.pdf with isolated Docling",
    ]
    assert all(event == event.strip() and event for event in events)
    assert (workdir / "lesson.md").read_text(encoding="utf-8") == _STUB_MARKDOWN


def test_parse_local_reports_mid_conversion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_root = tmp_path / "stub-engine"
    _write_stub_engine(stub_root)
    _point_pythonpath(monkeypatch, stub_root)
    monkeypatch.setenv("DOCLING_STUB_FAIL", "1")
    source = _source(tmp_path)
    events: list[str] = []

    with pytest.raises(ParserError, match="exited with code 1") as excinfo:
        local_worker.parse_local(
            source,
            tmp_path / "parsed",
            config=DoclingConfig(mode="local"),
            on_output=events.append,
        )

    assert "RuntimeError: stub engine exploded mid-conversion" in str(excinfo.value)
    assert events[0] == _PROGRESS_READY


def test_parse_local_engine_missing_reports_import_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_root = tmp_path / "stub-missing"
    _write_missing_engine_stub(stub_root)
    _point_pythonpath(monkeypatch, stub_root)
    source = _source(tmp_path)

    with pytest.raises(ParserError, match="exited with code 1") as excinfo:
        local_worker.parse_local(source, tmp_path / "parsed", config=DoclingConfig(mode="local"))

    assert "ImportError: docling stub: package intentionally unavailable" in str(excinfo.value)


def test_parse_local_start_failure_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_popen(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(local_worker.subprocess, "Popen", broken_popen)

    with pytest.raises(ParserError, match="Could not start the isolated Docling worker"):
        local_worker.parse_local(
            _source(tmp_path), tmp_path / "parsed", config=DoclingConfig(mode="local")
        )


def test_parse_local_error_tail_is_capped_at_twenty_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [f"diag-{index:02d}" for index in range(25)]
    process = _FakeStreamProcess(iter(lines), returncode=1)
    monkeypatch.setattr(local_worker.subprocess, "Popen", lambda *_a, **_k: process)

    with pytest.raises(ParserError) as excinfo:
        local_worker.parse_local(
            _source(tmp_path), tmp_path / "parsed", config=DoclingConfig(mode="local")
        )

    message = str(excinfo.value)
    assert message.startswith("Docling worker exited with code 1:")
    assert "diag-00" not in message
    assert "diag-04" not in message
    assert "diag-05" in message
    assert "diag-24" in message


def test_parse_local_stops_worker_when_output_consumer_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeStreamProcess(iter(["line-1", "line-2"]), returncode=0)
    monkeypatch.setattr(local_worker.subprocess, "Popen", lambda *_a, **_k: process)

    def consume(event: str) -> None:
        if event == "line-2":
            raise ValueError("consumer boom")

    with pytest.raises(ValueError, match="consumer boom"):
        local_worker.parse_local(
            _source(tmp_path),
            tmp_path / "parsed",
            config=DoclingConfig(mode="local"),
            on_output=consume,
        )

    assert process.terminated is True
    assert process.killed is False
    assert process.waits == [5]


def test_stop_worker_skips_termination_when_already_done() -> None:
    process = _FakeStreamProcess(iter(()), returncode=0, poll_return=0)

    local_worker._stop_worker(process)

    assert process.terminated is False
    assert process.killed is False
    assert process.waits == []


def test_stop_worker_escalates_from_terminate_to_kill() -> None:
    class _StubbornProcess(_FakeStreamProcess):
        def wait(self, timeout=None):
            self.waits.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
            return 0

    process = _StubbornProcess(iter(()), returncode=0)

    local_worker._stop_worker(process)

    assert process.terminated is True
    assert process.killed is True


def _install_fake_docling(
    monkeypatch: pytest.MonkeyPatch, *, options_api_breaks: bool = False
) -> list[dict]:
    calls: list[dict] = []

    class InputFormat:
        PDF = "pdf"

    class PdfPipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = False
            self.do_table_structure = False

    class PdfFormatOption:
        def __init__(self, pipeline_options=None) -> None:
            if options_api_breaks:
                raise TypeError("options API changed upstream")
            self.pipeline_options = pipeline_options

    class DocumentConverter:
        def __init__(self, format_options=None) -> None:
            calls.append({"format_options": format_options})

    modules = {
        "docling": types.ModuleType("docling"),
        "docling.document_converter": types.ModuleType("docling.document_converter"),
        "docling.datamodel": types.ModuleType("docling.datamodel"),
        "docling.datamodel.base_models": types.ModuleType("docling.datamodel.base_models"),
        "docling.datamodel.pipeline_options": types.ModuleType(
            "docling.datamodel.pipeline_options"
        ),
    }
    modules["docling.document_converter"].DocumentConverter = DocumentConverter
    modules["docling.document_converter"].PdfFormatOption = PdfFormatOption
    modules["docling.datamodel.base_models"].InputFormat = InputFormat
    modules["docling.datamodel.pipeline_options"].PdfPipelineOptions = PdfPipelineOptions
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def test_build_converter_passes_pipeline_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_docling(monkeypatch)

    converter = local_worker._build_converter(do_ocr=True, do_table_structure=False)

    assert converter is not None
    assert len(calls) == 1
    (format_options,) = calls[0]["format_options"].values()
    assert calls[0]["format_options"] is not None
    assert format_options.pipeline_options.do_ocr is True
    assert format_options.pipeline_options.do_table_structure is False


def test_build_converter_falls_back_to_defaults_when_options_api_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_docling(monkeypatch, options_api_breaks=True)

    converter = local_worker._build_converter(do_ocr=True, do_table_structure=True)

    assert converter is not None
    assert calls == [{"format_options": None}]


def test_worker_main_failure_reports_type_and_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def failing_convert(*_args, **_kwargs):
        raise ValueError("disk full")

    monkeypatch.setattr(local_worker, "_convert", failing_convert)

    exit_code = local_worker.main(
        [
            "--source",
            str(_source(tmp_path)),
            "--workdir",
            str(tmp_path / "parsed"),
            "--do-ocr",
        ]
    )

    assert exit_code == 1
    assert capsys.readouterr().err.strip() == "ValueError: disk full"


def test_worker_main_success_reports_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(local_worker, "_convert", lambda *_args, **_kwargs: None)

    exit_code = local_worker.main(
        ["--source", str(_source(tmp_path)), "--workdir", str(tmp_path / "parsed")]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Converted lesson.pdf with isolated Docling" in captured.out
