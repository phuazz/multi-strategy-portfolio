import json

import numpy as np
import pandas as pd
import pytest
import requests

import sgd_fx
from benchmarks import observed_on_axis


def observation(day):
    return {"date": day, "DEXSIUS": "1.3789", "EXR.D.USD.EUR.SP00.A": "1.1171",
            "EXR.D.SGD.EUR.SP00.A": "1.5399"}


@pytest.mark.parametrize("start", ["2019-04-30", "2019-12-31"])
def test_interior_fixing_is_archived_and_primary_wins(monkeypatch, tmp_path, start):
    # Python calendar months are 1-indexed. Exercise month and year boundaries.
    idx = pd.date_range(start, periods=4)
    day = idx[1].date().isoformat()
    prices = pd.Series(1., index=idx)
    raw = pd.Series([.71, np.nan, .73, np.nan], index=idx)
    def check():
        fx, info = observed_on_axis(raw, idx, None)
        used = sgd_fx.recover_history(fx, info, prices, tmp_path)
        assert info["missing_dates"] == [idx[-1].date().isoformat()]
        assert info["source_dates"][1] == day and pd.isna(fx.iloc[-1])
        return used, fx
    monkeypatch.setattr(sgd_fx, "_fetch", lambda days: {d: observation(d) for d in days})
    used, fx = check()
    assert fx.iloc[1] == pytest.approx(1 / 1.3789) and set(used) == {day}
    assert json.loads((tmp_path / f"{day}.json").read_text()) == observation(day)
    monkeypatch.setattr(sgd_fx, "_fetch", lambda *_: pytest.fail("unnecessary network call"))
    assert check()[0] == used
    raw.iloc[1] = .72
    used, fx = check()
    assert not used and fx.iloc[1] == .72


@pytest.mark.parametrize("key,value", [("date", "2019-05-21"), ("DEXSIUS", None),
                         ("DEXSIUS", "NaN"), ("EXR.D.SGD.EUR.SP00.A", 0),
                         ("EXR.D.USD.EUR.SP00.A", 1.5)])
def test_unconfirmed_observations_are_rejected(key, value):
    day = "2019-05-22"
    record = observation(day)
    record[key] = value
    assert sgd_fx._quote(day, record) is None


def test_source_outage_and_missing_native_price_keep_gaps(monkeypatch, tmp_path):
    idx = pd.date_range("2019-05-20", periods=4)
    raw = pd.Series([.72, np.nan, np.nan, .73], index=idx)
    fx, info = observed_on_axis(raw, idx, None)
    native = pd.Series([1, 1, np.nan, 1], index=idx)
    def outage(days):
        assert days == ["2019-05-21"]
        raise requests.Timeout()
    monkeypatch.setattr(sgd_fx, "_fetch", outage)
    assert not sgd_fx.recover_history(fx, info, native, tmp_path)
    assert info["missing_dates"] == ["2019-05-21", "2019-05-22"]


def test_fetch_rejects_duplicate_or_wrong_ecb_series(monkeypatch):
    day = "2019-05-22"
    leg = {"KEY": "EXR.D.SGD.EUR.SP00.A", "OBS_STATUS": "A", "UNIT_MULT": "0",
           "TIME_PERIOD": day, "CURRENCY": "SGD", "OBS_VALUE": "1.5399"}
    def rows(url, params):
        if url == sgd_fx.FRED:
            return [{"observation_date": day, "DEXSIUS": "1.3789"}]
        return [leg, leg, dict(leg, CURRENCY="USD")]
    monkeypatch.setattr(sgd_fx, "_rows", rows)
    record = sgd_fx._fetch([day])[day]
    assert record["EXR.D.SGD.EUR.SP00.A"] is None and record["EXR.D.USD.EUR.SP00.A"] is None
