"""Adapter logic that is easy to get subtly wrong: the weight build-decomposition
(it must reproduce the engine's effective weights from sleeve allocation x within-
sleeve weight, plus the EM tilt) and the exposure roll-ups.
"""
import adapter
from config import load_registry

REG = load_registry("multi-strategy-portfolio")


def _live(tilt=True):
    # Post-Phase-29 book: EEM is OVERLAY-ONLY (removed from the Strategy B
    # rotation universe on 2026-07-02), so it appears solely as the 10% tilt
    # leg when the tilt is on, and not at all when it is off. The registry's
    # etf_meta accordingly tags EEM sleeve TILT (implementation-audit item
    # D2, closed 2026-07-18).
    eff = {"SOXX": 0.13583, "SPY": 0.04958, "EXH1": 0.07214, "SHY": 0.00003}
    if tilt:
        eff["EEM"] = 0.10
    return {
        "computed_at_utc": "2026-06-19T22:50:00Z",
        "eem_tilt_active": tilt,
        "regime_state": "RISK_ON",
        "anchor_date": "2026-06-17", "anchor_equity": 2.9638,
        "live_dates": ["2026-06-18"], "live_equity": [3.0052],
        "effective_weights": eff,
        "sleeve_extensions": {
            "strategy_a": {"weights": {"SOXX": 0.3881}},
            "strategy_b": {"weights": {"SPY": 0.1983}},
            "strategy_c": {"weights": {}},
            "strategy_d": {"weights": {"EXH1": 0.3607}},
        },
    }


def test_eem_build_is_tilt_only_post_phase29():
    w = adapter.build_weights(_live(tilt=True), REG)
    eem = next(r for r in w["rows"] if r["ticker"] == "EEM")
    assert {b["sleeve"] for b in eem["build"]} == {"TILT"}
    total = sum(b["contrib"] for b in eem["build"])
    assert abs(total - eem["weight"]) < 1e-3          # reconstruct the effective weight
    assert abs(eem["weight"] - 0.10) < 1e-9
    # Sleeve B's allocation is reduced to 25% while the tilt is on — visible
    # on a genuine B holding's build leg.
    spy = next(r for r in w["rows"] if r["ticker"] == "SPY")
    b_leg = next(b for b in spy["build"] if b["sleeve"] == "B")
    assert abs(b_leg["alloc"] - 0.25) < 1e-9


def test_sector_holding_single_sleeve_leg():
    w = adapter.build_weights(_live(), REG)
    soxx = next(r for r in w["rows"] if r["ticker"] == "SOXX")
    assert [b["sleeve"] for b in soxx["build"]] == ["A"]
    assert abs(soxx["build"][0]["contrib"] - 0.35 * 0.3881) < 1e-4


def test_exposure_rollups_and_concentration():
    w = adapter.build_weights(_live(), REG)
    # Europe oil & gas should land in sleeve D and Europe geography.
    assert "D" in w["by_sleeve"] and "Europe" in w["by_geo"]
    assert w["concentration"]["n_holdings"] >= 3
    assert 0 < w["concentration"]["hhi"] <= 1


def test_trade_ledger_initial_then_rebalance():
    w1 = adapter.build_weights(_live(tilt=True), REG)          # EEM, SOXX, EXH1 (SHY ~0 excluded)
    led, tr = adapter.build_trades(None, w1, REG, "2026-06-17")
    assert tr["count"] == 1 and tr["log"][0]["type"] == "initial"

    # A genuine rebalance: trim EEM, add SOXX, exit EXH1, open QQQ.
    live2 = _live(tilt=True)
    live2["effective_weights"] = {"EEM": 0.10, "SOXX": 0.20, "QQQ": 0.05}
    w2 = adapter.build_weights(live2, REG)
    led2, tr2 = adapter.build_trades(led, w2, REG, "2026-06-24")
    assert tr2["count"] == 2 and tr2["log"][0]["type"] == "rebalance"
    acts = {d["ticker"]: d["action"] for d in tr2["log"][0]["deltas"]}
    assert acts.get("QQQ") == "NEW" and acts.get("EXH1") == "EXIT"

    # No change -> no new entry (sub-threshold drift is ignored).
    led3, tr3 = adapter.build_trades(led2, w2, REG, "2026-06-25")
    assert tr3["count"] == 2


def _th(rows):
    return {"headline": {"trade_history": rows}}


def test_weight_history_reconstruction_and_tilt():
    bundle = {
        "topk_robustness.json": _th([
            {"date": "2026-06-05", "holdings": [{"etf": "SOXX", "weight": 0.5}, {"etf": "IUES", "weight": 0.5}]},
            {"date": "2026-06-12", "holdings": [{"etf": "SOXX", "weight": 0.6}, {"etf": "IUES", "weight": 0.4}]}]),
        "asset_class_rotation.json": _th([
            {"date": "2026-06-05", "holdings": [{"etf": "EEM", "weight": 0.5}, {"etf": "SPY", "weight": 0.5}]},
            {"date": "2026-06-12", "holdings": [{"etf": "EEM", "weight": 0.5}, {"etf": "SPY", "weight": 0.5}]}]),
        "thematic_rotation.json": _th([{"date": "2026-06-05", "holdings": [{"etf": "CIBR", "weight": 1.0}]},
                                       {"date": "2026-06-12", "holdings": [{"etf": "CIBR", "weight": 1.0}]}]),
        "europe_rotation.json": _th([{"date": "2026-06-05", "holdings": [{"etf": "EXH1", "weight": 1.0}]},
                                     {"date": "2026-06-12", "holdings": [{"etf": "EXH1", "weight": 1.0}]}]),
    }
    # No tilt, no de-risk: allocations 0.35/0.35/0.10/0.20.
    overlay = {"gate_parameters": {"derisk_fraction": 0.5, "fallback_ticker": "SHY"},
               "events": [], "phase22_eem_tilt": {"events": []}}
    h = adapter.build_weight_history(bundle, REG, overlay)
    assert h and h["reconstructed"] and h["count"] >= 1
    W = h["alloc_history"]["weights"]                        # per-ticker weekly weight matrix
    assert abs(W["SOXX"][0] - 0.35 * 0.5) < 1e-6            # alloc x within-sleeve, first week
    assert abs(W["EEM"][0] - 0.35 * 0.5) < 1e-6
    assert abs(W["CIBR"][0] - 0.10) < 1e-6 and abs(W["EXH1"][0] - 0.20) < 1e-6
    assert abs(W["SOXX"][-1] - 0.35 * 0.6) < 1e-6           # latest week: SOXX added
    assert abs(W["IUES"][-1] - 0.35 * 0.4) < 1e-6           # IUES trimmed

    # With the EM tilt on, sleeve B drops to 0.25 and EEM gets +0.10.
    overlay_tilt = {"gate_parameters": {"derisk_fraction": 0.5, "fallback_ticker": "SHY"}, "events": [],
                    "phase22_eem_tilt": {"events": [{"date": "2026-06-01", "direction": "EM_TILT_ON"}]}}
    h2 = adapter.build_weight_history(bundle, REG, overlay_tilt)
    assert abs(h2["alloc_history"]["weights"]["EEM"][0] - (0.25 * 0.5 + 0.10)) < 1e-6   # B at 25% + 10% tilt


def test_tilt_off_drops_eem_and_restores_b_alloc():
    w = adapter.build_weights(_live(tilt=False), REG)
    # Post-Phase-29 the book holds EEM only via the tilt: tilt off -> no row.
    assert all(r["ticker"] != "EEM" for r in w["rows"])
    spy = next(r for r in w["rows"] if r["ticker"] == "SPY")
    b_leg = next(b for b in spy["build"] if b["sleeve"] == "B")
    assert abs(b_leg["alloc"] - 0.35) < 1e-9           # full 35% when tilt is off
