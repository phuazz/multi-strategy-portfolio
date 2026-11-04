# Historical model attribution

The dashboard, morning email and PDF consume one version-2 attribution object,
built by `scripts/historical_attribution.py`. This is a dossier of the published
paper model, not actual-account attribution or a new strategy backtest.

## Holdings and timing

Raw per-strategy trade histories come from one immutable engine source commit.
A fill dated at a close changes the holdings used for the following session.
The calculation retains exited ETFs and keeps strategy ownership when the same
ETF appears in multiple strategies. It does not use the dashboard's weekly
weight-history grid or infer historical positions from today's holdings.

The historical engine uses constant target weights between fills. Attribution
mirrors that model convention, including lagged gate and emerging-market tilt
allocations. Defensive and tilt positions have separate owners. After the engine
anchor, the published live extension uses fixed units: beginning-of-session
weights drift with prices and NAV. Reconstructed ownership must match the
published anchor book within two basis points of weight before that extension
can be attributed.

## Periods and arithmetic

1D uses the previous official NAV observation. 1M is a trailing calendar month,
anchored to the last official NAV observation on or before the corresponding date
one month earlier. Both periods display their actual endpoints. Missing NYSE
sessions in the official NAV window make the period unavailable.

For an ETF and session, gross contribution is beginning-of-session model weight
times its USD adjusted-price return. Strategy contribution uses the published net
sleeve return times its lagged allocation through the engine anchor; the live
extension uses its owned ETF marks. Daily contributions are linked by
`NAV(previous session) / NAV(period start)` before summation. This preserves
compounding and makes the residual bridge additive to the official period return.

There are two bridges: all known ETF marks plus ETF residual, and all known
strategy contributions plus strategy residual. Each must equal the official NAV
return within 1e-10 in decimal-return units. A strategy's net contribution less its
known ETF marks is also retained. No unexplained amount is forced into an ETF or
called a trading cost without independent evidence. Residual magnitudes of five
basis points or more trigger review, regardless of sign.

## Prices and incomplete observations

All ETFs held during the period are requested, including exited names. Yahoo
Finance adjusted closes are the primary price source; the engine's rounded
USD/EUR export is a fallback. Native EUR and CNY lines are converted to USD with
date-matched FX. An unstamped CNY engine export is not reused because it may
already have been converted. Per-ETF pricing symbols, source and last-price dates,
the acquisition timestamp and engine commit accompany the dataset.

An exchange holiday may use the last actual session close. An absent close on an
open exchange session is unavailable. A missing FX mark is also unavailable.
An incomplete ETF row has no full-period contribution and is excluded from winner
and loser rankings; its known partial contribution remains in the bridge.
Coverage is one minus missing held weight-days divided by total held weight-days.
Published historical net strategy returns may remain available when independent
ETF price verification is incomplete; those strategy figures carry a marker.

These marks are vendor-based estimates of model contribution. Reconciliation
through an explicit residual does not establish complete economic explanation.
Absolute contribution is distinct from the separately reported excess return
against the clearly labelled S&P 500 total-return proxy.

## Presentation and guards

Email: named strategy contributions for both horizons, three verified positive
and negative ETF contributors per horizon, signed colour bars, coverage and
reconciliation. Dashboard: the full named ETF and strategy comparisons, plus
theme grouping. PDF: the complete historical ETF table with owning strategy,
monthly average weight, both contributions and provenance. Zero and unavailable
remain distinct. Each comparison states its common bar scale.

Tests cover fill timing, exited holdings, shared ownership, monthly compounding,
overlay timing, fixed-unit live drift, FX, holidays, incomplete prices, missing NAV,
month/year boundaries and broken bridges. Before delivery, content guards check
the rendered PDF for every historical ETF and the email for selected contributors.
Real browser checks measure 390/844/768/1280-pixel viewports. Dashboard checks also
compare every rendered chart value and row count with the attribution object.
