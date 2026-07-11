# DESIGN — the monitor as a multi-strategy valuation layer

Status: proposal · Author: Zhenghao · Date: 2026-06-27 · Layers on `README.md` and `CLAUDE.md`.

This note defines the target architecture for this monitor once it covers more than one
strategy, and the contract every engine must publish into it. It exists so that work done
in the engine repos and work done here converge on the same boundary rather than drifting.
Until the work below lands, the current thin-renderer path (see `README.md` → Architecture)
remains the production system and the fallback.

---

## The problem this solves

Today the monitor is a thin renderer of a single engine (`breadth-thrust-etf`). Its headline
NAV, cost model, FX convention and freshness are all inherited from that engine: the
dashboard's `meta.asOf` traces directly to the engine's `live_track.json`
(`scripts/pipeline.py` → `adapter.build_equity` → `stats["end"]`). For one strategy this is
correct and simple.

It does not survive a second strategy. The failure is structural, not incidental:

1. **Freshness collapses to the minimum across engines.** If each engine marks itself to
   market on its own daily job, the monitor's headline is only as current as the least reliable
   engine. The 2026-06-26 freeze — where the monitor stuck at "AS OF 25 JUN" because the engine's
   daily mark-to-market aborted on a stale breadth panel — is the first instance of this. With
   N engines, a frozen headline becomes the normal state.
2. **A blended NAV needs a common date axis.** To report portfolio-level NAV, contribution
   and risk across sleeves, every sleeve must be valued on the *same* close. If each engine
   values itself on its own calendar and cadence, the blend is silently misaligned.
3. **One valuation standard, not a patchwork.** Different engines will carry different
   slippage, cost and FX assumptions. A blended NAV stitched from divergent methodologies
   cannot be reconciled or defended to an allocator.

## The target architecture: engines generate, the monitor values

A clean separation of concerns. This **moves** the daily mark-to-market that each engine
currently performs into one place; it does not add a new computation on top.

**Engines** (e.g. `breadth-thrust-etf`) become *weekly publishers* of:
- target weights for the deployed strategy,
- the weekly NAV anchor (the Friday close point the backtest re-establishes),
- regime / signal state,
- backtest statistics (Sharpe, CAGR, max DD, the in-sample/OOS split).

These are genuinely weekly concerns — signal logic, walk-forward refits and the regime gate
do not change materially day to day, and they are where the engine's comparative advantage
sits.

**The monitor** owns the *daily valuation layer*:
- mark each sleeve's published anchor weights to the latest available close, using the monitor's
  own price fetch, FX handling and a shared cost model,
- blend the sleeves onto one date axis,
- compute presentation analytics (risk, attribution, P&L) on the blended series,
- validate, bake, publish.

This respects the existing hard rule in `CLAUDE.md` — *never re-run or re-tune the strategy
here*. Mark-to-market is **valuation of given weights**, not signal generation. The monitor never
decides a weight or a regime; it only values the weights the engine published. The boundary
is: weights and regime are the engine's; valuation and accounting are the monitor's.

## Contract: what each engine must publish

A single per-strategy file under the existing registry mechanism
(`portfolios/<id>.json` points at the engine source). The valuation layer consumes:

| Field | Meaning | Cadence |
|-------|---------|---------|
| `weights` | target sleeve/ETF weights, summing to 1 (or to the deployed gross) | weekly |
| `weights_as_of` | the date those weights became effective | weekly |
| `anchor_date`, `anchor_equity` | the weekly NAV anchor point to extend from | weekly |
| `regime_state`, `regime_since` | de-risk / tilt state and the switch date that set it | weekly |
| `backtest_stats` | Sharpe, CAGR, max DD, inception, OOS split — for reconciliation only | weekly |
| `cost_assumption_bps` | the engine's round-trip cost assumption, so the monitor replicates it | static |

The monitor supplies the rest itself: the price panel (latest closes per holding), FX, and the
daily NAV extension from `anchor_equity` forward.

## The discipline it must carry from day one

A self-marking layer built carelessly is *worse* than the renderer, because it can value
positions the strategy should never have held. These are the ways it would be silently
wrong, and each needs a guard before the first sleeve goes live:

1. **Two as-of stamps per sleeve, always shown and never collapsed.** `weights_as_of` (from
   the engine, may lag) and `nav_as_of` (the monitor's mark, current). The honest display of the
   2026-06-26 state would have been "weights 25 Jun · NAV 26 Jun", not a single frozen date.
   This extends the existing per-feed as-of discipline on the Data Health tab.
2. **A freshness budget on the *weights*, not only the prices.** The 2026-06-26 abort was the
   regime gate, not the mark — the *de-risk decision* was the thing going stale. If the monitor
   marks stale weights past a budget, it must flag loudly (STALE banner, red Data Health) that
   it may be valuing a position a fresh signal would have exited. Graceful degradation with
   disclosure, never silent confidence. Budgets live in `portfolios/<id>.json` alongside the
   existing `*_bdays` lag budgets.
3. **Anchor reconciliation.** Each time an engine republishes its weekly anchor, the monitor's own
   marked NAV at that same anchor date must reconcile to `anchor_equity` within tolerance. A
   breach means the cost/FX replication has drifted — surface it immediately. Build on the
   existing `stats["reconcile"]` check.

Two further invariants carried over from `README.md` / `CLAUDE.md`:
- The live mark-to-market extension always renders as a **distinct dashed segment**, never
  spliced silently into the backtest curve.
- Dates only via libraries (`datetime` / `dateutil` in the pipeline), with month-boundary and
  year-boundary tests for any new date arithmetic.

## Multi-strategy blending

Once two or more strategies report on a common date axis, the blend is mechanical:
portfolio NAV is the weighted sum of sleeve NAVs; contribution and risk decompose by sleeve.
The registry already supports multiple portfolios (`ACTIVE_PORTFOLIO_IDS` in
`scripts/config.py`); the addition is a *blended* view that aggregates across registered
strategies rather than rendering each in isolation. Each strategy keeps its own engine, its
own weekly contract, and its own freshness budgets — the valuation layer is what they share.

## Phased plan

1. **Valuation module (single strategy, behind a flag).** Add a `mark_to_market` step to the
   pipeline that extends `anchor_equity` to the latest close from engine weights + monitor
   prices + the shared cost model. Gate it behind a config flag; the thin-renderer path stays
   the default. Land the anchor-reconciliation test against the live engine's own figures.
2. **Two-date display + weights-freshness budget.** Surface `weights_as_of` vs `nav_as_of`
   throughout the dashboard and Data Health; add the weights budget and its STALE behaviour.
3. **Cut breadth-thrust-etf over.** Once reconciliation holds, the monitor becomes the source of
   the daily mark for this strategy; the engine's daily mark-to-market workflow can be retired
   (engine keeps the weekly run as source of truth). Coordinate this change *in the engine
   repo*, never from a session in this repo.
4. **Second strategy + blended view.** Onboard the next engine against the same contract; add
   the aggregated blended NAV / contribution view.

## When NOT to do this

If the monitor were to remain single-engine indefinitely, do not build this. The thin renderer is
simpler, the duplication of NAV logic is a liability, and the reconciliation burden is not
worth carrying. The multi-strategy ambition is the only thing that justifies the valuation
layer. Revisit this note if that ambition changes.
