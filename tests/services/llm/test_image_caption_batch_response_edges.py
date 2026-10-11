"""Response-shape edges for batch decoding and single-image degrade paths.

Complements ``test_image_caption_batch.py``: fenced JSON payloads, non-mapping
caption rows, and provider errors that surface only when the split tree has
already bottomed out at one image.
"""

import json

import pytest

from deeptutor.services.llm.exceptions import ProviderContextWindowError
from deeptutor.services.llm.image_caption_batch import ImageCaptionBatcher, _decode


def images(count):
    return [
        {"base64": f"data{i}", "mimetype": "image/png", "filename": f"{i}.png"}
        for i in range(count)
    ]


class ScriptedClient:
    """Fake provider: group calls and single-image calls drain separate queues."""

    def __init__(self, batch_responses=(), single_responses=()):
        self.batch_responses = list(batch_responses)
        self.single_responses = list(single_responses)
        self.batch_calls = 0
        self.single_calls = 0

    async def complete(self, prompt, **kwargs):
        if "image_data" in kwargs:
            self.single_calls += 1
            item = self.single_responses.pop(0)
        else:
            self.batch_calls += 1
            item = self.batch_responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def batcher(client):
    return ImageCaptionBatcher(client, prompt="Describe each figure", system_prompt="Be factual")


@pytest.mark.asyncio
async def test_fenced_json_batch_response_is_unwrapped():
    payload = json.dumps(
        {"captions": [{"image_id": f"IMAGE_{i}", "caption": f"c{i}"} for i in range(3)]}
    )
    client = ScriptedClient([f"```json\n{payload}\n```"])
    assert await batcher(client).describe(images(3)) == ["c0", "c1", "c2"]
    assert client.batch_calls == 1
    assert client.single_calls == 0


def test_decode_rejects_non_mapping_caption_rows():
    with pytest.raises(ValueError):
        _decode(json.dumps({"captions": ["not a mapping"]}), ["IMAGE_0"])


@pytest.mark.asyncio
async def test_non_mapping_caption_row_degrades_to_single_image_answers():
    bad_batch = json.dumps({"captions": [{"image_id": "IMAGE_0", "caption": "x"}, ["row"]]})
    client = ScriptedClient([bad_batch], ["solo 0", "solo 1"])
    job = batcher(client)
    assert await job.describe(images(2)) == ["solo 0", "solo 1"]
    assert not job.halted
    assert client.batch_calls == 1
    assert client.single_calls == 2


@pytest.mark.asyncio
async def test_single_image_overflow_yields_none_while_sibling_answers():
    client = ScriptedClient(
        [ProviderContextWindowError("too large")],
        ["solo 0", ProviderContextWindowError("too large")],
    )
    job = batcher(client)
    assert await job.describe(images(2)) == ["solo 0", None]
    assert not job.halted
    assert client.batch_calls == 1
    assert client.single_calls == 2


@pytest.mark.asyncio
async def test_empty_request_short_circuits_without_provider_calls():
    client = ScriptedClient()
    assert await batcher(client).describe([]) == []
    assert client.batch_calls == 0
    assert client.single_calls == 0
