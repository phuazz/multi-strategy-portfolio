"""Benchmark curves (SPY and 60/40 SPY/IEF) aligned to the model's date axis.

The engine does not publish a long benchmark history, so the monitor owns its
benchmark definition and fetches it via yfinance. Both benchmarks are rebased to
1.0 on the model's first date so they overlay the model equity directly.

Design choice: SPY is the honest all-equity hurdle ("did the tactical book beat
just holding stocks?"); 60/40 is the multi-asset hurdle. The 60/40 is a daily
constant-mix (rebalanced every day to 60/40), which slightly flatters vs a
drifting mix but is the standard reference and is labelled as such.

Robustness: a yfinance failure must NOT kill the build. We return ok=False and
the dashboard renders model-only with a flagged, missing benchmark feed.
"""
from __future__ import annotations

import pandas as pd

try:
    import yfinance as yf
    _HAS_YF = True
except Exception:  # pragma: no cover - yfinance always present in our env
    _HAS_YF = False


def _download(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Adjusted-close frame indexed by date, one column per ticker."""
    raw = yf.download(
        tickers, start=start, end=end, auto_adjust=True,
        progress=False, threads=False,
    )
    if raw is None or len(raw) == 0:
        raise RuntimeError("yfinance returned no rows")
    # Single ticker -> flat columns; multi -> MultiIndex with 'Close' level.
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]] if "Close" in raw else raw
        close.columns = [tickers[0]]
    return close.dropna(how="all")


def build_benchmarks(model_dates: list[str], registry: dict,
                     live_dates: list[str] | None = None) -> tuple[dict, bool, str]:
    """Return ({key: {dates, equity}}, ok, note) aligned to model + live dates.

    Including the live mark-to-market dates means the benchmark series covers the
    same latest day as the model, so intraday/1-day P&L is a like-for-like compare.
    """
    bms = registry.get("benchmarks", {})
    if not bms:
        return {}, True, "no benchmarks configured"
    if not _HAS_YF:
        return {}, False, "yfinance not installed"

    idx = pd.to_datetime(sorted(set(model_dates) | set(live_dates or [])))
    start = (idx[0] - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    end = (idx[-1] + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

    # Collect every raw ticker referenced by any benchmark (including FX pairs).
    tickers: set[str] = set()
    for cfg in bms.values():
        if cfg["type"] == "yfinance":
            tickers.add(cfg["ticker"])
            if cfg.get("fx"):
                tickers.add(cfg["fx"])
        elif cfg["type"] == "blend":
            tickers.update(cfg["components"].keys())

    try:
        close = _download(sorted(tickers), start, end)
    except Exception as exc:
        return {}, False, f"yfinance fetch failed: {exc}"

    # Reindex every raw series onto the model's trading days (ffill gaps).
    px = close.reindex(close.index.union(idx)).ffill().reindex(idx)

    def _have(t: str) -> bool:
        return t in px.columns and not px[t].isna().all()

    def _rebase(series: pd.Series) -> pd.Series:
        s = series.dropna()
        return series / s.iloc[0] if len(s) else series

    out: dict = {}
    skipped: list[str] = []
    for key, cfg in bms.items():
        try:
            if cfg["type"] == "yfinance":
                if not _have(cfg["ticker"]) or (cfg.get("fx") and not _have(cfg["fx"])):
                    skipped.append(key)
                    continue
                series = px[cfg["ticker"]].ffill()
                if cfg.get("fx"):                     # convert a local-currency index to USD
                    series = series * px[cfg["fx"]].ffill()
                eq = _rebase(series)
            else:  # daily constant-mix blend
                comps = list(cfg["components"])
                if any(not _have(c) for c in comps):
                    skipped.append(key)
                    continue
                rets = px[comps].pct_change().fillna(0.0)
                weights = pd.Series(cfg["components"])
                eq = _rebase((1.0 + (rets[weights.index] * weights).sum(axis=1)).cumprod())
            out[key] = {
                "dates": [d.strftime("%Y-%m-%d") for d in idx],
                "equity": [None if pd.isna(v) else round(float(v), 6) for v in eq.values],
            }
        except Exception:
            skipped.append(key)

    if not out:
        return {}, False, f"no benchmark had usable data (skipped {skipped})"
    return out, True, ("ok" if not skipped else f"ok; skipped {skipped}")
