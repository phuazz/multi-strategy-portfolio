"""The S&P 500 curve must be the engine's series, and must never be
forward-filled onto a date it has no bar for.

Background (2026-09-05/06): the dashboard printed S&P YTD +13.1% against the
model's Friday mark while the engine's email said +12.7% on the same Friday.
The model series was identical to the engine's; the benchmark was not — the
Saturday 01:22 UTC yfinance fetch received no 4 Sep SPY bar, and the old
alignment forward-filled Thursday's close onto Friday's date. These pin the
new rule: the engine's committed export is the base, yfinance only chains
returns after it, and a series ends at its own last served close.
Python datetime months are 1-indexed (January = 1).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import benchmarks as bmk
from config import load_registry

ROOT = Path(__file__).resolve().parent.parent

MODEL_DATES = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"]
LIVE_DATES = ["2026-09-04"]
AXIS = MODEL_DATES + LIVE_DATES


def _reg(spy_type="engine", blend=True):
    bms = {"SPY": {"label": "S&P 500", "type": spy_type, "ticker": "SPY",
                   "file": "benchmark_spy.json", "default": True}}
    if blend:
        bms["BAL6040"] = {"label": "60/40", "type": "blend",
                          "components": {"SPY": 0.6, "IEF": 0.4}}
    return {"benchmarks": bms}


def _export(dates, closes):
    return {"ticker": "SPY", "basis": "adjusted close (sleeve B cache)",
            "written_at_utc": "2026-09-06T15:00:00+00:00",
            "dates": dates, "closes": closes}


def _fake_download(frame: pd.DataFrame):
    def _dl(tickers, start, end):
        cols = [t for t in tickers if t in frame.columns]
        return frame[cols].copy()
    return _dl


@pytest.fixture
def yf_frame(monkeypatch):
    """yfinance on a different scale from the export, serving IEF and SPY."""
    dates = pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"])
    frame = pd.DataFrame({"SPY": [50.0, 50.5, 51.0, 51.5, 52.0],
                          "IEF": [90.0, 90.0, 90.9, 90.9, 91.8]}, index=dates)
    monkeypatch.setattr(bmk, "_download", _fake_download(frame))
    return frame


def test_engine_export_is_the_base_and_yfinance_only_chains_returns(yf_frame):
    export = _export(["2026-08-31", "2026-09-01", "2026-09-02"], [100.0, 101.0, 102.0])
    out, ok, note = bmk.build_benchmarks(MODEL_DATES, _reg(blend=False), LIVE_DATES,
                                         engine_files={"benchmark_spy.json": export})
    assert ok and "SPY: engine export benchmark_spy.json to 2026-09-02 + yfinance returns for 2 sessions" in note
    spy = out["SPY"]
    assert spy["dates"] == AXIS and spy["asOf"] == "2026-09-04"
    # Rebased to the export's first value; the extension carries yfinance's
    # RETURNS (51.5/51, 52/51) on the export's scale, not yfinance's levels.
    expected = [1.0, 1.01, 1.02, 1.02 * 51.5 / 51.0, 1.02 * 52.0 / 51.0]
    assert spy["equity"] == pytest.approx(expected, abs=1e-6)
    assert spy["extension"] == {"from": "2026-09-02", "sessions": 2, "note": None}
    assert spy["basis"].startswith("engine export:") and spy["export_written_at_utc"]


def test_withheld_newest_bar_ends_the_series_instead_of_forward_filling(monkeypatch):
    dates = pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"])
    frame = pd.DataFrame({"SPY": [50.0, 50.5, 51.0, 51.5]}, index=dates)   # no 4 Sep bar
    monkeypatch.setattr(bmk, "_download", _fake_download(frame))
    export = _export(["2026-08-31", "2026-09-01", "2026-09-02"], [100.0, 101.0, 102.0])
    out, ok, _ = bmk.build_benchmarks(MODEL_DATES, _reg(blend=False), LIVE_DATES,
                                      engine_files={"benchmark_spy.json": export})
    spy = out["SPY"]
    assert spy["asOf"] == "2026-09-03"
    assert spy["dates"][-1] == "2026-09-04" and spy["equity"][-1] is None, \
        "the model's Friday date must carry NO benchmark value, not Thursday's close"
    assert spy["equity"][-2] == pytest.approx(1.02 * 51.5 / 51.0)


def test_export_alone_when_yfinance_cannot_chain(monkeypatch):
    # yfinance lacks the export's last date: nothing to chain from, so the
    # curve ends where the export ends and says why.
    dates = pd.to_datetime(["2026-09-03", "2026-09-04"])
    frame = pd.DataFrame({"SPY": [51.5, 52.0]}, index=dates)
    monkeypatch.setattr(bmk, "_download", _fake_download(frame))
    export = _export(["2026-08-31", "2026-09-01", "2026-09-02"], [100.0, 101.0, 102.0])
    out, ok, note = bmk.build_benchmarks(MODEL_DATES, _reg(blend=False), LIVE_DATES,
                                         engine_files={"benchmark_spy.json": export})
    assert ok and out["SPY"]["asOf"] == "2026-09-02"
    assert out["SPY"]["extension"]["sessions"] == 0 and "not chained" in note
    assert out["SPY"]["equity"][-2:] == [None, None]


def test_interior_gap_is_forward_filled_and_counted(yf_frame):
    export = _export(["2026-08-31", "2026-09-01", "2026-09-03"], [100.0, 101.0, 103.0])  # no 2 Sep
    out, _, _ = bmk.build_benchmarks(MODEL_DATES, _reg(blend=False), LIVE_DATES,
                                     engine_files={"benchmark_spy.json": export})
    spy = out["SPY"]
    assert spy["interior_filled"] == 1
    assert spy["equity"][2] == pytest.approx(1.01), "2 Sep carries 1 Sep's close"
    assert spy["equity"][3] == pytest.approx(1.03)


def test_blend_leg_uses_the_engine_based_spy(yf_frame):
    export = _export(["2026-08-31", "2026-09-01", "2026-09-02"], [100.0, 101.0, 102.0])
    out, _, _ = bmk.build_benchmarks(MODEL_DATES, _reg(), LIVE_DATES,
                                     engine_files={"benchmark_spy.json": export})
    bal = out["BAL6040"]
    spy = pd.Series([1.0, 1.01, 1.02, 1.02 * 51.5 / 51.0, 1.02 * 52.0 / 51.0])
    ief = pd.Series([90.0, 90.0, 90.9, 90.9, 91.8])
    rets = 0.6 * spy.pct_change().fillna(0) + 0.4 * ief.pct_change().fillna(0)
    expected = (1 + rets).cumprod()
    assert bal["equity"] == pytest.approx(list(expected / expected.iloc[0]), abs=1e-6)
    assert bal["asOf"] == "2026-09-04" and "SPY: engine export" in bal["source"]


def test_blend_ends_at_its_shortest_leg(monkeypatch):
    dates = pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"])
    frame = pd.DataFrame({"SPY": [50.0, 50.5, 51.0, 51.5, 52.0],
                          "IEF": [90.0, 90.0, 90.9, 90.9, np.nan]}, index=dates)
    monkeypatch.setattr(bmk, "_download", _fake_download(frame))
    export = _export(["2026-08-31", "2026-09-01", "2026-09-02"], [100.0, 101.0, 102.0])
    out, _, _ = bmk.build_benchmarks(MODEL_DATES, _reg(), LIVE_DATES,
                                     engine_files={"benchmark_spy.json": export})
    assert out["SPY"]["asOf"] == "2026-09-04"
    assert out["BAL6040"]["asOf"] == "2026-09-03" and out["BAL6040"]["equity"][-1] is None


def test_missing_export_falls_back_to_yfinance_and_says_so(yf_frame):
    out, ok, note = bmk.build_benchmarks(MODEL_DATES, _reg(blend=False), LIVE_DATES,
                                         engine_files={})
    assert ok and "yfinance fallback" in note
    spy = out["SPY"]
    assert spy["basis"] == bmk.YF_BASIS and "engine export benchmark_spy.json unavailable" in spy["source"]
    assert spy["equity"] == pytest.approx([1.0, 1.01, 1.02, 1.03, 1.04])


def test_plain_yfinance_benchmark_keeps_its_own_tail(monkeypatch):
    dates = pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"])
    frame = pd.DataFrame({"QQQ": [10.0, 10.1, 10.2, 10.3]}, index=dates)
    monkeypatch.setattr(bmk, "_download", _fake_download(frame))
    reg = {"benchmarks": {"QQQ": {"label": "NASDAQ-100", "type": "yfinance", "ticker": "QQQ"}}}
    out, ok, _ = bmk.build_benchmarks(MODEL_DATES, reg, LIVE_DATES)
    assert ok and out["QQQ"]["asOf"] == "2026-09-03" and out["QQQ"]["equity"][-1] is None
    assert out["QQQ"]["source"] == "yfinance" and out["QQQ"]["basis"] == bmk.YF_BASIS


def test_registry_contract_pins_spy_to_the_engine_export():
    reg = load_registry("multi-strategy-portfolio")
    spy = reg["benchmarks"]["SPY"]
    assert spy["type"] == "engine" and spy["file"] == "benchmark_spy.json" and spy["ticker"] == "SPY"
    assert "benchmark_spy.json" in reg["source"]["files"], \
        "the export must be a REQUIRED source: a missing file stops the build, it does not fall back silently"
    assert reg["freshness"]["benchmark_sessions"] >= 0


def test_engine_series_rejects_empty_or_hollow_exports():
    assert bmk.engine_series(None) is None
    assert bmk.engine_series({"dates": [], "closes": []}) is None
    s = bmk.engine_series({"dates": ["2026-09-02", "2026-09-01", "2026-09-01"],
                           "closes": [102.0, np.nan, 101.0]})
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-09-01", "2026-09-02"]
    assert list(s.values) == [101.0, 102.0]


# --- tail wait (2026-09-09) ------------------------------------------------
# The 2026-09-08 build fetched at 01:30 UTC, before the vendor posted that
# session's US bar (it appeared by 02:03), and published a 2026-09-08 NAV
# against a 2026-09-04 benchmark. The fetch now waits inside a bounded budget
# rather than publishing the mixed basis. Python datetime months are 1-indexed.
WAIT_REG = {"benchmarks": {"SPY": {"label": "S&P 500", "type": "engine", "ticker": "SPY",
                                   "file": "benchmark_spy.json", "default": True},
                           "STI": {"label": "STI", "type": "yfinance", "ticker": "^STI"}}}


def _built(spy_asof, sti_asof="2026-09-09"):
    return {"SPY": {"asOf": spy_asof}, "STI": {"asOf": sti_asof}}


def _builder(asofs):
    """A fetch that returns the next as-of each time it is called."""
    seq, calls = list(asofs), []

    def build(model_dates, registry, live_dates, engine_files):
        calls.append(1)
        return _built(seq[min(len(calls) - 1, len(seq) - 1)]), True, "ok"
    build.calls = calls
    return build


def test_engine_bench_lag_measures_only_the_engine_curve():
    # 2026-09-07 is Labor Day, so 09-04 -> 09-08 is ONE session, not two.
    assert bmk.engine_bench_lag(_built("2026-09-04"), WAIT_REG, "2026-09-08") == 1
    assert bmk.engine_bench_lag(_built("2026-09-08"), WAIT_REG, "2026-09-08") == 0
    # A foreign-market curve running a session AHEAD must not trigger a wait.
    assert bmk.engine_bench_lag(_built("2026-09-08", "2026-09-04"), WAIT_REG, "2026-09-08") == 0
    # Nothing to judge against, or no engine benchmark: no wait.
    assert bmk.engine_bench_lag(_built("2026-09-04"), WAIT_REG, None) == 0
    assert bmk.engine_bench_lag(_built("2026-09-04"), {"benchmarks": {}}, "2026-09-08") == 0


def test_wait_stops_as_soon_as_the_vendor_bar_lands():
    slept, build = [], _builder(["2026-09-04", "2026-09-04", "2026-09-08"])
    out, ok, note = bmk.build_benchmarks_awaiting_tail(
        MODEL_DATES, WAIT_REG, LIVE_DATES, {}, "2026-09-08",
        attempts=4, sleep_s=360, builder=build, sleep=slept.append, log=lambda *_: None)
    assert ok and out["SPY"]["asOf"] == "2026-09-08"
    assert len(build.calls) == 3 and slept == [360, 360]
    assert "waited 12m for the vendor tail" in note and "short" not in note


def test_wait_is_fail_open_when_the_bar_never_lands():
    slept, build = [], _builder(["2026-09-04"])
    out, ok, note = bmk.build_benchmarks_awaiting_tail(
        MODEL_DATES, WAIT_REG, LIVE_DATES, {}, "2026-09-08",
        attempts=2, sleep_s=60, builder=build, sleep=slept.append, log=lambda *_: None)
    # Publishes anyway, with the short tail intact for the health gate to row.
    assert ok and out["SPY"]["asOf"] == "2026-09-04"
    assert len(build.calls) == 3 and slept == [60, 60]
    assert "still 1 session(s) short" in note


def test_a_fresh_build_never_waits_and_attempts_zero_is_the_old_behaviour():
    slept, build = [], _builder(["2026-09-08"])
    _, _, note = bmk.build_benchmarks_awaiting_tail(
        MODEL_DATES, WAIT_REG, LIVE_DATES, {}, "2026-09-08",
        attempts=4, sleep_s=360, builder=build, sleep=slept.append, log=lambda *_: None)
    assert len(build.calls) == 1 and slept == [] and note == "ok"

    slept, build = [], _builder(["2026-09-04"])
    bmk.build_benchmarks_awaiting_tail(
        MODEL_DATES, WAIT_REG, LIVE_DATES, {}, "2026-09-08",
        attempts=0, sleep_s=360, builder=build, sleep=slept.append, log=lambda *_: None)
    assert len(build.calls) == 1 and slept == []


def test_a_failed_fetch_is_not_something_waiting_can_mend():
    slept, calls = [], []

    def build(*_a):
        calls.append(1)
        return {}, False, "yfinance fetch failed: boom"
    out, ok, note = bmk.build_benchmarks_awaiting_tail(
        MODEL_DATES, WAIT_REG, LIVE_DATES, {}, "2026-09-08",
        attempts=4, sleep_s=360, builder=build, sleep=slept.append, log=lambda *_: None)
    assert not ok and len(calls) == 1 and slept == [] and "boom" in note


def test_wait_crosses_a_year_boundary_on_the_true_session_calendar():
    # 2027-01-01 is a New Year holiday: 2026-12-31 -> 2027-01-04 is one session.
    assert bmk.engine_bench_lag(_built("2026-12-31"), WAIT_REG, "2027-01-04") == 1
    assert bmk.engine_bench_lag(_built("2027-01-04"), WAIT_REG, "2027-01-04") == 0
    # Month boundary: 2026-09-30 -> 2026-10-01 is one session.
    assert bmk.engine_bench_lag(_built("2026-09-30"), WAIT_REG, "2026-10-01") == 1


def test_the_wait_ceiling_stays_below_the_workflow_timeout():
    """A wait longer than the job's timeout would convert an intermittent warn
    into an intermittent FAIL — the one outcome worse than the mixed basis."""
    import re

    from config import BENCH_TAIL_WAIT_ATTEMPTS, BENCH_TAIL_WAIT_SECONDS
    wf = (ROOT / ".github" / "workflows" / "daily_monitor.yml").read_text(encoding="utf-8")
    timeout_s = int(re.search(r"^\s*timeout-minutes:\s*(\d+)", wf, re.M).group(1)) * 60
    ceiling = BENCH_TAIL_WAIT_ATTEMPTS * BENCH_TAIL_WAIT_SECONDS
    assert ceiling + 600 <= timeout_s, (
        f"wait ceiling {ceiling}s + 10m of build leaves no room in a {timeout_s}s timeout")
