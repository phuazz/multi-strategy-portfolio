"""No look-ahead, correct active-risk denominator and single-session samples."""
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest
from return_context import build


def fixture(end='2026-11-03'):
    # Python months are 1-indexed. Exchange calendar handles year/month boundaries.
    dates=mcal.get_calendar('NYSE').schedule(start_date='2024-01-01',end_date=end).index
    i=np.arange(len(dates)); b=.0002+.008*np.sin(i*.7); a=.0001+.003*np.cos(i*.4)
    return pd.Series(np.cumprod(1+b+a),index=dates),pd.Series(np.cumprod(1+b),index=dates)


def test_prior_estimate_excludes_entire_reported_window():
    m,b=fixture();before=build(m,b)
    start=pd.Timestamp(before['periods']['1M']['start']);m.loc[m.index>start]*=1.1
    after=build(m,b)
    for key in ('model','active'):
        assert before['periods']['1M'][key]['one_sd']==after['periods']['1M'][key]['one_sd']
    assert before['periods']['1M']['model']['return']!=after['periods']['1M']['model']['return']


def test_active_units_use_tracking_error_and_actual_session_count():
    m,b=fixture();p=build(m,b)['periods']['1M'];start=pd.Timestamp(p['start'])
    train=pd.concat([m.pct_change(),b.pct_change()],axis=1).loc[:start].dropna().tail(252)
    expected=(train.iloc[:,0]-train.iloc[:,1]).std(ddof=1)*np.sqrt(p['sessions'])
    assert p['active']['one_sd']==pytest.approx(expected)
    assert p['active']['units']==pytest.approx(p['active']['return']/expected)
    assert p['active']['one_sd']!=p['model']['one_sd']
    assert p['observations']==252 and p['training_end']<=p['start']


def test_historical_gaps_are_excluded_and_window_gaps_fail_closed():
    m,b=fixture();m=m.drop(m.index[-40]);p=build(m,b)['periods']['1D']
    assert p['status']=='ok' and p['excluded_gaps']==2 and p['observations']==252
    m=m.drop(m.index[-2]);assert build(m,b)['periods']['1D']['status']=='unavailable'


@pytest.mark.parametrize('end,start',[('2026-11-02','2026-10-30'),('2027-01-04','2026-12-31')])
def test_month_and_year_boundaries(end,start):
    p=build(*fixture(end))['periods']['1D']
    assert p['start']==start and p['sessions']==1


def test_insufficient_or_missing_benchmark_is_unavailable():
    m,b=fixture()
    assert build(m.tail(252),b.tail(252))['periods']['1D']['status']=='unavailable'
    assert build(m,None)['periods']['1D']['status']=='unavailable'


def test_zero_active_risk_is_unknown_not_infinite_or_zero_units():
    m,_=fixture();p=build(m,m)['periods']['1D']
    assert p['active']['units'] is None and p['active']['one_sd']==0


def test_risk_bar_encoding_is_symmetric_and_clipping_is_labelled():
    from return_context_visuals import segments,RiskMove,gauge
    assert sum(x[1] for x in segments(.7))==pytest.approx(sum(x[1] for x in segments(-.7)))
    assert sum(x[1] for x in segments(3))==5
    assert sum(x[1] for x in segments(0))==0
    assert '(beyond scale)' in RiskMove(-3).text and '-3.00x' in RiskMove(-3).text
    assert 'table' not in gauge(None)
    for v in [-4,-2.5,-1.12,0,.01,.7,3]:
        assert all(min(row)>=0 and sum(row)==pytest.approx(1) for row in segments(v))


def test_benchmark_period_shock_does_not_change_prior_tracking_error():
    m,b=fixture();before=build(m,b)['periods']['1D'];b.iloc[-1]*=1.1
    after=build(m,b)['periods']['1D']
    assert before['active']['one_sd']==after['active']['one_sd']
    assert before['active']['units']!=after['active']['units']
