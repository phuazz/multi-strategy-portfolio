"""Health validity uses the real NYSE calendar and UTC date rollovers.

Python datetime months are 1-indexed (January = 1).
"""
import copy
import datetime as dt
from unittest.mock import Mock

import pandas as pd
import pytest

import nyse_sessions
import validate


def instant(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("now,expected", [
    ("2026-06-30T19:59:59Z", "2026-06-30T20:00:00Z"),
    ("2026-06-30T20:00:00Z", "2026-07-01T20:00:00Z"),  # exact close/month boundary
    ("2026-12-31T21:00:00Z", "2027-01-04T21:00:00Z"),  # year/holiday/weekend
    ("2026-08-21T20:00:00Z", "2026-08-24T20:00:00Z"),  # Friday close
    ("2026-08-22T12:00:00Z", "2026-08-24T20:00:00Z"),  # weekend
    ("2026-06-19T12:00:00Z", "2026-06-22T20:00:00Z"),  # Juneteenth
    ("2026-12-24T17:59:59Z", "2026-12-24T18:00:00Z"),  # early close
    ("2026-12-24T18:00:00Z", "2026-12-28T21:00:00Z"),
    ("2026-03-06T20:59:59Z", "2026-03-06T21:00:00Z"),  # before spring DST
    ("2026-03-06T21:00:00Z", "2026-03-09T20:00:00Z"),  # after spring DST
    ("2026-10-30T19:59:59Z", "2026-10-30T20:00:00Z"),  # before autumn DST
    ("2026-10-30T20:00:00Z", "2026-11-02T21:00:00Z"),  # after autumn DST
])
def test_next_real_close(now, expected):
    result = nyse_sessions.next_session_close(instant(now))
    assert result == instant(expected)
    assert result.tzinfo == dt.timezone.utc


def test_next_close_rejects_naive_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        nyse_sessions.next_session_close(dt.datetime(2026, 6, 30))


def test_next_close_empty_schedule_and_bounded_window(monkeypatch):
    calendar = Mock()
    calendar.schedule.return_value = pd.DataFrame({
        "market_close": pd.Series([], dtype="datetime64[ns, UTC]")})
    monkeypatch.setattr(nyse_sessions, "_NYSE", calendar)
    with pytest.raises(RuntimeError, match="no future NYSE close"):
        nyse_sessions.next_session_close(instant("2026-12-31T21:00:00Z"))
    calendar.schedule.assert_called_once_with(start_date="2026-12-31", end_date="2027-01-15")


def inputs(now):
    asof = nyse_sessions.last_completed_session(now).isoformat()
    return ({"source_commit": "abc123", "live_track.json": {"live_dates": [asof]},
             "risk_overlay.json": {"panel_end_date": asof},
             "multi_strategy.json": {"common_end": asof}},
            {"freshness": {"regime_bdays": 8, "strategy_bdays": 8}},
            {"reconcile": {"ok": True}})


def health(now, run_date=None, args=None):
    bundle, registry, stats = args if args is not None else inputs(now)
    return validate.run(bundle, registry, run_date or now.date(), stats,
                        bench_ok=True, bench_note="ok", now_utc=now)


@pytest.mark.parametrize("now,expected", [
    ("2026-06-30T19:59:59Z", "2026-06-30T20:00:00Z"),
    ("2026-06-30T20:00:00Z", "2026-07-01T00:00:00Z"),
    ("2026-12-31T21:00:00Z", "2027-01-01T00:00:00Z"),
    ("2026-08-21T20:00:00Z", "2026-08-22T00:00:00Z"),
    ("2026-08-22T12:00:00Z", "2026-08-23T00:00:00Z"),
    ("2026-06-19T12:00:00Z", "2026-06-20T00:00:00Z"),
    ("2026-12-24T17:59:59Z", "2026-12-24T18:00:00Z"),
    ("2026-03-09T19:00:00Z", "2026-03-09T20:00:00Z"),
    ("2026-11-02T20:00:00Z", "2026-11-02T21:00:00Z"),
])
def test_health_expiry(now, expected):
    h = health(instant(now))
    assert h["checked_at_utc"] == now
    assert h["valid_until_utc"] == expected
    assert "validity_error" not in h


def test_metadata_additive_and_inputs_unchanged():
    now = instant("2026-06-30T21:00:00.123456Z")
    args = inputs(now)
    before = copy.deepcopy(args)
    h = health(now, args=args)
    assert args == before
    assert h.pop("checked_at_utc") == "2026-06-30T21:00:00Z"
    assert h.pop("valid_until_utc") == "2026-07-01T00:00:00Z"
    feeds = []
    for name, basis, budget in [
        ("Price / NAV (live_track)", "NYSE sessions", 0),
        ("Breadth / regime panel (risk_overlay)", "business days", 8),
        ("Strategy equity (multi_strategy)", "business days", 8),
    ]:
        feeds.append({"feed": name, "asOf": "2026-06-30", "bday_lag": 0,
                      "budget_bdays": budget, "level": "ok", "computed_at": None, "basis": basis})
    assert h == {"level": "ok", "ok": True, "feeds": feeds, "consistency_ok": True,
                 "reconcile_ok": True, "benchmark_ok": True, "messages": [],
                 "source_commit": "abc123", "checked_at": "2026-06-30"}


@pytest.mark.parametrize("failure", [RuntimeError("calendar unavailable"), KeyError("market_close")])
def test_future_lookup_errors_are_explicit_without_changing_verdict(monkeypatch, failure):
    now = instant("2026-06-30T21:00:00Z")
    expected = health(now)
    monkeypatch.setattr(validate, "next_session_close", Mock(side_effect=failure))
    h = health(now)
    assert h["valid_until_utc"] is None
    assert type(failure).__name__ in h.pop("validity_error")
    expected["valid_until_utc"] = None
    assert h == expected


@pytest.mark.parametrize("returned", [None, dt.datetime(2026, 7, 1), instant("2026-06-30T21:00:00Z")])
def test_missing_or_invalid_future_close_fails_closed(monkeypatch, returned):
    now = instant("2026-06-30T21:00:00Z")
    monkeypatch.setattr(validate, "next_session_close", lambda _: returned)
    h = health(now)
    assert h["valid_until_utc"] is None and h["validity_error"]


@pytest.mark.parametrize("run_date", [dt.date(2026, 6, 29), dt.date(2026, 7, 1)])
def test_run_date_mismatch_has_no_validity(monkeypatch, run_date):
    lookup = Mock(side_effect=AssertionError("must not extend mismatched verdict"))
    monkeypatch.setattr(validate, "next_session_close", lookup)
    h = health(instant("2026-06-30T21:00:00Z"), run_date=run_date)
    assert h["valid_until_utc"] is None
    assert "differs from validation UTC date" in h["validity_error"]
    lookup.assert_not_called()


def test_current_health_calendar_failure_still_raises(monkeypatch):
    now = instant("2026-06-30T21:00:00Z")
    args = inputs(now)
    monkeypatch.setattr(validate, "last_completed_session", Mock(side_effect=RuntimeError("current failed")))
    with pytest.raises(RuntimeError, match="current failed"):
        health(now, args=args)


def test_validation_rejects_naive_clock():
    args = inputs(instant("2026-06-30T21:00:00Z"))
    with pytest.raises(ValueError, match="timezone-aware"):
        health(dt.datetime(2026, 6, 30, 21), args=args)


def test_timezone_normalised_before_date_comparison():
    h = health(instant("2026-07-01T05:00:00+08:00"), run_date=dt.date(2026, 6, 30))
    assert h["checked_at_utc"] == "2026-06-30T21:00:00Z"
    assert h["valid_until_utc"] == "2026-07-01T00:00:00Z"


def test_single_clock_read(monkeypatch):
    now = instant("2026-06-30T21:00:00Z")
    bundle, registry, stats = inputs(now)

    class Clock(dt.datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return now

    monkeypatch.setattr(validate.dt, "datetime", Clock)
    h = validate.run(bundle, registry, now.date(), stats, bench_ok=True, bench_note="ok")
    assert Clock.calls == 1
    assert h["checked_at_utc"] == "2026-06-30T21:00:00Z"
    assert h["valid_until_utc"] == "2026-07-01T00:00:00Z"


def test_future_schedule_failure_propagates(monkeypatch):
    calendar = Mock()
    calendar.schedule.side_effect = RuntimeError("schedule unavailable")
    monkeypatch.setattr(nyse_sessions, "_NYSE", calendar)
    with pytest.raises(RuntimeError, match="schedule unavailable"):
        nyse_sessions.next_session_close(instant("2026-06-30T21:00:00Z"))
