"""ETF volatility uses price returns, prior information and verified USD marks."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest
from etf_return_context import build,validate,leaders


def fixture(end='2026-11-03',ccy='USD'):
    # Python/pandas months are 1-indexed; exchange calendars determine sessions.
    idx=mcal.get_calendar('NYSE').schedule(start_date='2024-12-01',end_date=end).index
    i=np.arange(len(idx));s=pd.Series(100*np.cumprod(1+.001+.01*np.sin(i*.7)),index=idx)
    start=idx[idx<=idx[-1]-pd.DateOffset(months=1)][-1]
    a={'version':2,'asOf':end,'source_commit':'fixture','periods':{
        h:{'start':str(d.date()),'end':end,'status':'ok','etf':[{'ticker':'AAA','name':'Fund A','contrib':.0001}]}
        for h,d in [('1D',idx[-2]),('1M',start)]}}
    panel={'prices':{'AAA':s},'symbols':{'AAA':'AAA'},'currencies':{'AAA':ccy},
           'fx_symbols':{'EUR':'EURUSD=X'},'sources':{'AAA':'Fixture'},'acquired_at_utc':'fixture'}
    if ccy=='EUR':
        x=mcal.get_calendar('XETR').schedule(start_date=idx[0],end_date=end).index
        panel['prices']['AAA']=pd.Series(100.,index=x)
        panel['prices']['EURUSD=X']=s/100
    return a,panel,{'etf_meta':{'AAA':{'name':'Fund A'}}},[{'ticker':'AAA','weight':.3}]


def test_price_return_not_portfolio_contribution_and_weight_independent():
    args=fixture();a=build(*args)['periods']['1D']['rows'][0]
    s=args[1]['prices']['AAA'];expected=s.iloc[-1]/s.iloc[-2]-1
    assert a['return']==pytest.approx(expected)
    assert a['units']==pytest.approx(expected/a['one_sd'])
    assert a['contribution']==.0001
    args[3][0]['weight']=.8
    assert build(*args)['periods']['1D']['rows'][0]['units']==a['units']


def test_reported_window_never_enters_its_own_estimate():
    args=fixture();before=build(*args)['periods']['1M']['rows'][0]
    start=args[0]['periods']['1M']['start'];s=args[1]['prices']['AAA'];s.loc[s.index>start]*=1.2
    after=build(*args)['periods']['1M']['rows'][0]
    assert before['one_sd']==after['one_sd'] and before['units']!=after['units']
    assert after['training_end']<=start and after['observations']==252


def test_usd_fx_is_used_for_both_return_and_volatility():
    args=fixture(ccy='EUR');r=build(*args)['periods']['1D']['rows'][0]
    fx=args[1]['prices']['EURUSD=X']
    assert r['return']==pytest.approx(fx.iloc[-1]/fx.iloc[-2]-1)
    assert r['one_sd']>0 and r['status']=='ok'
    args[1]['prices']['EURUSD=X']=fx.iloc[:-1]
    assert build(*args)['periods']['1D']['rows'][0]['units'] is None


def test_holiday_carry_is_allowed_but_missing_open_close_is_not():
    args=fixture('2026-05-04','EUR')
    assert build(*args)['periods']['1D']['rows'][0]['status']=='ok'
    args[1]['prices']['AAA']=args[1]['prices']['AAA'].iloc[:-1]
    assert build(*args)['periods']['1D']['rows'][0]['units'] is None


def test_missing_training_intervals_are_excluded_without_compressing_time():
    args=fixture();s=args[1]['prices']['AAA'];args[1]['prices']['AAA']=s.drop(s.index[-40])
    r=build(*args)['periods']['1D']['rows'][0]
    assert r['excluded_gaps']==2 and r['observations']==252
    args[1]['prices']['AAA']=s.drop(s.index[-2])
    assert build(*args)['periods']['1D']['rows'][0]['units'] is None


@pytest.mark.parametrize('end,start',[('2026-11-02','2026-10-30'),('2027-01-04','2026-12-31')])
def test_month_and_year_boundaries(end,start):
    p=build(*fixture(end))['periods']['1D']
    assert p['start']==start and p['sessions']==1


def test_inadequate_history_and_zero_volatility_are_not_zero_scores():
    args=fixture();args[1]['prices']['AAA']=args[1]['prices']['AAA'].tail(252)
    assert build(*args)['periods']['1D']['rows'][0]['units'] is None
    args=fixture();args[1]['prices']['AAA'][:]=100
    assert build(*args)['periods']['1D']['rows'][0]['units'] is None


def test_exited_holdings_keep_context_but_do_not_enter_current_email_ranking():
    args=fixture();args[3].clear();result=build(*args)
    assert result['periods']['1M']['rows'][0]['units'] is not None
    assert leaders(result,'1M')==[]
    result['periods']['1M']['rows'][0]['units']=99
    with pytest.raises(ValueError,match='disagree'):validate(result,args[0])


def test_absent_position_has_zero_impact_but_its_own_price_return():
    args=fixture();args[0]['periods']['1D']['etf']=[]
    row=build(*args)['periods']['1D']['rows'][0]
    assert row['contribution']==0 and row['return']!=0 and row['held_in_period'] is False
