"""Parameter and timeout-branch tests for deeptutor.tools.exec_tool.

Locks the request-side contract (language resolution, timeout clamping,
platform command assembly, per-call source layout) and the response-side
branches (blocked shell commands, sandbox timeout, sandbox error, clean
success) against a fake sandbox service — nothing outside the pytest process
is ever started.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

from deeptutor.core.tool_protocol import BaseTool
from deeptutor.services.i18n import t
from deeptutor.services.path_service import PathService
from deeptutor.services.sandbox.spec import ExecResult, ResourceLimits
from deeptutor.tools.exec_tool import ExecTool


class FakeSandboxService:
    """Records every ExecRequest and replays one canned ExecResult."""

    def __init__(self, result: ExecResult | None = None) -> None:
        self.result = result or ExecResult(stdout="ok\n", exit_code=0)
        self.requests: list[Any] = []

    async def run(self, request: Any, *, user_id: str) -> ExecResult:
        self.requests.append((request, user_id))
        return self.result


class RefusingSandboxService:
    """Fails the test if the sandbox is ever consulted."""

    async def run(self, request: Any, *, user_id: str) -> ExecResult:
        raise AssertionError("sandbox must not be reached for this call")


def _install_sandbox(monkeypatch: pytest.MonkeyPatch, service: Any) -> None:
    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: service)
    monkeypatch.setattr(
        sandbox_artifacts,
        "get_path_service",
        lambda: PathService(workspace_root=Path("/tmp")),
    )


class TestTimeoutLimits:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, 30),
            ("", 30),
            (0, 30),
            (30, 30),
            ("45", 45),
            ("not-a-number", 30),
            (-25, 1),
            (299, 299),
            (10_000, 300),
        ],
    )
    def test_raw_timeout_is_clamped_into_the_supported_window(
        self, raw: Any, expected: int
    ) -> None:
        limits = ExecTool._limits(raw)
        assert limits == ResourceLimits(timeout_s=expected)

    @pytest.mark.asyncio
    async def test_clamped_limit_reaches_the_sandbox_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = FakeSandboxService()
        _install_sandbox(monkeypatch, service)

        result = await ExecTool().execute(code="echo hi", language="shell", timeout="9999")

        assert result.success is True
        assert service.requests[0][0].limits.timeout_s == 300


class TestLanguageResolution:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, "python"),
            ("", "python"),
            ("python", "python"),
            ("PY", "python"),
            ("Python3", "python"),
            ("c", "c"),
            ("CC", "c"),
            ("c++", "cpp"),
            ("cxx", "cpp"),
            ("sh", "shell"),
            ("  Shell  ", "shell"),
        ],
    )
    def test_known_spellings_and_aliases_resolve(self, raw: Any, expected: str) -> None:
        assert ExecTool._resolve_language(raw) == expected

    def test_unsupported_language_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported exec language"):
            ExecTool._resolve_language("ruby")


class TestExecContract:
    def test_definition_exposes_the_single_sandbox_surface(self) -> None:
        tool = ExecTool()
        assert tool.name == "exec"
        assert isinstance(tool, BaseTool)
        definition = tool.get_definition()
        assert definition.name == "exec"
        schema = definition.raw_parameters
        assert schema is not None
        assert schema["required"] == ["code"]
        assert schema["properties"]["language"]["enum"] == ["python", "c", "cpp", "shell"]
        assert "30" in schema["properties"]["timeout"]["description"]
        assert "300" in schema["properties"]["timeout"]["description"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["", "   \n\t "])
    async def test_empty_code_is_rejected_before_any_execution(
        self, monkeypatch: pytest.MonkeyPatch, code: str
    ) -> None:
        service = RefusingSandboxService()
        _install_sandbox(monkeypatch, service)

        with pytest.raises(ValueError, match="non-empty 'code'"):
            await ExecTool().execute(code=code)

    @pytest.mark.asyncio
    async def test_blocked_shell_pattern_never_reaches_the_sandbox(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = RefusingSandboxService()
        _install_sandbox(monkeypatch, service)

        result = await ExecTool().execute(code="rm -rf /tmp/scratch", language="shell")

        assert result.success is False
        assert result.content == t("sandbox.command_blocked")
        assert result.metadata == {}

    @pytest.mark.asyncio
    async def test_shell_success_reports_language_and_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = FakeSandboxService(ExecResult(stdout="hello\n", exit_code=0))
        _install_sandbox(monkeypatch, service)

        result = await ExecTool().execute(
            code="echo hello",
            language="shell",
            _sandbox_user_id="user-7",
            _sandbox_workdir="",
        )

        assert result.success is True
        assert result.metadata["language"] == "shell"
        assert result.metadata["exit_code"] == 0
        assert result.metadata["timed_out"] is False
        assert "hello" in result.content
        assert service.requests[0][1] == "user-7"

    @pytest.mark.asyncio
    async def test_sandbox_timeout_marks_the_result_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = FakeSandboxService(
            ExecResult(stdout="partial output\n", exit_code=124, timed_out=True)
        )
        _install_sandbox(monkeypatch, service)

        result = await ExecTool().execute(code="sleep 999", language="shell", timeout=5)

        assert result.success is False
        assert result.metadata["timed_out"] is True
        assert result.metadata["exit_code"] == 124
        assert "(command timed out)" in result.content
        assert "partial output" in result.content
        assert service.requests[0][0].limits.timeout_s == 5

    @pytest.mark.asyncio
    async def test_sandbox_error_is_surfaced_without_masking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = FakeSandboxService(ExecResult(error="no sandbox backend available"))
        _install_sandbox(monkeypatch, service)

        result = await ExecTool().execute(code="echo hi", language="shell")

        assert result.success is False
        assert result.content.startswith("Error: no sandbox backend available")
        assert result.metadata["sandbox_error"] == "no sandbox backend available"
        assert result.metadata["timed_out"] is False


class TestSourceCallLayout:
    @pytest.mark.asyncio
    async def test_stdin_is_staged_beside_the_source_and_redirected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        service = FakeSandboxService(ExecResult(stdout="hello\n", exit_code=0))
        _install_sandbox(monkeypatch, service)
        code_workdir = tmp_path / "code_runs"

        result = await ExecTool().execute(
            code="print(input())",
            stdin="hello",
            _sandbox_code_workdir=str(code_workdir),
        )

        assert result.success is True
        run_dirs = list((code_workdir / ".deeptutor" / "exec_calls").glob("python_*"))
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "main.py").read_text(encoding="utf-8") == "print(input())"
        assert (run_dirs[0] / "stdin.txt").read_text(encoding="utf-8") == "hello"
        command = result.metadata["command"]
        assert command == (
            f"python3 .deeptutor/exec_calls/{run_dirs[0].name}/main.py"
            f" < .deeptutor/exec_calls/{run_dirs[0].name}/stdin.txt"
        )

    @pytest.mark.asyncio
    async def test_explicit_source_root_uses_absolute_call_dirs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        service = FakeSandboxService(ExecResult(stdout="ok\n", exit_code=0))
        _install_sandbox(monkeypatch, service)
        source_root = tmp_path / "sources"

        result = await ExecTool().execute(
            code="print('x')",
            _sandbox_code_workdir=str(tmp_path / "code_runs"),
            _sandbox_source_dir=str(source_root),
        )

        assert result.success is True
        command = result.metadata["command"]
        assert command.startswith("python3 ")
        assert str(source_root) in command
        call_dirs = list(source_root.glob("python_*"))
        assert len(call_dirs) == 1
        assert (call_dirs[0] / "main.py").exists()


class TestPlatformCommands:
    def test_posix_python_command_quotes_and_redirects_stdin(self) -> None:
        command = ExecTool._command_for_platform(
            "python", has_stdin=True, call_dir="call dir/python_1"
        )
        assert command == "python3 'call dir/python_1/main.py' < 'call dir/python_1/stdin.txt'"

    def test_posix_c_command_compiles_then_runs(self) -> None:
        command = ExecTool._command_for_platform("c", has_stdin=False, call_dir="calls/c_1")
        assert command == "cc calls/c_1/main.c -O2 -o calls/c_1/prog && calls/c_1/prog"

    def test_posix_cpp_command_pins_the_standard(self) -> None:
        command = ExecTool._command_for_platform("cpp", has_stdin=False, call_dir="calls/cpp_1")
        assert command == (
            "c++ -std=c++17 calls/cpp_1/main.cpp -O2 -o calls/cpp_1/prog && calls/cpp_1/prog"
        )

    def test_windows_python_without_call_dir_runs_relative_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        command = ExecTool._command_for_platform("python", has_stdin=False, call_dir="")
        assert command == "python main.py"

    def test_windows_python_pipes_stdin_through_get_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        command = ExecTool._command_for_platform(
            "python", has_stdin=True, call_dir="C:/work/python_1"
        )
        assert command == (
            "Get-Content C:\\work\\python_1\\stdin.txt | python C:\\work\\python_1\\main.py"
        )

    def test_windows_c_compiler_guards_the_run_on_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        command = ExecTool._command_for_platform("c", has_stdin=False, call_dir="C:/work/c_1")
        assert command == (
            "gcc -O2 C:\\work\\c_1\\main.c -o C:\\work\\c_1\\prog.exe; "
            "if ($LASTEXITCODE -eq 0) { & C:\\work\\c_1\\prog.exe }"
        )
