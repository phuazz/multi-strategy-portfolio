"""Lagged realised-volatility context, not a forecast or significance test.

Python/pandas months are 1-indexed. Only consecutive NYSE-session returns enter
the matched 252-observation estimate; period anchors use date libraries.
"""
import math
import pandas as pd
import pandas_market_calendars as mcal
from historical_attribution import curve

METHOD = ('252 prior matched single-session returns, known at the period-start close; '
          'sample standard deviation scaled by the square root of the actual session count. '
          'Model return / model volatility; excess return / active-return volatility. '
          'Zero-centred volatility units, without subtracting an expected return; not a z-score, '
          'probability band or risk limit. Historical model risk, not a current-holdings forecast. '
          'Monthly scaling approximates compounding and assumes stable variance and no serial correlation.')


def build(model, benchmark):
    model=curve(model.index,model.values)
    if len(model)<2: raise ValueError('Return context requires two NAV observations')
    end=model.index[-1]
    month=model.index[model.index<=end-pd.DateOffset(months=1)]
    starts={'1D':model.index[-2], '1M':month[-1] if len(month) else None}
    output={'version':1,'asOf':str(end.date()),'method':METHOD,
            'benchmark':'S&P 500 TR proxy (SPY adjusted close)','periods':{}}
    benchmark=curve(benchmark.index,benchmark.values) if benchmark is not None else pd.Series(dtype=float)
    sessions=mcal.get_calendar('NYSE').schedule(start_date=model.index[0],end_date=end).index
    # Reindex before differencing: missing prices cannot become multi-day returns.
    panel=pd.DataFrame({'model':model,'benchmark':benchmark}).reindex(sessions)
    daily=panel.pct_change(fill_method=None)
    for horizon,start in starts.items():
        p={'start':str(start.date()) if start is not None else None,'end':str(end.date()),
           'status':'unavailable','reason':'Insufficient matched history'}
        output['periods'][horizon]=p
        if start is None: continue
        window=daily.loc[(daily.index>start)&(daily.index<=end)]
        if start not in sessions or end not in sessions or window.empty or window.isna().any().any():
            p['reason']='Reported window contains a missing model or benchmark session';continue
        training=daily.loc[daily.index<=start].dropna().tail(252)
        if len(training)<252: continue
        n=len(window)
        values={'model':(float(model.loc[end]/model.loc[start]-1),training['model']),
                'active':(float(model.loc[end]/model.loc[start]-benchmark.loc[end]/benchmark.loc[start]),training['model']-training['benchmark'])}
        first=sessions.get_loc(training.index[0])
        p.update(status='ok',reason=None,sessions=n,observations=len(training),
                 training_start=str(sessions[first-1].date()),training_end=str(training.index[-1].date()),
                 excluded_gaps=int(daily.loc[training.index[0]:training.index[-1]].isna().any(axis=1).sum()))
        for key,(value,history) in values.items():
            sd=float(history.std(ddof=1)*math.sqrt(n))
            p[key]={'return':value,'one_sd':sd,'units':value/sd if sd>1e-12 else None,
                    'reason':None if sd>1e-12 else 'Prior volatility is zero or too small'}
    return output


def units(value):
    return 'Unavailable' if value is None else f'{value:+.2f}x'


def rows(context):
    result=[]
    for horizon,p in context.get('periods',{}).items():
        for key,label in [('model','Model'),('active','Excess vs S&P 500 TR proxy')]:
            result.append({'horizon':horizon,'label':label,'kind':key,
                           **p.get(key,{'return':None,'one_sd':None,'units':None}), 'period':p})
    return result
