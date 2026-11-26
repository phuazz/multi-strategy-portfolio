"""Classification tests for scripts/check_capture_integrity.py.

evaluate_dataset is a pure function of (baked dataset blob, expected
session), so these tests pin the calendar explicitly — no clock
monkeypatching. Policy under test: upstream staleness warns but never
fails (the monitor surfaces problems, it does not go dark on them);
only a corrupt baked artefact fails.
"""

from __future__ import annotations

from datetime import date

from check_capture_integrity import alert_decision, evaluate_dataset

EXPECTED = date(2026, 7, 2)  # Thu — last completed session in the fixtures


def _blob(live_asof: str | None, health: str = "ok") -> dict:
    meta = {"asOf": live_asof, "live_asOf": live_asof,
            "portfolio_anchor": live_asof, "strategy_asOf": live_asof}
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


def test_current_prices_on_previous_book_warn_even_with_green_health():
    blob = _blob("2026-11-02")
    blob["meta"].update(portfolio_anchor="2026-10-30", strategy_asOf="2026-10-30")
    verdict = evaluate_dataset(blob, date(2026, 11, 2))
    assert verdict["lag"] == 0
    assert verdict["status"] == "warn"
    assert verdict["book_level"] == "stale"


def test_legacy_dataset_without_book_provenance_cannot_pass():
    blob = _blob("2026-11-02")
    del blob["meta"]["portfolio_anchor"]
    assert evaluate_dataset(blob, date(2026, 11, 2))["book_level"] == "stale"

def test_historical_receipts_track_exact_dates_and_observation_types():
    fx = "STI FX SGDUSD=X 2019-05-22"
    price = "STI price ES3.SI 2019-05-22"
    blob = _blob("2026-07-02", "warn")
    blob["health"].update(consistency_ok=True, reconcile_ok=True,
                          dashboard_only_history_warnings=["STI"],
                          dashboard_only_history_gaps=[fx])
    verdict = evaluate_dataset(blob, EXPECTED)
    assert verdict["status"] == "warn"
    assert alert_decision(blob, verdict, EXPECTED, [fx]) == (False, [fx], [])
    assert alert_decision(blob, verdict, EXPECTED, []) == (True, [fx], [fx])
    blob["health"]["dashboard_only_history_gaps"] = [price]
    assert alert_decision(blob, verdict, EXPECTED, [fx]) == (True, [price], [price])
    assert alert_decision(blob, verdict, EXPECTED, [fx, price]) == (False, [price], [])
    blob["health"]["level"] = "ok"
    assert alert_decision(blob, evaluate_dataset(blob, EXPECTED), EXPECTED, [price]) == (False, [], [])


def test_history_receipt_cannot_silence_current_or_unclassified_alerts():
    gap = "STI FX SGDUSD=X 2019-05-22"
    blob = _blob("2026-07-02", "warn")
    blob["health"].update(consistency_ok=True, reconcile_ok=True,
                          dashboard_only_history_warnings=["STI"], dashboard_only_history_gaps=[gap])
    def notify():
        return alert_decision(blob, evaluate_dataset(blob, EXPECTED), EXPECTED, [gap])[0]
    for field in ("consistency_ok", "reconcile_ok"):
        blob["health"][field] = False
        assert notify()
        blob["health"][field] = True
    for late_or_future in ("2026-07-01", "2026-07-06"):
        blob["meta"]["live_asOf"] = late_or_future
        assert notify()
    blob["meta"]["live_asOf"] = "2026-07-02"
    blob["meta"]["portfolio_anchor"] = "2026-06-15"
    assert notify()
    blob["meta"]["portfolio_anchor"] = "2026-07-02"
    del blob["health"]["dashboard_only_history_gaps"]
    assert notify()
