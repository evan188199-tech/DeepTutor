"""Unit tests for the ``github_query`` tool's pure logic.

We never spawn ``gh`` for real — every test injects its own
``command_runner`` so we can pin returncode / stdout / stderr.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from deeptutor.tools.github_query import (
    MAX_OUTPUT_CHARS,
    GithubOutcome,
    run_github_query,
)


def _runner(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    record: list[list[str]] | None = None,
):
    async def _run(argv, timeout_s):
        if record is not None:
            record.append(list(argv))
        return returncode, stdout, stderr

    return _run


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_missing_query_type() -> None:
    outcome = await run_github_query(
        query_type="",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "query_type" in outcome.error


@pytest.mark.asyncio
async def test_rejects_missing_target() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "target" in outcome.error


@pytest.mark.asyncio
async def test_rejects_unsupported_query_type() -> None:
    outcome = await run_github_query(
        query_type="merge",  # explicitly write-flavoured, not in the whitelist
        target="owner/repo#1",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "Unsupported query_type" in outcome.error


# ---------------------------------------------------------------------------
# gh CLI availability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_gh_missing_gracefully() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="owner/repo#1",
        gh_available=lambda: False,
        command_runner=_runner(),  # should never be invoked
    )
    assert outcome.ok is False
    assert "`gh`" in outcome.error or "gh" in outcome.error.lower()


# ---------------------------------------------------------------------------
# argv shape — confirms each query_type stays read-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_argv_is_view_only() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="pr",
        target="owner/repo#42",
        gh_available=lambda: True,
        command_runner=_runner(stdout='{"title":"x"}', record=record),
    )
    assert record == [
        [
            "gh",
            "pr",
            "view",
            "owner/repo#42",
            "--json",
            "title,state,statusCheckRollup,reviews,url,author,createdAt,body",
        ]
    ]


@pytest.mark.asyncio
async def test_issue_argv_is_view_only() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="issue",
        target="owner/repo#7",
        gh_available=lambda: True,
        command_runner=_runner(stdout='{"title":"x"}', record=record),
    )
    assert record[0][:4] == ["gh", "issue", "view", "owner/repo#7"]


@pytest.mark.asyncio
async def test_run_argv_uses_list_subcommand() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="run",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(stdout="[]", record=record),
    )
    assert record[0][:5] == ["gh", "run", "list", "--repo", "owner/repo"]


@pytest.mark.asyncio
async def test_api_argv_does_not_set_method() -> None:
    """`gh api` defaults to GET; we never pass --method so the tool
    can't be coerced into a mutating call by creative ``target``s."""
    record: list[list[str]] = []
    await run_github_query(
        query_type="api",
        target="repos/owner/repo/issues",
        gh_available=lambda: True,
        command_runner=_runner(stdout="[]", record=record),
    )
    assert "--method" not in record[0]
    assert "-X" not in record[0]
    assert record[0][0:2] == ["gh", "api"]


# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncates_oversized_output() -> None:
    huge = "y" * (MAX_OUTPUT_CHARS + 500)
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(stdout=huge),
    )
    assert outcome.ok is True
    assert outcome.output.endswith("[truncated]")


@pytest.mark.asyncio
async def test_surfaces_nonzero_exit_as_failure() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(returncode=1, stderr="not found"),
    )
    assert outcome.ok is False
    assert "not found" in outcome.error


# ---------------------------------------------------------------------------
# argv completeness — every template, full shape, normalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_argv_full_shape() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="repo",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(stdout="{}", record=record),
    )
    assert record == [
        [
            "gh",
            "repo",
            "view",
            "owner/repo",
            "--json",
            "description,defaultBranchRef,stargazerCount,forkCount,visibility,url",
        ]
    ]


@pytest.mark.asyncio
async def test_run_argv_pins_limit_and_fields() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="run",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(stdout="[]", record=record),
    )
    argv = record[0]
    assert "--limit" in argv
    assert argv[argv.index("--limit") + 1] == "10"
    assert (
        argv[argv.index("--json") + 1]
        == "name,status,conclusion,workflowName,event,createdAt,url"
    )


@pytest.mark.asyncio
async def test_query_type_and_target_are_normalized() -> None:
    record: list[list[str]] = []
    outcome = await run_github_query(
        query_type="  PR  ",
        target="  owner/repo#1  ",
        gh_available=lambda: True,
        command_runner=_runner(stdout="ok", record=record),
    )
    assert outcome.ok is True
    assert outcome.query_type == "pr"
    assert outcome.target == "owner/repo#1"
    assert record[0][:4] == ["gh", "pr", "view", "owner/repo#1"]


# ---------------------------------------------------------------------------
# Failure branches — timeout, runner crash, gh error output parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_reports_timed_out_error() -> None:
    async def _slow(argv, timeout_s):
        raise asyncio.TimeoutError()

    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        timeout_s=2.5,
        gh_available=lambda: True,
        command_runner=_slow,
    )
    assert outcome.ok is False
    assert "timed out" in outcome.error
    assert "2.5" in outcome.error


@pytest.mark.asyncio
async def test_runner_crash_reports_invocation_failed() -> None:
    async def _boom(argv, timeout_s):
        raise RuntimeError("spawn exploded")

    outcome = await run_github_query(
        query_type="issue",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_boom,
    )
    assert outcome.ok is False
    assert "invocation failed" in outcome.error
    assert "spawn exploded" in outcome.error


@pytest.mark.asyncio
async def test_failure_with_empty_stderr_falls_back_to_stdout() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(returncode=1, stdout="gh: rate limit exceeded\nretry later"),
    )
    assert outcome.ok is False
    assert "rate limit exceeded" in outcome.error


@pytest.mark.asyncio
async def test_failure_error_keeps_first_three_lines_only() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(returncode=4, stderr="l1\nl2\nl3\nl4\nl5"),
    )
    assert outcome.ok is False
    assert outcome.error == "l1 / l2 / l3"


@pytest.mark.asyncio
async def test_failure_with_no_output_reports_exit_code() -> None:
    outcome = await run_github_query(
        query_type="run",
        target="o/r",
        gh_available=lambda: True,
        command_runner=_runner(returncode=7),
    )
    assert outcome.ok is False
    assert outcome.error == "gh exited with code 7."


# ---------------------------------------------------------------------------
# Output handling — trimming details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_is_stripped_and_metadata_echoed() -> None:
    outcome = await run_github_query(
        query_type="issue",
        target="o/r#9",
        gh_available=lambda: True,
        command_runner=_runner(stdout="  \n payload \n "),
    )
    assert outcome.ok is True
    assert outcome.output == "payload"
    assert outcome.query_type == "issue"
    assert outcome.target == "o/r#9"


@pytest.mark.asyncio
async def test_output_at_exact_char_limit_is_not_marked_truncated() -> None:
    body = "x" * MAX_OUTPUT_CHARS
    outcome = await run_github_query(
        query_type="api",
        target="users/octocat",
        gh_available=lambda: True,
        command_runner=_runner(stdout=body),
    )
    assert outcome.ok is True
    assert outcome.output == body
    assert "[truncated]" not in outcome.output


@pytest.mark.asyncio
async def test_output_over_char_limit_is_marked_truncated() -> None:
    body = "x" * (MAX_OUTPUT_CHARS + 1)
    outcome = await run_github_query(
        query_type="api",
        target="users/octocat",
        gh_available=lambda: True,
        command_runner=_runner(stdout=body),
    )
    assert outcome.ok is True
    assert outcome.output.startswith("x" * MAX_OUTPUT_CHARS)
    assert outcome.output.endswith("\n…[truncated]")
    assert len(outcome.output) == MAX_OUTPUT_CHARS + len("\n…[truncated]")


# ---------------------------------------------------------------------------
# Default dependency implementations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_availability_probe_uses_shutil_which(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.tools.github_query as gq

    monkeypatch.setattr(gq.shutil, "which", lambda name: None)
    outcome = await run_github_query(
        query_type="repo",
        target="o/r",
        command_runner=_runner(),  # must never be reached
    )
    assert outcome.ok is False
    assert "not installed" in outcome.error


@pytest.mark.asyncio
async def test_default_command_runner_decodes_streams() -> None:
    from deeptutor.tools.github_query import _default_command_runner

    argv = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')",
    ]
    rc, stdout, stderr = await _default_command_runner(argv, 10.0)
    assert rc == 0
    assert stdout == "OUT"
    assert stderr == "ERR"


@pytest.mark.asyncio
async def test_default_command_runner_times_out_and_kills_child() -> None:
    from deeptutor.tools.github_query import _default_command_runner

    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(asyncio.TimeoutError):
        await _default_command_runner(argv, 0.2)
