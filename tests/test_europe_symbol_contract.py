"""Europe symbol contract on the consumer side (2026-08-07).

The engine corrected registry key ``EXH3`` on 2026-08-03: its constituent panel
is Industrial Goods & Services (iShares product 251948) but it was priced as
``EXH3.DE``, which is the Xetra ticker of the Food & Beverage fund. The
industrials fund trades as ``EXH4.DE``. Evidence on daily log returns over
495-497 observations: ``EXH4.DE`` correlates 0.973 with that panel's own
constituents, ``EXH3.DE`` correlates 0.244 and correlates 0.933 with food and
beverage majors.

The engine fixed ``etf_registry.py`` and guarded it with its own contract test.
This repository kept ``tradeAs: EXH3.DE`` for four more days, which is why 5.4%
of NAV returned a null 200-DMA proximity in every daily digest from 2026-08-03
to 2026-08-07. This module is the consumer-side half of that guard.

Two invariants, both cheap and both offline:

1. No registry entry may assume its traded ticker is the panel key plus a
   suffix. ``EXH3`` is the standing counter-example; the shortcut is what let
   the engine and this repository disagree in the first place.
2. Every entry's ``tradeAs`` must resolve against the engine price panel. This
   is the invariant that actually failed, and it catches drift in EITHER
   direction -- a rename here or a re-keying upstream.

Invariant 2 runs against a checked-in snapshot of the panel keys so the suite
stays offline; refresh ``PANEL_KEYS`` if the engine adds or renames a series.
"""

from __future__ import annotations

import pytest

from config import load_registry

REG = load_registry("multi-strategy-portfolio")
META = REG["etf_meta"]

# Keys present in the engine's data/holdings_prices_1y.json.
# Snapshot taken 2026-08-07 (computed_at 2026-08-07T09:56:42+00:00, 58 series).
PANEL_KEYS = {
    "159801.SZ", "ARKG", "ARKK", "BLOK", "BOTZ", "BTC-USD", "CIBR", "COPX",
    "CQQQ", "DBC", "EEM", "EFA", "EWJ", "EXH1.DE", "EXH4.DE", "EXH9.DE",
    "EXV1.DE", "EXV3.DE", "GDX", "GLD", "ICLN", "IEF", "IHI", "IJR", "INDA",
    "ITA", "JETS", "LIT", "MCHI", "MOO", "PAVE", "PHO", "QQQ", "REMX", "SHY",
    "SKYY", "SOXX", "SPY", "TAN", "TIP", "TLT", "URA", "VGK", "VNQ", "WOOD",
    "XBI", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU",
    "XLV", "XLY", "XME",
}

# Panel key -> traded ticker, for lines whose traded ticker is NOT the key.
# Mirrors etf_registry.py's `yfinance_trading_proxy` for the sleeve D members.
EUROPE_TRADED = {
    "EXV1": "EXV1.DE",
    "EXH1": "EXH1.DE",
    "EXV3": "EXV3.DE",
    "EXH9": "EXH9.DE",
    "EXH3": "EXH4.DE",  # NOT EXH3.DE -- that is the Food & Beverage fund.
}


def test_exh3_trades_as_exh4_not_exh3():
    """The regression itself, asserted both ways so neither drifts back."""
    assert META["EXH3"]["tradeAs"] == "EXH4.DE"
    assert META["EXH3"]["tradeAs"] != "EXH3.DE", (
        "EXH3.DE is the iShares Stoxx Europe 600 Food & Beverage UCITS ETF. "
        "The panel key EXH3 is Industrial Goods & Services and trades as EXH4.DE."
    )
    # The name and theme must keep describing the PANEL, not the wrong fund.
    assert "Industrial" in META["EXH3"]["name"]
    assert META["EXH3"]["theme"] == "Industrials"
    assert META["EXH3"]["sleeve"] == "D"


@pytest.mark.parametrize("key,traded", sorted(EUROPE_TRADED.items()))
def test_europe_members_carry_the_engine_traded_ticker(key, traded):
    assert META[key]["tradeAs"] == traded, (
        f"{key} must trade as {traded} to match the engine registry's "
        f"yfinance_trading_proxy; got {META[key]['tradeAs']!r}"
    )


def test_no_entry_relies_on_key_plus_suffix():
    """`tradeAs` is never derivable by appending '.DE' to the panel key.

    EXH3 is the standing counter-example. If a future entry is added whose
    traded ticker genuinely is key + '.DE', that is fine -- it just must be
    written out explicitly, which it already is. What this pins is that no
    CONSUMER may reconstruct the mapping, so the assertion is on EXH3 alone.
    """
    assert META["EXH3"]["tradeAs"] != "EXH3" + ".DE"


def test_every_tradeas_resolves_against_the_engine_price_panel():
    """The invariant that actually failed on 2026-08-03..07.

    A ticker whose `tradeAs` is absent from the panel silently returns a null
    proximity: it vanishes from the risk monitor rather than raising.
    """
    from build_risk_visuals import PROXY

    unresolved = []
    for key, m in META.items():
        traded = m.get("tradeAs")
        assert traded, f"{key} has no tradeAs"
        if traded in PANEL_KEYS or key in PANEL_KEYS or PROXY.get(key) in PANEL_KEYS:
            continue
        unresolved.append((key, traded))
    assert not unresolved, (
        "these registry entries do not resolve to any engine price-panel key: "
        f"{unresolved}"
    )


def test_price_key_does_not_append_a_suffix():
    """build_risk_visuals.price_key must go through `tradeAs`, not key + '.DE'.

    Constructed so that the removed shortcut would return the WRONG fund: the
    panel offers both EXH3.DE and EXH4.DE, and only the registry disambiguates.
    """
    from build_risk_visuals import price_key

    prices = {"EXH3.DE": {}, "EXH4.DE": {}}
    meta = {"EXH3": {"tradeAs": "EXH4.DE"}}
    assert price_key("EXH3", prices, meta) == "EXH4.DE"


def test_price_key_returns_none_when_unmapped():
    from build_risk_visuals import price_key

    assert price_key("NOPE", {"SPY": {}}, {"NOPE": {"tradeAs": "NOPE.DE"}}) is None
