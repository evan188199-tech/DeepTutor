"""Transient source-image delivery through the active agent loop (#1611)."""

from __future__ import annotations

from deeptutor.runtime.agentic.messages import (
    extend_transient_model_messages,
    with_transient_model_messages,
)


def _image_message(anchor: str, token: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"Source evidence {token}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{token}"}},
        ],
        "_after_tool_call_id": anchor,
    }


def test_transient_images_require_a_valid_tool_anchor():
    messages = [
        {"role": "user", "content": "Show the figure"},
        {"role": "tool", "tool_call_id": "rag", "content": "found"},
    ]
    unanchored = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}],
        },
        {"role": "user", "content": [], "_after_tool_call_id": ""},
        {"role": "user", "content": [], "_after_tool_call_id": 7},
    ]
    request = with_transient_model_messages(messages, unanchored)
    assert request == messages
    assert messages[1]["role"] == "tool"


def test_anchor_without_tool_reply_is_never_injected():
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "rag"}]},
        {"role": "tool", "tool_call_id": "rag", "content": "found"},
    ]
    request = with_transient_model_messages(messages, [_image_message("missing-anchor", "aa")])
    assert request == messages
    assert all("content" not in message or message["role"] != "user" for message in request[1:])


def test_batch_transients_keep_order_after_the_last_tool_reply():
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "one"}, {"id": "two"}]},
        {"role": "tool", "tool_call_id": "one", "content": "first"},
        {"role": "tool", "tool_call_id": "two", "content": "second"},
        {"role": "assistant", "content": "answer"},
    ]
    transient = [
        _image_message("two", "aa"),
        _image_message("two", "bb"),
        _image_message("unrelated", "cc"),
    ]
    request = with_transient_model_messages(messages, transient)
    assert [item["role"] for item in request] == [
        "assistant",
        "tool",
        "tool",
        "user",
        "user",
        "assistant",
    ]
    assert request[3]["content"] == transient[0]["content"]
    assert request[4]["content"] == transient[1]["content"]
    assert [item["role"] for item in messages] == ["assistant", "tool", "tool", "assistant"]


def test_extend_transient_evicts_oldest_images_across_rounds():
    transient: list[dict] = []
    extend_transient_model_messages(
        transient, [_image_message("one", "aa"), _image_message("one", "ab")]
    )
    extend_transient_model_messages(
        transient, [_image_message("two", "ba"), _image_message("two", "bb")]
    )
    assert [item["content"][-1]["image_url"]["url"] for item in transient] == [
        "data:image/png;base64,ba",
        "data:image/png;base64,bb",
    ]
    text_only = {"role": "user", "content": [{"type": "text", "text": "no pixels here"}]}
    extend_transient_model_messages(
        transient, [text_only, _image_message("three", "ca")], max_images=2
    )
    assert [item.get("_after_tool_call_id") for item in transient] == ["two", None, "three"]
    assert transient[0]["content"] == _image_message("two", "bb")["content"]
    assert transient[1] is text_only
    assert transient[2]["content"] == _image_message("three", "ca")["content"]
