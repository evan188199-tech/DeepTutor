"""SourceExplorer contract: two LLM calls, then a usable report either way.

Stage 2 of BookEngine runs ``queries`` (design the sweep) and ``summary``
(distil what came back). Both calls go through ``BaseAgent.stream_llm`` with
``json_with_reasoning_retry`` parsing, and both must degrade instead of
raising: unusable query output falls back to the default sweep, unusable
summary output leaves the report empty but still delivers its chunks. The
tests stub ``stream_llm`` — no provider, no retrieval backend is touched.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.source_explorer import (
    _DEFAULT_QUERIES,
    SourceExplorer,
    _balanced_slice,
)
from deeptutor.book.models import (
    BookInputs,
    BookProposal,
    ChatMessageSnapshot,
    SourceChunk,
)
from deeptutor.services.config import loader as loader_module
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS


@pytest.fixture(autouse=True)
def _agent_settings_home(tmp_path, monkeypatch):
    """``get_agent_params`` requires ``data/user/settings/agents.yaml``.

    Tests must not depend on a runtime home seeded by a real install, so every
    test gets its own tmp home holding the shipped defaults.
    """
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "agents.yaml").write_text(
        yaml.safe_dump(DEFAULT_AGENTS_SETTINGS), encoding="utf-8"
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", tmp_path)


def _proposal() -> BookProposal:
    return BookProposal(
        title="Linear Algebra",
        description="An undergraduate introduction",
        scope="vectors through eigenvalues",
        target_level="undergraduate",
        estimated_chapters=2,
    )


def _inputs(**overrides: Any) -> BookInputs:
    fields: dict[str, Any] = {
        "user_intent": "help students build intuition",
        "knowledge_bases": [],
        "source_context": "Lecture note: a vector space is closed under addition.",
        "chat_history": [
            ChatMessageSnapshot(
                role="user",
                content="Why is every basis the same size?",
                created_at=17.0,
            )
        ],
    }
    fields.update(overrides)
    return BookInputs(**fields)


def _stub_stream_llm(
    monkeypatch: pytest.MonkeyPatch,
    by_stage: dict[str, Any],
    *,
    calls: list[dict[str, Any]] | None = None,
) -> None:
    """Replay scripted responses per ``stage`` kwarg of ``stream_llm``.

    A string entry is yielded chunk by chunk; a callable entry is invoked and
    may raise or mutate ``outcome``. Every call's kwargs land in ``calls``.
    """
    log = calls if calls is not None else []

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        log.append(kwargs)
        script = by_stage.get(kwargs.get("stage"), "")
        if callable(script):
            script(**kwargs)
        if isinstance(script, str):
            for piece in script.split("chunksplit"):
                yield piece
        else:  # scripted non-string (e.g. json payload via str)
            yield str(script)

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)


def _queries_payload(*queries: str) -> str:
    return json.dumps({"queries": list(queries)})


def _summary_payload(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "summary": "Sources converge on vector spaces as the core theme.",
        "candidate_concepts": ["vector space", "basis", "dimension"],
        "notes": ["Chat asked about basis cardinality."],
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_design_queries_assembles_input_and_parses_the_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_stream_llm(
        monkeypatch,
        {
            "explore_queries": _queries_payload(
                "vector spaces overview", "VECTOR SPACES OVERVIEW", "", "  ", "basis size"
            )
        },
        calls=calls,
    )
    explorer = SourceExplorer()
    inputs = _inputs(knowledge_bases=["kb0", "kb1"])

    queries = await explorer._design_queries(proposal=_proposal(), inputs=inputs)

    # Duplicates (case-insensitive) and blanks are dropped, order preserved.
    assert queries == ["vector spaces overview", "basis size"]
    assert len(calls) == 1  # a good first answer is not retried
    assert calls[0]["stage"] == "explore_queries"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["outcome"] is not None
    assert "help students build intuition" in calls[0]["user_prompt"]
    assert "kb0" in calls[0]["user_prompt"]
    assert "Linear Algebra" in calls[0]["user_prompt"]
    # Retrieval queries follow the sources, not the book's language.
    assert "language the source material" in calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_design_queries_caps_length_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stream_llm(
        monkeypatch,
        {"explore_queries": _queries_payload("q" * 300, "r" * 300, "keep me")},
    )
    explorer = SourceExplorer(max_queries=2)

    queries = await explorer._design_queries(proposal=_proposal(), inputs=_inputs())

    assert queries == ["q" * 160, "r" * 160]


@pytest.mark.asyncio
async def test_design_queries_returns_empty_on_malformed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_stream_llm(
        monkeypatch,
        {"explore_queries": "I would rather write prose than JSON."},
        calls=calls,
    )

    queries = await SourceExplorer()._design_queries(proposal=_proposal(), inputs=_inputs())

    assert queries == []
    assert len(calls) == 2  # the reasoning retry also saw no JSON


@pytest.mark.asyncio
async def test_design_queries_returns_empty_when_stream_is_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _truncate(**kwargs: Any) -> None:
        kwargs["outcome"].finish_reason = "length"

    _stub_stream_llm(
        monkeypatch,
        {"explore_queries": _truncate},
        calls=calls,
    )

    queries = await SourceExplorer()._design_queries(proposal=_proposal(), inputs=_inputs())

    # A provider-cut payload is unusable even though it parsed: both attempts
    # must be made and both discarded.
    assert queries == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_design_queries_returns_empty_when_the_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("provider down")

    _stub_stream_llm(monkeypatch, {"explore_queries": _boom}, calls=calls)

    queries = await SourceExplorer()._design_queries(proposal=_proposal(), inputs=_inputs())

    assert queries == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_summarise_skips_the_llm_when_there_is_nothing_to_summarise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected(**_kwargs: Any) -> None:
        raise AssertionError("no chunks means no summary call")

    _stub_stream_llm(monkeypatch, {"explore_summary": _unexpected})

    result = await SourceExplorer()._summarise(
        proposal=_proposal(), intent="x", chunks=[], coverage={}
    )

    assert result == ("", [], [])


@pytest.mark.asyncio
async def test_summarise_parses_coerces_and_clips_the_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_stream_llm(
        monkeypatch,
        {
            "explore_summary": _summary_payload(
                summary="s" * 3000,
                candidate_concepts=[
                    "Vector Space",
                    "vector space",
                    "",
                    42,
                    {"a": 1},
                ],
                notes="not a list",
            )
        },
        calls=calls,
    )
    explorer = SourceExplorer(language="ja")
    chunk = SourceChunk(chunk_id="c1", source="notebook", ref="r1", text="t")

    summary, concepts, notes = await explorer._summarise(
        proposal=_proposal(),
        intent="help me",
        chunks=[chunk],
        coverage={"notebook": 1},
    )

    assert summary == "s" * 2400 + "…"  # clipped, ellipsis marks the cut
    assert concepts[:2] == ["Vector Space", "42"]  # deduped case-insensitively
    assert str({"a": 1}) in concepts
    assert notes == []  # a scalar where a list belongs coerces to nothing
    assert calls[0]["stage"] == "explore_summary"
    # The summary is reader-facing, so it carries the language directive.
    assert "日本語" in calls[0]["system_prompt"]
    assert "help me" in calls[0]["user_prompt"]


@pytest.mark.asyncio
async def test_summarise_returns_empty_when_the_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("provider down")

    _stub_stream_llm(monkeypatch, {"explore_summary": _boom})
    chunk = SourceChunk(chunk_id="c1", source="notebook", ref="r1", text="t")

    result = await SourceExplorer()._summarise(
        proposal=_proposal(), intent="x", chunks=[chunk], coverage={"notebook": 1}
    )

    assert result == ("", [], [])


@pytest.mark.asyncio
async def test_explore_delivers_a_report_with_default_queries_and_non_kb_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stream_llm(
        monkeypatch,
        {
            # Query design unusable → the default sweep must take over.
            "explore_queries": "no json here",
            "explore_summary": _summary_payload(),
        },
    )

    report = await SourceExplorer().explore(
        book_id="book-1", proposal=_proposal(), inputs=_inputs()
    )

    assert report.queries == list(_DEFAULT_QUERIES)
    assert report.book_id == "book-1"
    by_source = {ch.source for ch in report.chunks}
    assert by_source == {"notebook", "chat"}
    assert report.coverage == {"notebook": 1, "chat": 1}
    assert report.summary.startswith("Sources converge")
    assert "basis" in report.candidate_concepts


@pytest.mark.asyncio
async def test_explore_reports_connected_knowledge_bases_it_could_not_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stream_llm(
        monkeypatch,
        {
            "explore_queries": _queries_payload("vector spaces"),
            "explore_summary": _summary_payload(),
        },
    )
    monkeypatch.setattr(
        SourceExplorer,
        "partition_knowledge_bases",
        staticmethod(lambda kb_list: ([], ["obsidian-vault"])),
    )
    inputs = _inputs(knowledge_bases=["obsidian-vault"])

    report = await SourceExplorer().explore(book_id="book-1", proposal=_proposal(), inputs=inputs)

    assert report.queries == ["vector spaces"]
    assert any("obsidian-vault" in note for note in report.notes)


def test_dedupe_and_clip_dedupes_and_caps_the_report_chunks() -> None:
    first = SourceChunk(chunk_id="a", source="kb", ref="d1", text="same text")
    duplicate = SourceChunk(chunk_id="b", source="kb", ref="d1", text="same text")
    chunks = [first, duplicate] + [
        SourceChunk(chunk_id=f"c{i}", source="kb", ref=f"d{i}", text=f"text {i}")
        for i in range(100)
    ]

    result = SourceExplorer._dedupe_and_clip(chunks)

    assert len(result) == 96
    assert len({(c.source, c.ref, c.text[:200]) for c in result}) == 96


def test_balanced_slice_round_robins_across_sources() -> None:
    chunks: list[SourceChunk] = []
    for kb in ("kb0", "kb1", "kb2"):
        for rank in range(5):
            chunks.append(
                SourceChunk(
                    chunk_id=f"{kb}-{rank}",
                    kb_name=kb,
                    source="kb",
                    ref=f"{kb}-{rank}",
                    text=f"{kb} passage {rank}",
                    score=10.0 - rank,
                )
            )

    picked = _balanced_slice(chunks, limit=6)

    assert len(picked) == 6
    # Round one takes the best chunk of every source before any second pick.
    assert [c.kb_name for c in picked[:3]] == ["kb0", "kb1", "kb2"]
    assert {c.kb_name for c in picked} == {"kb0", "kb1", "kb2"}
