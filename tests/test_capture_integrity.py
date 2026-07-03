"""Classification tests for scripts/check_capture_integrity.py.

evaluate_dataset is a pure function of (baked dataset blob, expected
session), so these tests pin the calendar explicitly — no clock
monkeypatching. Policy under test: upstream staleness warns but never
fails (the monitor surfaces problems, it does not go dark on them);
only a corrupt baked artefact fails.
"""

from __future__ import annotations

from datetime import date

from check_capture_integrity import evaluate_dataset

EXPECTED = date(2026, 7, 2)  # Thu — last completed session in the fixtures


def _blob(live_asof: str | None, health: str = "ok") -> dict:
    meta = {"asOf": live_asof, "live_asOf": live_asof}
    if live_asof is None:
        meta = {}
    return {"meta": meta, "health": {"level": health}}


def test_current_and_healthy_is_ok():
    v = evaluate_dataset(_blob("2026-07-02"), EXPECTED)
    assert v["status"] == "ok"
    assert v["lag"] == 0


def test_one_session_behind_warns():
    # Wed 1 Jul baked when Thu 2 Jul is expected — the fetch-before-
    # engine-publish race signature. Publishes, but emails.
    v = evaluate_dataset(_blob("2026-07-01"), EXPECTED)
    assert v["status"] == "warn"
    assert v["lag"] == 1


def test_holiday_gap_is_not_a_lag():
    # Baked Thu 2 Jul, expected Thu 2 Jul, checked across the Fri 3 Jul
    # holiday weekend: still lag 0 — the calendar, not weekday counting,
    # decides.
    v = evaluate_dataset(_blob("2026-07-02"), date(2026, 7, 2))
    assert v["lag"] == 0


def test_unhealthy_baked_state_warns_even_when_current():
    v = evaluate_dataset(_blob("2026-07-02", health="stale"), EXPECTED)
    assert v["status"] == "warn"
    assert v["health_level"] == "stale"


def test_missing_asof_fails():
    v = evaluate_dataset(_blob(None), EXPECTED)
    assert v["status"] == "fail"
    assert v["lag"] is None


def test_unparseable_asof_fails():
    v = evaluate_dataset(_blob("not-a-date"), EXPECTED)
    assert v["status"] == "fail"
