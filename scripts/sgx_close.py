"""Recover the Singapore comparator's recent missing native close.

Both feeds must identify the same listing, session and unadjusted SGD price.
Python and pandas calendar months are 1-indexed.
"""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

from config import DOCS_DATA_DIR

SYMBOL = "ES3.SI"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/ES3.SI"
EXCHANGE = "https://api.sgx.com/securities/v1.1"
STORAGE = DOCS_DATA_DIR / "sgx-observations"


def _get(url, params):
    response = requests.get(url, params=params, timeout=(4, 8),
                            headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


def capture(day, previous, following, schedule, anchor, now):
    charts = []
    for span in ("1d", "5d"):
        data = _get(CHART, {"range": span, "interval": "1d", "events": "div,splits,capitalGains"})
        chart, = data["chart"]["result"]
        meta = chart["meta"]
        if (meta["symbol"], meta["fullExchangeName"], meta["currency"],
                meta["exchangeTimezoneName"], meta["dataGranularity"]) != (
                SYMBOL, "SES", "SGD", "Asia/Singapore", "1d"):
            raise ValueError("Yahoo listing mismatch")
        charts.append(chart)
    single, history = charts
    meta = single["meta"]
    stamp = pd.Timestamp(meta["regularMarketTime"], unit="s", tz="UTC")
    quote_day = stamp.tz_convert("Asia/Singapore").date()
    if quote_day not in (day.date(), following.date()) or stamp > now:
        raise ValueError("Yahoo quote is outside the required sessions")
    if single["timestamp"] != [meta["regularMarketTime"]]:
        raise ValueError("Yahoo daily bar and quote time differ")

    dates = pd.to_datetime(history["timestamp"], unit="s", utc=True).tz_convert("Asia/Singapore").date
    indices = np.flatnonzero(dates == previous.date())
    if len(indices) != 1:
        raise ValueError("missing daily basis anchor")
    idx = int(indices[0])
    quotes, = history["indicators"]["quote"]
    adjusted, = history["indicators"]["adjclose"]
    if quotes["close"][idx] != anchor or adjusted["adjclose"][idx] != anchor:
        raise ValueError("adjustment basis changed at the preceding session")
    for events in history.get("events", {}).values():
        for event in events.values():
            ex_date = pd.Timestamp(event["date"], unit="s", tz="UTC").tz_convert("Asia/Singapore").date()
            if previous.date() <= ex_date <= quote_day:
                raise ValueError("corporate action across the valuation")

    snapshot = _get(EXCHANGE, {"excludetypes": "bonds", "params": "nc,cur,lt,c,pv"})
    if str(snapshot["meta"]["code"]) != "200":
        raise ValueError("SGX quote unavailable")
    row, = [r for r in snapshot["data"]["prices"] if r["nc"] == "ES3"]
    sgx_time = datetime.strptime(row["trading_time"], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    if (row["type"] != "etfs" or row["cur"] != "SGD" or sgx_time > now or
            pd.Timestamp(sgx_time).tz_convert("Asia/Singapore").date() != quote_day):
        raise ValueError("SGX listing or quote session differs")
    if quote_day == day.date():
        close_time = schedule.loc[day, "market_close"]
        price = meta["regularMarketPrice"]
        quote, = single["indicators"]["quote"]
        adj, = single["indicators"]["adjclose"]
        if (min(stamp, sgx_time) < close_time or single.get("events")
                or float(np.float32(meta["chartPreviousClose"])) != anchor
                or quote["close"] != [float(np.float32(price))]
                or adj["adjclose"] != quote["close"] or not quote["volume"][0] > 0):
            raise ValueError("single-session adjusted close is unconfirmed")
        sgx = row["lt"]
        field = "closing daily bar"
    else:
        if min(stamp, sgx_time) < schedule.loc[following, "market_open"]:
            raise ValueError("following SGX session has not opened")
        price, sgx = meta["chartPreviousClose"], row["pv"]
        if Decimal(str(row["lt"])) - Decimal(str(row["c"])) != Decimal(str(sgx)):
            raise ValueError("SGX previous close does not reconcile to the day's change")
        field = "previous close"
    if Decimal(str(sgx)) != Decimal(str(price)) or not np.isfinite(float(price)) or price <= 0:
        raise ValueError("SGX and Yahoo prices differ")
    return {"symbol": SYMBOL, "currency": "SGD", "session": str(day.date()),
            "previous_session": str(previous.date()), "previous_adjusted": float(anchor),
            "close": float(np.float32(price)), "sgx_price": sgx, "yahoo_price": price,
            "field": field, "sgx_quote_utc": sgx_time.isoformat(), "yahoo_quote_utc": stamp.isoformat(),
            "acquired_at": now.isoformat(), "sgx_source": EXCHANGE, "yahoo_source": CHART}


def recover_tail(series, target, calendar, *, directory=None, now=None):
    directory = STORAGE if directory is None else Path(directory)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    schedule = calendar.schedule(target - pd.Timedelta(days=15), target + pd.Timedelta(days=15))
    required = schedule.index[schedule.index <= target][-1]
    observations = {}
    result = series.copy()
    files = sorted(directory.glob("*.json"))
    dates = {pd.Timestamp(p.stem) for p in files if str(series.index.min().date()) <= p.stem <= str(target.date())}
    for day in sorted(dates | {required}):
        if day in result.dropna().index:
            continue
        nearby = schedule if schedule.index[0] < day < schedule.index[-1] else calendar.schedule(
            day - pd.Timedelta(days=15), day + pd.Timedelta(days=15))
        loc = nearby.index.get_loc(day)
        previous, following = nearby.index[loc - 1], nearby.index[loc + 1]
        anchor = result.get(previous)
        if anchor is None or not np.isfinite(anchor) or anchor <= 0:
            continue
        path = directory / (str(day.date()) + ".json")
        try:
            if path.exists():
                e = json.loads(path.read_text(encoding="utf-8"))
            else:
                if not nearby.loc[day, "market_close"] <= now <= nearby.loc[following, "market_close"] + pd.Timedelta(days=1):
                    continue
                e = capture(day, previous, following, nearby, anchor, now)
                directory.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
                    tmp = Path(f.name)
                    json.dump(e, f, indent=2, allow_nan=False)
                    f.write("\n")
                try:
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)
            if ((e["symbol"], e["currency"], e["session"], e["previous_session"]) !=
                    (SYMBOL, "SGD", str(day.date()), str(previous.date()))
                    or e["previous_adjusted"] != anchor or pd.Timestamp(e["acquired_at"]) > now
                    or not 0 < e["close"] == float(np.float32(e["yahoo_price"]))
                    or e["yahoo_price"] != e["sgx_price"]):
                raise ValueError("archived close or adjustment basis differs")
            result.loc[day] = e["close"]
            observations[str(day.date())] = e
        except (requests.RequestException, KeyError, TypeError, ValueError, IndexError, InvalidOperation) as exc:
            print(f"  {SYMBOL}: could not verify {day.date()} close: {exc}")
    return result.sort_index(), observations
