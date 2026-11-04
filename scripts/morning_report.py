"""Read-only morning dossier for the personal paper portfolio.

Python/pandas months are 1-indexed. No strategy execution or email sending.
Output is plain text: no layout-dependent HTML or public publication.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from nyse_sessions import last_completed_session

URL = 'https://phuazz.github.io/multi-strategy-portfolio/data/portfolio-multi-strategy-portfolio.json'
PAGE = 'https://phuazz.github.io/multi-strategy-portfolio/'


def series(dates, values, minimum=2):
    if len(dates) != len(values) or len(dates) < minimum:
        raise ValueError('Incomplete date/value pairs')
    s = pd.Series(values, index=pd.to_datetime(dates), dtype=float)
    if not s.index.is_unique or not s.index.is_monotonic_increasing:
        raise ValueError('Dates must be unique and increasing')
    if not np.isfinite(s).all() or (s <= 0).any():
        raise ValueError('NAV must be positive and finite')
    return s


def since(s, anchor):
    base = s.loc[s.index <= anchor]
    return float(s.iloc[-1] / base.iloc[-1] - 1) if len(base) else None


def fmt(x, percent=False):
    if x is None or not math.isfinite(x):
        return 'unavailable'
    return f'{x:+.2%}' if percent else f'{x:.2f}'


def risk_stats(s, cash=None):
    r = s.pct_change(fill_method=None).dropna()
    dd = s / s.cummax() - 1
    peak = s[s == s.cummax()].index[-1]
    days = (s.index[-1] - s.index[0]).days
    growth = float((s.iloc[-1] / s.iloc[0]) ** (365.25 / days) - 1)
    out = dict(cagr=growth, vol=float(r.std(ddof=1) * np.sqrt(252)),
               max_dd=float(dd.min()), current_dd=float(dd.iloc[-1]),
               underwater_days=(s.index[-1] - peak).days,
               calmar=growth / abs(dd.min()) if dd.min() < 0 else None,
               sharpe=None, sortino=None)
    if cash is not None:
        # Require identical level dates: dropping a gap can create a multi-day return.
        c = cash.reindex(s.index)
        if c.notna().all():
            ex = r - c.pct_change(fill_method=None).dropna()
            sd = ex.std(ddof=1)
            downside = np.sqrt(np.mean(np.minimum(ex, 0) ** 2))
            out['sharpe'] = float(ex.mean() / sd * np.sqrt(252)) if sd > 0 else None
            out['sortino'] = float(ex.mean() / downside * np.sqrt(252)) if downside > 0 else None
    return out


def relative_stats(s, b):
    b = b.reindex(s.index)
    if b.isna().any():
        return None
    r, q = s.pct_change().dropna(), b.pct_change().dropna()
    active = r - q
    sd = active.std(ddof=1)
    return dict(beta=float(r.cov(q) / q.var()) if q.var() > 0 else None,
                tracking_error=float(sd * np.sqrt(252)),
                information_ratio=float(active.mean() / sd * np.sqrt(252)) if sd > 0 else None)


def build(d, now):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    meta, eq = d['meta'], d['equity']
    s = series(eq['dates'], eq['model'])
    live = eq.get('live')
    if live and live.get('dates'):
        tail = series(live['dates'], live['equity'], minimum=1)
        anchor = pd.Timestamp(live['anchor_date'])
        if anchor not in s.index or not np.isclose(s.loc[anchor],live['anchor_equity'],atol=0.00001,rtol=0):
            raise ValueError('Live NAV anchor does not reconcile to history')
        overlap = s.index.intersection(tail.index)
        if len(overlap) and not np.allclose(s.loc[overlap], tail.loc[overlap], atol=0.00001, rtol=0):
            raise ValueError('Historical/live NAV overlap does not reconcile')
        s = pd.concat([s, tail.loc[tail.index > s.index[-1]]])
    expected = last_completed_session(now)
    end = s.index[-1]
    if end.date().isoformat() != meta['live_asOf']:
        raise ValueError('NAV tail and published as-of disagree')
    if end.date() > expected:
        raise ValueError('NAV includes an uncompleted NYSE session')
    stale = end.date() < expected
    state = 'DATA DELAYED' if stale else 'CURRENT'
    if d['health']['level'] != 'ok':
        state += ' / HEALTH WARNING'
    lines = [f'Multi-Strategy Portfolio | {state}',
             f'Paper model; USD. Expected completed US session: {expected.isoformat()}.',
             f'Official model NAV through {end:%A %d %B %Y}; built {meta["built_at_utc"]}.',
             'Source: deployed portfolio dataset; all figures are model estimates, not account returns.', '']
    if stale:
        lines += ['Overnight performance is not yet available. The figures below are the latest prior-session record; they are not last night\'s return.', '']
    if live and live.get('dates'):
        lines += [f'Live mark-to-market extension after {live["anchor_date"]}; kept distinct from backtested history.', '']
    benchmarks = {}
    for key in ('SPY', 'AOR', 'BIL'):
        b = eq['benchmarks'].get(key)
        if b:
            benchmarks[key] = series(b['dates'], b['equity'])
    lines += [f'1. Performance through {end:%Y-%m-%d} (USD, identical period endpoints)']
    performance, risk_rows, relative_rows = [], [], []
    anchors = {'1 session': s.index[-2],
               '1 week': end - pd.Timedelta(days=7),
               'MTD': end.to_period('M').start_time - pd.Timedelta(days=1),
               'YTD': end.to_period('Y').start_time - pd.Timedelta(days=1),
               '1 year': end - pd.DateOffset(years=1)}
    for name, anchor in anchors.items():
        base = s.loc[s.index <= anchor]
        if base.empty:
            continue
        start = base.index[-1]
        val = float(s.iloc[-1] / s.loc[start] - 1)
        item = {'period':name,'start':str(start.date()),'end':str(end.date()),'model':val}
        row = f'{name} ({start:%Y-%m-%d} to {end:%Y-%m-%d}): model {fmt(val, True)}'
        for key, label in [('SPY', 'S&P 500'), ('AOR', 'global 60/40 fund')]:
            b = benchmarks.get(key)
            if b is not None and start in b.index and end in b.index:
                br = float(b.loc[end] / b.loc[start] - 1)
                item[key] = br
                row += f'; {label} {fmt(br, True)}, excess {(val-br)*100:+.2f}pp'
            else:
                row += f'; {label} unavailable on matched dates'
        lines.append(row)
        performance.append(item)
    lines += ['', f'2. Risk and long-term record through {end:%Y-%m-%d}']
    def trailing(years):
        prior = s.loc[s.index <= end-pd.DateOffset(years=years)]
        return s.loc[s.index >= prior.index[-1]] if len(prior) else s.iloc[0:0]
    for label, window in [('Full published history (includes backtest)', s),
                          ('Trailing 3 years', trailing(3)),
                          ('Trailing 1 year', trailing(1))]:
        if len(window) < 60:
            continue
        rs = risk_stats(window, benchmarks.get('BIL'))
        risk_rows.append({'period':label,'start':str(window.index[0].date()),'end':str(end.date()),'observations':len(window)-1,**rs})
        lines += [f'{label}: {window.index[0]:%Y-%m-%d} to {end:%Y-%m-%d}; {len(window)-1} returns.',
                  f'CAGR {fmt(rs["cagr"],True)}; volatility {fmt(rs["vol"],True)}; Sharpe {fmt(rs["sharpe"])}; Sortino {fmt(rs["sortino"])}; Calmar {fmt(rs["calmar"])}; maximum drawdown {fmt(rs["max_dd"],True)}.']
        if label == 'Trailing 1 year':
            for key, name in [('SPY', 'S&P 500'), ('AOR', 'global 60/40 fund')]:
                rel = relative_stats(window, benchmarks[key]) if key in benchmarks else None
                if rel:
                    relative_rows.append({'benchmark':name,**rel})
                    lines.append(f'Against {name}: beta {fmt(rel["beta"])}; tracking error {fmt(rel["tracking_error"],True)}; information ratio {fmt(rel["information_ratio"])}.')
    rs = risk_stats(s)
    lines += [f'Current drawdown {fmt(rs["current_dd"],True)}; {rs["underwater_days"]} calendar days since the latest high-water mark.']
    oos = meta.get('oos_start')
    if oos:
        ret = since(s, pd.Timestamp(oos)-pd.Timedelta(days=1))
        lines += [f'Engine-labelled out-of-sample period from {oos}: {fmt(ret,True)} through {end:%Y-%m-%d}. This label does not independently establish an untouched holdout.']
    weights, regime = d['weights'], d['regime']
    lines += ['', f'3. Executed model exposures at {meta.get("portfolio_anchor",meta["asOf"])}',
              f'Gate {regime["state"]}; breadth {fmt(regime.get("breadth"),True)} as at {regime.get("panel_end_date")}; defensive allocation {fmt(weights.get("cash_pct"),True)} (may include short-duration Treasury funds).',
              f'Top-five weight {fmt(weights["concentration"].get("top5"),True)}; holdings {weights["concentration"].get("n_holdings")}.',
              'Largest allocations (portfolio labels):']
    for row in sorted(weights['rows'], key=lambda x: x['weight'], reverse=True)[:3]:
        lines.append(f'- {row["name"]}: {row["weight"]:.2%}.')
    risk = sorted(d.get('risk',{}).get('holdings',[]), key=lambda x: x.get('risk_pct',0), reverse=True)[:3]
    if risk:
        lines.append('Largest estimated risk shares (current-weight historical covariance): ' + '; '.join(f'{r["name"]} {r["risk_pct"]:.1%}' for r in risk) + '.')
    lines += ['', f'4. Indicative attribution supplied in the build {meta["built_at_utc"]}']
    attrs = d.get('attribution',{}).get('etf',[])
    covered = [a for a in attrs if a.get('covered') and a.get('1D',{}).get('contrib') is not None]
    if covered:
        for title, rows in [('Positive contributors',sorted([a for a in covered if a['1D']['contrib']>0],key=lambda x:-x['1D']['contrib'])[:3]),('Negative contributors',sorted([a for a in covered if a['1D']['contrib']<0],key=lambda x:x['1D']['contrib'])[:3])]:
            lines.append(title + ': ' + ('; '.join(f'{a["name"]} {a["1D"]["contrib"]*100:+.2f}pp' for a in rows) or 'none') + '.')
        residual = float(s.iloc[-1]/s.iloc[-2]-1)-sum(a['1D']['contrib'] for a in covered)
        lines.append(f'Residual to official one-session model return: {residual*100:+.2f}pp. Current-weight approximation; not realised holdings attribution. Quote dates/FX, rebalancing and coverage can differ; no causal interpretation of this residual.')
    lines += ['', '5. Exceptions and basis',
              'No trade instructions. Review delayed data, concentration and any pending model changes before acting.',
              f'Dataset health: {d["health"]["level"]}. Source commit: {meta["source_commit"]}.',
              'Volatility, Sharpe and tracking error use daily observations and 252 sessions/year; CAGR uses actual calendar days. Sharpe uses daily return less the published Treasury-bill proxy; Sortino uses the root mean square of negative excess returns over ALL observations. Both depend on proxy data quality. Calmar is CAGR / absolute maximum drawdown. Information ratio uses arithmetic active daily return / tracking error.',
              'Statistics use the published common-date panel; gaps can span more than one exchange session, so annualised risk statistics are approximations. No missing benchmark observations are forward-filled. Fund proxies include their own embedded expenses. Attribution has no independent per-row valuation timestamp and is indicative only.',
              f'Cost assumption in source: {meta.get("cost_assumption_bps","unavailable")}bp; hypothetical performance, with no verification of actual fills, account costs or capacity.',
              'Historical statistics are descriptive, not evidence of future returns. Dates are source-derived and library-checked; flag any disputed valuation date for confirmation.',
              f'Dashboard: {PAGE}', f'Data: {URL}']
    return {'subject':f'Multi-Strategy morning | {state} | NAV {end:%Y-%m-%d}',
            'body':'\n'.join(lines), 'expected_session':str(expected), 'nav_date':str(end.date()),
            'status':state, 'generated_at_utc':now.astimezone(timezone.utc).isoformat(),
            'performance':performance,'risk_rows':risk_rows,'relative_rows':relative_rows,
            'current_dd':rs['current_dd'],'underwater_days':rs['underwater_days'],
            'meta':meta,'regime':regime,'weights':weights,'risk_contributors':risk,
            'attribution':covered,'attribution_residual':residual if covered else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    response = requests.get(URL, params={'morning':now.isoformat()}, timeout=45)
    response.raise_for_status()
    report = build(response.json(),now)
    out = Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(report['body'])


if __name__ == '__main__':
    main()
