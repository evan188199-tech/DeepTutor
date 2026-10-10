from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deeptutor.logging.stats.llm_stats import (
    MODEL_PRICING,
    LLMStats,
    estimate_tokens,
    get_pricing,
)
from deeptutor.runtime.agentic.usage import UsageTracker


@pytest.mark.parametrize(
    ("model", "pricing_key"),
    [
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4", "gpt-4"),
        ("openai/gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),
    ],
)
def test_get_pricing_prefers_the_most_specific_model(model: str, pricing_key: str) -> None:
    assert get_pricing(model) == MODEL_PRICING[pricing_key]


def test_get_pricing_falls_back_for_an_unknown_model() -> None:
    assert get_pricing("unknown-model") == MODEL_PRICING["gpt-4o-mini"]


def test_usage_tracker_uses_gpt_4o_mini_pricing() -> None:
    tracker = UsageTracker(model="gpt-4o-mini")
    tracker.add_from_response(
        {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}
    )

    assert tracker.summary()["total_cost_usd"] == pytest.approx(0.00075)


def test_estimate_tokens_handles_empty_and_multiword_text() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("   \n\t ") == 0
    assert estimate_tokens("one two three four") == 5


def test_add_call_accumulates_totals_and_tracks_first_model() -> None:
    stats = LLMStats("Solver")
    stats.add_call(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
    stats.add_call(model="gpt-4o", prompt_tokens=100, completion_tokens=50)

    assert len(stats.calls) == 2
    assert stats.calls[0].model == "gpt-4o-mini"
    assert stats.calls[0].prompt_tokens == 1000
    assert stats.calls[0].completion_tokens == 500
    assert stats.total_prompt_tokens == 1100
    assert stats.total_completion_tokens == 550
    assert stats.model_used == "gpt-4o-mini"

    expected_cost = (
        (1000 / 1000.0) * MODEL_PRICING["gpt-4o-mini"]["input"]
        + (500 / 1000.0) * MODEL_PRICING["gpt-4o-mini"]["output"]
        + (100 / 1000.0) * MODEL_PRICING["gpt-4o"]["input"]
        + (50 / 1000.0) * MODEL_PRICING["gpt-4o"]["output"]
    )
    assert stats.total_cost == pytest.approx(expected_cost, rel=1e-12)


def test_add_call_estimates_tokens_from_prompt_and_response_text() -> None:
    stats = LLMStats("Estimator")
    stats.add_call(
        model="gpt-4o-mini",
        system_prompt="one two three",
        user_prompt="four five",
        response="six seven eight",
    )

    record = stats.calls[0]
    assert record.prompt_tokens == estimate_tokens("one two three\nfour five")
    assert record.completion_tokens == estimate_tokens("six seven eight")
    assert stats.total_prompt_tokens == record.prompt_tokens
    assert stats.total_completion_tokens == record.completion_tokens


def test_add_call_matches_model_pricing_case_insensitively() -> None:
    stats = LLMStats("CaseCheck")
    stats.add_call(model="GPT-4O-MINI", prompt_tokens=1000, completion_tokens=1000)

    expected = (1000 / 1000.0) * MODEL_PRICING["gpt-4o-mini"]["input"] + (
        1000 / 1000.0
    ) * MODEL_PRICING["gpt-4o-mini"]["output"]
    assert stats.calls[0].cost == pytest.approx(expected, rel=1e-12)
    assert stats.calls[0].cost == pytest.approx(0.00075, rel=1e-9)


def test_add_call_without_tokens_or_text_records_zero_cost_entry() -> None:
    stats = LLMStats("Empty")
    stats.add_call(model="mystery-model")

    record = stats.calls[0]
    assert record.prompt_tokens == 0
    assert record.completion_tokens == 0
    assert record.cost == 0.0
    assert stats.model_used == "mystery-model"

    summary = stats.get_summary()
    assert summary["total_tokens"] == 0
    assert summary["cost_usd"] == 0.0
    assert summary["calls"] == 1


def test_add_call_tolerates_malformed_token_values_and_keeps_aggregates_consistent() -> None:
    stats = LLMStats("Malformed")
    stats.add_call(model="gpt-4o-mini", prompt_tokens=-10, completion_tokens=-5)
    stats.add_call(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=50)

    assert len(stats.calls) == 2
    assert stats.total_prompt_tokens == 90
    assert stats.total_completion_tokens == 45
    assert stats.total_cost == sum(call.cost for call in stats.calls)

    summary = stats.get_summary()
    assert summary["calls"] == 2
    assert summary["total_tokens"] == 135


def test_add_call_stays_consistent_under_concurrent_writers() -> None:
    stats = LLMStats("Concurrent")
    thread_count, per_thread = 8, 50
    barrier = threading.Barrier(thread_count)

    def record() -> None:
        barrier.wait()
        for _ in range(per_thread):
            stats.add_call(model="gpt-4o-mini", prompt_tokens=10, completion_tokens=5)

    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        futures = [pool.submit(record) for _ in range(thread_count)]
        for future in futures:
            future.result(timeout=60)

    total_calls = thread_count * per_thread
    assert len(stats.calls) == total_calls
    assert stats.model_used == "gpt-4o-mini"
    assert stats.total_prompt_tokens == total_calls * 10
    assert stats.total_completion_tokens == total_calls * 5
    assert stats.total_cost == pytest.approx(sum(call.cost for call in stats.calls), rel=1e-9)


def test_get_summary_snapshots_state_with_unknown_model_default() -> None:
    stats = LLMStats("Snapshot")

    assert stats.get_summary() == {
        "module": "Snapshot",
        "model": "Unknown",
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }

    stats.add_call(model="gpt-4o", prompt_tokens=1000, completion_tokens=1000)
    summary = stats.get_summary()
    assert summary["module"] == "Snapshot"
    assert summary["model"] == "gpt-4o"
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 2000
    assert summary["cost_usd"] == pytest.approx(
        MODEL_PRICING["gpt-4o"]["input"] + MODEL_PRICING["gpt-4o"]["output"], rel=1e-12
    )


def test_log_summary_reports_recorded_usage_and_skips_empty_stats() -> None:
    empty = LLMStats("Silent")
    silent_logger = Mock(spec=logging.Logger)
    empty.log_summary(silent_logger)
    silent_logger.info.assert_not_called()

    stats = LLMStats("Reported")
    stats.add_call(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=1000)
    logger = Mock(spec=logging.Logger)
    stats.log_summary(logger)

    logged = " ".join(str(call.args[0]) for call in logger.info.call_args_list)
    assert "LLM Usage Summary for Reported" in logged
    assert "gpt-4o-mini" in logged
    assert "2,000" in logged
    assert "USD" in logged


def test_log_summary_uses_default_logger_named_for_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = LLMStats("Default")
    stats.add_call(model="gpt-4o-mini", prompt_tokens=1, completion_tokens=1)

    logger = Mock(spec=logging.Logger)
    seen_names: list[str] = []

    def fake_get_logger(name: object = None) -> logging.Logger:
        seen_names.append(str(name))
        return logger  # type: ignore[return-value]

    monkeypatch.setattr(
        "deeptutor.logging.stats.llm_stats.logging",
        SimpleNamespace(getLogger=fake_get_logger),
    )
    stats.log_summary()

    assert seen_names == ["deeptutor.stats.Default"]
    assert logger.info.called


def test_print_summary_delegates_to_log_summary() -> None:
    stats = LLMStats("Deprecated")
    stats.log_summary = Mock()  # type: ignore[method-assign]
    stats.print_summary()
    stats.log_summary.assert_called_once_with()


def test_reset_clears_calls_totals_and_model() -> None:
    stats = LLMStats("Reset")
    stats.add_call(model="gpt-4o", prompt_tokens=1000, completion_tokens=1000)

    stats.reset()

    assert stats.calls == []
    assert stats.total_prompt_tokens == 0
    assert stats.total_completion_tokens == 0
    assert stats.total_cost == 0.0
    assert stats.model_used is None
    assert stats.get_summary()["model"] == "Unknown"
    assert stats.get_summary()["calls"] == 0
