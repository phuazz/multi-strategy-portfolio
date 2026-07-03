"""Edge-case tests for scripts/nyse_sessions.py (ported with the module
from breadth-thrust-etf, 2026-07-03).

Month- and year-boundary cases per vault CLAUDE.md date rules, plus the
holiday cases that distinguish this TRUE-calendar module from
validate.py's plain business-day budgets. Python date months are
1-indexed (January = 1); each expected value states its session walk in
a comment.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from nyse_sessions import last_completed_session, sessions_behind


# ---------------------------------------------------------------------------
# last_completed_session
# ---------------------------------------------------------------------------

def test_holiday_friday_resolves_to_thursday():
    # Fri 3 Jul 2026 is the Independence Day observance (4 Jul falls on a
    # Saturday) — no NYSE session. At 22:00 UTC that Friday the last
    # completed session is Thu 2 Jul.
    now = datetime(2026, 7, 3, 22, 0, tzinfo=timezone.utc)
    assert last_completed_session(now) == date(2026, 7, 2)


def test_before_and_after_the_close_on_a_session_day():
    # Thu 2 Jul 2026: the close is 20:00 UTC (16:00 EDT). At 19:00 UTC
    # the session is not complete -> Wed 1 Jul; at 21:30 UTC -> Thu 2 Jul.
    assert last_completed_session(
        datetime(2026, 7, 2, 19, 0, tzinfo=timezone.utc)) == date(2026, 7, 1)
    assert last_completed_session(
        datetime(2026, 7, 2, 21, 30, tzinfo=timezone.utc)) == date(2026, 7, 2)


def test_year_boundary():
    # 1 Jan 2026 (Thu) is a holiday: at midday UTC the last completed
    # session is Wed 31 Dec 2025 — the year boundary must not confuse
    # the lookback window.
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert last_completed_session(now) == date(2025, 12, 31)


def test_early_close_is_respected():
    # Thu 24 Dec 2026 is a half session (Christmas Day Fri 25 Dec):
    # close 13:00 EST = 18:00 UTC. At 19:00 UTC the session has already
    # completed — a naive 20:00 UTC close assumption would say otherwise.
    now = datetime(2026, 12, 24, 19, 0, tzinfo=timezone.utc)
    assert last_completed_session(now) == date(2026, 12, 24)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        last_completed_session(datetime(2026, 7, 2, 22, 0))


# ---------------------------------------------------------------------------
# sessions_behind
# ---------------------------------------------------------------------------

def test_zero_when_current_or_ahead():
    assert sessions_behind(date(2026, 7, 2), date(2026, 7, 2)) == 0
    # A 24/7-traded component can stamp a date past the NYSE session.
    assert sessions_behind(date(2026, 7, 4), date(2026, 7, 2)) == 0


def test_holiday_does_not_count_as_a_session():
    # Thu 2 Jul -> Mon 6 Jul 2026 is ONE session behind: Fri 3 Jul was
    # the Independence Day observance. (validate.py's busday_count would
    # say 2 — that slack is why its budgets are wide; this module is the
    # exact calendar.)
    assert sessions_behind(date(2026, 7, 2), date(2026, 7, 6)) == 1


def test_month_boundary():
    # Fri 26 Jun -> Thu 2 Jul 2026: sessions Jun 29, 30, Jul 1, 2 = 4.
    assert sessions_behind(date(2026, 6, 26), date(2026, 7, 2)) == 4


def test_year_boundary_lag():
    # Wed 31 Dec 2025 -> Fri 2 Jan 2026: New Year's Day (Thu) is a
    # holiday, so the only session after 31 Dec is 2 Jan = 1.
    assert sessions_behind(date(2025, 12, 31), date(2026, 1, 2)) == 1
