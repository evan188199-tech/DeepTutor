"""Contract tests for deeptutor.services.llm.request_cache.

Covers cache-key construction stability (canonical JSON + sha256),
hit/miss branches of compare_requests, degradation on corrupted stored
fingerprints, and a fake-storage round trip (plain dict storage, no
network access).
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.request_cache import (
    _digest,
    _encoded,
    compare_requests,
    fingerprint_request,
)


def _messages(*contents: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": content} for content in contents]


def _header_of(current: dict[str, Any]) -> dict[str, Any]:
    return {"route": current["route"], "tools": current["tools"]}


def test_encoded_key_material_is_canonical_and_order_independent():
    assert _encoded({"b": 2, "a": 1}) == _encoded({"a": 1, "b": 2})
    assert _encoded({"a": 1, "b": 2}) == '{"a":1,"b":2}'
    assert _encoded({"outer": {"z": [1, {"y": 2, "x": 3}]}}) == _encoded(
        {"outer": {"z": [1, {"x": 3, "y": 2}]}}
    )
    assert _encoded({"k": "中文"}) == '{"k":"中文"}'


def test_digest_is_deterministic_and_content_sensitive():
    value = {"route": {"model": "m"}, "n": [1, 2, 3]}
    reordered = {"n": [1, 2, 3], "route": {"model": "m"}}
    digest = _digest(value)
    assert _digest(value) == digest
    assert _digest(reordered) == digest
    assert _digest(value) != _digest({"route": {"model": "m"}, "n": [1, 2]})
    assert len(digest) == 64
    int(digest, 16)


def test_unserializable_key_material_raises_instead_of_silently_hashing():
    with pytest.raises(TypeError):
        _encoded({"k": b"bytes"})
    with pytest.raises(TypeError):
        fingerprint_request([{"role": "user", "content": b"raw"}], [], {})


def test_fingerprint_key_stable_across_calls_tool_none_and_key_order():
    messages = _messages("q")
    route_a = {"model": "m", "temperature": 0}
    route_b = {"temperature": 0, "model": "m"}
    tools_a = [{"type": "function", "function": {"name": "t", "parameters": {"b": 1, "a": 2}}}]
    tools_b = [{"function": {"parameters": {"a": 2, "b": 1}, "name": "t"}, "type": "function"}]

    assert fingerprint_request(messages, tools_a, route_a) == fingerprint_request(
        messages, tools_b, route_b
    )
    assert fingerprint_request(messages, None, route_a) == fingerprint_request(
        messages, [], route_a
    )


def test_fingerprint_hash_tracks_content_with_equal_token_estimates(monkeypatch):
    from deeptutor.services.session import context_builder

    monkeypatch.setattr(context_builder, "count_tokens", lambda _text: 5)
    route = {"model": "m"}
    first = fingerprint_request(_messages("alpha"), [], route)
    second = fingerprint_request(_messages("beta"), [], route)
    third = fingerprint_request(_messages("alpha"), [], route)
    assert first["messages"][0]["hash"] != second["messages"][0]["hash"]
    assert first["messages"][0]["tokens"] == second["messages"][0]["tokens"] == 5
    assert first == third


def test_compare_requests_first_observation_and_route_tools_misses():
    current = fingerprint_request(_messages("q"), [], {"model": "m"})
    stored = fingerprint_request(_messages("q"), [], {"model": "m"})

    miss = compare_requests(None, current)
    assert miss == {"first_change": "first_observed_request", "shared_prefix_messages": 0}

    assert compare_requests("corrupted-entry", current) == {
        "first_change": "first_observed_request",
        "shared_prefix_messages": 0,
    }
    assert compare_requests(7, current)["first_change"] == "first_observed_request"

    assert (
        compare_requests(stored, fingerprint_request(_messages("q"), [], {"model": "other"}))[
            "first_change"
        ]
        == "route"
    )
    assert (
        compare_requests(stored, fingerprint_request(_messages("q"), [{"name": "t"}], {"model": "m"}))[
            "first_change"
        ]
        == "tools"
    )
    both = fingerprint_request(_messages("q"), [{"name": "t"}], {"model": "other"})
    assert compare_requests(stored, both)["first_change"] == "route"


def test_compare_requests_degrades_on_corrupted_stored_fingerprint():
    current = fingerprint_request(_messages("q"), [], {"model": "m"})
    header = _header_of(current)

    assert compare_requests({"tools": current["tools"]}, current)["first_change"] == "route"
    for corrupted in (
        {**header, "messages": "not-a-list"},
        {**header, "messages": 12},
        {**header, "messages": ["entry", 7]},
    ):
        result = compare_requests(corrupted, current)
        assert result["first_change"] == "first_observed_request"
        assert result["shared_prefix_messages"] == 0


def test_compare_requests_empty_or_missing_history_reports_zero_prefix():
    current = fingerprint_request(_messages("q"), [], {"model": "m"})
    header = _header_of(current)

    for stored in (header, {**header, "messages": []}, {**header, "messages": None}):
        result = compare_requests(stored, current)
        assert result["first_change"] == "append"
        assert result["shared_prefix_messages"] == 0
        assert result["previous_request_messages"] == 0


def test_compare_requests_hit_and_append_via_fake_storage(monkeypatch):
    from deeptutor.services.session import context_builder

    monkeypatch.setattr(context_builder, "count_tokens", lambda _text: 5)
    storage: dict[str, Any] = {}
    route = {"model": "m"}
    messages = _messages("a", "b", "c")

    storage["turn"] = fingerprint_request(messages, [], route)
    replay = storage["turn"]

    hit = compare_requests(replay, fingerprint_request(messages, [], route))
    assert hit["first_change"] == "append"
    assert hit["shared_prefix_messages"] == 3
    assert hit["shared_prefix_tokens_estimate"] == 15
    assert hit["previous_request_messages"] == 3

    grown = fingerprint_request([*messages, {"role": "assistant", "content": "d"}], [], route)
    grown_hit = compare_requests(replay, grown)
    assert grown_hit["first_change"] == "append"
    assert grown_hit["shared_prefix_messages"] == 3
    assert grown_hit["shared_prefix_tokens_estimate"] == 15


def test_compare_requests_partial_prefix_and_system_change_branches():
    route = {"model": "m"}
    base = fingerprint_request(
        [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}], [], route
    )
    new_system = fingerprint_request(
        [{"role": "system", "content": "new rules"}, {"role": "user", "content": "q"}], [], route
    )
    system_change = compare_requests(base, new_system)
    assert system_change["first_change"] == "system"
    assert system_change["shared_prefix_messages"] == 0

    three = fingerprint_request(
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ],
        [],
        route,
    )
    two = fingerprint_request(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}], [], route
    )
    shrunk = compare_requests(three, two)
    assert shrunk["first_change"] == "history"
    assert shrunk["shared_prefix_messages"] == 2
    assert shrunk["previous_request_messages"] == 3

    first_swap = fingerprint_request(
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "changed"},
            {"role": "user", "content": "b"},
        ],
        [],
        route,
    )
    swapped = compare_requests(three, first_swap)
    assert swapped["first_change"] == "history"
    assert swapped["shared_prefix_messages"] == 1
    assert swapped["previous_request_messages"] == 3

    empty = compare_requests(three, fingerprint_request([], [], route))
    assert empty["first_change"] == "history"
    assert empty["shared_prefix_messages"] == 0


def test_fake_storage_round_trip_eviction_degrades_to_first_observation(monkeypatch):
    from deeptutor.services.session import context_builder

    monkeypatch.setattr(context_builder, "count_tokens", lambda _text: 2)
    storage: dict[str, Any] = {}
    route = {"model": "m"}

    storage["session"] = fingerprint_request(_messages("q1"), [], route)
    second = fingerprint_request([*_messages("q1"), {"role": "assistant", "content": "a1"}], [], route)
    assert compare_requests(storage["session"], second)["first_change"] == "append"

    storage.pop("session")
    evicted = compare_requests(storage.get("session"), second)
    assert evicted["first_change"] == "first_observed_request"
    assert evicted["shared_prefix_messages"] == 0
