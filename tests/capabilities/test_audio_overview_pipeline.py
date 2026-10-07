"""Focused pure-logic behavior tests for the audio_overview pipeline.

Covers transcript excerpt selection (``parse_script`` / ``normalize_rag_result``),
chapter structure (transcript rendering, stem sanitizing, request bounds), and
provider failure paths — all with in-process fakes: no network, no LLM/TTS
services, no ffmpeg requirement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.capabilities.audio_overview.pipeline import (
    AudioOverviewError,
    AudioOverviewPipeline,
    AudioOverviewScript,
    RetrievedContext,
    ScriptSegment,
    SourceCitation,
    _safe_stem,
    _transcript,
    normalize_rag_result,
    parse_script,
)
from deeptutor.capabilities.audio_overview.request_config import AudioOverviewRequestConfig

# ---------------------------------------------------------------------------
# Normal paths
# ---------------------------------------------------------------------------


def test_request_config_defaults_reject_unknown_fields_and_out_of_bounds_values() -> None:
    config = AudioOverviewRequestConfig()
    assert (config.topic, config.target_minutes, config.max_context_chunks) == ("", 5, 6)
    assert config.host_voice is None and config.expert_voice is None

    with pytest.raises(ValueError, match="Extra"):
        AudioOverviewRequestConfig.model_validate({"unknown_key": "x"})
    for minutes in (0, 16):
        with pytest.raises(ValueError):
            AudioOverviewRequestConfig(target_minutes=minutes)
    for chunks in (0, 13):
        with pytest.raises(ValueError):
            AudioOverviewRequestConfig(max_context_chunks=chunks)
    with pytest.raises(ValueError):
        AudioOverviewRequestConfig(topic="t" * 501)
    with pytest.raises(ValueError):
        AudioOverviewRequestConfig(host_voice="")
    AudioOverviewRequestConfig(target_minutes=1, max_context_chunks=12, host_voice="v" * 64)


def test_parse_script_normalizes_segments_ignores_extra_fields_keeps_citation_order() -> None:
    script = parse_script(
        json.dumps(
            {
                "title": "Overview",
                "unused_section": {"note": "must be ignored"},
                "segments": [
                    {"speaker": "host", "text": "Welcome.", "flavor": "warm"},
                    {"speaker": "expert", "text": "Mechanism.", "source_ids": ["S2", "S2", "S1"]},
                    {"speaker": "host", "text": "Follow-up."},
                    {"speaker": "expert", "text": "Wrap-up.", "source_ids": ["S1", "S2"]},
                ],
            }
        ),
        {"S1", "S2"},
    )
    assert [segment.speaker for segment in script.segments] == [
        "host",
        "expert",
        "host",
        "expert",
    ]
    assert script.segments[1].source_ids == ["S2", "S1"]
    assert script.segments[2].source_ids == []
    assert script.segments[3].source_ids == ["S1", "S2"]


def test_parse_script_accepts_minimal_two_segment_script_without_citations() -> None:
    script = parse_script(
        '{"title": "T", "segments": ['
        '{"speaker": "host", "text": "a"}, {"speaker": "expert", "text": "b"}]}',
        set(),
    )
    assert script.title == "T"
    assert [(segment.speaker, segment.text, segment.source_ids) for segment in script.segments] == [
        ("host", "a", []),
        ("expert", "b", []),
    ]


def test_normalize_rag_result_supports_alternative_source_fields_and_fallback_titles() -> None:
    context = normalize_rag_result(
        {
            "content": "Answer synthesized from the content field.",
            "citations": [
                {"url": "https://example.com/paper", "text": "Evidence one."},
                "not-a-mapping-row",
                {"title": "Notes.md", "locator": "section 2", "snippet": "Evidence two."},
            ],
        }
    )
    assert context.answer == "Answer synthesized from the content field."
    assert [citation.source_id for citation in context.citations] == ["S1", "S2"]
    assert context.citations[0].title == "S1"
    assert context.citations[0].locator == "https://example.com/paper"
    assert context.citations[0].snippet == "Evidence one."
    assert context.citations[1].title == "Notes.md"
    assert context.citations[1].locator == "section 2"


def test_transcript_renders_chapter_structure_with_language_labels_and_citations() -> None:
    script = AudioOverviewScript(
        title="Deep Dive",
        segments=[
            ScriptSegment(speaker="host", text="Intro."),
            ScriptSegment(speaker="expert", text="Body.", source_ids=["S1"]),
            ScriptSegment(speaker="host", text="Outro.", source_ids=["S2", "S1"]),
        ],
    )
    citations = [
        SourceCitation(source_id="S1", title="Alpha.pdf", locator="p. 3", snippet="s1"),
        SourceCitation(source_id="S2", title="Beta.pdf", locator="", snippet="s2"),
    ]
    en = _transcript(script, citations, "en")
    en_lines = en.splitlines()
    assert en_lines[0] == "# Deep Dive"
    assert "## Sources" in en_lines
    assert "- [S1] Alpha.pdf — p. 3" in en_lines
    assert "- [S2] Beta.pdf" in en_lines
    assert "### Host" in en_lines and "### Expert" in en_lines
    assert "Body. [S1]" in en_lines
    assert "Outro. [S2] [S1]" in en_lines
    assert en.endswith("\n") and not en.endswith("\n\n")

    zh = _transcript(script, [], "zh-CN")
    assert "## Sources" not in zh
    assert "### 主持人" in zh and "### 专家" in zh


def test_safe_stem_sanitizes_unsafe_characters_and_clamps_length() -> None:
    assert _safe_stem("Turn 42: <overview>/draft", "fallback") == "turn-42-overview-draft"
    assert _safe_stem("_keep-underscore.txt", "fallback") == "_keep-underscore.txt"
    assert _safe_stem("---....", "fallback") == "fallback"
    assert _safe_stem("a" * 250, "fallback") == "a" * 100
    assert _safe_stem("MiXeD Case_9.txt", "fallback") == "mixed-case_9.txt"


@pytest.mark.asyncio
async def test_retrieve_builds_bounded_query_and_passes_top_k() -> None:
    captured: list[tuple[str, str, int]] = []

    async def fake_rag(query: str, kb_name: str, *, top_k: int) -> dict[str, Any]:
        captured.append((query, kb_name, top_k))
        return {"answer": "ok", "sources": [{"title": "T.pdf", "text": "s"}]}

    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="s",
        instruction_prompt="i",
        rag_search_func=fake_rag,
    )
    context = await pipeline.retrieve(
        topic="  reliability  ",
        kb_name="eng-kb",
        request_config=AudioOverviewRequestConfig(max_context_chunks=9),
    )
    assert captured == [("reliability audio overview", "eng-kb", 9)]
    assert context.answer == "ok"

    await pipeline.retrieve(
        topic="q" * 1_200,
        kb_name="eng-kb",
        request_config=AudioOverviewRequestConfig(),
    )
    assert captured[1][0] == "q" * 1_000
    assert captured[1][2] == 6


# ---------------------------------------------------------------------------
# Truncated / edge inputs
# ---------------------------------------------------------------------------


def test_parse_script_rejects_unparseable_and_non_object_payloads() -> None:
    for raw in ("The model declined to answer.", "[]", "null"):
        with pytest.raises(AudioOverviewError, match="did not return a JSON object"):
            parse_script(raw, set())
    # A truncated payload may or may not survive JSON repair, but it must never
    # yield a script silently.
    with pytest.raises(AudioOverviewError, match="audio overview"):
        parse_script('{"title": "Overview", "segments": [{"speaker": "hos', set())


def test_parse_script_reports_field_level_validation_details() -> None:
    with pytest.raises(AudioOverviewError) as exc:
        parse_script(
            json.dumps(
                {
                    "title": "",
                    "segments": [
                        {"speaker": "host", "text": "a"},
                        {"speaker": "expert", "text": ""},
                    ],
                }
            ),
            set(),
        )
    message = str(exc.value)
    assert message.startswith("Invalid audio overview script:")
    assert "title" in message and "text" in message

    with pytest.raises(AudioOverviewError, match="segments"):
        parse_script(
            json.dumps({"title": "T", "segments": [{"speaker": "host", "text": "only"}]}),
            set(),
        )


def test_normalize_rag_result_clamps_context_snippet_and_locator_fields() -> None:
    context = normalize_rag_result(
        {
            "answer": "a" * 20_000,
            "sources": [
                {
                    "snippet": "",
                    "content": "preferred-content",
                    "text": "lower-priority-text",
                    "section": "L" * 300,
                }
            ],
        }
    )
    assert len(context.answer) == 16_000
    assert context.citations[0].snippet == "preferred-content"
    assert len(context.citations[0].locator) == 200


# ---------------------------------------------------------------------------
# Provider failure paths
# ---------------------------------------------------------------------------


def test_normalize_rag_result_raises_for_rag_failure_envelopes() -> None:
    with pytest.raises(AudioOverviewError, match="RAG retrieval failed: kb not indexed"):
        normalize_rag_result({"error_type": "kb_missing", "answer": "kb not indexed"})
    with pytest.raises(AudioOverviewError) as exc:
        normalize_rag_result({"needs_reindex": True, "content": "c" * 700})
    reason = str(exc.value).removeprefix("RAG retrieval failed: ")
    assert len(reason) == 500


def test_normalize_rag_result_raises_when_nothing_is_usable() -> None:
    for result in ({}, {"answer": "   "}, {"sources": []}, {"answer": "", "content": ""}):
        with pytest.raises(AudioOverviewError, match="no usable content"):
            normalize_rag_result(result)


@pytest.mark.asyncio
async def test_publish_requires_workspace_then_defaults_distinct_injected_voices(
    tmp_path: Path,
) -> None:
    script = AudioOverviewScript(
        title="T",
        segments=[
            ScriptSegment(speaker="host", text="first"),
            ScriptSegment(speaker="expert", text="second"),
            ScriptSegment(speaker="host", text="third"),
        ],
    )
    context = RetrievedContext(answer="a", citations=[])

    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="s",
        instruction_prompt="i",
        speech_func=_unused_speech,
    )
    with pytest.raises(AudioOverviewError, match="No writable runtime workspace"):
        await pipeline.publish(
            turn_id="t1",
            script=script,
            context=context,
            request_config=AudioOverviewRequestConfig(),
        )

    calls: list[tuple[str, str]] = []

    async def fake_speech(text: str, **kwargs: Any) -> tuple[bytes, str]:
        calls.append((text, str(kwargs["voice"])))
        return _wav_bytes(), "audio/wav"

    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="s",
        instruction_prompt="i",
        speech_func=fake_speech,
        workspace_output_dir=tmp_path / "outputs",
    )
    artifacts = await pipeline.publish(
        turn_id="t2",
        script=script,
        context=context,
        request_config=AudioOverviewRequestConfig(),
    )
    assert [voice for _, voice in calls] == ["host", "expert", "host"]
    assert [text for text, _ in calls] == ["first", "second", "third"]
    assert artifacts.audio_path.is_file() and artifacts.transcript_path.is_file()
    assert artifacts.citations == []
    assert "## Transcript" in artifacts.transcript


@pytest.mark.asyncio
async def test_publish_wraps_empty_speech_audio_and_unwritable_workspace(tmp_path: Path) -> None:
    script = AudioOverviewScript(
        title="T",
        segments=[
            ScriptSegment(speaker="host", text="a"),
            ScriptSegment(speaker="expert", text="b"),
        ],
    )
    context = RetrievedContext(answer="a", citations=[])

    async def speech_then_empty(text: str, **kwargs: Any) -> tuple[bytes, str]:
        return (_wav_bytes() if text == "a" else b""), "audio/wav"

    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="s",
        instruction_prompt="i",
        speech_func=speech_then_empty,
        workspace_output_dir=tmp_path / "outputs",
    )
    with pytest.raises(AudioOverviewError, match="returned empty audio"):
        await pipeline.publish(
            turn_id="t3",
            script=script,
            context=context,
            request_config=AudioOverviewRequestConfig(),
        )

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="s",
        instruction_prompt="i",
        speech_func=_wav_speech,
        workspace_output_dir=blocker / "nested",
    )
    with pytest.raises(AudioOverviewError, match="Could not write audio overview artifacts"):
        await pipeline.publish(
            turn_id="t4",
            script=script,
            context=context,
            request_config=AudioOverviewRequestConfig(),
        )


async def _unused_speech(*args: Any, **kwargs: Any) -> tuple[bytes, str]:
    raise AssertionError("speech provider must not be called on this path")


async def _wav_speech(*args: Any, **kwargs: Any) -> tuple[bytes, str]:
    return _wav_bytes(), "audio/wav"


def _wav_bytes() -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\x00\x00" * 120)
    return buffer.getvalue()
