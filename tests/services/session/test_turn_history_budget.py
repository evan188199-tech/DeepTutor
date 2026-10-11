"""Per-turn cumulative replay budget for long tutoring sessions (#1926).

A large context window alone postpones the ratio-based compaction far
beyond what a sustained session can afford to re-carry on every internal
model call. These tests pin the two #1926 knobs:

* the soft per-turn budget that triggers the regular on-demand
  summarization earlier than the window ratio would;
* the hard cap that drops oldest whole turns when compaction is disabled,
  fails, or is configured away — never the newest exchange, and never
  advancing the summarize watermark.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.services.session.context_builder import (
    DEFAULT_TURN_HISTORY_BUDGET_TOKENS,
    DEFAULT_TURN_HISTORY_HARD_CAP_TOKENS,
    MAX_HISTORY_PLAN_TOKENS,
    ContextBuilder,
)


@pytest.fixture(autouse=True)
def _no_budget_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_TURN_HISTORY_BUDGET_TOKENS", raising=False)
    monkeypatch.delenv("DEEPTUTOR_TURN_HISTORY_HARD_CAP_TOKENS", raising=False)


def _cfg(
    *,
    context_window: int | None = 1_000_000,
    max_tokens: int = 4096,
    model: str = "claude-sonnet-4-5",
) -> MagicMock:
    cfg = MagicMock()
    cfg.max_tokens = max_tokens
    cfg.model = model
    cfg.context_window = context_window
    cfg.binding = None
    return cfg


def _store(
    messages: list[dict[str, Any]],
    *,
    summary: str = "",
    up_to: int = 0,
) -> AsyncMock:
    store = AsyncMock()
    store.get_session = AsyncMock(
        return_value={
            "id": "s1",
            "compressed_summary": summary,
            "summary_up_to_msg_id": up_to,
        }
    )
    store.get_messages_for_context = AsyncMock(return_value=messages)
    return store


def _tutoring_rows(turns: int, *, words_per_message: int = 800) -> list[dict[str, Any]]:
    """Long-session rows: each turn is a user question plus an assistant reply."""
    rows: list[dict[str, Any]] = []
    for turn in range(turns):
        rows.append(
            {
                "id": turn * 2 + 1,
                "role": "user",
                "content": f"question {turn} " + ("alpha " * words_per_message),
            }
        )
        rows.append(
            {
                "id": turn * 2 + 2,
                "role": "assistant",
                "content": f"answer {turn} " + ("beta " * words_per_message),
            }
        )
    return rows


def _replay_text(model_history: list[dict[str, Any]]) -> str:
    return " ".join(
        str(message.get("content") or "")
        for message in model_history
        if isinstance(message.get("content"), str)
    )


# ---------------------------------------------------------------------------
# Soft budget: _history_budget table
# ---------------------------------------------------------------------------


class TestHistoryBudgetTurnBound:
    @pytest.mark.parametrize(
        ("context_window", "turn_budget", "expected_budget"),
        [
            # Windows up to ~140k keep the exact ratio plan the defaults
            # already produced: 0.35 * 128000 = 44800 < 49152.
            (128_000, None, 44_800),
            # Large windows no longer scale the replay with the window.
            (200_000, None, DEFAULT_TURN_HISTORY_BUDGET_TOKENS),
            (983_616, None, DEFAULT_TURN_HISTORY_BUDGET_TOKENS),
            (1_000_000, None, DEFAULT_TURN_HISTORY_BUDGET_TOKENS),
            # An explicit smaller per-turn budget binds first.
            (1_000_000, 8_192, 8_192),
            # The per-turn budget never raises a smaller ratio plan.
            (4_000, 8_192, 1_400),
            # 0 disables the soft bound: the ratio plan (capped by
            # MAX_HISTORY_PLAN_TOKENS) is restored byte-for-byte.
            (983_616, 0, MAX_HISTORY_PLAN_TOKENS),
            (128_000, 0, 44_800),
            # The floor still applies below every configured bound.
            (4_000, 100, 256),
        ],
    )
    def test_budget_table(
        self,
        context_window: int,
        turn_budget: int | None,
        expected_budget: int,
    ) -> None:
        builder = ContextBuilder(
            store=MagicMock(),
            turn_history_budget_tokens=turn_budget,
        )
        assert builder._history_budget(_cfg(context_window=context_window)) == expected_budget

    def test_env_overrides_default_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPTUTOR_TURN_HISTORY_BUDGET_TOKENS", "12000")
        builder = ContextBuilder(store=MagicMock())
        assert builder.turn_history_budget_tokens == 12_000
        assert builder._history_budget(_cfg()) == 12_000

    def test_env_zero_disables_soft_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPTUTOR_TURN_HISTORY_BUDGET_TOKENS", "0")
        builder = ContextBuilder(store=MagicMock())
        assert builder._history_budget(_cfg()) == MAX_HISTORY_PLAN_TOKENS

    def test_env_garbage_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPTUTOR_TURN_HISTORY_BUDGET_TOKENS", "not-a-number")
        monkeypatch.setenv("DEEPTUTOR_TURN_HISTORY_HARD_CAP_TOKENS", " ")
        builder = ContextBuilder(store=MagicMock())
        assert builder.turn_history_budget_tokens == DEFAULT_TURN_HISTORY_BUDGET_TOKENS
        assert builder.turn_history_hard_cap_tokens == DEFAULT_TURN_HISTORY_HARD_CAP_TOKENS

    def test_explicit_argument_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPTUTOR_TURN_HISTORY_BUDGET_TOKENS", "12000")
        builder = ContextBuilder(store=MagicMock(), turn_history_budget_tokens=8_192)
        assert builder.turn_history_budget_tokens == 8_192


# ---------------------------------------------------------------------------
# Long-session build: on-demand compression triggers under the soft budget
# ---------------------------------------------------------------------------


class TestLongSessionCompactsWithinTurnBudget:
    @pytest.mark.asyncio
    async def test_large_window_history_compacts_under_default_budget(self) -> None:
        # ~1-1.2k tokens per row * 80 rows ~= 64-97k tokens of replayed
        # history: far below the 131k ratio plan, far above the per-turn
        # soft budget of 49152.
        rows = _tutoring_rows(40)
        store = _store(rows)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(return_value=("SESSION SUMMARY", []))

        result = await builder.build(session_id="s1", llm_config=_cfg())

        # On-demand compression triggered even though the window ratio
        # alone (0.35 * 1M, capped at 131k) would have accepted the replay.
        builder._summarize.assert_awaited_once()
        store.update_summary.assert_awaited_once()
        assert result.conversation_summary == "SESSION SUMMARY"
        # The replay the turn carries is controlled: the verbatim tail plus
        # the summary stays under the soft budget.
        assert result.token_count <= DEFAULT_TURN_HISTORY_BUDGET_TOKENS
        assert result.model_history[0]["role"] == "system"
        replay_text = _replay_text(result.model_history)
        assert "answer 39" in replay_text  # newest exchange retained
        assert "question 0" not in replay_text  # oldest scrolled into the summary

    @pytest.mark.asyncio
    async def test_summary_failure_degrades_within_turn_budget(self) -> None:
        rows = _tutoring_rows(40)
        store = _store(rows)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(side_effect=RuntimeError("llm down"))

        result = await builder.build(session_id="s1", llm_config=_cfg())

        # Failure keeps the watermark; the turn still fits the soft budget
        # via the degrade trim, and the newest exchange survives.
        store.update_summary.assert_not_called()
        assert result.conversation_summary == ""
        assert result.token_count <= DEFAULT_TURN_HISTORY_BUDGET_TOKENS
        assert "answer 39" in _replay_text(result.model_history)


# ---------------------------------------------------------------------------
# Hard cap backstop table
# ---------------------------------------------------------------------------


class TestHardCapBackstop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("hard_cap", "expect_trimmed"),
        [
            # The default cap does not bind while the soft budget is
            # disabled and the replay stays under it.
            (None, False),
            (70_000, False),
            # A cap under the replay trims oldest turns on the fast path
            # without touching the summarize watermark.
            (20_000, True),
            # 0 disables the backstop entirely.
            (0, False),
        ],
    )
    async def test_fast_path_hard_cap_table(
        self,
        hard_cap: int | None,
        expect_trimmed: bool,
    ) -> None:
        rows = _tutoring_rows(16)  # ~= 26-39k tokens of replay
        store = _store(rows)
        builder = ContextBuilder(
            store=store,
            turn_history_budget_tokens=0,  # disable the soft bound
            turn_history_hard_cap_tokens=hard_cap,
        )
        builder._summarize = AsyncMock(return_value=("SUMMARY", []))

        result = await builder.build(session_id="s1", llm_config=_cfg())

        # Fast path: no compression was requested or recorded.
        builder._summarize.assert_not_called()
        store.update_summary.assert_not_called()
        replay_text = _replay_text(result.model_history)
        assert "answer 15" in replay_text  # newest exchange always retained
        assert ("question 0" in replay_text) != expect_trimmed
        if expect_trimmed:
            assert result.token_count <= int(hard_cap)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_hard_cap_binds_below_soft_budget(self) -> None:
        # When the cap sits under the soft budget, the post-summarize
        # replay is trimmed to the cap as the final backstop.
        rows = _tutoring_rows(40)
        store = _store(rows)
        builder = ContextBuilder(
            store=store,
            turn_history_budget_tokens=24_000,
            turn_history_hard_cap_tokens=8_000,
        )
        builder._summarize = AsyncMock(return_value=("SUMMARY", []))

        result = await builder.build(session_id="s1", llm_config=_cfg())

        builder._summarize.assert_awaited_once()
        assert result.token_count <= 8_000
        assert "answer 39" in _replay_text(result.model_history)

    @pytest.mark.asyncio
    async def test_tiny_cap_keeps_newest_exchange(self) -> None:
        rows = _tutoring_rows(4)
        store = _store(rows)
        builder = ContextBuilder(
            store=store,
            turn_history_budget_tokens=0,
            turn_history_hard_cap_tokens=100,
        )

        result = await builder.build(session_id="s1", llm_config=_cfg())

        # A single row larger than the cap is still retained whole — the
        # newest exchange is never dropped, only bounded by turn count.
        assert result.model_history
        replay_text = _replay_text(result.model_history)
        assert "answer 3" in replay_text
        assert "question 2" not in replay_text


# ---------------------------------------------------------------------------
# Short sessions: no regression under default parameters
# ---------------------------------------------------------------------------


class TestShortSessionNoRegression:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("turns", "context_window"),
        [
            (1, 1_000),  # tiny window, tiny session
            (2, 16_384),  # fallback window
            (6, 128_000),  # default large window, still far under 44.8k
        ],
    )
    async def test_small_sessions_replay_verbatim(self, turns: int, context_window: int) -> None:
        rows = _tutoring_rows(turns, words_per_message=50)
        store = _store(rows)
        builder = ContextBuilder(store=store)
        builder._summarize = AsyncMock(return_value=("SUMMARY", []))

        result = await builder.build(
            session_id="s1", llm_config=_cfg(context_window=context_window)
        )

        builder._summarize.assert_not_called()
        store.update_summary.assert_not_called()
        assert result.conversation_history == builder._build_history("", rows)
        assert result.model_history == [
            {"role": row["role"], "content": row["content"]} for row in rows
        ]
        assert result.token_count == builder._model_tokens(rows, "")
