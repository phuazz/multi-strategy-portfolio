"""Intraday P&L basis contract (2026-08-10).

The Overview intraday card fetches a live quote per holding and reports the
weighted ``price / prior_close - 1``. Yahoo's ``v8/finance/chart`` meta on the
``range=5d`` request frequently omits ``regularMarketPreviousClose``, and the
original helper then fell back to ``chartPreviousClose``.

``chartPreviousClose`` is the close before the WHOLE requested range -- five
sessions back, not the prior session. So the card reported a five-day
cumulative return under an "Intraday P&L" label with a pulsing live dot.
Measured on Mon 10 Aug 2026 while US markets were open:

    SPY    shown +2.09%  (773.81 against 757.67)   true +0.04% (against 773.26)
    model  shown +1.55%                            true +0.41%
    vs SPY shown -0.54%                            true +0.37%   <- sign flip

The relative figure changed sign, so the card claimed the model was behind the
index on a day it was ahead. Worst single names were the thematic sleeve, where
a five-day run compounds hardest: ARKG +11.85% against a true +2.96%, SKYY
+8.23% against +2.55%, XBI +7.17% against +0.32%.

The fix derives the prior close from the daily bars carried in the same
response and removes the fallback entirely. These invariants are offline
string checks over the template -- the quote path is browser JavaScript with
no test harness in this repository, so a content guard is what is available.
It is cheap and it pins the exact line that regressed.
"""
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "template.html"


@pytest.fixture(scope="module")
def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_quote_path_does_not_read_chart_previous_close(template: str):
    """chartPreviousClose must never be a value source for the intraday move.

    It may still be named in the explanatory comment -- that is the record of
    why it is barred -- so the assertion targets the property read, not the
    word.
    """
    reads = template.count("m.chartPreviousClose")
    assert reads == 0, (
        f"{reads} read(s) of m.chartPreviousClose remain in the quote path. "
        "It is the close before the whole requested range, not the prior "
        "session; using it reports a five-day return as intraday."
    )


def test_prior_close_helper_exists_and_is_used(template: str):
    """The derivation must go through _priorClose, not an inline fallback."""
    assert "function _priorClose(" in template, "the _priorClose helper is gone"
    assert "_priorClose(res,m)" in template or "_priorClose(res, m)" in template, (
        "_yfQuote no longer calls _priorClose -- the basis derivation was inlined "
        "or reverted"
    )


def test_prior_close_reads_the_daily_bars(template: str):
    """The prior close must come from the response's own close series."""
    start = template.index("function _priorClose(")
    body = template[start:start + 1200]
    assert "indicators" in body and "close" in body, (
        "_priorClose no longer reads indicators.quote[0].close -- it must derive "
        "the prior close from the daily bars"
    )
    assert "regularMarketTime" in body, (
        "_priorClose no longer compares the quote day against the last bar, so it "
        "cannot tell a live partial bar from a completed session"
    )
