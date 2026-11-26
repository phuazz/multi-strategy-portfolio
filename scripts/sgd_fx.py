"""Recover interior SGD/USD benchmark gaps from corroborated official fixings."""
import csv
import io
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import requests

from config import DOCS_DATA_DIR


FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+SGD.EUR.SP00.A"
ARCHIVE = DOCS_DATA_DIR / "sgd-fx-observations"
# Different fixing times. Larger discrepancies require individual review.
MAX_DIFFERENCE_BPS = 10


def _rows(url, params):
    response = requests.get(url, params=params, timeout=(4, 10))
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))


def _unique(rows, key, value):
    result = {}
    for row in rows:
        k = key(row)
        # Duplicate observations are ambiguous, even if rounded values agree.
        result[k] = None if k in result else row[value]
    return result


def _fetch(days):
    start, end = min(days), max(days)
    fed = _unique(_rows(FRED, {"id": "DEXSIUS", "cosd": start, "coed": end}),
                  lambda r: r["observation_date"], "DEXSIUS")
    rows = _rows(ECB, {"startPeriod": start, "endPeriod": end, "format": "csvdata"})
    legs = _unique((r for r in rows if r["KEY"] == f"EXR.D.{r['CURRENCY']}.EUR.SP00.A"
                    and r["OBS_STATUS"] == "A" and r["UNIT_MULT"] == "0"),
                   lambda r: (r["TIME_PERIOD"], r["CURRENCY"]), "OBS_VALUE")
    return {day: {"date": day, "DEXSIUS": fed.get(day),
                  "EXR.D.USD.EUR.SP00.A": legs.get((day, "USD")),
                  "EXR.D.SGD.EUR.SP00.A": legs.get((day, "SGD"))} for day in days}


def _quote(day, record):
    if not isinstance(record, dict) or record.get("date") != day:
        return None
    try:
        sgd, eur_usd, eur_sgd = (float(record[k]) for k in
                                 ("DEXSIUS", "EXR.D.USD.EUR.SP00.A", "EXR.D.SGD.EUR.SP00.A"))
    except (KeyError, ValueError, TypeError):
        return None
    if not all(math.isfinite(x) and x > 0 for x in (sgd, eur_usd, eur_sgd)):
        return None
    difference = abs(eur_usd / eur_sgd * sgd - 1) * 10000
    if not math.isfinite(difference) or difference > MAX_DIFFERENCE_BPS:
        return None
    return {"usdPerSgd": 1 / sgd, "fedSgdPerUsd": sgd, "ecbUsdPerEur": eur_usd,
            "ecbSgdPerEur": eur_sgd, "differenceBps": round(difference, 4),
            "basis": "Federal Reserve H.10, New York noon buying rate, inverted",
            "fedSource": f"{FRED}?id=DEXSIUS&cosd={day}&coed={day}",
            "ecbSource": f"{ECB}?startPeriod={day}&endPeriod={day}&format=csvdata"}


def recover_history(fx, info, native, directory=None):
    """Use exact dates strictly inside the observed primary FX series on the NAV axis."""
    valid = fx.dropna()
    if valid.empty:
        return {}
    days = [d for d in info["missing_dates"] if valid.index[0] < pd.Timestamp(d) < valid.index[-1]
            and pd.notna(native.loc[d])]
    directory = ARCHIVE if directory is None else Path(directory)
    records, missing = {}, []
    for day in days:
        try:
            records[day] = json.loads((directory / f"{day}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if _quote(day, records.get(day)) is None:
            missing.append(day)
    if missing:
        try:
            records.update(_fetch(missing))
        except (requests.RequestException, ValueError, KeyError, csv.Error):
            pass  # Keep unresolved dates visible in the existing health check.
    recovered = {}
    for day in days:
        quote = _quote(day, records.get(day))
        if quote is None:
            continue
        if day in missing:
            directory.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile("w", dir=directory, encoding="utf-8", delete=False) as tmp:
                json.dump(records[day], tmp, indent=2, allow_nan=False)
                tmp.write("\n")
            Path(tmp.name).replace(directory / f"{day}.json")
        fx.loc[day] = quote["usdPerSgd"]
        info["source_dates"][fx.index.get_loc(day)] = day
        recovered[day] = quote
    info["missing_dates"] = [day for day in info["missing_dates"] if day not in recovered]
    return recovered
