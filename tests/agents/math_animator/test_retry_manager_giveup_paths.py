"""Give-up paths and degraded callbacks for the math animator retry manager."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.agents.math_animator.models import GeneratedCode, RenderResult
from deeptutor.agents.math_animator.renderer import ManimRenderError
from deeptutor.agents.math_animator.retry_manager import CodeRetryManager


class _AlwaysFailRenderer:
    def __init__(self, message: str = "compile failed") -> None:
        self.calls = 0
        self.seen_codes: list[str] = []
        self._message = message

    async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
        self.calls += 1
        self.seen_codes.append(code)
        raise ManimRenderError(self._message)


@pytest.mark.asyncio
async def test_retries_exhausted_gives_up_with_original_error() -> None:
    renderer = _AlwaysFailRenderer("scene compile failed")
    retry_notes: list[int] = []
    status_messages: list[str] = []
    repair_calls: list[tuple[str, int]] = []

    async def _on_retry(attempt) -> None:
        retry_notes.append(attempt.attempt)

    async def _on_status(message: str) -> None:
        status_messages.append(message)

    async def _repair(code: str, error_message: str, attempt: int) -> GeneratedCode:
        repair_calls.append((code, attempt))
        return GeneratedCode(code=code + "\n# repaired", rationale="patch")

    manager = CodeRetryManager(
        renderer=renderer,
        repair_callback=_repair,
        on_retry=_on_retry,
        on_status=_on_status,
        max_retries=2,
    )

    with pytest.raises(ManimRenderError, match="scene compile failed"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )

    assert renderer.calls == 3
    assert retry_notes == [1, 2]
    assert [attempt_num for _code, attempt_num in repair_calls] == [1, 2]
    assert repair_calls[0][0] == "from manim import *"
    assert repair_calls[1][0].endswith("# repaired")
    assert status_messages[0] == "Starting render attempt 1/3."
    assert "Generating repaired code for retry #2." in status_messages


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Render failed: No such file or directory: 'latex'",
        'render exited: No such file or directory: "latex"',
        "LaTeX could not be found on this machine",
        "no such file or directory: 'LATEX'",
    ],
)
async def test_missing_latex_abandons_immediately_with_guidance(message: str) -> None:
    renderer = _AlwaysFailRenderer(message)
    repair_calls: list[int] = []

    async def _repair(code: str, error_message: str, attempt: int) -> GeneratedCode:
        repair_calls.append(attempt)
        return GeneratedCode(code=code, rationale="unused")

    manager = CodeRetryManager(
        renderer=renderer,
        repair_callback=_repair,
        max_retries=4,
    )

    with pytest.raises(ManimRenderError, match="local LaTeX is missing"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )

    assert renderer.calls == 1
    assert repair_calls == []


@pytest.mark.asyncio
async def test_visual_review_timeout_gives_up_without_repair() -> None:
    class _PassRenderer:
        def __init__(self) -> None:
            self.calls = 0

        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            self.calls += 1
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    async def _slow_review(_code: str, _render_result: RenderResult) -> None:
        await asyncio.sleep(0.08)

    repair_calls: list[int] = []

    async def _repair(code: str, error_message: str, attempt: int) -> GeneratedCode:
        repair_calls.append(attempt)
        return GeneratedCode(code=code, rationale="unused")

    manager = CodeRetryManager(
        renderer=_PassRenderer(),
        repair_callback=_repair,
        review_callback=_slow_review,
        max_retries=0,
        review_timeout_seconds=0.01,
    )

    with pytest.raises(ManimRenderError, match="Visual quality review timed out"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )

    assert manager.renderer.calls == 1
    assert repair_calls == []


@pytest.mark.asyncio
async def test_visual_review_timeout_is_retried_then_gives_up() -> None:
    class _PassRenderer:
        def __init__(self) -> None:
            self.calls = 0

        async def render(self, *, code: str, output_mode: str, quality: str) -> RenderResult:
            self.calls += 1
            return RenderResult(output_mode=output_mode, artifacts=[], quality=quality)

    async def _slow_review(_code: str, _render_result: RenderResult) -> None:
        await asyncio.sleep(0.08)

    repair_calls: list[int] = []

    async def _repair(code: str, error_message: str, attempt: int) -> GeneratedCode:
        assert "Visual quality review timed out" in error_message
        repair_calls.append(attempt)
        return GeneratedCode(code=code + "\n# repaired", rationale="retry")

    manager = CodeRetryManager(
        renderer=_PassRenderer(),
        repair_callback=_repair,
        review_callback=_slow_review,
        max_retries=1,
        review_timeout_seconds=0.01,
    )

    with pytest.raises(ManimRenderError, match="Visual quality review timed out"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )

    assert manager.renderer.calls == 2
    assert repair_calls == [1]


@pytest.mark.asyncio
async def test_empty_repaired_code_keeps_previous_code() -> None:
    renderer = _AlwaysFailRenderer("syntax error")
    status_messages: list[str] = []

    async def _on_status(message: str) -> None:
        status_messages.append(message)

    async def _repair(_code: str, _error_message: str, _attempt: int) -> GeneratedCode:
        return GeneratedCode(code="   \n", rationale="empty patch")

    manager = CodeRetryManager(
        renderer=renderer,
        repair_callback=_repair,
        on_status=_on_status,
        max_retries=1,
    )

    with pytest.raises(ManimRenderError, match="syntax error"):
        await manager.render_with_retries(
            initial_code="from manim import *",
            output_mode="video",
            quality="medium",
        )

    assert renderer.calls == 2
    assert renderer.seen_codes == ["from manim import *", "from manim import *"]
