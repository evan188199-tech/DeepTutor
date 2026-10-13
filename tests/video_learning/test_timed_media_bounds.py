"""Behavioral contract for timed media material size bounds (F1).

Covers the storage upper bounds documented for video-learning materials:
transcript cue count/byte budgets in ``service.normalize_cues``, the caption
payload rejection path, per-material mark caps, per-field quote/note clipping,
metadata field-count and serialized-size limits, and a full disk round-trip of
a truncated material file.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from deeptutor.video_learning import service
from deeptutor.video_learning.marks import (
    MAX_MARKS_PER_MATERIAL,
    MAX_NOTE_CHARS,
    MAX_QUOTE_CHARS,
    create_mark,
    delete_mark,
)


def _material(store: service.TimedMediaStore, *, duration: float = 120) -> dict:
    material = {
        "version": 1,
        "type": "timed_media",
        "material_id": service.material_id_for("dQw4w9WgXcQ"),
        "created_at": "2026-01-01T00:00:00+00:00",
        "_caption_text_version": 1,
        "source": {
            "provider": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://youtu.be/dQw4w9WgXcQ",
        },
        "metadata": {"title": "Demo", "duration_seconds": duration},
        "transcript": {
            "status": "ready",
            "cues": [{"start": 10, "end": 18, "text": "Gradient descent finds a minimum."}],
        },
        "segments": [
            {"locator": 1, "start": 10, "end": 18, "text": "Gradient descent finds a minimum."}
        ],
        "learning": {"last_position": 0},
    }
    return store.save(material)


def test_normalize_cues_caps_at_max_cue_count() -> None:
    assert service.MAX_TRANSCRIPT_CUES == 20_000
    rows = [
        {"start": float(i), "duration": 1.0, "text": f"cue {i}"}
        for i in range(service.MAX_TRANSCRIPT_CUES + 50)
    ]
    cues = service.normalize_cues(rows)
    assert len(cues) == service.MAX_TRANSCRIPT_CUES
    assert cues[0]["text"] == "cue 0"
    assert cues[-1]["text"] == f"cue {service.MAX_TRANSCRIPT_CUES - 1}"


def test_normalize_cues_caps_total_bytes_at_two_megabytes() -> None:
    assert service.MAX_TRANSCRIPT_BYTES == 2 * 1024 * 1024
    chunk = "x" * 512
    rows = [
        {"start": float(i), "duration": 1.0, "text": chunk}
        for i in range(3 * service.MAX_TRANSCRIPT_BYTES // (2 * len(chunk.encode())))
    ]
    cues = service.normalize_cues(rows)
    used = sum(len(cue["text"].encode("utf-8")) for cue in cues)
    assert len(cues) == service.MAX_TRANSCRIPT_BYTES // 512
    assert used == service.MAX_TRANSCRIPT_BYTES
    assert len(cues) < len(rows)
    assert all(cue["text"] == chunk for cue in cues)


def test_normalize_cues_byte_budget_counts_utf8_bytes() -> None:
    # 699050 CJK chars encode to 2097150 UTF-8 bytes: fits, but a further
    # 3-byte cue would exceed the budget, proving byte-based accumulation.
    cjk = "字" * (service.MAX_TRANSCRIPT_BYTES // 3)
    cues = service.normalize_cues(
        [
            {"start": 0.0, "duration": 1.0, "text": cjk},
            {"start": 1.0, "duration": 1.0, "text": "字"},
        ]
    )
    assert len(cues) == 1
    assert len(cues[0]["text"].encode("utf-8")) == service.MAX_TRANSCRIPT_BYTES // 3 * 3


@pytest.mark.asyncio
async def test_oversized_caption_payload_is_rejected() -> None:
    payload = b"x" * (service.MAX_TRANSCRIPT_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    captions = [
        {"label": "English", "languageCode": "en", "url": "https://captions.example.test/en.vtt"}
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(service.TimedMediaError, match="safety limit"):
            await service._invidious_transcript(
                client,
                "https://invidious.example.test",
                "abc12345678",
                captions,
                "en",
                raise_on_failure=True,
            )
        cues, language, status = await service._invidious_transcript(
            client, "https://invidious.example.test", "abc12345678", captions, "en"
        )
    assert cues == []
    assert language == "en"
    assert status == "unavailable"


def test_mark_quote_is_clipped_to_max_chars(tmp_path: Path) -> None:
    assert MAX_QUOTE_CHARS == 4000
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    mark = create_mark(
        material,
        {
            "kind": "key_point",
            "start_seconds": 10,
            "end_seconds": 18,
            "quote": "q" * (MAX_QUOTE_CHARS + 1234),
        },
    )
    assert mark["quote"] == "q" * MAX_QUOTE_CHARS
    store.save(material)
    reread = service.TimedMediaStore(root=store.root).get(material["material_id"])
    assert reread["learning"]["marks"][0]["quote"] == mark["quote"]


def test_mark_note_is_clipped_to_max_chars(tmp_path: Path) -> None:
    assert MAX_NOTE_CHARS == 2000
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    mark = create_mark(
        material,
        {
            "kind": "review",
            "start_seconds": 10,
            "end_seconds": 18,
            "note": "n" * (MAX_NOTE_CHARS + 5678),
        },
    )
    assert mark["note"] == "n" * MAX_NOTE_CHARS
    store.save(material)
    reread = service.TimedMediaStore(root=store.root).get(material["material_id"])
    assert reread["learning"]["marks"][0]["note"] == mark["note"]


def test_mark_metadata_rejects_more_than_sixteen_fields(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    fields = {f"field_{i:02d}": i for i in range(16)}
    mark = create_mark(
        material,
        {"kind": "key_point", "start_seconds": 10, "end_seconds": 18, "metadata": fields},
    )
    assert mark["metadata"] == fields
    with pytest.raises(service.TimedMediaError, match="too many fields"):
        create_mark(
            material,
            {
                "kind": "question",
                "start_seconds": 20,
                "end_seconds": 21,
                "metadata": dict(fields, field_16=1),
            },
        )


def test_mark_metadata_rejects_oversized_serialization(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    compact = {"summary": "s" * 3000}
    mark = create_mark(
        material,
        {"kind": "key_point", "start_seconds": 10, "end_seconds": 18, "metadata": compact},
    )
    assert mark["metadata"] == compact
    bloated = {"a": "x" * 2500, "b": "y" * 2500}
    assert len(json.dumps(bloated, ensure_ascii=False)) > 4000
    with pytest.raises(service.TimedMediaError, match="too large"):
        create_mark(
            material,
            {"kind": "question", "start_seconds": 20, "end_seconds": 21, "metadata": bloated},
        )


def test_marks_capped_at_five_hundred_per_material(tmp_path: Path) -> None:
    assert MAX_MARKS_PER_MATERIAL == 500
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    for i in range(MAX_MARKS_PER_MATERIAL):
        create_mark(
            material,
            {
                "kind": "key_point",
                "start_seconds": float(i) * 100,
                "end_seconds": float(i) * 100 + 1,
            },
        )
    with pytest.raises(service.TimedMediaError, match="maximum number of marks"):
        create_mark(
            material,
            {"kind": "key_point", "start_seconds": 60_000.0, "end_seconds": 60_001.0},
        )
    store.save(material)
    reread = service.TimedMediaStore(root=store.root).get(material["material_id"])
    assert len(reread["learning"]["marks"]) == MAX_MARKS_PER_MATERIAL
    delete_mark(reread, reread["learning"]["marks"][0]["mark_id"])
    create_mark(reread, {"kind": "question", "start_seconds": 70_000.0})
    assert len(reread["learning"]["marks"]) == MAX_MARKS_PER_MATERIAL


def test_truncated_material_roundtrips_from_disk(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store, duration=86_400)
    oversized_rows = [{"start": float(i), "duration": 1.0, "text": "x" * 512} for i in range(6000)]
    cues = service.normalize_cues(oversized_rows)
    material["transcript"]["cues"] = cues
    mark = create_mark(
        material,
        {
            "kind": "review",
            "start_seconds": 5,
            "end_seconds": 8,
            "quote": "q" * (MAX_QUOTE_CHARS * 2),
            "note": "n" * (MAX_NOTE_CHARS * 2),
        },
    )
    store.save(material)

    on_disk = json.loads(
        (store.root / f"{material['material_id']}.json").read_text(encoding="utf-8")
    )
    assert len(on_disk["transcript"]["cues"]) == len(cues)
    assert on_disk["learning"]["marks"][0]["quote"] == mark["quote"]
    assert on_disk["learning"]["marks"][0]["note"] == mark["note"]

    reread = service.TimedMediaStore(root=store.root).get(material["material_id"])
    assert reread["transcript"]["cues"] == cues
    assert reread["learning"]["marks"][0]["quote"] == mark["quote"]
    assert reread["learning"]["marks"][0]["note"] == mark["note"]
    assert len(reread["learning"]["marks"][0]["quote"]) == MAX_QUOTE_CHARS
    assert len(reread["learning"]["marks"][0]["note"]) == MAX_NOTE_CHARS
