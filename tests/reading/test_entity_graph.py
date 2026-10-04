from __future__ import annotations

import json
from pathlib import Path
import tomllib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.entity_graph import EntityGraphExtension
from deeptutor.reading.extensions import ReadingContext, ReadingExtensionRegistry
from deeptutor.services.path_service import PathService

VISIBLE = (
    "Chapter 3. Alice met her sister Lena at the harbour. "
    "Alice waved to Captain Bell, the harbourmaster, and Lena smiled."
)


def _context(visible_text: str = VISIBLE) -> ReadingContext:
    return ReadingContext(
        material_id="material",
        locator=3,
        locale="en",
        selection="",
        visible_text=visible_text,
    )


def _model_response() -> str:
    return json.dumps(
        {
            "nodes": [
                {"name": "Alice", "kind": "character", "aliases": ["alice"]},
                {"name": "Lena", "kind": "character", "aliases": []},
                {
                    "name": "Captain Bell",
                    "kind": "character",
                    "aliases": ["harbourmaster"],
                },
                {"name": "the harbour", "kind": "place", "aliases": []},
            ],
            "edges": [
                {
                    "source": "Alice",
                    "target": "Lena",
                    "label": "sister of",
                    "evidence": "Alice met her sister Lena at the harbour",
                },
                {
                    "source": "Captain Bell",
                    "target": "the harbour",
                    "label": "harbourmaster of",
                    "evidence": "Alice waved to Captain Bell, the harbourmaster",
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_entity_graph_returns_a_grounded_card(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context())

    assert result.type == "card"
    assert result.title == "Character & entity graph"
    assert result.message == "Relationships and evidence come from the current chapter."
    assert result.payload["degraded"] is False
    assert [node["name"] for node in result.payload["nodes"]] == [
        "Alice",
        "Lena",
        "Captain Bell",
        "the harbour",
    ]
    assert result.payload["edges"] == [
        {
            "source": "Alice",
            "target": "Lena",
            "label": "sister of",
            "evidence": "Alice met her sister Lena at the harbour",
        },
        {
            "source": "Captain Bell",
            "target": "the harbour",
            "label": "harbourmaster of",
            "evidence": "Alice waved to Captain Bell, the harbourmaster",
        },
    ]
    mermaid = result.payload["mermaid"]
    assert mermaid.startswith("graph TD")
    assert 'n1["Alice"]' in mermaid
    assert 'n2["Lena"]' in mermaid
    assert 'n1 -->|"sister of"| n2' in mermaid
    prompt = json.loads(calls[0]["prompt"])
    assert prompt["selection"] == ""
    assert "Chapter 3" in prompt["surrounding_context"]
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_entity_graph_merges_duplicate_and_alias_nodes(monkeypatch):
    async def complete(**_kwargs):
        return json.dumps(
            {
                "nodes": [
                    {"name": "Alice", "kind": "character", "aliases": []},
                    {
                        "name": "ALICE",
                        "kind": "person",
                        "aliases": ["Alice Liddell"],
                    },
                    {"name": "Lena", "kind": "character", "aliases": []},
                ],
                "edges": [
                    {
                        "source": "Alice Liddell",
                        "target": "lena",
                        "label": "sister of",
                        "evidence": "Alice met her sister Lena at the harbour",
                    }
                ],
            }
        )

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context())

    names = [node["name"] for node in result.payload["nodes"]]
    assert names == ["Alice", "Lena"]
    assert result.payload["edges"][0]["source"] == "Alice"
    assert result.payload["edges"][0]["target"] == "Lena"


@pytest.mark.asyncio
async def test_entity_graph_drops_invented_entities(monkeypatch):
    async def complete(**_kwargs):
        return json.dumps(
            {
                "nodes": [
                    {"name": "Alice", "kind": "character", "aliases": []},
                    {"name": "Lena", "kind": "character", "aliases": []},
                    {"name": "Zeus", "kind": "character", "aliases": []},
                ],
                "edges": [
                    {
                        "source": "Alice",
                        "target": "Lena",
                        "label": "sister of",
                        "evidence": "Alice met her sister Lena at the harbour",
                    },
                    {
                        "source": "Zeus",
                        "target": "Alice",
                        "label": "protects",
                        "evidence": "Alice met her sister Lena at the harbour",
                    },
                ],
            }
        )

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context())

    assert [node["name"] for node in result.payload["nodes"]] == ["Alice", "Lena"]
    assert [edge["source"] for edge in result.payload["edges"]] == ["Alice"]
    assert "Zeus" not in result.payload["mermaid"]


@pytest.mark.asyncio
async def test_ungrounded_evidence_degrades_instead_of_inventing_links(monkeypatch):
    async def complete(**_kwargs):
        return (
            _model_response()
            .replace(
                "Alice met her sister Lena at the harbour",
                "Alice fought her cousin Lena in the mountains",
            )
            .replace(
                "Alice waved to Captain Bell, the harbourmaster",
                "Alice ignored Captain Bell, the pirate",
            )
        )

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context())

    assert result.type == "card"
    assert result.payload["degraded"] is True
    assert result.payload["nodes"] == []
    assert result.payload["edges"] == []
    assert result.payload["mermaid"] == ""
    assert "No relationships could be verified" in result.message


@pytest.mark.asyncio
async def test_empty_extraction_degrades_explicitly(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps({"nodes": [], "edges": []})

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context())

    assert result.type == "card"
    assert result.payload["degraded"] is True
    assert result.payload["edges"] == []
    assert result.payload["mermaid"] == ""
    # An empty answer is unusable for the structured retry, so it is asked
    # once more before the extension accepts the empty chapter.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_mermaid_labels_survive_quotes_and_pipes(monkeypatch):
    text = (
        'Chapter 3. Alice "the Bold" met her sister Lena at the harbour. '
        "Alice waved to Captain Bell, the harbourmaster, and Lena smiled."
    )

    async def complete(**_kwargs):
        return json.dumps(
            {
                "nodes": [
                    {"name": 'Alice "the Bold"', "kind": "character", "aliases": []},
                    {"name": "Lena", "kind": "character", "aliases": []},
                ],
                "edges": [
                    {
                        "source": 'Alice "the Bold"',
                        "target": "Lena",
                        "label": 'calls "twin" | often',
                        "evidence": "met her sister Lena at the harbour",
                    }
                ],
            }
        )

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context(text))

    mermaid = result.payload["mermaid"]
    assert "#quot;the Bold#quot;" in mermaid
    assert "#quot;twin#quot; / often" in mermaid
    for line in mermaid.splitlines():
        assert line.count('"') % 2 == 0


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        json.dumps({}),
        json.dumps({"edges": []}),
        json.dumps({"nodes": "Alice"}),
        json.dumps(
            {
                "nodes": [{"name": "A", "kind": "character", "aliases": []}],
                "edges": [],
            }
        ),
        json.dumps(
            {
                "nodes": [
                    {"name": "Alice", "kind": "character", "aliases": []},
                    {"name": "Lena", "kind": "character", "aliases": []},
                ],
                "edges": [
                    {
                        "source": "Alice",
                        "target": "Lena",
                        "label": "sister of",
                        "evidence": "short",
                    }
                ],
            }
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_model_output_is_rejected(monkeypatch, response):
    async def complete(**_kwargs):
        return response

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    with pytest.raises(ValueError):
        await EntityGraphExtension().run_action("build", _context())


@pytest.mark.asyncio
async def test_missing_visible_text_fails_before_an_llm_call(monkeypatch):
    async def complete(**_kwargs):
        pytest.fail("missing text must not invoke the model")

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    with pytest.raises(ValueError, match="requires visible text"):
        await EntityGraphExtension().run_action("build", _context(""))


@pytest.mark.asyncio
async def test_graph_size_is_capped(monkeypatch):
    names = [f"Member{index}" for index in range(15)]
    text = "Chapter roster: " + ", ".join(names) + " gathered."
    edges = [
        {
            "source": "Member0",
            "target": name,
            "label": f"relation {index}",
            "evidence": "Chapter roster",
        }
        for index, name in enumerate(names[1:], start=1)
    ]
    edges += [
        {
            "source": "Member1",
            "target": name,
            "label": f"extra relation {index}",
            "evidence": "gathered",
        }
        for index, name in enumerate(names[2:], start=2)
    ]

    async def complete(**_kwargs):
        return json.dumps(
            {
                "nodes": [{"name": name, "kind": "character", "aliases": []} for name in names],
                "edges": edges,
            }
        )

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    result = await EntityGraphExtension().run_action("build", _context(text))

    assert len(result.payload["nodes"]) <= 12
    assert len(result.payload["edges"]) <= 20
    kept_names = {node["name"] for node in result.payload["nodes"]}
    for edge in result.payload["edges"]:
        assert edge["source"] in kept_names
        assert edge["target"] in kept_names


def test_entity_graph_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["entity_graph"] == "deeptutor.reading.entity_graph:EntityGraphExtension"


def _client(monkeypatch) -> TestClient:
    registry = ReadingExtensionRegistry([EntityGraphExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_entity_graph_crosses_the_api_boundary_with_stored_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text(VISIBLE, encoding="utf-8")
    material = ReadingStore().ingest(source)
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return _model_response()

    monkeypatch.setattr("deeptutor.reading.entity_graph.complete", complete)
    client = _client(monkeypatch)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/entity_graph/actions/build",
            json={
                "locator": 1,
                "selection": "",
                "visible_text": "forged chapter text with no names",
                "locale": "en",
            },
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "card"
    assert body["payload"]["degraded"] is False
    assert 'n1["Alice"]' in body["payload"]["mermaid"]
    prompt = json.loads(captured["prompt"])
    assert "Chapter 3" in prompt["surrounding_context"]
    assert "forged chapter text" not in prompt["surrounding_context"]
