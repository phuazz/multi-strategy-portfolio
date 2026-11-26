"""Read-only stress and gap diagnostics for public paper allocations.

Weights, price changes and NAV contributions are fractions. Python/pandas
calendar months are 1-indexed. No broker or private-book adapter is provided.
"""
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from config import TRADING_DAYS_PER_YEAR

POLICIES = Path(__file__).resolve().parents[1] / "portfolios" / "risk"
UNRESOLVED = "Unresolved sleeve"


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def load_policy(portfolio_id):
    path = POLICIES / f"{portfolio_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def instrument_map(policy):
    if policy["mode"] != "shadow":
        raise ValueError("Only shadow policies are supported")
    by_ticker = {}
    groups = policy["groups"]
    for group, tickers in groups.items():
        for ticker in tickers:
            if ticker in by_ticker:
                raise ValueError(f"Duplicate scenario mapping: {ticker}")
            by_ticker[ticker] = group
    names = set()
    for scenario in policy["scenarios"]:
        prices = scenario["prices"]
        unpriced = set(scenario.get("unpriced", []))
        flat = set(scenario.get("flat", []))
        assigned = set(prices) | unpriced | flat
        if assigned - groups.keys() or len(assigned) != len(prices) + len(unpriced) + len(flat):
            raise ValueError(f"Ambiguous or unknown bucket in {scenario['name']}")
        if scenario["name"] in names or not all(number(v) and v >= -1 for v in prices.values()):
            raise ValueError(f"Invalid scenario {scenario['name']}")
        names.add(scenario["name"])
    gap = policy["gap"]
    for values in (gap["adverseMoves"], gap["groupCaps"]):
        if values.keys() - groups.keys():
            raise ValueError("Unknown gap bucket")
    budgets = gap["lossBudgets"]
    for values in (gap["adverseMoves"], gap["groupCaps"], gap["positionCaps"],
                   {"portfolio": budgets["portfolio"]}, budgets["assetClass"],
                   budgets["instrumentType"], budgets["sleeve"]):
        if not all(number(v) and 0 < v <= 1 for v in values.values()):
            raise ValueError("Invalid gap-policy fraction")
    return by_ticker


def anchored_legs(live, registry, overlay):
    """Reconstruct shared holdings from same-anchor sleeve books and the live gate."""
    allocations = {}
    legs = defaultdict(dict)
    state = live.get("regime_state")
    if state not in ("RISK_ON", "RISK_OFF") or not isinstance(live.get("eem_tilt_active"), bool):
        return {}, {}
    gate = overlay["gate_parameters"]["derisk_fraction"] if state == "RISK_OFF" else 0
    key = "alloc_tilt" if live["eem_tilt_active"] else "alloc"
    for sleeve, cfg in registry["sleeves"].items():
        alloc = cfg.get(key, 0) * (1 - gate)
        allocations[sleeve] = alloc
        if not alloc:
            continue
        if sleeve == "TILT":
            ticker = overlay.get("phase22_eem_tilt", {}).get("parameters", {}).get("eem_ticker", "EEM")
            legs[ticker][sleeve] = alloc
            continue
        data = live.get("sleeve_extensions", {}).get(cfg["key"], {})
        weights = data.get("weights")
        if (not live.get("anchor_date") or data.get("anchor_date") != live["anchor_date"]
                or not isinstance(weights, dict) or not weights
                or not all(number(w) and w >= 0 for w in weights.values())):
            continue
        total = sum(weights.values())
        if total > 1.001:
            continue
        # Match upstream normalisation of four-decimal within-sleeve weights.
        divisor = total if abs(total - 1) <= .001 else 1
        for ticker, weight in weights.items():
            if weight:
                legs[ticker][sleeve] = alloc * weight / divisor
        if total < .999:
            reserve = overlay["gate_parameters"]["fallback_ticker"]
            legs[reserve][sleeve] = legs[reserve].get(sleeve, 0) + alloc * (1 - total)
    if gate:
        allocations["DEFENSIVE"] = gate
        legs[overlay["gate_parameters"]["fallback_ticker"]]["DEFENSIVE"] = gate
    return legs, allocations


def sleeve_weights(row, legs):
    """Use reconciled absolute construction legs, never normalise a material mismatch."""
    weight = row["weight"]
    if legs is not None:
        parts = legs.get(row["ticker"], {})
        total = sum(parts.values())
        if total and abs(total - weight) <= (len(parts) + 1) * 0.00005:
            return {key: value * weight / total for key, value in parts.items()}
        if 0 < total < weight:
            return {**parts, UNRESOLVED: weight - total}
        return {UNRESOLVED: weight}
    if row["sleeve"] == "CASH":
        return {UNRESOLVED: weight}
    legs = row.get("build") or []
    if legs and all(number(x.get("contrib")) and x.get("sleeve") for x in legs):
        parts = defaultdict(float)
        for leg in legs:
            parts[leg["sleeve"]] += leg["contrib"]
        total = sum(parts.values())
        if total and abs(total - weight) <= (len(legs) + 1) * 0.00005:
            return {key: v * weight / total for key, v in parts.items()}
    return {UNRESOLVED: weight}


def stress(rows, scenario):
    by_sleeve, by_factor = defaultdict(float), defaultdict(float)
    positions, missing = [], []
    coverage = {"shocked": 0.0, "flat": 0.0, "unpriced": 0.0}
    hedge_pnl = 0.0
    hedge_known = True
    for row in rows:
        group = row["group"]
        if group not in scenario["prices"] and group not in scenario.get("flat", []):
            missing.append(row["ticker"])
            coverage["unpriced"] += abs(row["weight"])
            if group is None or row.get("isHedge"):
                hedge_known = False
            continue
        shock = scenario["prices"].get(group, 0)
        coverage["shocked" if shock else "flat"] += abs(row["weight"])
        pnl = row["weight"] * shock
        if row.get("isHedge"):
            hedge_pnl += pnl
        positions.append({"ticker": row["ticker"], "pnl": pnl, "factor": group})
        by_factor[group] += pnl
        for sleeve, weight in row["parts"].items():
            by_sleeve[sleeve] += weight * shock
    covered = sum(p["pnl"] for p in positions)
    return {**scenario, "total": None if missing else covered, "coveredPnl": covered,
            "coverage": coverage, "missing": missing, "positions": sorted(positions, key=lambda p: p["pnl"]),
            "sleeves": dict(by_sleeve), "factors": dict(by_factor),
            "hedgePnl": hedge_pnl if hedge_known else None}


def gap_limits(rows, policy, allocations):
    gross = defaultdict(float)
    for row in rows:
        gross[row["group"]] += abs(row["weight"])
    limits = []
    for row in rows:
        group, size = row["group"], abs(row["weight"])
        shock = policy["adverseMoves"].get(group)
        item = {"ticker": row["ticker"], "weight": row["weight"], "shock": shock,
                "loss": None, "cap": None, "review": None, "constraints": {}, "binding": None}
        limits.append(item)
        if shock is None:
            continue
        budgets = policy["lossBudgets"]
        applicable = [budgets["portfolio"]]
        for axis, key in (("assetClass", row["assetClass"]), ("instrumentType", row["kind"])):
            if key in budgets[axis]:
                applicable.append(budgets[axis][key])
        # Each sleeve budget is a per-name budget, applied to that sleeve's share.
        for sleeve, allocation in row["parts"].items():
            if sleeve in budgets["sleeve"] and allocation:
                applicable.append(budgets["sleeve"][sleeve] * size / abs(allocation))
        constraints = {"gap": min(applicable) / shock}
        for sleeve, allocation in row["parts"].items():
            if sleeve in allocations and allocation:
                constraints["sleeve " + sleeve] = allocations[sleeve] * size / abs(allocation)
        if row["ticker"] in policy["positionCaps"]:
            constraints["concentration"] = policy["positionCaps"][row["ticker"]]
        if group in policy["groupCaps"]:
            constraints["factor headroom"] = max(0, policy["groupCaps"][group] - (gross[group] - size))
        item.update(loss=size * shock, constraints=constraints, cap=min(constraints.values()),
                    binding=min(constraints, key=constraints.get),
                    review=size > min(constraints.values()) + .000005)
        if UNRESOLVED in row["parts"]:
            # A proven breach survives incomplete ownership. An incomplete pass
            # cannot establish either a ceiling or clearance to increase size.
            item.update(cap=None, binding="Sleeve ownership incomplete",
                        review=True if item["review"] else None)
    return limits


def shared_proxies(rows, gaps):
    """Common symmetric price gap on signed weights, grouped by execution proxy."""
    groups = defaultdict(list)
    for row, gap in zip(rows, gaps, strict=True):
        if row.get("tradeAs"):
            groups[row["tradeAs"]].append(gap)
    output = []
    for proxy, positions in groups.items():
        if len(positions) < 2:
            continue
        shocks = {p["shock"] for p in positions}
        shock = shocks.pop() if len(shocks) == 1 else None
        net = sum(p["weight"] for p in positions)
        output.append({"proxy": proxy, "tickers": [p["ticker"] for p in positions],
                       "net": net, "shock": shock, "loss": abs(net)*shock if shock is not None else None})
    return output


def historical_path(equity):
    """Most recent 252 valid close-to-close NYSE returns; never bridge a gap."""
    dates, nav = list(equity["dates"]), list(equity["model"])
    extension = equity.get("live") or {}
    dates.extend(extension.get("dates", []))
    nav.extend(extension.get("equity", []))
    result = {"asOf": dates[-1] if dates else None, "observations": 0, "metrics": None}
    if not dates or len(dates) != len(nav):
        return result
    index = pd.to_datetime(dates)
    if index.has_duplicates or not index.is_monotonic_increasing:
        return result
    series = pd.Series(nav, index=index, dtype=float)
    sessions = mcal.get_calendar("NYSE").schedule(start_date=index[0], end_date=index[-1]).index
    valid_nav = series.where((series > 0) & np.isfinite(series)).reindex(sessions)
    daily = valid_nav.pct_change(fill_method=None)
    sample = daily.dropna().tail(TRADING_DAYS_PER_YEAR)
    result["observations"] = len(sample)
    if len(sample) < TRADING_DAYS_PER_YEAR or sample.index[-1] != index[-1]:
        return result
    losses = np.sort(-sample.to_numpy())[::-1]
    count = len(losses)
    tail = count * 0.025
    whole = int(tail)
    result.update(start=str(sessions[sessions.get_loc(sample.index[0]) - 1].date()),
                  excluded=int(daily.loc[sample.index[0]:].isna().sum()),
                  metrics={"vol": float(sample.std() * math.sqrt(TRADING_DAYS_PER_YEAR)),
                           "var95": float(losses[math.ceil(.05 * count) - 1]),
                           "var99": float(losses[math.ceil(.01 * count) - 1]),
                           "es975": float((losses[:whole].sum() + (tail-whole)*losses[whole])/tail)})
    return result


def build(dataset, policy, *, legs=None, allocations=None):
    meta = dataset["meta"]
    if meta.get("status") != "paper" or meta.get("base_currency") != "USD":
        return {"status": "unavailable", "reason": "Requires public USD paper-model data."}
    by_ticker = instrument_map(policy)
    rows = []
    seen = set()
    for raw in dataset["weights"]["rows"]:
        ticker, weight = raw.get("ticker"), raw.get("weight")
        if not ticker or ticker in seen or not number(weight):
            return {"status": "unavailable", "reason": "Missing or duplicate instrument or invalid weight."}
        seen.add(ticker)
        if weight == 0:
            continue
        if not isinstance(raw.get("isHedge", False), bool):
            return {"status": "unavailable", "reason": "Invalid hedge designation."}
        # Only listed, fully funded instruments are covered. A future adapter
        # must supply contract economics for derivatives and leveraged products.
        kind = raw.get("instrumentType", "spot" if raw.get("assetClass") == "Crypto" else "fund")
        group = by_ticker.get(ticker) if kind in ("fund", "stock", "spot") else None
        rows.append({**raw, "kind": kind, "group": group, "parts": sleeve_weights(raw, legs)})
    if (not rows or not meta.get("portfolio_anchor") or
            abs(sum(r["weight"] for r in rows) - 1) > len(rows) * .000005 + 1e-10):
        return {"status": "unavailable", "reason": "Undated book or weights do not reconcile to NAV."}
    scenarios = [stress(rows, s) for s in policy["scenarios"]]
    regime = dataset.get("regime", {})
    gate_state = regime.get("live_state")
    fraction = regime.get("derisk_fraction")
    reserve = regime.get("fallback_ticker")
    reserve_group = by_ticker.get(reserve)
    for scenario in scenarios:
        if (scenario.get("compareDefensiveGate") and gate_state == "RISK_ON"
                and scenario["total"] is not None and number(fraction) and 0 < fraction <= 1
                and reserve_group in scenario["prices"]):
            reserve_return = scenario["prices"][reserve_group]
            scenario["gateComparison"] = {"fraction": fraction, "reserve": reserve,
                                          "total": (1-fraction)*scenario["total"] + fraction*reserve_return}
    complete = [s for s in scenarios if s["total"] is not None]
    worst = min(complete, key=lambda x: x["total"]) if complete else None
    known = all(r["group"] for r in rows)
    factors = defaultdict(float)
    for r in rows:
        factors[r["group"] or "unmapped"] += abs(r["weight"])
    net = sum(r["weight"] for r in rows) if known else None
    gaps = gap_limits(rows, policy["gap"], allocations or {})
    return {"status": "shadow", "version": policy["version"], "anchor": meta["portfolio_anchor"],
            "history": historical_path(dataset["equity"]), "gross": sum(factors.values()) if known else None,
            "net": net, "preHedgeNet": sum(r["weight"] for r in rows if not r.get("isHedge")) if known else None,
            "grossByBucket": dict(factors),
            "equityNet": sum(r["weight"] for r in rows if r["assetClass"] == "Equity") if known else None,
            "worst": {"name": worst["name"], "total": worst["total"]} if worst else None,
            "gateState": gate_state, "complete": len(complete), "scenarios": scenarios,
            "gaps": gaps, "sharedProxies": shared_proxies(rows, gaps)}
