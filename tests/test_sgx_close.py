"""SGX corroboration, independent vendor retries and calendar boundaries."""
from datetime import datetime

import pandas as pd
import pytest

import benchmarks
import sgx_close
import sync_source


@pytest.mark.parametrize("anchor,day,next_session", [
    ("2026-10-29","2026-10-30","2026-11-02"),
    ("2025-12-30","2025-12-31","2026-01-02"),
])
def test_exchange_corroboration_and_replay(tmp_path, monkeypatch, anchor, day, next_session):
    # Python and pandas months are 1-indexed. All clocks use the listing's session.
    target = pd.Timestamp(day)
    stamp = pd.Timestamp(next_session + "T03:00Z")
    now = stamp + pd.Timedelta(minutes=2)
    meta = dict(symbol="ES3.SI", fullExchangeName="SES", currency="SGD", exchangeTimezoneName="Asia/Singapore",
                dataGranularity="1d", regularMarketTime=int(stamp.timestamp()), chartPreviousClose=5.009)
    before = pd.Timestamp(anchor + "T01:00Z")
    history = dict(meta=meta, timestamp=[int(before.timestamp())],
                   indicators={"quote":[{"close":[5.]}], "adjclose":[{"adjclose":[5.]}]})
    one = dict(meta=meta, timestamp=[int(stamp.timestamp())])
    row = dict(type="etfs",cur="SGD",nc="ES3",pv=5.009,lt=5.1,c=.091,trading_time=stamp.strftime("%Y%m%d_%H%M%S"))
    def get(url, params):
        if url == sgx_close.EXCHANGE:
            return {"meta":{"code":"200"}, "data":{"prices":[row]}}
        return {"chart":{"result":[one if params["range"] == "1d" else history]}}
    monkeypatch.setattr(sgx_close,"_get",get)
    original = pd.Series([5.], index=pd.to_datetime([anchor]))
    cal = benchmarks._calendar("XSES")
    def run():
        return sgx_close.recover_tail(original, target, cal, directory=tmp_path, now=now)

    row["pv"] = 5.01
    assert not run()[1]
    assert not list(tmp_path.iterdir())
    row["pv"] = 5.009
    history["events"] = {"dividends":{"ex":{"date":int(target.tz_localize("Asia/Singapore").timestamp())}}}
    assert not run()[1]
    history.pop("events")
    one["meta"]["currency"] = "USD"
    assert not run()[1]
    one["meta"]["currency"] = "SGD"
    result, evidence = run()
    assert result.loc[target] == evidence[day]["close"]
    assert evidence[day]["sgx_price"] == 5.009
    monkeypatch.setattr(sgx_close,"_get",lambda *args: pytest.fail("unexpected network call"))
    pd.testing.assert_series_equal(result, run()[0])
    original.iloc[0] = 4.9
    assert not run()[1]
    original.loc[target] = 5.011
    assert run()[0].loc[target] == 5.011


@pytest.mark.parametrize("nav,checked,now", [
    ("2026-10-30","2026-10-31T23:50:00Z","2026-11-01T02:00:00+00:00"),
    ("2025-12-31","2025-12-31T23:50:00Z","2026-01-01T02:00:00+00:00"),
])
def test_retry_only_for_recent_unpriced_benchmark(nav, checked, now):
    instant = datetime.fromisoformat(now)
    data = {"meta":{"live_asOf":nav}, "health":{"checked_at_utc":checked, "feeds":[
        {"feed":"Price / NAV (live_track)", "level":"ok", "asOf":nav},
        {"feed":"Benchmark STI (USD) (valuation)", "versus":nav,"asOf":None}]}}
    assert sync_source.benchmark_retry(data,instant)
    assert not sync_source.benchmark_retry(data,instant + pd.Timedelta(days=4))
    assert not sync_source.benchmark_retry(data,instant - pd.Timedelta(hours=1))
    data["health"]["feeds"][1]["asOf"] = nav
    assert not sync_source.benchmark_retry(data,instant)
