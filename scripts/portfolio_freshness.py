"""Freshness of the engine's executed core book, separately from daily prices.

The deployed engine fills on Monday, rolling NYSE holidays to the next session
(rebalance_calendar.DEFAULT_MODE = HOLIDAY_AWARE_NEXT). This checks publication
coverage only; it never generates a signal, allocation or assumed trade. A valid
HOLD may retain its selection while the engine publishes a current book anchor.
Python datetime months are 1-indexed; datetime.weekday uses Monday = 0.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nyse_sessions import _NYSE, sessions_behind


def expected_book_session(now: datetime) -> date:
    if now.tzinfo is None:
        raise ValueError("Book freshness requires a timezone-aware clock")
    now = now.astimezone(timezone.utc)
    start = now.date() - timedelta(days=28)
    schedule = _NYSE.schedule(start_date=start, end_date=now.date() + timedelta(days=7))
    due = []
    for scheduled in (start + timedelta(days=i) for i in range(29)):
        if scheduled.weekday() != 0:
            continue
        candidates = schedule[(schedule.index.date >= scheduled)
                              & (schedule.index.date < scheduled + timedelta(days=7))]
        if not candidates.empty and candidates.iloc[0]["market_close"] <= now:
            due.append(candidates.index[0].date())
    if not due:
        raise ValueError("No completed weekly core fill in the calendar window")
    return max(due)


def evaluate_book(anchor: str | None, strategy_end: str | None, now: datetime) -> dict:
    expected = expected_book_session(now)
    try:
        coverage = min(date.fromisoformat(str(d)[:10]) for d in (anchor, strategy_end))
    except ValueError:
        coverage = None
    lag = sessions_behind(coverage, expected) if coverage else None
    return {"asOf": coverage.isoformat() if coverage else None,
            "expected": expected.isoformat(), "lag": lag,
            "level": "ok" if lag == 0 else "stale"}
