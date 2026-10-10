"""Usage accumulation, aggregation, and pricing-tolerance tests for research token tracking.

Complements test_token_tracker_pricing.py (pricing table only) by covering
TokenTracker accounting invariants: record-level totals, cross-stage/cross-agent
bucket consistency, malformed/missing price entry behavior, and persistence.
"""

import json

import pytest

from deeptutor.agents.research.utils import token_tracker as tt
from deeptutor.agents.research.utils.token_tracker import (
    MODEL_PRICING,
    TokenTracker,
    TokenUsage,
    calculate_cost,
    count_tokens_with_litellm,
    count_tokens_with_tiktoken,
    get_model_pricing,
    get_token_tracker,
)


def _add(tracker: TokenTracker, agent: str, stage: str, model: str, prompt: int, completion: int) -> None:
    tracker.add_usage(
        agent_name=agent,
        stage=stage,
        model=model,
        token_counts={"prompt_tokens": prompt, "completion_tokens": completion},
    )


def test_add_usage_accumulates_totals_across_records() -> None:
    tracker = TokenTracker()
    _add(tracker, "planner", "plan", "gpt-4o", 1000, 500)
    _add(tracker, "planner", "plan", "gpt-4o", 2000, 500)
    _add(tracker, "writer", "write", "deepseek-v4-pro", 10000, 2000)

    assert len(tracker.usage_records) == 3
    assert tracker.total_prompt_tokens == 13000
    assert tracker.total_completion_tokens == 3000
    assert tracker.total_tokens == 16000
    for record in tracker.usage_records:
        assert record.total_tokens == record.prompt_tokens + record.completion_tokens
    expected_cost = sum(calculate_cost(r.model, r.prompt_tokens, r.completion_tokens) for r in tracker.usage_records)
    assert tracker.total_cost_usd == pytest.approx(expected_cost)


def test_add_usage_per_record_cost_matches_pricing_table() -> None:
    tracker = TokenTracker()
    _add(tracker, "planner", "plan", "gpt-4o", 1000, 1000)
    _add(tracker, "writer", "write", "gpt-4o-mini", 1000, 1000)

    gpt4o, mini = tracker.usage_records
    assert gpt4o.cost_usd == pytest.approx(MODEL_PRICING["gpt-4o"]["input"] + MODEL_PRICING["gpt-4o"]["output"])
    assert mini.cost_usd == pytest.approx(
        MODEL_PRICING["gpt-4o-mini"]["input"] + MODEL_PRICING["gpt-4o-mini"]["output"]
    )
    assert tracker.total_cost_usd == pytest.approx(gpt4o.cost_usd + mini.cost_usd)


def test_get_summary_buckets_match_records() -> None:
    tracker = TokenTracker()
    _add(tracker, "planner", "plan", "gpt-4o", 1000, 100)
    _add(tracker, "planner", "plan", "deepseek-chat", 500, 50)
    _add(tracker, "writer", "write", "gpt-4o", 3000, 900)

    summary = tracker.get_summary()

    assert summary["total_calls"] == 3 == len(tracker.usage_records)
    assert summary["total_tokens"] == tracker.total_tokens == 5550

    assert set(summary["by_agent"]) == {"planner", "writer"}
    planner = summary["by_agent"]["planner"]
    assert planner["calls"] == 2
    assert planner["prompt_tokens"] == 1500
    assert planner["completion_tokens"] == 150
    assert planner["total_tokens"] == 1650

    assert set(summary["by_model"]) == {"gpt-4o", "deepseek-chat"}
    assert summary["by_model"]["gpt-4o"]["calls"] == 2
    assert summary["by_model"]["gpt-4o"]["total_tokens"] == 5000
    assert summary["by_model"]["deepseek-chat"]["total_tokens"] == 550

    assert set(summary["by_method"]) == {"api"}
    assert summary["by_method"]["api"]["calls"] == 3


def test_cross_stage_accounting_consistency() -> None:
    tracker = TokenTracker()
    stages = [
        ("planner", "plan", "gpt-4o", 1200, 300),
        ("searcher", "search", "deepseek-chat", 4000, 800),
        ("writer", "write", "gpt-4o-mini", 9000, 2500),
        ("writer", "revise", "deepseek-v4-flash", 1500, 450),
    ]
    for agent, stage, model, prompt, completion in stages:
        _add(tracker, agent, stage, model, prompt, completion)

    summary = tracker.get_summary()
    records = tracker.usage_records

    for bucket_name in ("by_agent", "by_model", "by_method"):
        bucket_totals = sum(bucket["total_tokens"] for bucket in summary[bucket_name].values())
        bucket_costs = sum(bucket["cost_usd"] for bucket in summary[bucket_name].values())
        assert bucket_totals == summary["total_tokens"] == tracker.total_tokens
        assert bucket_costs == pytest.approx(summary["total_cost_usd"])

    for stage in ("plan", "search", "write", "revise"):
        stage_records = [r for r in records if r.stage == stage]
        assert len(stage_records) == 1
        stage_tokens = sum(r.total_tokens for r in stage_records)
        stage_cost = sum(r.cost_usd for r in stage_records)
        assert stage_tokens > 0
        assert stage_cost == pytest.approx(sum(calculate_cost(r.model, r.prompt_tokens, r.completion_tokens) for r in stage_records))

    assert sum(r.total_tokens for r in records) == summary["total_tokens"]
    assert sum(r.cost_usd for r in records) == pytest.approx(summary["total_cost_usd"])


def test_get_model_pricing_unknown_model_falls_back_to_default() -> None:
    fallback = MODEL_PRICING["gpt-4o-mini"]
    for unknown in ("totally-unknown-model", "vendor-x/custom-v2", "gpt-9"):
        assert get_model_pricing(unknown) == fallback


def test_get_model_pricing_fuzzy_and_case_insensitive_matching() -> None:
    assert get_model_pricing("GPT-4O") == MODEL_PRICING["gpt-4o"]
    assert get_model_pricing("DeepSeek-Chat") == MODEL_PRICING["deepseek-chat"]
    assert get_model_pricing("deepseek-v4-pro-2026-01-15") == MODEL_PRICING["deepseek-v4-pro"]
    assert get_model_pricing("prefix-gpt-4-turbo-suffix") == MODEL_PRICING["gpt-4-turbo"]


@pytest.mark.parametrize("bad_name", ["", "   ", "!!!", "??/", "\n\t"])
def test_get_model_pricing_returns_valid_dict_for_malformed_names(bad_name: str) -> None:
    pricing = get_model_pricing(bad_name)
    assert isinstance(pricing, dict)
    assert set(pricing) == {"input", "output"}
    assert all(isinstance(v, float) for v in pricing.values())


def test_calculate_cost_known_models_exact_math() -> None:
    assert calculate_cost("gpt-4o", 1000, 1000) == pytest.approx(0.0025 + 0.010)
    assert calculate_cost("gpt-4o-mini", 2000, 0) == pytest.approx(2 * 0.00015)
    assert calculate_cost("deepseek-v4-pro", 0, 3000) == pytest.approx(3 * 0.00087)
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_calculate_cost_price_entry_missing_output_key_raises_keyerror() -> None:
    monkeypatched = {"broken-model": {"input": 0.01}}
    original = dict(MODEL_PRICING)
    try:
        tt.MODEL_PRICING.clear()
        tt.MODEL_PRICING.update(monkeypatched)
        with pytest.raises(KeyError):
            calculate_cost("broken-model", 1000, 1000)
    finally:
        tt.MODEL_PRICING.clear()
        tt.MODEL_PRICING.update(original)


def test_calculate_cost_price_entry_non_numeric_values_raise_typeerror() -> None:
    original = dict(MODEL_PRICING)
    try:
        tt.MODEL_PRICING.clear()
        tt.MODEL_PRICING.update({"stringy-model": {"input": "0.01", "output": "0.02"}})
        with pytest.raises(TypeError):
            calculate_cost("stringy-model", 1000, 1000)
    finally:
        tt.MODEL_PRICING.clear()
        tt.MODEL_PRICING.update(original)


def test_add_usage_estimated_method_uses_word_count_heuristic() -> None:
    tracker = TokenTracker(prefer_tiktoken=False, prefer_litellm=False)
    tracker.add_usage(
        agent_name="estimator",
        stage="plan",
        model="gpt-4o",
        system_prompt=None,
        user_prompt="one two three four five six seven eight nine ten",
        response_text="alpha beta gamma",
    )

    assert len(tracker.usage_records) == 1
    record = tracker.usage_records[0]
    assert record.calculation_method == "estimated"
    assert record.prompt_tokens == int(10 * 1.3)
    assert record.completion_tokens == int(3 * 1.3)
    assert record.total_tokens == record.prompt_tokens + record.completion_tokens
    assert tracker.total_tokens == record.total_tokens
    assert tracker.total_cost_usd == pytest.approx(record.cost_usd)


def test_add_usage_empty_token_counts_dict_uses_estimated_fallback() -> None:
    tracker = TokenTracker(prefer_tiktoken=False)
    tracker.add_usage(
        agent_name="caller",
        stage="plan",
        model="gpt-4o",
        token_counts={},
    )

    record = tracker.usage_records[0]
    assert record.calculation_method == "estimated"
    assert record.prompt_tokens == 0
    assert record.completion_tokens == 0
    assert record.total_tokens == 0
    assert record.cost_usd == 0.0
    assert tracker.total_tokens == 0


def test_add_usage_partial_token_counts_merge_with_positional_args() -> None:
    tracker = TokenTracker()
    tracker.add_usage(
        agent_name="caller",
        stage="plan",
        model="gpt-4o",
        prompt_tokens=7,
        completion_tokens=8,
        token_counts={"prompt_tokens": 100},
    )

    record = tracker.usage_records[0]
    assert record.prompt_tokens == 100
    assert record.completion_tokens == 8
    assert record.total_tokens == 108
    assert tracker.total_prompt_tokens == 100
    assert tracker.total_completion_tokens == 8


def test_reset_clears_records_and_totals() -> None:
    tracker = TokenTracker()
    _add(tracker, "planner", "plan", "gpt-4o", 1000, 200)
    tracker.reset()

    assert tracker.usage_records == []
    assert tracker.total_prompt_tokens == 0
    assert tracker.total_completion_tokens == 0
    assert tracker.total_tokens == 0
    assert tracker.total_cost_usd == 0.0
    summary = tracker.get_summary()
    assert summary["total_calls"] == 0
    assert summary["by_agent"] == {}
    assert summary["by_model"] == {}
    assert summary["by_method"] == {}


def test_save_persists_records_and_summary_consistently(tmp_path) -> None:
    tracker = TokenTracker()
    _add(tracker, "planner", "plan", "gpt-4o", 1200, 300)
    _add(tracker, "writer", "write", "deepseek-chat", 4000, 800)

    target = tmp_path / "token_usage.json"
    tracker.save(str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert len(payload["records"]) == 2
    assert payload["summary"]["total_calls"] == 2
    assert payload["summary"]["total_tokens"] == sum(r["total_tokens"] for r in payload["records"])
    assert payload["summary"]["total_cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in payload["records"]))
    saved = [TokenUsage(**r) for r in payload["records"]]
    assert [(r.agent_name, r.stage, r.model) for r in saved] == [
        ("planner", "plan", "gpt-4o"),
        ("writer", "write", "deepseek-chat"),
    ]
    for original, restored in zip(tracker.usage_records, saved):
        assert restored.total_tokens == original.total_tokens
        assert restored.cost_usd == pytest.approx(original.cost_usd)


def test_format_summary_reports_totals_sorted_agents_and_models() -> None:
    tracker = TokenTracker()
    _add(tracker, "writer", "write", "gpt-4o-mini", 900, 100)
    _add(tracker, "planner", "plan", "gpt-4o", 1100, 400)

    text = tracker.format_summary()

    assert "Total API Calls: 2" in text
    assert f"Total Tokens: {tracker.total_tokens:,}" in text
    assert f"  - Input: {tracker.total_prompt_tokens:,}" in text
    assert f"  - Output: {tracker.total_completion_tokens:,}" in text
    assert "By Agent:" in text and "By Model:" in text
    assert "planner:" in text and "writer:" in text
    assert "gpt-4o:" in text and "gpt-4o-mini:" in text
    assert text.index("planner:") < text.index("writer:")
    assert text.index("gpt-4o:") < text.index("gpt-4o-mini:")
    assert text.rstrip().endswith("=" * 70)


def test_get_token_tracker_returns_stable_singleton() -> None:
    first = get_token_tracker()
    second = get_token_tracker()
    assert first is second
    assert isinstance(first, TokenTracker)


def test_count_token_helpers_tolerate_missing_backend_and_malformed_messages(monkeypatch) -> None:
    monkeypatch.setattr(tt, "TIKTOKEN_AVAILABLE", False)
    monkeypatch.setattr(tt, "tiktoken", None)

    assert count_tokens_with_tiktoken("any text", "gpt-4o") == 0
    assert count_tokens_with_litellm(
        [{"content": "hello"}], "gpt-4o"
    ) == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    monkeypatch.setattr(tt, "TIKTOKEN_AVAILABLE", True)
    assert count_tokens_with_litellm(["not-a-dict"], "gpt-4o") == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert count_tokens_with_litellm([], "gpt-4o")["total_tokens"] == 0
