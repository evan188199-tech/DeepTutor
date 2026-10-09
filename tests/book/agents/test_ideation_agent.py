"""Input/output contract tests for the Stage-1 IdeationAgent.

Top100 #97 — ``deeptutor/book/agents/ideation_agent.py``.

The agent turns a rendered ``IdeationContext`` into a ``BookProposal`` via one
streamed, JSON-mode LLM call routed through ``json_with_reasoning_retry``.
These tests pin that contract end to end with the LLM faked at
``BaseAgent.stream_llm``: prompt construction (rendered context sections plus
the language directive), the full-payload mapping into ``BookProposal``, the
``_coerce_proposal`` normalisation matrix (chapter clamping, blank / missing /
oversized fields), the ``title``-keyed retry of a complete-but-unusable answer,
and the degrade-to-defaults path when no attempt yields a usable payload.

All external work is faked. No LLM, no network, no real credentials.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.ideation_agent import IdeationAgent
from deeptutor.book.inputs import IdeationContext
from deeptutor.services.config import loader as loader_module
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS

# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _agent_settings_home(tmp_path, monkeypatch):
    """``get_agent_params`` requires ``data/user/settings/agents.yaml``.

    Tests must not depend on a runtime home seeded by a real install, so every
    test gets its own tmp home holding the shipped defaults. Same isolation as
    ``tests/book/test_spine_synthesizer.py``.
    """
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "agents.yaml").write_text(
        yaml.safe_dump(DEFAULT_AGENTS_SETTINGS), encoding="utf-8"
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", tmp_path)


def _fake_stream(responses: list[str], calls: list[dict[str, Any]]):
    """Return a ``BaseAgent.stream_llm`` replacement serving canned responses.

    One entry per attempt; the last entry repeats when the agent calls more
    often than ``responses`` has answers. Every stream is reported as a
    complete response (``finish_reason="stop"``) unless the test says
    otherwise.
    """

    async def fake_stream(self: BaseAgent, **kwargs: Any):
        calls.append(dict(kwargs))
        outcome = kwargs.get("outcome")
        if outcome is not None:
            outcome.finish_reason = "stop"
        yield responses[min(len(calls) - 1, len(responses) - 1)]

    return fake_stream


async def _run_process(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    context: IdeationContext | None = None,
    **agent_kwargs: Any,
):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(BaseAgent, "stream_llm", _fake_stream(responses, calls))
    agent = IdeationAgent(**agent_kwargs)
    proposal = await agent.process(
        ideation_context=context or IdeationContext(user_intent="Math"),
    )
    return proposal, calls


# ─────────────────────────────────────────────────────────────────────────────
# Contract: context in → proposal out
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_maps_full_llm_payload_to_book_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        '{"title":"Linear Algebra Made Visible",'
        '"description":"A visual first course.",'
        '"scope":"Vectors through eigendecomposition; no functional analysis.",'
        '"target_level":"intermediate",'
        '"estimated_chapters":6,'
        '"rationale":"Two chapters per theme."}'
    )

    proposal, calls = await _run_process(monkeypatch, [payload])

    assert proposal.title == "Linear Algebra Made Visible"
    assert proposal.description == "A visual first course."
    assert proposal.scope == "Vectors through eigendecomposition; no functional analysis."
    assert proposal.target_level == "intermediate"
    assert proposal.estimated_chapters == 6
    assert proposal.rationale == "Two chapters per theme."
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_process_builds_prompts_from_rendered_context_and_stream_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = IdeationContext(
        user_intent="Learn linear algebra visually",
        knowledge_bases=["Linear KB"],
    )

    _proposal, calls = await _run_process(
        monkeypatch,
        ['{"title":"T","estimated_chapters":5}'],
        context=context,
        language="en",
    )
    assert len(calls) == 1
    call = calls[0]

    assert call["stage"] == "ideation"
    assert call["response_format"] == {"type": "json_object"}
    assert call["reasoning_effort"] is None

    user_prompt = call["user_prompt"]
    assert "[User Intent]" in user_prompt
    assert "Learn linear algebra visually" in user_prompt
    assert "[Knowledge Sources]" in user_prompt
    assert "- Linear KB" in user_prompt

    system_prompt = call["system_prompt"]
    assert system_prompt
    assert "[Language] Write ALL reader-facing text" in system_prompt
    assert system_prompt == system_prompt.rstrip()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "marker"),
    [
        ("en", "[Language] Write ALL reader-facing text"),
        ("zh", "语言要求"),
    ],
)
async def test_process_appends_language_directive_for_agent_language(
    monkeypatch: pytest.MonkeyPatch, language: str, marker: str
) -> None:
    _proposal, calls = await _run_process(
        monkeypatch,
        ['{"title":"T"}'],
        language=language,
    )
    assert marker in calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_process_uses_builtin_fallback_prompts_when_prompts_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = IdeationContext(user_intent="Graph theory")
    seen: list[dict[str, Any]] = []

    async def fake_stream(self: BaseAgent, **kwargs: Any):
        seen.append(dict(kwargs))
        kwargs["outcome"].finish_reason = "stop"
        yield '{"title":"Fallback Book"}'

    monkeypatch.setattr(BaseAgent, "stream_llm", fake_stream)
    monkeypatch.setattr(IdeationAgent, "get_prompt", lambda self, *a, **k: None)

    agent = IdeationAgent(language="en")
    proposal = await agent.process(ideation_context=context)

    assert proposal.title == "Fallback Book"
    assert seen[0]["user_prompt"] == (context.render() + "\n\nRespond with the JSON object only.")
    assert "Propose ONE coherent book" in seen[0]["system_prompt"]


@pytest.mark.asyncio
async def test_process_title_only_payload_is_usable_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal, calls = await _run_process(monkeypatch, ['{"title":"Only A Title"}'])

    assert proposal.title == "Only A Title"
    assert proposal.estimated_chapters == 2
    assert [c["reasoning_effort"] for c in calls] == [None]


@pytest.mark.asyncio
async def test_process_retries_complete_answer_missing_title_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal, calls = await _run_process(
        monkeypatch,
        [
            '{"description":"complete JSON but the required key is absent"}',
            '{"title":"Recovered","description":"second attempt"}',
        ],
    )

    assert proposal.title == "Recovered"
    assert proposal.description == "second attempt"
    assert [c["reasoning_effort"] for c in calls] == [None, "low"]


@pytest.mark.asyncio
async def test_process_degrades_to_defaults_when_no_attempt_is_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal, calls = await _run_process(
        monkeypatch,
        ["sorry, no JSON this time", '{"unrelated": true}'],
    )

    assert proposal.title == "Untitled Book"
    assert proposal.description == ""
    assert proposal.scope == ""
    assert proposal.target_level == "mixed"
    assert proposal.estimated_chapters == 2
    assert proposal.rationale == ""
    assert [c["reasoning_effort"] for c in calls] == [None, "low"]


# ─────────────────────────────────────────────────────────────────────────────
# Contract: _coerce_proposal normalisation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 2),
        (1, 2),
        (2, 2),
        (5, 5),
        (8, 8),
        (9, 8),
        (99, 8),
        ("6", 6),
        (3.9, 3),
        (None, 2),
        ("abc", 4),
        (["two"], 4),
    ],
)
def test_coerce_clamps_estimated_chapters_to_supported_range(raw: Any, expected: int) -> None:
    proposal = IdeationAgent._coerce_proposal(
        {"title": "T", "estimated_chapters": raw},
        IdeationContext(user_intent="Math"),
    )
    assert proposal.estimated_chapters == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (None, "Untitled Book"),
        ("", "Untitled Book"),
        ("   ", "Untitled Book"),
        ("Real Title", "Real Title"),
        (404, "404"),
    ],
)
def test_coerce_normalises_title(title: Any, expected: str) -> None:
    proposal = IdeationAgent._coerce_proposal(
        {"title": title},
        IdeationContext(user_intent="Math"),
    )
    assert proposal.title == expected


def test_coerce_truncates_oversized_title_to_hard_cap() -> None:
    proposal = IdeationAgent._coerce_proposal(
        {"title": "A" * 300},
        IdeationContext(user_intent="Math"),
    )
    assert proposal.title == "A" * 120


@pytest.mark.parametrize(
    ("target_level", "expected"),
    [
        (None, "mixed"),
        ("", "mixed"),
        ("  advanced  ", "advanced"),
    ],
)
def test_coerce_defaults_target_level(target_level: Any, expected: str) -> None:
    proposal = IdeationAgent._coerce_proposal(
        {"title": "T", "target_level": target_level},
        IdeationContext(user_intent="Math"),
    )
    assert proposal.target_level == expected


def test_coerce_strips_blank_optional_text_fields() -> None:
    proposal = IdeationAgent._coerce_proposal(
        {
            "title": "T",
            "description": "  pitch  ",
            "scope": None,
            "rationale": "\n\t",
        },
        IdeationContext(user_intent="Math"),
    )
    assert proposal.description == "pitch"
    assert proposal.scope == ""
    assert proposal.rationale == ""
