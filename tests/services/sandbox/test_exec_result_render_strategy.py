"""Failure-branch tests for the model-facing exec result template render.

``ExecResult.render`` assembles stdout, stderr and exit status into the single
string the model sees for an exec tool call, applying a head+tail truncation
strategy when the text exceeds the character budget. These tests pin the
truncation boundaries and the empty/failed branches.
"""

from __future__ import annotations

from deeptutor.services.sandbox.spec import ExecResult

# The exit-code line already starts with a newline and the parts are joined
# with another one: the overhead a caller must count against ``max_chars``.
_TRAILER = "\nExit code: 0"
_OVERHEAD = len(_TRAILER) + 1


class TestTruncationStrategy:
    def test_at_exactly_max_chars_is_untouched(self) -> None:
        stdout = "a" * (100 - _OVERHEAD)
        rendered = ExecResult(stdout=stdout).render(max_chars=100)
        assert rendered == stdout + "\n" + _TRAILER
        assert "truncated" not in rendered

    def test_over_max_chars_keeps_head_and_tail_halves(self) -> None:
        stdout = "H" * 60 + "MIDDLE" + "T" * 60
        rendered = ExecResult(stdout=stdout).render(max_chars=100)
        half = 50
        assert rendered.startswith("H" * half)
        assert rendered.endswith("Exit code: 0")
        assert "MIDDLE" not in rendered
        assert "truncated" in rendered

    def test_truncation_marker_reports_dropped_count(self) -> None:
        stdout = "x" * 300
        rendered = ExecResult(stdout=stdout).render(max_chars=100)
        dropped = len(stdout) + _OVERHEAD - 100
        assert f"({dropped:,} chars truncated)" in rendered

    def test_stderr_tail_is_preserved_by_truncation(self) -> None:
        rendered = ExecResult(stdout="o" * 200, stderr="E" * 40).render(max_chars=120)
        # The tail half keeps the whole stderr block; the exit-code trailer
        # stays last after the truncation marker.
        assert "E" * 40 in rendered
        assert rendered.endswith("\nExit code: 0")
        assert "truncated" in rendered


class TestStreamAssembly:
    def test_stdout_only(self) -> None:
        rendered = ExecResult(stdout="out").render(max_chars=100)
        assert rendered == "out\n\nExit code: 0"

    def test_stderr_is_labelled(self) -> None:
        rendered = ExecResult(stderr="warn").render(max_chars=100)
        assert "STDERR:\nwarn" in rendered
        assert rendered.endswith("Exit code: 0")

    def test_exit_code_is_included(self) -> None:
        rendered = ExecResult(stdout="out", exit_code=3).render(max_chars=100)
        assert "Exit code: 3" in rendered

    def test_empty_streams_render_as_bare_exit_code_line(self) -> None:
        # The "(no output)" placeholder in the source is currently
        # unreachable: the exit-code part is always appended first.
        assert ExecResult().render(max_chars=100) == "\nExit code: 0"


class TestFailedExecBranches:
    def test_error_short_circuits_stream_rendering(self) -> None:
        rendered = ExecResult(stdout="out", error="sandbox gone").render(max_chars=100)
        assert rendered == "Error: sandbox gone"

    def test_timeout_marker_is_appended(self) -> None:
        rendered = ExecResult(stdout="partial", timed_out=True).render(max_chars=1000)
        assert "partial" in rendered
        assert "(command timed out)" in rendered
        assert "Exit code: 0" in rendered
