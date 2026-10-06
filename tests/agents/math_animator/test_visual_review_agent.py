"""Envelope and verdict tests for VisualReviewAgent (visual_review_agent.py).

Pins the review-result envelope against the shared agents._shared JSON
contract (extract_json_object) with a faked stream layer — no model, no
network, no real prompt files.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import deeptutor.agents.math_animator.agents.visual_review_agent as visual_review_agent_module
from deeptutor.agents.math_animator.agents.visual_review_agent import VisualReviewAgent
from deeptutor.agents.math_animator.models import (
    RenderedArtifact,
    RenderResult,
    RetryAttempt,
    VisualReviewResult,
)
from deeptutor.core.context import Attachment


def _attachments(count: int) -> list[Attachment]:
    return [
        Attachment(
            type="image",
            filename=f"review_frame_{index:02d}.png",
            mime_type="image/png",
            base64="QUFB",
        )
        for index in range(1, count + 1)
    ]


VIDEO_RENDER_RESULT = RenderResult(
    output_mode="video",
    artifacts=[RenderedArtifact(type="video", url="", filename="out.mp4")],
)


def _agent(
    monkeypatch: pytest.MonkeyPatch, *, vision: bool = True, response: str = ""
) -> tuple[VisualReviewAgent, list[dict[str, Any]], dict[str, Any]]:
    # BaseAgent.__init__ reads agents.yaml for stage budgets; stub it so the
    # test runs without a seeded runtime settings dir (no agents.yaml needed).
    monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _module_name: {})
    agent = VisualReviewAgent()
    agent.prompts = {
        "system": "Review the rendered frames.",
        "user_template": (
            "{user_input}|{output_mode}|{reviewed_frames}|{render_json}|{current_code}"
        ),
    }
    monkeypatch.setattr(agent, "get_model", lambda: "review-model")
    seen_vision: dict[str, Any] = {}

    def fake_supports_vision(binding: str, model: str | None) -> bool:
        seen_vision["binding"] = binding
        seen_vision["model"] = model
        return vision

    monkeypatch.setattr(visual_review_agent_module, "supports_vision", fake_supports_vision)
    calls: list[dict[str, Any]] = []

    async def fake_stream_llm(**kwargs: Any):
        calls.append(kwargs)
        yield response

    monkeypatch.setattr(agent, "stream_llm", fake_stream_llm)
    return agent, calls, seen_vision


async def _process(agent: VisualReviewAgent, attachments: list[Attachment]):
    return await agent.process(
        user_input="  Animate a proof of the Pythagorean theorem  ",
        output_mode="video",
        current_code="class Scene(Scene):\n    pass",
        render_result=VIDEO_RENDER_RESULT,
        attachments=attachments,
    )


class TestShortCircuitVerdicts:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("output_mode", ["video", "image"])
    async def test_no_attachments_passes_without_a_model_call(
        self, monkeypatch: pytest.MonkeyPatch, output_mode: str
    ) -> None:
        agent, calls, _ = _agent(monkeypatch)

        result = await agent.process(
            user_input="Animate a proof",
            output_mode=output_mode,
            current_code="code",
            render_result=VIDEO_RENDER_RESULT,
            attachments=[],
        )

        assert isinstance(result, VisualReviewResult)
        assert result.passed is True
        assert "no review frames" in result.summary
        assert result.reviewed_frames == 0
        assert calls == []

    @pytest.mark.asyncio
    async def test_model_without_vision_support_passes_without_a_model_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent, calls, seen_vision = _agent(monkeypatch, vision=False)
        attachments = _attachments(2)

        result = await _process(agent, attachments)

        assert result.passed is True
        assert "does not support image inspection" in result.summary
        assert result.reviewed_frames == 2
        assert calls == []
        # The capability gate consults this agent's own binding and model.
        assert seen_vision["binding"] == agent.binding
        assert seen_vision["model"] == "review-model"

    @pytest.mark.asyncio
    async def test_missing_prompts_raise_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent, _, _ = _agent(monkeypatch)
        agent.prompts = {}

        with pytest.raises(ValueError, match="prompts are not configured"):
            await _process(agent, _attachments(1))


# Review verdicts: pass / reject / needs-modification. The envelope keeps a
# boolean ``passed`` plus ``issues`` and ``suggested_fix`` for the repair step;
# missing optional fields fall back to the model defaults.
VERDICT_CASES = [
    pytest.param(
        "pass",
        '{"passed": true, "summary": "Clear, readable, nothing overlaps.", "reviewed_frames": 1}',
        VisualReviewResult(
            passed=True,
            summary="Clear, readable, nothing overlaps.",
            issues=[],
            suggested_fix="",
            reviewed_frames=1,
        ),
        id="pass",
    ),
    pytest.param(
        "reject",
        '{"passed": false, "summary": "Labels overlap the curve.", '
        '"issues": ["label overlap"], "suggested_fix": "Move labels above the '
        'curve.", "reviewed_frames": 1}',
        VisualReviewResult(
            passed=False,
            summary="Labels overlap the curve.",
            issues=["label overlap"],
            suggested_fix="Move labels above the curve.",
            reviewed_frames=1,
        ),
        id="reject",
    ),
    pytest.param(
        "needs-modification",
        '{"passed": false, "summary": "Frame is too crowded.", '
        '"issues": ["too many objects in one frame"]}',
        VisualReviewResult(
            passed=False,
            summary="Frame is too crowded.",
            issues=["too many objects in one frame"],
            suggested_fix="",
            reviewed_frames=2,
        ),
        id="needs-modification-minimal",
    ),
    pytest.param(
        "pass-without-reviewed-frames",
        '{"passed": true, "summary": "Looks good."}',
        VisualReviewResult(
            passed=True,
            summary="Looks good.",
            issues=[],
            suggested_fix="",
            reviewed_frames=2,
        ),
        id="pass-defaults-reviewed-frames",
    ),
    pytest.param(
        "reject-with-model-reviewed-frames",
        '{"passed": false, "summary": "Off-screen.", "issues": ["clipped"], "reviewed_frames": 5}',
        VisualReviewResult(
            passed=False,
            summary="Off-screen.",
            issues=["clipped"],
            suggested_fix="",
            reviewed_frames=5,
        ),
        id="reject-payload-reviewed-frames-wins",
    ),
]


class TestVerdictEnvelope:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("label", "raw", "expected"), VERDICT_CASES)
    async def test_llm_payload_maps_to_review_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        label: str,
        raw: str,
        expected: VisualReviewResult,
    ) -> None:
        agent, calls, _ = _agent(monkeypatch, response=raw)

        result = await _process(agent, _attachments(2))

        assert result == expected
        assert len(calls) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("raw", "expected_passed", "expected_summary"),
        [
            # Fenced JSON with prose around it (agents._shared contract).
            (
                'Review:\n```json\n{"passed": false, "summary": "Blurry text."}\n```',
                False,
                "Blurry text.",
            ),
            # Reasoning-model preamble before the bare object.
            (
                '<think>I see slight overlap.</think>\n{"passed": true, "summary": "Acceptable."}',
                True,
                "Acceptable.",
            ),
            # Prose tail after the object.
            (
                'Sure. {"passed": false, "summary": "Too crowded."} — done.',
                False,
                "Too crowded.",
            ),
        ],
    )
    async def test_parses_raw_model_output_shapes_via_shared_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        expected_passed: bool,
        expected_summary: str,
    ) -> None:
        agent, _, _ = _agent(monkeypatch, response=raw)

        result = await _process(agent, _attachments(1))

        assert result.passed is expected_passed
        assert result.summary == expected_summary
        assert result.reviewed_frames == 1

    @pytest.mark.asyncio
    async def test_empty_model_output_falls_back_to_default_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent, calls, _ = _agent(monkeypatch, response="")

        result = await _process(agent, _attachments(3))

        assert result.passed is True
        assert result.summary == ""
        assert result.issues == []
        assert result.reviewed_frames == 3
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_unparsable_model_output_raises_decode_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent, _, _ = _agent(monkeypatch, response="The visuals look great, no JSON for you.")

        with pytest.raises(json.JSONDecodeError):
            await _process(agent, _attachments(1))


class TestStreamEnvelopeContract:
    @pytest.mark.asyncio
    async def test_stream_call_carries_the_review_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        render_result = RenderResult(
            output_mode="video",
            artifacts=[RenderedArtifact(type="video", url="", filename="out.mp4")],
            quality="high",
            retry_attempts=1,
            retry_history=[RetryAttempt(attempt=1, error="Visual review failed: x")],
            visual_review=VisualReviewResult(passed=False, summary="prior round"),
        )
        agent, calls, _ = _agent(monkeypatch, response='{"passed": true, "summary": "ok"}')
        attachments = _attachments(2)

        await agent.process(
            user_input="Animate a proof",
            output_mode="video",
            current_code="class Scene(Scene):\n    pass",
            render_result=render_result,
            attachments=attachments,
        )

        kwargs = calls[0]
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["model"] == "review-model"
        assert kwargs["stage"] == "render_output"
        assert kwargs["attachments"] is attachments
        assert kwargs["system_prompt"] == "Review the rendered frames."
        assert kwargs["messages"] == [
            {"role": "system", "content": "Review the rendered frames."},
            {"role": "user", "content": kwargs["user_prompt"]},
        ]
        user_prompt = kwargs["user_prompt"]
        assert "Animate a proof" in user_prompt
        assert "video" in user_prompt
        assert "2" in user_prompt
        assert "class Scene(Scene):" in user_prompt
        # The current round's own review is excluded from the render JSON.
        assert '"quality": "high"' in user_prompt
        assert '"retry_attempts": 1' in user_prompt
        assert "visual_review" not in user_prompt
        trace_meta = kwargs["trace_meta"]
        assert trace_meta["call_kind"] == "math_visual_review"
        assert trace_meta["trace_role"] == "review"
        assert trace_meta["phase"] == "render_output"
        assert trace_meta["label"] == "Visual quality review"
        assert trace_meta["call_id"].startswith("math-visual-review-")
        assert trace_meta["trace_kind"] == "llm_output"
