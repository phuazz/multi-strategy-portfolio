"""Guard tests for the price-panel as-of stamp in build_risk_visuals.py.

Regression cover for the 2026-08-08 incident. The engine's holdings price
panel rewrote EEM — 10.0% of NAV, the model's largest line — four sessions
BACKWARDS, from a 2026-08-07 bar to a 2026-08-03 one, while every other
holding stayed current. Nothing downstream could see it: ``prices_asof`` is a
max() across the held series when live_track carries no live_dates, so one
lagging line cannot move the header stamp. risk_triggers.json therefore
claimed ``as_of_prices`` 2026-08-07 while EEM's published +7.3% above its
200-DMA was computed on the 2026-08-03 close (the 2026-08-07 bar puts it at
+8.4%).

This is the same class of defect as ``uncovered_holdings`` from the 2026-07-18
audit — a series that is PRESENT but not current, rather than absent — and it
is guarded the same way: reported loudly and carried in the JSON so the digest
and the factsheet can show the gap instead of implying full coverage.

Python date months are 1-indexed (January = 1). All dates here are literals,
so no date arithmetic is performed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_risk_visuals as brv  # noqa: E402


CURRENT = "2026-08-07"
LAGGING = "2026-08-03"


def _series(last_date: str, above_ma_pct: float) -> dict:
    """A minimal panel record ending on ``last_date``.

    Only the last bar matters to the as-of guard, but prox_pct_week_ago walks
    the dates array, so give it a fortnight of bars to walk.
    """
    dates = ["2026-07-20", "2026-07-27", "2026-08-03"]
    if last_date != "2026-08-03":
        dates.append(last_date)
    n = len(dates)
    ma = 100.0
    px = ma * (1.0 + above_ma_pct / 100.0)
    return {
        "dates": dates,
        "prices": [px] * n,
        "ma50": [ma] * n,
        "ma100": [ma] * n,
        "ma200": [ma] * n,
        "vs_ma200": above_ma_pct / 100.0,
        "change_pct": 0.1,
        "n_days": n,
    }


def _write_engine_fixture(root: Path, eem_last: str, live_dates: list[str]) -> Path:
    """A minimal breadth-thrust-etf checkout: the three files main() reads."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    (data / "risk_overlay.json").write_text(json.dumps({
        "current_breadth": 0.62,
        "current_state": "RISK_ON",
        "panel_end_date": "2026-08-07",
        "gate_parameters": {"off_threshold": 0.30, "on_threshold": 0.50,
                            "fallback_ticker": "SHY"},
    }), encoding="utf-8")

    (data / "live_track.json").write_text(json.dumps({
        "effective_weights": {"EEM": 0.10, "SPY": 0.60, "IJR": 0.30},
        "live_dates": live_dates,
        "eem_tilt_active": True,
    }), encoding="utf-8")

    (data / "holdings_prices_1y.json").write_text(json.dumps({
        "computed_at_utc": "2026-08-08T22:27:00+00:00",
        "lookback_days": 252,
        "prices": {
            "EEM": _series(eem_last, 7.32),
            "SPY": _series(CURRENT, 5.0),
            "IJR": _series(CURRENT, 3.0),
        },
    }), encoding="utf-8")
    return root


def _run(tmp_path: Path, eem_last: str, live_dates: list[str],
         monkeypatch: pytest.MonkeyPatch) -> dict:
    local = _write_engine_fixture(tmp_path / "engine", eem_last, live_dates)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv",
                        ["build_risk_visuals.py", "--out", str(out),
                         "--local", str(local)])
    brv.main()
    return json.loads((out / "risk_triggers.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (b) One lagging ticker must be REPORTED as lagging, not hidden behind the
#     newest date in the panel.
# ---------------------------------------------------------------------------
def test_a_lagging_holding_is_reported_not_hidden(tmp_path, monkeypatch):
    """The exact 2026-08-08 shape: EEM four sessions behind a panel whose
    other lines are current, and live_track carrying no live_dates so the
    max() fallback fires."""
    triggers = _run(tmp_path, eem_last=LAGGING, live_dates=[],
                    monkeypatch=monkeypatch)

    stale = {h["ticker"]: h for h in triggers["stale_holdings"]}
    assert "EEM" in stale, (
        "EEM lagged the panel by four sessions and was not reported — this is "
        "the defect: a single lagging series is invisible in a max() stamp")
    assert stale["EEM"]["last_bar"] == LAGGING
    assert stale["EEM"]["weight_pct"] == pytest.approx(10.0)

    # The current lines must NOT be flagged.
    assert "SPY" not in stale and "IJR" not in stale

    # The honest floor: the oldest bar any held line sits on. A consumer that
    # reads this can never overstate the panel's coverage.
    assert triggers["as_of_prices_oldest"] == LAGGING
    assert triggers["as_of_prices_oldest"] < triggers["as_of_prices"]

    # And the share of NAV that IS marked to the header date.
    assert triggers["panel_current_pct_nav"] == pytest.approx(90.0)


def test_a_fully_current_panel_reports_no_staleness(tmp_path, monkeypatch):
    """Control: with every line on the same bar the guard stays silent, so it
    cannot pass by always flagging."""
    triggers = _run(tmp_path, eem_last=CURRENT, live_dates=[],
                    monkeypatch=monkeypatch)

    assert triggers["stale_holdings"] == []
    assert triggers["as_of_prices"] == CURRENT
    assert triggers["as_of_prices_oldest"] == CURRENT
    assert triggers["panel_current_pct_nav"] == pytest.approx(100.0)


def test_staleness_is_measured_against_the_panel_not_the_live_mark(
        tmp_path, monkeypatch):
    """live_track's live_dates set the HEADER date, but they must not decide
    which holdings count as lagging.

    The live mark runs ahead of the price panel by construction (it extends
    the model to the latest session). Comparing every holding against it
    would flag the whole book on a perfectly healthy panel, and comparing
    against a live date that trails the panel would flag nothing on a broken
    one. The staleness verdict must come from the panel's own newest held bar.
    """
    triggers = _run(tmp_path, eem_last=LAGGING, live_dates=["2026-08-10"],
                    monkeypatch=monkeypatch)

    stale = {h["ticker"] for h in triggers["stale_holdings"]}
    assert stale == {"EEM"}, (
        f"expected only EEM to be lagging, got {sorted(stale)} — staleness is "
        "being measured against the live mark, not the panel's own newest bar")
    assert triggers["panel_current_pct_nav"] == pytest.approx(90.0)


def test_the_cash_leg_is_not_counted_as_a_holding(tmp_path, monkeypatch):
    """SHY is the gate's fallback cash leg, not a trend position. It is
    excluded from the coverage guard and the all_above_200dma verdict, so it
    must be excluded from the staleness report too — otherwise a de-risked
    book reads as a stale one."""
    local = _write_engine_fixture(tmp_path / "engine", LAGGING, [])
    hp_path = local / "data" / "holdings_prices_1y.json"
    hp = json.loads(hp_path.read_text(encoding="utf-8"))
    hp["prices"]["SHY"] = _series("2026-07-27", 0.5)
    hp_path.write_text(json.dumps(hp), encoding="utf-8")

    lt_path = local / "data" / "live_track.json"
    lt = json.loads(lt_path.read_text(encoding="utf-8"))
    lt["effective_weights"]["SHY"] = 0.20
    lt_path.write_text(json.dumps(lt), encoding="utf-8")

    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv",
                        ["build_risk_visuals.py", "--out", str(out),
                         "--local", str(local)])
    brv.main()
    triggers = json.loads((out / "risk_triggers.json").read_text(encoding="utf-8"))

    stale = {h["ticker"] for h in triggers["stale_holdings"]}
    assert "SHY" not in stale, "the cash leg is not a priced trend position"
    assert stale == {"EEM"}
