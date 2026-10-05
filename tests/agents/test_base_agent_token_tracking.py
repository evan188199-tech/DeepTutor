"""Tests for BaseAgent token tracking failure visibility."""

from __future__ import annotations

import logging

from deeptutor.agents.base_agent import BaseAgent


class _DummyAgent(BaseAgent):
    async def process(self, **_kwargs):  # noqa: ANN003
        return {}


class _FailingTracker:
    """External token tracker whose add_usage always fails."""

    def __init__(self) -> None:
        self.calls = 0

    def add_usage(self, **_kwargs) -> None:
        self.calls += 1
        raise RuntimeError("tracker backend unavailable")


class _RecordingTracker:
    """External token tracker that records add_usage arguments."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_usage(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _make_agent(token_tracker, monkeypatch) -> _DummyAgent:
    # Avoid FileNotFoundError for data/user/settings/agents.yaml in test runs.
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module_name: {},
    )
    return _DummyAgent(
        module_name="question",
        agent_name="idea_agent",
        language="en",
        token_tracker=token_tracker,
    )


def test_track_tokens_failure_is_logged_and_non_fatal(caplog, monkeypatch) -> None:
    """Tracker failure must surface as a warning without breaking the call flow."""
    agent = _make_agent(_FailingTracker(), monkeypatch)
    stats = agent.get_stats("question")
    calls_before = len(stats.calls)

    with caplog.at_level(logging.WARNING, logger="deeptutor.Question.idea_agent"):
        agent._track_tokens("model-x", "sys prompt", "user prompt", "response")

    assert any(
        record.levelno == logging.WARNING and "token" in record.message.lower()
        for record in caplog.records
    )
    assert len(stats.calls) == calls_before + 1


def test_track_tokens_reports_usage_to_external_tracker(monkeypatch) -> None:
    """Healthy tracker still receives the usage record unchanged."""
    tracker = _RecordingTracker()
    agent = _make_agent(tracker, monkeypatch)

    agent._track_tokens("model-x", "sys prompt", "user prompt", "response", stage="draft")

    assert tracker.calls == [
        {
            "agent_name": "idea_agent",
            "stage": "draft",
            "model": "model-x",
            "system_prompt": "sys prompt",
            "user_prompt": "user prompt",
            "response_text": "response",
        }
    ]
