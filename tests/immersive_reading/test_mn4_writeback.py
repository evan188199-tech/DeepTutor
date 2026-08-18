"""MarginNote 4 writeback persistence and state-machine tests."""

from __future__ import annotations

import pytest

from deeptutor.immersive_reading.models import (
    DictionaryResult,
    MN4WriteReceipt,
)
from deeptutor.immersive_reading.service import ImmersiveReadingService


@pytest.mark.asyncio
async def test_add_word_queues_idempotent_mn4_writeback(
    reading_service: ImmersiveReadingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def lookup(word: str, context: str) -> DictionaryResult:
        return DictionaryResult(word=word, chinese="clear")

    monkeypatch.setattr(reading_service, "lookup_word", lookup)

    first = await reading_service.add_word(
        "bright",
        context="The bright harbour slept.",
        document_id="mn4-source",
        document_title="MN4 Book",
        section_title="Chapter 1",
    )
    second = await reading_service.add_word(
        "bright",
        context="The bright harbour slept.",
        document_id="mn4-source",
        document_title="MN4 Book",
        section_title="Chapter 1",
    )

    assert first.id == second.id
    writebacks = reading_service.list_mn4_writebacks()
    assert len(writebacks) == 1
    assert writebacks[0].source_type == "word"
    assert writebacks[0].source_object_id == first.id
    assert writebacks[0].status == "pending_confirmation"
    assert writebacks[0].model == "test-model"


@pytest.mark.asyncio
async def test_non_mn4_word_does_not_create_writeback(
    reading_service: ImmersiveReadingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def lookup(word: str, context: str) -> DictionaryResult:
        return DictionaryResult(word=word)

    monkeypatch.setattr(reading_service, "lookup_word", lookup)
    await reading_service.add_word("bright", context="A sentence", document_id="ordinary")

    assert reading_service.list_mn4_writebacks() == []


def test_mn4_state_machine_and_receipt(reading_service: ImmersiveReadingService) -> None:
    item = reading_service.create_mn4_writeback(
        source_type="translation",
        source_object_id="source-1",
        content_hash="a" * 64,
        idempotency_key="translation:source-1:" + "a" * 64,
        model="test-model",
    )

    assert reading_service.update_mn4_writeback_status([item.id], "approved") == 1
    assert [pulled.id for pulled in reading_service.pull_mn4_writebacks()] == [item.id]
    assert reading_service.list_mn4_writebacks()[0].status == "applying"

    receipt = MN4WriteReceipt(
        writeback_id=item.id,
        remote_object_id="marginnote-object",
        content_hash=item.content_hash,
    )
    assert reading_service.submit_mn4_receipts([receipt]) == 1
    stored = reading_service.list_mn4_writebacks()[0]
    assert stored.status == "applied"
    assert stored.receipt == receipt


def test_mn4_receipt_hash_conflict_is_recorded(reading_service: ImmersiveReadingService) -> None:
    item = reading_service.create_mn4_writeback(
        source_type="translation",
        source_object_id="source-1",
        content_hash="a" * 64,
        idempotency_key="translation:source-1:" + "a" * 64,
    )
    reading_service.update_mn4_writeback_status([item.id], "approved")
    reading_service.pull_mn4_writebacks()
    receipt = MN4WriteReceipt(
        writeback_id=item.id,
        remote_object_id="remote",
        content_hash="b" * 64,
    )

    assert reading_service.submit_mn4_receipts([receipt]) == 1

    assert reading_service.list_mn4_writebacks()[0].status == "conflicted"


def test_mn4_illegal_transition_is_rejected(reading_service: ImmersiveReadingService) -> None:
    item = reading_service.create_mn4_writeback(
        source_type="word",
        source_object_id="word-1",
        content_hash="c" * 64,
        idempotency_key="word:word-1:" + "c" * 64,
    )

    with pytest.raises(ValueError, match="Invalid MarginNote 4 writeback status"):
        reading_service.update_mn4_writeback_status([item.id], "bogus")
