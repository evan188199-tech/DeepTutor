"""Focused tests for interrupted-turn usage accounting recovery.

Covers ``deeptutor.services.session.usage_recovery``: model attribution from
recorded turn evidence, repeat-recovery idempotency, tolerance of corrupted
records, and the recorded token-report lookup.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.services.session.usage_recovery import model_evidence, recover_summary


def llm_event(model="glm-test", provider="zhipu", **meta_extra):
    meta = {"model": model, "provider": provider, "call_kind": "llm"}
    meta.update(meta_extra)
    return {"type": "llm", "metadata": meta}


def output_dir_event(path):
    return {"type": "llm", "metadata": {"metadata": {"output_dir": str(path)}}}


@pytest.fixture
def user_root(tmp_path, monkeypatch):
    """Point the recovery path service at an isolated per-test directory."""
    root = tmp_path.resolve()
    fake = SimpleNamespace(get_user_root=lambda: root)
    monkeypatch.setattr("deeptutor.multi_user.paths.get_current_path_service", lambda: fake)
    return root


def write_report(directory, filename, payload):
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        (directory / filename).write_text(payload)
    else:
        (directory / filename).write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def test_evidence_reads_turn_route_and_llm_events():
    metadata = {"model_turn": {"route": {"provider": "zhipu", "model": "glm-air"}}}
    events = [llm_event(model="glm-test", provider="zhipu")]
    assert model_evidence(events, metadata) == {
        ("zhipu", "glm-air"),
        ("zhipu", "glm-test"),
    }


def test_evidence_ignores_tool_metadata_and_malformed_events():
    events = [
        {"type": "tool", "metadata": {"model": "search-model", "call_kind": "tool"}},
        {"type": "tool", "metadata": {"model": "search-model", "trace_kind": "tool"}},
        {"type": "tool", "metadata": "not-a-dict"},
        {"type": "tool", "metadata": None},
        {"metadata": {"model": "unmarked"}},
    ]
    assert model_evidence(events, {"model_turn": "broken"}) == set()


def test_evidence_accepts_llm_markers_via_trace_kind_and_event_name():
    events = [
        llm_event(model="m-a", call_kind=None, trace_kind="llm_call"),
        llm_event(model="m-b", call_kind=None, trace_kind=None, event="llm_call"),
    ]
    assert model_evidence(events) == {("zhipu", "m-a"), ("zhipu", "m-b")}


def test_evidence_reads_context_budget_scopes():
    events = [
        {
            "type": "llm",
            "metadata": {
                "metadata": {
                    "context_budget": {"model": "budget-model"},
                    "loop": {"metadata": {"context_budget": {"model": "loop-model"}}},
                }
            },
        }
    ]
    assert model_evidence(events) == {("", "budget-model"), ("", "loop-model")}


def test_evidence_tolerates_malformed_budget_payloads():
    events = [
        {"type": "llm", "metadata": {"metadata": {"context_budget": "broken"}}},
        {"type": "llm", "metadata": {"metadata": {"loop": "broken"}}},
        {"type": "llm", "metadata": {"metadata": {"loop": {"metadata": 7}}}},
        {"type": "llm", "metadata": {"metadata": 3}},
    ]
    assert model_evidence(events) == set()


# ---------------------------------------------------------------------------
# Already-recovered summaries and repeat-recovery idempotency
# ---------------------------------------------------------------------------


def test_summary_with_recorded_attribution_is_returned_unchanged():
    summary = {"total_tokens": 10, "call_details": [{"model": "glm-test"}]}
    evidence = [llm_event(model="other")]
    assert recover_summary(summary, evidence) == summary


def test_repeat_recovery_of_the_same_turn_is_idempotent():
    summary = {"total_tokens": 120, "prompt_tokens": 100, "completion_tokens": 20}
    evidence = [llm_event(model="glm-test", provider="zhipu")]

    first = recover_summary(dict(summary), evidence)
    second = recover_summary(dict(first), evidence)

    assert first == {
        **summary,
        "model": "glm-test",
        "provider": "zhipu",
    }
    assert second == first


def test_repeat_recovery_of_report_backed_turn_is_idempotent(user_root):
    report_dir = user_root / "turn-1"
    write_report(
        report_dir,
        "cost_report.json",
        {
            "total_tokens": 120,
            "by_model": {"glm-test": {"prompt_tokens": 100, "completion_tokens": 20}},
        },
    )
    events = [output_dir_event(report_dir)]
    bare = {"total_tokens": 120}

    first = recover_summary(dict(bare), events)
    second = recover_summary(dict(first), events)

    assert second == first
    assert second["by_model"] == {"glm-test": {"prompt_tokens": 100, "completion_tokens": 20}}


# ---------------------------------------------------------------------------
# Partial-stream evidence attribution
# ---------------------------------------------------------------------------


def test_single_model_evidence_is_applied_to_bare_summary():
    summary = {"total_tokens": 30}
    recovered = recover_summary(summary, [llm_event(model="glm-test", provider="zhipu")])
    assert recovered == {**summary, "model": "glm-test", "provider": "zhipu"}


def test_model_without_provider_keeps_empty_provider_string():
    summary = {"total_tokens": 30}
    recovered = recover_summary(summary, [llm_event(provider=None)])
    assert recovered["model"] == "glm-test"
    assert recovered["provider"] == ""


def test_ambiguous_model_evidence_leaves_summary_unchanged():
    summary = {"total_tokens": 30}
    evidence = [llm_event(model="glm-test"), llm_event(model="glm-air")]
    assert recover_summary(summary, evidence) == summary


def test_no_evidence_leaves_summary_unchanged():
    summary = {"total_tokens": 30}
    assert recover_summary(summary, []) == summary


# ---------------------------------------------------------------------------
# Corrupted and hostile records are tolerated
# ---------------------------------------------------------------------------


def test_corrupted_events_and_metadata_do_not_raise():
    summary = {"total_tokens": 30}
    evidence = [
        llm_event(model="glm-test", provider="zhipu"),
        {"metadata": {"metadata": {"context_budget": "broken"}}},
        {"metadata": {"metadata": "broken"}},
        {"metadata": "broken"},
        {"metadata": None},
    ]
    recovered = recover_summary(summary, evidence, {"model_turn": 7})
    assert recovered["model"] == "glm-test"
    assert recovered["provider"] == "zhipu"


def test_corrupted_report_files_are_tolerated(user_root):
    broken_json = user_root / "broken-json"
    write_report(broken_json, "cost_report.json", "{not json")
    wrong_shape = user_root / "wrong-shape"
    write_report(wrong_shape, "token_cost_summary.json", {"summary": [1, 2, 3]})
    missing_file = user_root / "missing-file"

    events = [
        output_dir_event(broken_json),
        output_dir_event(wrong_shape),
        output_dir_event(missing_file),
        llm_event(model="glm-test", provider="zhipu"),
    ]
    recovered = recover_summary({"total_tokens": 120}, events)

    assert recovered["model"] == "glm-test"
    assert "by_model" not in recovered


def test_non_dict_summary_tokens_do_not_raise(user_root):
    report_dir = user_root / "turn"
    write_report(
        report_dir,
        "cost_report.json",
        {"total_tokens": 120, "by_model": {"glm-test": {"prompt_tokens": 100}}},
    )
    events = [output_dir_event(report_dir), llm_event(model="glm-test")]

    recovered = recover_summary({"total_tokens": None}, events)

    assert recovered["model"] == "glm-test"


def test_report_total_mismatch_is_ignored(user_root):
    report_dir = user_root / "turn"
    write_report(
        report_dir,
        "cost_report.json",
        {"total_tokens": 999, "by_model": {"other-model": {}}},
    )
    events = [output_dir_event(report_dir), llm_event(model="glm-test")]

    recovered = recover_summary({"total_tokens": 120}, events)

    assert "by_model" not in recovered
    assert recovered["model"] == "glm-test"


def test_report_outside_user_root_is_ignored(user_root):
    outside = user_root.parent / "elsewhere" / "turn"
    write_report(
        outside,
        "cost_report.json",
        {"total_tokens": 120, "by_model": {"other-model": {}}},
    )
    events = [output_dir_event(outside), llm_event(model="glm-test")]

    recovered = recover_summary({"total_tokens": 120}, events)

    assert "by_model" not in recovered
    assert recovered["model"] == "glm-test"


# ---------------------------------------------------------------------------
# Recorded token-report recovery
# ---------------------------------------------------------------------------


def test_matching_report_merges_by_model(user_root):
    report_dir = user_root / "turn"
    write_report(
        report_dir,
        "cost_report.json",
        {
            "total_tokens": 120,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "by_model": {"glm-test": {"prompt_tokens": 100, "completion_tokens": 20}},
        },
    )
    events = [output_dir_event(report_dir)]
    bare = {"total_tokens": 120}

    recovered = recover_summary(bare, events)

    assert recovered["by_model"] == {"glm-test": {"prompt_tokens": 100, "completion_tokens": 20}}
    assert recovered["prompt_tokens"] == 100
    assert recovered["completion_tokens"] == 20


def test_token_cost_summary_used_when_cost_report_absent(user_root):
    report_dir = user_root / "turn"
    write_report(
        report_dir,
        "token_cost_summary.json",
        {
            "total_tokens": 120,
            "prompt_tokens": 90,
            "completion_tokens": 30,
            "by_model": {"glm-test": {"prompt_tokens": 90, "completion_tokens": 30}},
        },
    )
    recovered = recover_summary({"total_tokens": 120}, [output_dir_event(report_dir)])

    assert recovered["by_model"] == {"glm-test": {"prompt_tokens": 90, "completion_tokens": 30}}
    assert recovered["prompt_tokens"] == 90
    assert recovered["completion_tokens"] == 30


def test_report_without_top_level_tokens_sums_by_model(user_root):
    report_dir = user_root / "turn"
    write_report(
        report_dir,
        "cost_report.json",
        {
            "total_tokens": 150,
            "by_model": {
                "glm-test": {"prompt_tokens": 100, "completion_tokens": 20},
                "glm-air": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        },
    )
    recovered = recover_summary({"total_tokens": 150}, [output_dir_event(report_dir)])

    assert recovered["prompt_tokens"] == 120
    assert recovered["completion_tokens"] == 30


def test_empty_by_model_report_is_ignored(user_root):
    report_dir = user_root / "turn"
    write_report(report_dir, "cost_report.json", {"total_tokens": 120, "by_model": {}})
    events = [output_dir_event(report_dir), llm_event(model="glm-test")]

    recovered = recover_summary({"total_tokens": 120}, events)

    assert "by_model" not in recovered
    assert recovered["model"] == "glm-test"
