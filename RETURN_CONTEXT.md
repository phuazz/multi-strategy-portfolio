# Return context in prior volatility units

This reporting panel supplements percentage returns and basis-point attribution.
It is a dossier component, not a trading signal or a statistical significance test.
The model return and arithmetic excess against the S&P 500 total-return proxy are
shown for 1D and trailing 1M, alongside each horizon's estimated one-standard-
deviation move. The proxy remains SPY adjusted close, not literal SPX price return.

## Calculation contract

`scripts/return_context.py` produces `return_context` in the published dataset.
The reporting path recomputes the same method from the same published NAV and
benchmark arrays. A matched-input integration check compares the complete objects
before preview publication. No current-holdings forecast is inferred.

1D starts at the previous official NAV observation. 1M starts at the last official
NAV observation on or before one calendar month before the endpoint. Every NYSE
session in the reported window must have both model and benchmark levels.

Before differencing, both histories are reindexed onto the actual NYSE calendar.
No price is forward-filled. A missing session therefore invalidates both the
missing day's return and the following multi-session return. From the remaining
matched one-session returns, take the last 252 observations ending on or before
the period-start close. None of the reported period enters its own estimate.
Fewer than 252 matched observations makes the panel unavailable. The training
dates and excluded gap count are displayed beside each horizon.

For N actual sessions in the reported window:

- Portfolio risk scale = sample standard deviation of prior daily model returns,
  multiplied by sqrt(N).
- Active risk scale = sample standard deviation of prior daily model return minus
  benchmark return, multiplied by sqrt(N).
- Portfolio units = compounded period model return / portfolio risk scale.
- Active units = (compounded period model return minus compounded period benchmark
  return) / active risk scale.

The sample standard deviation uses ddof=1. Zero or numerically negligible risk
produces unavailable units, not zero or infinity. Active return and tracking error
use percentage points in presentation. Portfolio return and volatility use percent.
The active ratio is not divided by portfolio volatility.

The scale is zero-centred: no expected return is subtracted. It is consequently
not a z-score. Monthly scaling approximates compounding and assumes stable
variance and no serial correlation. The shaded regions are not probability
intervals or risk limits. The historical model can differ from today's holdings.

## Visual encoding and verification

All four tracks share a range of -2.5 to +2.5 volatility units. Shading and ticks
mark +/-1 and +/-2. Green/red encodes the sign of return or excess return. Bars
are clipped only at the track boundary; full numeric labels remain visible and
explicitly say when a value is beyond the scale. Attribution retains its bp scale.

Email uses nested presentation tables with inline padding overrides, so mobile
table padding cannot distort segment lengths. Browser guards measure filled bar
lengths against source values at 390/844/768/1280 px. Dashboard guards check both
Overview and Performance. PDF guards verify labels, bounds and page count; the
rendered risk page is inspected. Tests cover look-ahead, active-risk denominators,
missing sessions, month/year boundaries, inadequate history, zero tracking error,
sign symmetry and explicitly labelled clipping.
