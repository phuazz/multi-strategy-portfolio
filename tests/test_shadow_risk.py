from copy import deepcopy

import pandas as pd
import pytest

import shadow_risk as risk


@pytest.fixture
def policy():
    return risk.load_policy("multi-strategy-portfolio")


def book(*positions):
    return {"meta": {"status": "paper", "portfolio_anchor": "2025-01-03", "base_currency": "USD"},
            "equity": {"dates": [], "model": []},
            "weights": {"rows": [{"ticker": ticker, "weight": weight, "assetClass": "Equity",
                                  "sleeve": "A", "build": [{"sleeve": "A", "contrib": weight}]}
                                 for ticker, weight in positions]}}


def test_signed_shock_reconciliation_and_no_mutation(policy):
    ds = book(("SPY", 1.2), ("QQQ", -.2))
    ds["weights"]["rows"][1]["isHedge"] = True
    before = deepcopy(ds)
    out = risk.build(ds, policy)
    assert ds == before
    assert out["gross"] == pytest.approx(1.4)
    assert out["net"] == pytest.approx(1)
    assert out["preHedgeNet"] == pytest.approx(1.2)
    for s in out["scenarios"]:
        assert sum(x["pnl"] for x in s["positions"]) == pytest.approx(s["coveredPnl"])
        assert sum(s["sleeves"].values()) == pytest.approx(s["coveredPnl"])
        assert sum(s["factors"].values()) == pytest.approx(s["coveredPnl"])
    by_name = {s["name"]: s for s in out["scenarios"]}
    assert by_name["Nasdaq reversal up (dedicated technology funds)"]["total"] == pytest.approx(-.014)
    assert by_name["Nasdaq reversal up (dedicated technology funds)"]["hedgePnl"] == pytest.approx(-.014)
    assert by_name["Nasdaq reversal down (dedicated technology funds)"]["total"] == pytest.approx(.014)
    assert by_name["S&P 500 reversal down"]["total"] == pytest.approx(-.05)
    assert by_name["Mega-cap single stock up"]["total"] is None
    assert out["gaps"][1]["loss"] == pytest.approx(.03)


@pytest.mark.parametrize("kind", ["option", "future", "leveraged ETF"])
def test_unsupported_contract_never_priced_as_linear_fund(kind, policy):
    ds = book(("SPY", .5), ("QQQ", .5))
    ds["weights"]["rows"][1]["instrumentType"] = kind
    out = risk.build(ds, policy)
    assert out["complete"] == 0 and out["worst"] is None
    assert out["net"] is None and out["gaps"][1]["cap"] is None
    assert all(s["hedgePnl"] is None and "QQQ" in s["missing"] for s in out["scenarios"])


def test_incomplete_and_ambiguous_inputs(policy):
    assert risk.build(book(("SPY", .8)), policy)["status"] == "unavailable"
    assert risk.build(book(("SPY", None)), policy)["status"] == "unavailable"
    assert risk.build(book(("SPY", .5), ("SPY", .5)), policy)["status"] == "unavailable"
    assert risk.build(book(("UNMAPPED", 1)), policy)["complete"] == 0
    policy["groups"]["gold"].append("SPY")
    with pytest.raises(ValueError, match="Duplicate"):
        risk.instrument_map(policy)


def test_new_factor_requires_explicit_scenario_coverage(policy):
    policy["groups"]["additional"] = ["NEW"]
    out = risk.build(book(("NEW", 1)), policy)
    assert out["complete"] == 0 and out["worst"] is None
    assert all(s["missing"] == ["NEW"] for s in out["scenarios"])


def test_shared_reserve_and_overlay_legs(policy):
    ds = book(("SPY", .2), ("SHY", .7), ("EEM", .1))
    ds["weights"]["rows"][1].update(assetClass="Fixed Income", sleeve="CASH")
    reg = {"sleeves": {"A": {"key": "base", "alloc_tilt": .8}, "TILT": {"alloc_tilt": .2}}}
    live = {"regime_state": "RISK_OFF", "eem_tilt_active": True, "anchor_date": "2025-01-03",
            "sleeve_extensions": {"base": {"anchor_date": "2025-01-03", "weights": {"SHY": .5, "SPY": .5}}}}
    overlay = {"gate_parameters": {"derisk_fraction": .5, "fallback_ticker": "SHY"}}
    legs, allocations = risk.anchored_legs(live, reg, overlay)
    out = risk.build(ds, policy, legs=legs, allocations=allocations)
    s = next(x for x in out["scenarios"] if x["name"] == "Global risk-off / flight to quality")
    assert s["sleeves"]["DEFENSIVE"] == pytest.approx(.5 * .006)
    assert s["sleeves"]["A"] == pytest.approx(.2 * .006 - .2 * .09)
    assert s["sleeves"]["TILT"] == pytest.approx(-.1 * .10)
    live["sleeve_extensions"]["base"]["anchor_date"] = "2024-12-31"
    partial, _ = risk.anchored_legs(live, reg, overlay)
    assert dict(partial) == {"EEM": {"TILT": .1}, "SHY": {"DEFENSIVE": .5}}
    parts = risk.sleeve_weights(ds["weights"]["rows"][1], partial)
    assert parts == pytest.approx({"DEFENSIVE": .5, "Unresolved sleeve": .2})
    unknown = risk.build(ds, policy, legs={})["scenarios"][-1]
    assert list(unknown["sleeves"]) == ["Unresolved sleeve"]


def test_tightest_available_cap_and_treasury_yield_coverage(policy):
    ds = book(("SPY", .6), ("CSP1", .2), ("SHY", .2))
    policy["gap"]["lossBudgets"]["sleeve"]["A"] = .004
    policy["gap"]["groupCaps"]["us_equity"] = .22
    policy["gap"]["positionCaps"]["SPY"] = .03
    out = risk.build(ds, policy)
    g = out["gaps"][0]
    assert g["constraints"]["gap"] == pytest.approx(.04)
    assert g["cap"] == pytest.approx(.02)
    assert g["review"]
    s = next(s for s in out["scenarios"] if s["name"] == "US Treasury yields up")
    assert s["total"] is None and s["missing"] == ["SHY"]


def test_stale_unrelated_sleeve_cannot_clear_a_gap_flag(policy):
    ds = book(("SPY", .85), ("SHY", .15))
    p = policy["gap"]["lossBudgets"]["sleeve"]
    p["C"] = .001
    reg = {"sleeves": {s: {"key": s, "alloc": w} for s, w in (("A", .5), ("B", .4), ("C", .1))}}
    live = {"anchor_date": "2025-01-03", "regime_state": "RISK_ON", "eem_tilt_active": False,
            "sleeve_extensions": {s: {"anchor_date": "2025-01-03", "weights": weights} for s, weights in
                                 (("A", {"SPY": 1}), ("B", {"SHY": .125, "SPY": .875}), ("C", {"SHY": 1}))}}
    def check():
        legs, alloc = risk.anchored_legs(live, reg, {})
        result = risk.build(ds, policy, legs=legs, allocations=alloc)
        return result["gaps"][1]
    assert check()["cap"] == pytest.approx(.075)
    live["sleeve_extensions"]["A"]["anchor_date"] = None
    assert check()["review"] is True and check()["cap"] == pytest.approx(.075)
    live["sleeve_extensions"]["C"]["anchor_date"] = None
    assert check()["review"] is None and check()["cap"] is None
    policy["gap"]["positionCaps"]["SHY"] = .1
    assert check()["review"] is True and check()["cap"] is None


def test_coverage_gate_and_shared_proxy(policy):
    ds = book(("SPY", .6), ("CSP1", .2), ("SHY", .2))
    for row in ds["weights"]["rows"][:2]:
        row["tradeAs"] = "SPY"
    ds["regime"] = {"live_state": "RISK_ON", "derisk_fraction": .5, "fallback_ticker": "SHY"}
    out = risk.build(ds, policy)
    sc = {s["name"]: s for s in out["scenarios"]}
    nasdaq = next(s for s in sc.values() if s["name"].startswith("Nasdaq"))
    assert nasdaq["total"] == 0 and nasdaq["coverage"] == {"shocked": 0, "flat": 1, "unpriced": 0}
    assert sc["US Treasury yields up"]["coverage"] == pytest.approx({"shocked": 0, "flat": .8, "unpriced": .2})
    recovery = sc["Recovery shock on current weights"]
    assert recovery["gateComparison"]["total"] == pytest.approx((.8*.08 - .2*.005)*.5 - .5*.005)
    assert out["sharedProxies"][0]["loss"] == pytest.approx(.08)
    for state in ("RISK_OFF", None):
        ds["regime"]["live_state"] = state
        assert all("gateComparison" not in s for s in risk.build(ds, policy)["scenarios"])


def test_proxy_gap_respects_signs_and_incompatible_shocks(policy):
    ds = book(("SPY", 1.2), ("CSP1", -.2))
    for row in ds["weights"]["rows"]:
        row["tradeAs"] = "SPY"
    out = risk.build(ds, policy)
    assert out["sharedProxies"][0]["loss"] == pytest.approx(.1)
    assert out["scenarios"][-1]["coverage"]["shocked"] == pytest.approx(1.4)
    ds["weights"]["rows"][1]["instrumentType"] = "option"
    assert risk.build(ds, policy)["sharedProxies"][0]["loss"] is None


@pytest.mark.parametrize("start", ["2023-01-31", "2023-12-29"])
def test_calendar_boundaries_gap_and_exact_tail(start):
    # Python/pandas months are 1-indexed. Cover month and year transitions.
    dates = risk.mcal.get_calendar("NYSE").schedule(start, pd.Timestamp(start) + pd.DateOffset(months=15)).index
    returns = [0.001] * (len(dates)-1)
    returns[-1], returns[-2], returns[-3] = -.09, -.08, -.07
    nav = pd.Series([1] + [1 + r for r in returns], index=dates).cumprod()
    nav.iloc[-100] = None
    e = {"dates": list(nav.index.strftime("%Y-%m-%d")), "model": list(nav)}
    h = risk.historical_path(e)
    assert h["excluded"] == 2 and h["observations"] == 252
    assert h["metrics"]["var99"] == pytest.approx(.07)
    assert h["metrics"]["es975"] == pytest.approx((.24 - .0033) / 6.3)
    e["model"][-1] = None
    assert risk.historical_path(e)["metrics"] is None
