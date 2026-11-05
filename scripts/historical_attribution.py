"""Historical model attribution; consumes published holdings, never generates signals.

Python/pandas months are 1-indexed. Fill-date weights earn returns AFTER that close.
Daily contributions are linked by prior official NAV / period-start NAV. Residuals
remain explicit; price discrepancies and costs are never allocated pro rata to ETFs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math

import pandas as pd
import pandas_market_calendars as mcal

REVIEW_RESIDUAL = .0005  # Five basis points, symmetric reporting threshold.
METHOD = ('Historical published model holdings, effective after their fill-date close; '
          'daily contributions linked using prior official NAV / starting NAV. '
          'ETF contributions are gross of model trading costs; strategies use published '
          'net sleeve returns through the engine anchor and fixed-book marks thereafter. '
          'Unexplained residuals are shown separately.')


def curve(dates, values):
    s = pd.Series(values, index=pd.to_datetime(dates), dtype=float)
    if s.index.has_duplicates or not s.index.is_monotonic_increasing:
        raise ValueError('Attribution dates must be ordered and unique')
    if not all(math.isfinite(v) and v > 0 for v in s):
        raise ValueError('Attribution prices/NAV must be positive and finite')
    return s


def histories(bundle, registry):
    out = {}
    for code, fn in registry['source']['sleeve_history'].items():
        rows = bundle.get(fn, {}).get('headline', {}).get('trade_history', [])
        if not rows:
            raise ValueError(f'Historical holdings missing for strategy {code}')
        dates = [pd.Timestamp(r['date']) for r in rows]
        if dates != sorted(set(dates)):
            raise ValueError(f'Duplicate or unordered historical fills for {code}')
        out[code] = []
        for row, day in zip(rows, dates):
            if row.get('decision_date') and pd.Timestamp(row['decision_date']) > day:
                raise ValueError('Decision date is after fill date')
            weights = {h['etf']: float(h['weight']) for h in row['holdings']}
            if len(weights) != len(row['holdings']) or any(not math.isfinite(w) or w < 0 for w in weights.values()):
                raise ValueError('Invalid historical holdings')
            if sum(weights.values()) > 1.002:
                raise ValueError('Historical weights exceed one beyond rounding tolerance')
            out[code].append((day, weights))
    return out


def held_at(history, day):
    rows = [w for d, w in history if d <= day]
    if not rows:
        raise ValueError(f'No holdings at {day.date()}')
    return rows[-1]


def state_at(block, day, on, off):
    state = block.get('initial_state')
    if state not in (on, off):
        raise ValueError('Initial overlay state is not declared')
    for event in sorted(block.get('events', []), key=lambda x: x['date']):
        if pd.Timestamp(event['date']) <= day:
            state = event['direction']
    if state not in (on, off):
        raise ValueError('Unknown overlay state')
    return state == on


def allocations(overlay, registry, day):
    tilt = overlay.get('phase22_eem_tilt', {})
    on = state_at(tilt, day, 'EM_TILT_ON', 'EM_TILT_OFF') if tilt.get('enabled') else False
    # A stale tilt can be forced off by the engine without an event. Do not infer
    # a historical on/off decision across that exception from today's flag.
    if tilt.get('signal_stale') and day >= pd.Timestamp(tilt.get('signal_as_of', day)):
        raise ValueError('Stale tilt signal prevents verified historical allocation')
    off = state_at(overlay, day, 'RISK_OFF', 'RISK_ON')
    fraction = float(overlay.get('gate_parameters', {}).get('derisk_fraction', .5)) if off else 0.
    a = {c: float(r.get('alloc_tilt' if on else 'alloc', 0)) * (1-fraction)
         for c, r in registry['sleeves'].items() if r.get('key')}
    a['TILT'] = float(registry['sleeves'].get('TILT', {}).get('alloc_tilt', 0)) * (1-fraction) if on else 0.
    a['DEFENSIVE'] = fraction
    return a


def position_legs(history, overlay, registry, day):
    alloc = allocations(overlay, registry, day)
    legs = {(c, t): alloc[c]*w for c, rows in history.items() for t, w in held_at(rows, day).items() if w > 0}
    tilt_ticker = overlay.get('phase22_eem_tilt', {}).get('parameters', {}).get('eem_ticker', 'EEM')
    fallback = overlay.get('gate_parameters', {}).get('fallback_ticker', 'SHY')
    if alloc['TILT']:
        legs['TILT', tilt_ticker] = alloc['TILT']
    if alloc['DEFENSIVE']:
        legs['DEFENSIVE', fallback] = alloc['DEFENSIVE']
    return legs, alloc


def required_tickers(bundle, registry, end):
    history = histories(bundle, registry)
    start = pd.Timestamp(end) - pd.DateOffset(months=1) - pd.Timedelta(days=10)
    names = set(bundle['live_track.json'].get('effective_weights', {}))
    for rows in history.values():
        names.update(held_at(rows, start))
        for day, weights in rows:
            if start <= day <= pd.Timestamp(end): names.update(weights)
    names.update(['EEM', bundle['risk_overlay.json'].get('gate_parameters', {}).get('fallback_ticker', 'SHY')])
    return names


def symbol_for(ticker, registry, bundle):
    # The engine retains the Bitcoin label if its implementation switches to IBIT.
    basis = bundle.get('thematic_rotation.json', {}).get('c_btc_basis')
    if ticker == 'BTC-USD' and basis not in (None, 'incumbent'):
        if basis == 'ibit': return 'IBIT'
        raise ValueError(f'Unrecognised Bitcoin pricing basis: {basis}')
    return registry['etf_meta'].get(ticker, {}).get('tradeAs', ticker)


def fetch_panel(bundle, registry, end, *, fetch=True):
    """One native adjusted-close acquisition for all period holdings, including exits.

    The engine export is the fallback for USD/EUR lines only. Its CNY cache can
    already be USD-converted, so an unstamped CNY export is not converted again.
    """
    try:
        names = required_tickers(bundle, registry, end)
    except ValueError:
        # The build reports missing history as unavailable, without darkening NAV.
        names = set(bundle['live_track.json'].get('effective_weights', {}))
    symbols = {t: symbol_for(t, registry, bundle) for t in names}
    currencies = {t: 'EUR' if s.endswith('.DE') else 'CNY' if s.endswith('.SZ') else 'USD' for t,s in symbols.items()}
    fx_symbols = {'EUR': 'EURUSD=X', 'CNY': 'CNYUSD=X'}
    requested = sorted(set(symbols.values()) | {fx_symbols[c] for c in currencies.values() if c != 'USD'})
    raw_series, sources = {}, {}
    for symbol in set(symbols.values()):
        entry = bundle.get('holdings_prices_1y.json', {}).get('prices', {}).get(symbol)
        if entry and not symbol.endswith('.SZ'):
            pairs = [(d,v) for d,v in zip(entry['dates'],entry['prices']) if v is not None]
            if pairs:
                raw_series[symbol] = curve(*zip(*pairs))
                sources[symbol] = 'Engine published adjusted-close export (rounded)'
    if fetch:
        try:
            import yfinance as yf
            # Include enough pre-window history for the ETF risk-context estimate.
            start = pd.Timestamp(end)-pd.DateOffset(months=18)
            raw = yf.download(requested, start=str(start.date()), end=str((pd.Timestamp(end)+pd.Timedelta(days=1)).date()),
                              auto_adjust=True, progress=False, threads=False)
            close = raw['Close'] if isinstance(raw.columns,pd.MultiIndex) else raw[['Close']].rename(columns={'Close':requested[0]})
            for symbol in requested:
                if symbol in close:
                    s = close[symbol].dropna()
                    if not s.empty:
                        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                        raw_series[symbol] = curve(s.index, s.values)
                        sources[symbol] = 'Yahoo Finance adjusted close'
        except Exception as exc:
            print(f'  [attribution] supplemental price acquisition unavailable: {type(exc).__name__}')
    return {'prices':raw_series, 'symbols':symbols, 'currencies':currencies,
            'fx_symbols':fx_symbols, 'sources':sources,
            'acquired_at_utc':datetime.now(timezone.utc).isoformat()}


class Marks:
    def __init__(self, panel, start, end):
        self.panel = panel
        self.sessions = {name: mcal.get_calendar(name).schedule(start_date=start-pd.Timedelta(days=14),end_date=end).index
                         for name in ('NYSE','XETR','SSE')}
        self.cache = {}

    def native(self, symbol, day, calendar):
        expected = day
        if calendar:
            dates = self.sessions[calendar]
            prior = dates[dates<=day]
            if not len(prior): return None
            expected = prior[-1]
        s = self.panel['prices'].get(symbol)
        if s is None or expected not in s.index: return None
        return float(s.loc[expected])

    def usd(self, ticker, day):
        key=(ticker,day)
        if key in self.cache: return self.cache[key]
        symbol=self.panel['symbols'].get(ticker,ticker)
        ccy=self.panel['currencies'].get(ticker,'USD')
        calendar='XETR' if ccy=='EUR' else 'SSE' if ccy=='CNY' else None if symbol.endswith('-USD') else 'NYSE'
        value=self.native(symbol,day,calendar)
        if value is not None and ccy!='USD':
            # FX must be stamped on the valuation date; no open-day forward fill.
            rate=self.native(self.panel['fx_symbols'][ccy],day,None)
            value=value*rate if rate is not None else None
        self.cache[key]=value
        return value


def build(bundle, registry, model, panel):
    model=curve(model.index,model.values)
    if len(model)<2: raise ValueError('Attribution requires at least two official NAV observations')
    end=model.index[-1]
    starts={'1D':model.index[-2], '1M':model.index[model.index <= end-pd.DateOffset(months=1)][-1]
            if any(model.index<=end-pd.DateOffset(months=1)) else None}
    output={'version':2,'method':METHOD,'asOf':str(end.date()),'currency':'USD',
            'source_commit':bundle.get('source_commit'),'prices_acquired_at_utc':panel['acquired_at_utc'],
            'periods':{}}
    try:
        history=histories(bundle,registry)
    except ValueError as exc:
        for hz,start in starts.items(): output['periods'][hz]=unavailable(start,end,str(exc))
        return output
    marks=Marks(panel,min(s for s in starts.values() if s is not None),end)
    for hz,start in starts.items():
        if start is None:
            output['periods'][hz]=unavailable(start,end,'Insufficient official NAV history');continue
        try:
            output['periods'][hz]=period(bundle,registry,model.loc[start:end],history,marks)
        except ValueError as exc:
            output['periods'][hz]=unavailable(start,end,str(exc))
    validate(output,model)
    return output


def unavailable(start,end,reason):
    return {'start':str(start.date()) if start is not None else None,'end':str(end.date()),
            'status':'unavailable','issues':[reason],'etf':[],'strategy':[], 'reconciled':False}


def period(bundle, registry, nav, history, marks):
    start,end=nav.index[0],nav.index[-1]
    expected=marks.sessions['NYSE']; missing=expected[(expected>start)&(expected<=end)].difference(nav.index)
    if len(missing): raise ValueError('Official NAV has missing NYSE sessions: '+', '.join(str(d.date()) for d in missing))
    overlay=bundle['risk_overlay.json']; live=bundle['live_track.json']; anchor=pd.Timestamp(live['anchor_date'])
    multi=bundle['multi_strategy.json']['strategies']
    sleeve_nav={c:curve(multi[r['key']]['dates'],multi[r['key']]['equity'])
                for c,r in registry['sleeves'].items() if r.get('key')}
    etf_c=defaultdict(float); strat_c=defaultdict(float); leg_c=defaultdict(float)
    avg=defaultdict(float); strat_avg=defaultdict(float); owners=defaultdict(set)
    missing_weight=defaultdict(float); missing_strategy=defaultdict(float); missing_rows=set(); issues=[]; daily=[]
    incomplete_live=set()
    live_legs=None
    if end>anchor:
        live_legs,_=position_legs(history,overlay,registry,anchor)
        totals=defaultdict(float)
        for (c,t),w in live_legs.items(): totals[t]+=w
        actual=live['effective_weights']
        if any(abs(totals[t]-actual.get(t,0))>.0002 for t in set(totals)|set(actual)):
            raise ValueError('Historical strategy ownership does not match the published live book')
        live_legs={key:w*actual.get(key[1],0)/totals[key[1]] for key,w in live_legs.items() if totals[key[1]]}
    for prev,day in zip(nav.index[:-1],nav.index[1:]):
        model_ret=float(nav[day]/nav[prev]-1); factor=float(nav[prev]/nav[start])
        legs,alloc=position_legs(history,overlay,registry,prev)
        is_live=day>anchor
        if is_live: legs=live_legs
        day_etf=defaultdict(float); day_strategy=defaultdict(float); coverage=0.
        for (code,ticker),weight in legs.items():
            if weight<=0: continue
            owners[ticker].add(code)
            p0,p1=marks.usd(ticker,prev),marks.usd(ticker,day)
            if is_live:
                base=marks.usd(ticker,anchor)
                if base is None: p0=None
                effective=weight*float(live['anchor_equity'])/float(nav[prev])*(p0/base) if p0 is not None else weight
            else: effective=weight
            avg[ticker]+=effective; strat_avg[code]+=effective
            if p0 is None or p1 is None:
                missing_weight[ticker]+=effective; missing_strategy[code]+=effective
                if is_live or code in ('TILT','DEFENSIVE'): incomplete_live.add(code)
                missing_rows.add((ticker,str(day.date())));continue
            contribution=effective*(p1/p0-1)
            coverage+=effective
            day_etf[ticker]+=contribution; leg_c[code,ticker]+=contribution*factor
            if is_live or code in ('TILT','DEFENSIVE'): day_strategy[code]+=contribution
        if not is_live:
            for code,s in sleeve_nav.items():
                if prev not in s.index or day not in s.index:
                    raise ValueError(f'Strategy {code} NAV is missing a matched endpoint')
                day_strategy[code]=alloc[code]*float(s[day]/s[prev]-1)
        for t,v in day_etf.items(): etf_c[t]+=v*factor
        for c,v in day_strategy.items(): strat_c[c]+=v*factor
        daily.append({'date':str(day.date()),'model_return':model_ret,'etf_total':sum(day_etf.values()),
                      'strategy_total':sum(day_strategy.values()),'link_factor':factor,'covered_weight':coverage})
    n=len(daily)
    end_legs,_=position_legs(history,overlay,registry,end)
    end_weights=defaultdict(float)
    for (_,t),w in end_legs.items():end_weights[t]+=w
    rows=[]
    for t in sorted(avg):
        meta=registry['etf_meta'].get(t,{})
        complete=missing_weight[t]==0
        symbol=marks.panel['symbols'].get(t,t)
        series=marks.panel['prices'].get(symbol)
        observed=series.loc[series.index<=end] if series is not None else pd.Series(dtype=float)
        rows.append({'ticker':t,'name':meta.get('name',t),'theme':meta.get('theme','Other'),'strategies':sorted(owners[t]),
                     'avg_weight':avg[t]/n,'end_weight':end_weights[t],
                     'contrib':etf_c[t] if complete else None,'known_contrib':etf_c[t],
                     'coverage':1-missing_weight[t]/avg[t] if avg[t] else 1,
                     'price_symbol':symbol,'price_asOf':str(observed.index[-1].date()) if len(observed) else None,
                     'price_source':marks.panel['sources'].get(symbol,'Unavailable')})
    strategies=[]
    for code in sorted(set(strat_avg)|set(strat_c)):
        net=strat_c[code]; gross=sum(v for (c,t),v in leg_c.items() if c==code)
        strategies.append({'code':code,'name':registry['sleeves'].get(code,{}).get('name','Defensive overlay'),
                           'contrib':None if code in incomplete_live else net,'known_contrib':net,
                           'avg_weight':strat_avg[code]/n,'etf_total':gross,
                           'residual':net-gross,'coverage':1-missing_strategy[code]/strat_avg[code] if strat_avg[code] else 1})
    total=float(nav.iloc[-1]/nav.iloc[0]-1); etotal=sum(etf_c.values()); stotal=sum(strat_c.values())
    if missing_rows: issues.append(f'{len(missing_rows)} holding/session marks unavailable; incomplete ETF rows show no full-period figure')
    if abs(total-etotal)>=REVIEW_RESIDUAL: issues.append('ETF reconciliation residual exceeds 5 bp')
    if abs(total-stotal)>=REVIEW_RESIDUAL: issues.append('Strategy reconciliation residual exceeds 5 bp')
    result={'start':str(start.date()),'end':str(end.date()),'observations':n,'status':'review' if issues else 'ok',
            'issues':issues,'etf':rows,'strategy':strategies,'daily':daily,'model_return':total,
            'etf_total':etotal,'strategy_total':stotal,'etf_residual':total-etotal,'strategy_residual':total-stotal,
            'coverage':1-sum(missing_weight.values())/sum(avg.values()) if sum(avg.values()) else 0,
            'includes_live_tail':end>anchor,
            'missing_marks':[{'ticker':t,'date':d} for t,d in sorted(missing_rows)],'reconciled':True}
    return result


def validate(attribution, model=None):
    """Fail closed on broken bridges; explicit residual is not a claim of full explanation."""
    if attribution.get('version')!=2: raise ValueError('Historical attribution version is missing')
    if set(attribution.get('periods',{})) != {'1D','1M'}:
        raise ValueError('Both attribution periods are required')
    if model is not None and attribution['asOf']!=str(model.index[-1].date()):
        raise ValueError('Attribution is stale relative to official NAV')
    for hz,p in attribution['periods'].items():
        if p['status']=='unavailable': continue
        if p['end']!=attribution['asOf']: raise ValueError('Attribution valuation dates differ')
        if model is not None:
            expected_start=model.index[-2] if hz=='1D' else model.index[model.index<=model.index[-1]-pd.DateOffset(months=1)][-1]
            if p['start']!=str(expected_start.date()): raise ValueError('Attribution period start is not the matched NAV anchor')
        if model is not None and not math.isclose(p['model_return'],float(model.loc[p['end']]/model.loc[p['start']]-1),abs_tol=1e-10):
            raise ValueError('Attribution does not match official NAV endpoints')
        for kind in ('etf','strategy'):
            values=[r.get('known_contrib',r['contrib']) for r in p[kind]]
            if not all(math.isfinite(v) for v in values): raise ValueError('Non-finite attribution')
            if not math.isclose(sum(values),p[kind+'_total'],abs_tol=1e-10): raise ValueError('Attribution rows do not sum')
            if not math.isclose(sum(values)+p[kind+'_residual'],p['model_return'],abs_tol=1e-10):
                raise ValueError('Attribution bridge does not reconcile')
        if not math.isclose(sum(r['residual'] for r in p['strategy'])+p['strategy_residual'],p['etf_residual'],abs_tol=1e-10):
            raise ValueError('ETF and strategy bridges disagree')
