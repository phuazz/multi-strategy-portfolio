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
    assert risk.anchored_legs(live, reg, overlay) == ({}, {})
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
