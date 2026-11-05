"""ETF price-return context, independent of portfolio weights and contribution.

Python/pandas months are 1-indexed. USD marks use the portfolio's NYSE valuation
clock, with native closes carried only across verified local exchange holidays.
"""
import math
import pandas as pd
from historical_attribution import Marks

METHOD=('Full-window USD adjusted ETF/proxy return divided by its own estimated horizon volatility. '
        '252 prior valid NYSE valuation-interval returns, ending no later than the period-start close; '
        'sample standard deviation scaled by the square root of the actual NYSE interval count. '
        'FX uses same-date rates; local closes are asynchronous and carried only across verified exchange holidays. '
        'Missing open-session marks are not filled. The ratio includes income and carry and is not a z-score, '
        'probability or statistical surprise. Monthly scaling assumes stable variance and no serial correlation. '
        'ETF return covers the full window, including days not held; portfolio contribution uses historical holdings.')


def build(attribution,panel,registry,current_weights):
    end=pd.Timestamp(attribution['asOf'])
    first=end-pd.DateOffset(months=18)
    marks=Marks(panel,first,end)
    sessions=marks.sessions['NYSE'];sessions=sessions[sessions>=first]
    old={r['ticker']:r for p in attribution['periods'].values() for r in p['etf']}
    current={r['ticker']:r for r in current_weights if r.get('weight',0)>0}
    names=sorted(set(old)|set(current))
    levels={t:pd.Series([marks.usd(t,d) for d in sessions],index=sessions,dtype=float) for t in names}
    output={'version':1,'asOf':attribution['asOf'],'method':METHOD,'currency':'USD',
            'source_commit':attribution.get('source_commit'),
            'prices_acquired_at_utc':panel.get('acquired_at_utc'),'periods':{}}
    for hz,ap in attribution['periods'].items():
        p={'start':ap['start'],'end':ap['end'],'rows':[]};output['periods'][hz]=p
        impacts={r['ticker']:r for r in ap['etf']}
        for ticker in names:
            meta=registry['etf_meta'].get(ticker,{})
            row={'ticker':ticker,'name':meta.get('name',ticker),
                 'price_symbol':panel['symbols'].get(ticker,ticker),
                 'price_source':panel.get('sources',{}).get(panel['symbols'].get(ticker,ticker),'Unavailable'),
                 'current_weight':current.get(ticker,{}).get('weight',0),
                 'contribution':None if ap['status']=='unavailable' else impacts.get(ticker,{}).get('contrib',0.),
                 'held_in_period':ticker in impacts,'return':None,'one_sd':None,'units':None,
                 'status':'unavailable','reason':'Insufficient period history','observations':0,
                 'training_start':None,'training_end':None,'excluded_gaps':None,'missing_window':None}
            p['rows'].append(row)
            s=levels[ticker];valid=s.dropna();row['price_asOf']=str(valid.index[-1].date()) if len(valid) else None
            if ap['start'] is None:continue
            start=pd.Timestamp(ap['start'])
            daily=s.pct_change(fill_method=None)
            window=daily.loc[(daily.index>start)&(daily.index<=end)]
            p['sessions']=len(window)
            if start not in s.index or window.empty:continue
            if pd.notna(s[start]) and pd.notna(s[end]):row['return']=float(s[end]/s[start]-1)
            row['missing_window']=int(window.isna().sum())
            training=daily.loc[:start].dropna().tail(252);row['observations']=len(training)
            if len(training):
                offset=sessions.get_loc(training.index[0])
                row['training_start']=str(sessions[offset-1].date())
                row['training_end']=str(training.index[-1].date())
                row['excluded_gaps']=int(daily.loc[training.index[0]:training.index[-1]].isna().sum())
            if len(training)==252:
                row['one_sd']=float(training.std(ddof=1)*math.sqrt(len(window)))
            if row['missing_window']:
                row['reason']='Missing price or FX in the reported window'
            elif len(training)<252:
                row['reason']='Fewer than 252 prior valid USD valuation returns'
            elif row['one_sd']<=1e-12:
                row['reason']='Prior volatility is zero or too small'
            else:
                row.update(status='ok',reason=None,units=row['return']/row['one_sd'])
    validate(output,attribution)
    return output


def validate(context,attribution):
    if context.get('version')!=1 or context['asOf']!=attribution['asOf']:
        raise ValueError('ETF risk context version or valuation date differs')
    if set(context['periods'])!={'1D','1M'}:raise ValueError('ETF risk context needs both horizons')
    for hz,p in context['periods'].items():
        ap=attribution['periods'][hz]
        if (p['start'],p['end'])!=(ap['start'],ap['end']):raise ValueError('ETF risk windows differ from attribution')
        seen=set();impacts={r['ticker']:r['contrib'] for r in ap['etf']}
        for r in p['rows']:
            if r['ticker'] in seen:raise ValueError('Duplicate ETF risk row')
            seen.add(r['ticker'])
            expected=None if ap['status']=='unavailable' else impacts.get(r['ticker'],0.)
            if r['contribution']!=expected:raise ValueError('ETF contribution differs from attribution')
            for key in ('return','one_sd','units'):
                if r[key] is not None and not math.isfinite(r[key]):raise ValueError('Non-finite ETF risk context')
            if (r['status']=='ok')!=(r['units'] is not None):raise ValueError('ETF risk status and availability disagree')
            if r['units'] is not None:
                if r['status']!='ok' or r['missing_window'] or r['observations']!=252 or r['training_end']>p['start']:
                    raise ValueError('Unverified or forward-looking ETF risk estimate')
                if r['one_sd']<=1e-12 or not math.isclose(r['units'],r['return']/r['one_sd'],abs_tol=1e-10):
                    raise ValueError('ETF return and risk units disagree')
        if not set(impacts).issubset(seen):raise ValueError('Historical holding missing from ETF risk context')


def leaders(context,horizon,limit=3):
    """Rank current holdings symmetrically, without mistaking exits for current risk."""
    rows=context.get('periods',{}).get(horizon,{}).get('rows',[])
    return sorted([r for r in rows if r['current_weight']>0 and r['units'] is not None],
                  key=lambda r:(-abs(r['units']),r['ticker']))[:limit]
