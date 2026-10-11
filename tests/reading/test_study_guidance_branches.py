from __future__ import annotations

import json

import pytest

from deeptutor.reading.extensions import ReadingContext
from deeptutor.reading.study_guidance import StudyGuidanceExtension


_VALID_PAYLOAD = {
    "focus": "Connect the phrase to its surrounding argument.",
    "steps": [
        "Locate the two claims nearest the selected phrase.",
        "Explain how the phrase links those two claims.",
        "Rewrite the linked idea in one sentence.",
    ],
}


def _context(**overrides) -> ReadingContext:
    fields = {
        "material_id": "material",
        "locator": 1,
        "locale": "en",
        "selection": "verified phrase",
        "visible_text": "Before context verified phrase after context",
    }
    fields.update(overrides)
    return ReadingContext(**fields)


@pytest.mark.asyncio
async def test_unsupported_action_is_rejected_before_any_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("unsupported action must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    with pytest.raises(ValueError, match="Unsupported study-guidance action"):
        await StudyGuidanceExtension().run_action("summarize", _context())


@pytest.mark.asyncio
async def test_chinese_locale_switches_system_prompt_and_card_title(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(_VALID_PAYLOAD)

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    result = await StudyGuidanceExtension().run_action("guide", _context(locale="zh-CN"))

    assert result.title == "学习引导"
    assert calls[0]["system_prompt"].startswith("你根据一段已验证的阅读选文")
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert result.message == _VALID_PAYLOAD["focus"]
    assert result.payload["steps"] == _VALID_PAYLOAD["steps"]


@pytest.mark.asyncio
async def test_empty_object_answer_exhausts_retry_then_fails(monkeypatch):
    calls = []

    async def complete(**_kwargs):
        calls.append({"reasoning_effort": _kwargs["reasoning_effort"]})
        return "{}"

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    with pytest.raises(ValueError, match="invalid JSON"):
        await StudyGuidanceExtension().run_action("guide", _context())

    assert len(calls) == 2
    assert calls[0]["reasoning_effort"] is None


@pytest.mark.asyncio
async def test_wrong_step_count_is_rejected_as_invalid_shape(monkeypatch):
    short_payload = {
        "focus": "A valid focus for this selected reading passage.",
        "steps": _VALID_PAYLOAD["steps"][:2],
    }

    async def complete(**_kwargs):
        return json.dumps(short_payload)

    monkeypatch.setattr("deeptutor.reading.study_guidance.complete", complete)
    with pytest.raises(ValueError, match="invalid shape"):
        await StudyGuidanceExtension().run_action("guide", _context())
