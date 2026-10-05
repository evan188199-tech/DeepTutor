"""Unit coverage for the practice scheduler's cold-start SM-2 policy."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

import pytest

from deeptutor.services.practice.scheduler import DAY, day_bounds, schedule

NOON = datetime(2026, 9, 25, 12, 34, 56, tzinfo=dt_timezone.utc).timestamp()


def test_day_bounds_cover_the_utc_day():
    start, end = day_bounds("UTC", NOON)
    assert start == datetime(2026, 9, 25, tzinfo=dt_timezone.utc).timestamp()
    assert end - start == DAY
    assert start <= NOON < end


def test_day_bounds_align_to_local_midnight():
    start, _ = day_bounds("Asia/Shanghai", NOON)
    assert start == datetime(2026, 9, 24, 16, tzinfo=dt_timezone.utc).timestamp()
    assert day_bounds("Asia/Shanghai", NOON)[1] - start == DAY


def test_day_bounds_follow_dst_day_length():
    spring = datetime(2026, 3, 8, 12, tzinfo=dt_timezone.utc).timestamp()
    fall = datetime(2026, 11, 1, 12, tzinfo=dt_timezone.utc).timestamp()
    assert (
        day_bounds("America/New_York", spring)[1] - day_bounds("America/New_York", spring)[0]
        == 23 * 3600
    )
    assert (
        day_bounds("America/New_York", fall)[1] - day_bounds("America/New_York", fall)[0]
        == 25 * 3600
    )


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="Unknown timezone"):
        day_bounds("not/a-zone", NOON)


def test_first_good_review_enters_three_day_interval():
    state = schedule({}, "good", NOON)
    assert state == {
        "interval_days": 3.0,
        "ease": 2.5,
        "streak": 1,
        "lapses": 0,
        "due_at": NOON + 3 * DAY,
        "last_review_at": NOON,
        "review_count": 1,
        "version": 1,
    }


def test_good_grows_interval_by_ease_only_after_the_first_review():
    warmed = {"interval_days": 5.0, "ease": 2.5, "streak": 3, "review_count": 3}
    assert schedule(warmed, "good", NOON)["interval_days"] == 12.5
    assert schedule(warmed, "good", NOON)["streak"] == 4
    assert schedule({"interval_days": 5.0}, "good", NOON)["interval_days"] == 3.0
    assert schedule({"interval_days": 0.5, "review_count": 2}, "good", NOON)["interval_days"] == 3.0


def test_easy_bonus_extends_interval_and_ease():
    easy = schedule({}, "easy", NOON)
    assert easy["interval_days"] == pytest.approx(3.9)
    assert easy["ease"] == 2.65
    capped = schedule({"ease": 2.9, "review_count": 5}, "easy", NOON)
    assert capped["ease"] == 3.0


def test_again_lapses_and_resets_the_streak():
    again = schedule({"interval_days": 9.0, "ease": 1.4, "streak": 6, "lapses": 2}, "again", NOON)
    assert again["interval_days"] == round(10 / 1440, 3)
    assert again["streak"] == 0
    assert again["lapses"] == 3
    assert again["ease"] == 1.3
    assert again["due_at"] == NOON + again["interval_days"] * DAY


def test_hard_floors_interval_at_one_day_and_eases_down():
    hard = schedule({"interval_days": 0.5, "ease": 2.5, "streak": 4}, "hard", NOON)
    assert hard["interval_days"] == 1.0
    assert hard["ease"] == 2.35
    assert hard["streak"] == 0


def test_interval_rounds_to_three_decimals_and_caps_at_a_year():
    assert (
        schedule({"interval_days": 1.1111111, "review_count": 2}, "hard", NOON)["interval_days"]
        == 1.333
    )
    capped = schedule({"interval_days": 200, "ease": 2.5, "review_count": 9}, "good", NOON)
    assert capped["interval_days"] == 365.0
    assert capped["due_at"] == NOON + 365 * DAY


def test_counters_and_version_advance_monotonically():
    state = schedule({"version": 7, "review_count": 3}, "good", NOON)
    assert state["version"] == 8
    assert state["review_count"] == 4
    assert state["last_review_at"] == NOON
    assert schedule(state, "good", NOON)["version"] == 9


def test_unknown_rating_is_rejected():
    with pytest.raises(ValueError, match="Unknown review rating"):
        schedule({}, "perfect", NOON)
