"""Unit tests for the concept-graph block: ``render_mermaid`` and
``ConceptGraphGenerator``.

Covers Top100 #92 (``deeptutor/book/blocks/concept_graph.py``): the rendered
Mermaid output contract, chapter-mode numbering, id sanitisation, and the
generator's empty / invalid / unexpected payload branches. No LLM, network or
real services are involved.
"""

from __future__ import annotations

import pytest

from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.blocks.concept_graph import ConceptGraphGenerator, render_mermaid
from deeptutor.book.models import (
    Block,
    BlockType,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Page,
)


def _graph(**kwargs) -> ConceptGraph:
    return ConceptGraph(**kwargs)


def _chapter_mode_graph() -> ConceptGraph:
    return ConceptGraph(
        nodes=[
            ConceptNode(id="root", label="Linear Algebra"),
            ConceptNode(id="ch-one", label="Vectors", chapter_id="chapter-1"),
            ConceptNode(id="ch-two", label='Bases & "spaces"', chapter_id="chapter-2"),
        ],
        edges=[ConceptEdge(src="root", dst="ch-one", relation="extends")],
    )


def _generator_ctx(
    block: Block,
    extra: dict | None = None,
) -> BlockContext:
    return BlockContext(
        book_id="book-1",
        chapter=Chapter(id="chapter-1", title="T"),
        page=Page(book_id="book-1", chapter_id="chapter-1"),
        block=block,
        extra=extra if extra is not None else {},
    )


# ---------------------------------------------------------------------------
# render_mermaid — output contract
# ---------------------------------------------------------------------------


def test_render_mermaid_empty_graph_placeholder() -> None:
    rendered = render_mermaid(_graph(nodes=[], edges=[]))

    assert rendered == 'graph TD\n  empty["(no concepts yet)"]'


def test_render_mermaid_plain_mode_nodes_and_edges() -> None:
    graph = _graph(
        nodes=[
            ConceptNode(id="a", label="Alpha"),
            ConceptNode(id="b", label="Beta"),
        ],
        edges=[ConceptEdge(src="a", dst="b", relation="depends_on")],
    )

    rendered = render_mermaid(graph)

    lines = rendered.splitlines()
    assert lines[0] == "graph TD"
    assert lines[1] == '  a["Alpha"]'
    assert lines[2] == '  b["Beta"]'
    assert lines[3] == "  a --> b"
    # Plain mode: no stadium shape anywhere.
    assert "([" not in rendered


def test_render_mermaid_chapter_mode_numbers_and_stadium_root() -> None:
    rendered = render_mermaid(_chapter_mode_graph())

    lines = rendered.splitlines()
    # Root carries no chapter_id → stadium shape, no number, and does not
    # consume a chapter sequence slot.
    assert lines[1] == '  root(["Linear Algebra"])'
    assert lines[2] == '  ch_one["01 · Vectors"]'
    assert lines[3] == '  ch_two["02 · Bases & \'spaces\'"]'
    assert lines[4] == "  root ==> ch_one"


def test_render_mermaid_edge_arrow_mapping_and_default() -> None:
    graph = _graph(
        nodes=[
            ConceptNode(id="a", label="A"),
            ConceptNode(id="b", label="B"),
            ConceptNode(id="c", label="C"),
            ConceptNode(id="d", label="D"),
        ],
        edges=[
            ConceptEdge(src="a", dst="b", relation="related"),
            ConceptEdge(src="b", dst="c", relation="depends_on"),
            ConceptEdge(src="c", dst="d", relation="mystery-relation"),
            ConceptEdge(src="d", dst="a", relation=""),
        ],
    )

    lines = render_mermaid(graph).splitlines()

    assert "  a -.-> b" in lines
    assert "  b --> c" in lines
    # Unknown / empty relations fall back to the plain arrow.
    assert "  c --> d" in lines
    assert "  d --> a" in lines


def test_render_mermaid_skips_dangling_edges() -> None:
    graph = _graph(
        nodes=[ConceptNode(id="a", label="A")],
        edges=[
            ConceptEdge(src="a", dst="ghost"),
            ConceptEdge(src="phantom", dst="a"),
        ],
    )

    lines = render_mermaid(graph).splitlines()

    assert lines == ["graph TD", '  a["A"]']


def test_render_mermaid_sanitises_node_ids() -> None:
    graph = _graph(
        nodes=[
            ConceptNode(id="a.b c", label="dots and spaces"),
            ConceptNode(id="!!!", label="all punctuation"),
            ConceptNode(id="", label="Falls Back To Label"),
            ConceptNode(id="x" * 40, label="long id truncated"),
        ],
        edges=[],
    )

    rendered = render_mermaid(graph)

    assert '  a_b_c["dots and spaces"]' in rendered
    # Non-alphanumeric ids collapse to "_" then strip to nothing → "n".
    assert '  n["all punctuation"]' in rendered
    assert '  Falls_Back_To_Label["Falls Back To Label"]' in rendered
    assert ('  ' + "x" * 32) in rendered
    assert "x" * 33 not in rendered


def test_render_mermaid_deduplicates_colliding_ids() -> None:
    graph = _graph(
        nodes=[
            ConceptNode(id="dup", label="first"),
            ConceptNode(id="dup", label="second"),
        ],
        edges=[],
    )

    rendered = render_mermaid(graph)

    assert '  dup["first"]' in rendered
    assert '  dup_2["second"]' in rendered


def test_render_mermaid_escapes_labels() -> None:
    graph = _graph(
        nodes=[
            ConceptNode(id="a", label='say "hi"'),
            ConceptNode(id="b", label="line one\n  line\ttwo"),
            ConceptNode(id="c", label="   "),
            ConceptNode(id="d", label=""),
        ],
        edges=[],
    )

    rendered = render_mermaid(graph)

    assert '  a["say \'hi\'"]' in rendered
    assert '  b["line one line two"]' in rendered
    # Whitespace-only and empty labels fall back to the generic concept label.
    assert rendered.count('["concept"]') == 2


# ---------------------------------------------------------------------------
# ConceptGraphGenerator — payload contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generator_accepts_concept_graph_instance() -> None:
    graph = _chapter_mode_graph()
    block = Block(type=BlockType.CONCEPT_GRAPH)

    result = await ConceptGraphGenerator().generate(_generator_ctx(block, {"concept_graph": graph}))

    assert result.status.value == "ready"
    payload = result.payload
    assert payload["render_type"] == "concept_graph"
    assert payload["code"]["language"] == "mermaid"
    assert payload["code"]["content"] == render_mermaid(graph)
    assert payload["graph"] == graph.model_dump()
    assert result.source_anchors == []
    assert result.metadata["node_count"] == 3
    assert result.metadata["edge_count"] == 1
    assert "failure" not in result.metadata


@pytest.mark.asyncio
async def test_generator_validates_dict_payload_and_builds_index() -> None:
    graph = ConceptGraph(
        nodes=[
            ConceptNode(id="vectors", label="Vectors", chapter_id="chapter-1"),
            ConceptNode(id="root", label="Root"),
        ],
        edges=[ConceptEdge(src="vectors", dst="root")],
    )
    chapters_index = [{"id": "chapter-1", "title": "T"}]
    block = Block(
        type=BlockType.CONCEPT_GRAPH,
        params={"concept_graph": graph.model_dump()},
    )

    result = await ConceptGraphGenerator().generate(
        _generator_ctx(block, {"chapter_index": chapters_index})
    )

    assert result.status.value == "ready"
    index = result.payload["index"]
    assert index["chapters"] == chapters_index
    # Only nodes that carry a chapter_id land in the sidebar mapping.
    assert index["node_to_chapter"] == {"vectors": "chapter-1"}


@pytest.mark.asyncio
async def test_generator_extra_payload_wins_over_block_params() -> None:
    extra_graph = ConceptGraph(nodes=[ConceptNode(id="from-extra", label="Extra")])
    params_graph = ConceptGraph(nodes=[ConceptNode(id="from-params", label="Params")])
    block = Block(
        type=BlockType.CONCEPT_GRAPH,
        params={"concept_graph": params_graph.model_dump()},
    )

    result = await ConceptGraphGenerator().generate(
        _generator_ctx(block, {"concept_graph": extra_graph.model_dump()})
    )

    assert result.status.value == "ready"
    assert "from_extra" in result.payload["code"]["content"]
    assert "from_params" not in result.payload["code"]["content"]


@pytest.mark.asyncio
async def test_generator_coerces_non_list_chapter_index_to_empty() -> None:
    graph = ConceptGraph(nodes=[ConceptNode(id="a", label="A")])
    block = Block(type=BlockType.CONCEPT_GRAPH)

    result = await ConceptGraphGenerator().generate(
        _generator_ctx(block, {"concept_graph": graph.model_dump(), "chapter_index": "nope"})
    )

    assert result.status.value == "ready"
    assert result.payload["index"]["chapters"] == []


@pytest.mark.asyncio
async def test_generator_missing_payload_marks_block_error() -> None:
    block = Block(type=BlockType.CONCEPT_GRAPH)

    result = await ConceptGraphGenerator().generate(_generator_ctx(block, {}))

    assert result.status.value == "error"
    assert "missing from BlockContext.extra" in result.error
    failure = result.metadata["failure"]
    assert failure["kind"] == "generator_error"
    assert failure["retryable"] is True
    assert failure["source"] == "ConceptGraphGenerator"
    assert result.payload == {}


@pytest.mark.asyncio
async def test_generator_invalid_dict_payload_marks_block_error() -> None:
    block = Block(
        type=BlockType.CONCEPT_GRAPH,
        params={"concept_graph": {"nodes": [{"weight": "heavy"}], "edges": []}},
    )

    result = await ConceptGraphGenerator().generate(_generator_ctx(block, {}))

    assert result.status.value == "error"
    assert "invalid concept_graph payload" in result.error
    assert isinstance(result.metadata["failure"]["message"], str)


@pytest.mark.asyncio
async def test_generator_unexpected_payload_type_marks_block_error() -> None:
    block = Block(type=BlockType.CONCEPT_GRAPH)

    result = await ConceptGraphGenerator().generate(
        _generator_ctx(block, {"concept_graph": ["not", "a", "graph"]})
    )

    assert result.status.value == "error"
    assert "unexpected concept_graph payload type: list" in result.error


@pytest.mark.asyncio
async def test_generator_empty_graph_renders_placeholder_payload() -> None:
    block = Block(type=BlockType.CONCEPT_GRAPH)

    result = await ConceptGraphGenerator().generate(
        _generator_ctx(block, {"concept_graph": ConceptGraph()})
    )

    assert result.status.value == "ready"
    assert result.payload["code"]["content"] == 'graph TD\n  empty["(no concepts yet)"]'
    assert result.metadata["node_count"] == 0
    assert result.metadata["edge_count"] == 0


def test_generator_registered_for_concept_graph_block_type() -> None:
    from deeptutor.book.blocks.base import get_block_registry

    generator = get_block_registry().get(BlockType.CONCEPT_GRAPH)

    assert isinstance(generator, ConceptGraphGenerator)
    assert generator.block_type == BlockType.CONCEPT_GRAPH
