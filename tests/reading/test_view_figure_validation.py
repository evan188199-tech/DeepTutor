"""Validation, locator, size, and degradation branches of the ``view_figure`` tool.

Covers the failure paths the happy-path suite does not reach: a missing or
unknown figure name (with the capped availability listing), a bad locator,
an oversized image, vision-client unavailability via a raising constructor,
an empty vision answer, the default question, MIME inference, and the
no-open-material guard.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.reading.figure_view import (
    _DEFAULT_FIGURE_QUESTION,
    ViewFigureTool,
)


class _Store:
    def __init__(self, rows, paths, unit_count=3):
        self._rows = rows
        self._paths = paths
        self._unit_count = unit_count
        self.manifest_requested = False

    def media_items(self, material_id):
        return self._rows

    def media_path(self, material_id, name):
        return self._paths.get(name)

    def manifest(self, material_id):
        self.manifest_requested = True
        return SimpleNamespace(
            unit="page", unit_count=self._unit_count, revision=4, filename="paper.pdf"
        )


def _row(name="image-05.png", locator=2, mime="image/png", caption="A chart with two axes."):
    return {"name": name, "locator": locator, "mime": mime, "caption": caption}


class _RecordingVision:
    def __init__(self, answer="The vertical axis is probability."):
        self.answer = answer
        self.calls = []

    def supports_multimodal_images(self):
        return True

    async def complete(self, question, **kwargs):
        self.calls.append((question, kwargs))
        return self.answer


@pytest.fixture
def configure(monkeypatch):
    monkeypatch.setattr(ViewFigureTool, "_material_id", staticmethod(lambda _kwargs: "material-1"))
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.config.image_description_limits",
        lambda: (0, 2.0),
    )

    def configure(rows, paths, client, unit_count=3, store=None):
        store = store or _Store(rows, paths, unit_count)
        monkeypatch.setattr(ViewFigureTool, "_store", staticmethod(lambda: store))
        monkeypatch.setattr("deeptutor.services.llm.client.get_llm_client", lambda: client)
        return ViewFigureTool()

    return configure


def test_definition_requires_the_name_and_keeps_the_question_optional(configure):
    definition = configure([], {}, None).get_definition()

    assert definition.name == "view_figure"
    required = {p.name for p in definition.parameters if p.required}
    optional = {p.name for p in definition.parameters if not p.required}
    assert required == {"name"}
    assert optional == {"question"}


def test_missing_name_fails_before_the_store_is_consulted(configure):
    class _ForbiddenStore(_Store):
        def media_items(self, material_id):
            raise AssertionError("A blank name must not reach the store")

    tool = configure([], {}, None, store=_ForbiddenStore([], {}))

    result = asyncio.run(tool.execute(name="   "))

    assert result.success is False
    assert "needs a figure name" in result.content


def test_unknown_name_lists_the_available_figures_without_reading_the_manifest(configure):
    rows = [_row(name="image-01.png", locator=1), _row(name="image-05.png", locator=2)]
    store = _Store(rows, {})
    tool = configure(rows, {}, None, store=store)

    result = asyncio.run(tool.execute(name="image-99.png"))

    assert result.success is False
    assert "No figure named" in result.content
    assert "image-01.png" in result.content and "image-05.png" in result.content
    assert store.manifest_requested is False


def test_unknown_name_caps_the_listing_for_media_heavy_documents(configure):
    rows = [_row(name=f"image-{i:02d}.png", locator=1) for i in range(25)]
    result = asyncio.run(configure(rows, {}, None).execute(name="missing.png"))

    assert result.success is False
    assert "25 images in total" in result.content
    assert "image-19.png" in result.content
    assert "image-20.png" not in result.content


def test_unknown_name_with_no_figures_says_none_are_available(configure):
    result = asyncio.run(configure([], {}, None).execute(name="missing.png"))

    assert result.success is False
    assert "Available figures: none." in result.content


@pytest.mark.parametrize("locator", [None, "2", 2.0, 0, 4])
def test_invalid_or_out_of_range_locator_fails_before_disk(configure, tmp_path, locator):
    image = tmp_path / "image-05.png"
    image.write_bytes(b"pixels")

    class _ForbiddenVision:
        def supports_multimodal_images(self):
            raise AssertionError("A bad locator must not reach the vision client")

    result = asyncio.run(
        configure([_row(locator=locator)], {"image-05.png": image}, _ForbiddenVision()).execute(
            name="image-05.png"
        )
    )

    assert result.success is False
    assert "no valid document locator" in result.content


def test_oversized_image_fails_without_reaching_vision(configure, monkeypatch, tmp_path):
    import deeptutor.utils.document_images as document_images

    monkeypatch.setattr(document_images, "MAX_IMAGE_BYTES", 8)
    image = tmp_path / "image-05.png"
    image.write_bytes(b"way-more-than-eight-bytes")

    class _ForbiddenVision:
        def supports_multimodal_images(self):
            raise AssertionError("An oversized image must not reach the vision client")

    result = asyncio.run(
        configure([_row()], {"image-05.png": image}, _ForbiddenVision()).execute(
            name="image-05.png"
        )
    )

    assert result.success is False
    assert "over the 8-byte" in result.content
    assert "cannot be viewed" in result.content


def test_raising_client_constructor_degrades_to_caption_instead_of_crashing(
    configure, monkeypatch, tmp_path
):
    image = tmp_path / "image-05.png"
    image.write_bytes(b"pixels")
    monkeypatch.setattr(
        "deeptutor.services.llm.client.get_llm_client",
        lambda: (_ for _ in ()).throw(RuntimeError("no provider")),
    )
    tool = configure([_row()], {"image-05.png": image}, None)

    result = asyncio.run(tool.execute(name="image-05.png"))

    assert result.success is True
    assert "page 2" in result.content
    assert "could not be read" in result.content
    assert "A chart with two axes." in result.content
    assert result.sources[0]["page"] == 2


def test_empty_vision_answer_reports_the_recorded_caption(configure, tmp_path):
    image = tmp_path / "image-05.png"
    image.write_bytes(b"pixels")

    result = asyncio.run(
        configure(
            [_row(caption="")], {"image-05.png": image}, _RecordingVision(answer="   ")
        ).execute(name="image-05.png")
    )

    assert result.success is False
    assert "returned nothing" in result.content
    assert "(none)" in result.content


@pytest.mark.parametrize("question", [None, "   "])
def test_blank_question_falls_back_to_the_default_description_prompt(configure, tmp_path, question):
    image = tmp_path / "image-05.png"
    image.write_bytes(b"pixels")
    client = _RecordingVision()

    kwargs = {"name": "image-05.png"}
    if question is not None:
        kwargs["question"] = question
    result = asyncio.run(configure([_row()], {"image-05.png": image}, client).execute(**kwargs))

    assert result.success is True
    assert client.calls[0][0] == _DEFAULT_FIGURE_QUESTION
    assert result.content == "page 2 (image-05.png): The vertical axis is probability."


@pytest.mark.parametrize(
    ("filename", "expected_mime"),
    [("image-07.jpeg", "image/jpeg"), ("figure.blob", "application/octet-stream")],
)
def test_mime_falls_back_to_the_filename_guess_when_the_row_has_none(
    configure, tmp_path, filename, expected_mime
):
    image = tmp_path / filename
    image.write_bytes(b"pixels")
    client = _RecordingVision()

    result = asyncio.run(
        configure([_row(name=filename, mime="")], {filename: image}, client).execute(name=filename)
    )

    assert result.success is True
    assert client.calls[0][1]["image_mime_type"] == expected_mime


def test_execute_without_an_open_material_reports_a_readable_failure():
    result = asyncio.run(ViewFigureTool().execute(name="image-05.png"))

    assert result.success is False
    assert "No reading material is open" in result.content
