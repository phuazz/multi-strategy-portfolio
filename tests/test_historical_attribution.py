"""Protect effective dates, multi-period linking, ownership, FX and reconciliation."""
from copy import deepcopy
import pandas as pd
import pytest
from historical_attribution import build, validate, Marks, curve, histories


def fixture(dates, prices, fills=None, nav=None):
    # Python/pandas months are 1-indexed; fixture dates are exchange sessions.
    idx=pd.to_datetime(dates)
    if fills is None: fills=[{'date':dates[0],'holdings':[{'etf':'AAA','weight':1.}]}]
    if nav is None: nav=prices['AAA']
    reg={'source':{'sleeve_history':{'A':'a.json'}},
         'sleeves':{'A':{'key':'a','name':'Strategy A','alloc':1.,'alloc_tilt':1.}},
         'etf_meta':{t:{'name':'Fund '+t,'tradeAs':t} for t in prices}}
    bundle={'a.json':{'headline':{'trade_history':fills}},'source_commit':'fixture',
            'multi_strategy.json':{'strategies':{'a':{'dates':dates,'equity':nav}}},
            'risk_overlay.json':{'initial_state':'RISK_ON','events':[],'phase22_eem_tilt':{'enabled':False}},
            'live_track.json':{'anchor_date':dates[-1],'effective_weights':{'AAA':1.}}}
    panel={'prices':{t:curve(dates,p) for t,p in prices.items()},'symbols':{t:t for t in prices},
           'currencies':{t:'USD' for t in prices},'fx_symbols':{},'sources':{},'acquired_at_utc':'fixture'}
    return bundle,reg,curve(dates,nav),panel


def test_fill_close_does_not_earn_that_days_return_and_sold_position_survives():
    dates=['2026-10-30','2026-11-02','2026-11-03']
    fills=[{'date':dates[0],'holdings':[{'etf':'AAA','weight':1}]},
           {'date':dates[1],'decision_date':dates[0],'holdings':[{'etf':'BBB','weight':1}]}]
    args=fixture(dates,{'AAA':[100,110,121],'BBB':[100,200,220]},fills,[1,1.1,1.21])
    # At the rebalance close, the old ETF earns Monday's return.
    monday=deepcopy(args)
    monday[0]['live_track.json']['anchor_date']=dates[1]
    monday=(monday[0],monday[1],monday[2].iloc[:2],monday[3])
    p=build(*monday)['periods']['1D']
    assert p['etf'][0]['ticker']=='AAA' and p['etf'][0]['end_weight']==0
    assert p['etf'][0]['contrib']==pytest.approx(.1)
    assert build(*args)['periods']['1D']['etf'][0]['ticker']=='BBB'


def test_linked_month_reconciles_compounding_and_keeps_exited_names():
    dates=pd.bdate_range('2026-10-02','2026-11-03').strftime('%Y-%m-%d').tolist()
    a=[100.]*len(dates);b=[100.]*len(dates);nav=[1.]*len(dates)
    a[1:]=[110.]*(len(dates)-1);b[2:]=[120.]*(len(dates)-2)
    nav[1]=1.1;nav[2:]=[1.32]*(len(dates)-2)
    fills=[{'date':dates[0],'holdings':[{'etf':'AAA','weight':1}]},
           {'date':dates[1],'holdings':[{'etf':'BBB','weight':1}]}]
    p=build(*fixture(dates,{'AAA':a,'BBB':b},fills,nav))['periods']['1M']
    by={r['ticker']:r for r in p['etf']}
    assert p['start']=='2026-10-02' and p['end']=='2026-11-03'
    assert by['AAA']['contrib']==pytest.approx(.1)
    assert by['BBB']['contrib']==pytest.approx(.22)
    assert p['etf_total']==pytest.approx(.32) and abs(p['etf_residual'])<1e-12
    assert by['AAA']['avg_weight']==pytest.approx(1/(len(dates)-1))


def test_same_etf_in_two_strategies_keeps_ownership():
    args=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110]},nav=[1,1.1])
    b,r,n,p=args
    r['sleeves']['A']['alloc']=.6
    r['sleeves']['B']={'key':'b','name':'Strategy B','alloc':.4}
    r['source']['sleeve_history']['B']='b.json';b['b.json']=deepcopy(b['a.json'])
    b['multi_strategy.json']['strategies']['b']=deepcopy(b['multi_strategy.json']['strategies']['a'])
    result=build(b,r,n,p)['periods']['1D']
    assert result['etf'][0]['strategies']==['A','B']
    assert [x['contrib'] for x in result['strategy']]==pytest.approx([.06,.04])
    assert result['etf_total']==pytest.approx(.1)


def test_missing_open_session_is_not_a_zero_and_residual_is_visible():
    b,r,n,p=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110]},nav=[1,1.1])
    p['prices']['AAA']=p['prices']['AAA'].iloc[:1]
    result=build(b,r,n,p)['periods']['1D']
    assert result['etf'][0]['contrib'] is None
    assert result['coverage']==0 and result['status']=='review'
    assert result['etf_residual']==pytest.approx(.1)
    assert result['strategy_total']==pytest.approx(.1)


def test_fx_conversion_includes_currency_return_without_double_counting():
    b,r,n,p=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,100]},nav=[1,1.02])
    p['currencies']['AAA']='EUR';p['fx_symbols']['EUR']='EURUSD=X'
    p['prices']['EURUSD=X']=curve(n.index,[1,1.02])
    result=build(b,r,n,p)['periods']['1D']
    assert result['etf_total']==pytest.approx(.02)


def test_closed_market_can_use_last_close_but_open_market_cannot():
    p={'prices':{'AAA':curve(['2026-12-24'],[100])},'symbols':{'AAA':'AAA'},'currencies':{'AAA':'USD'}}
    marks=Marks(p,pd.Timestamp('2026-12-24'),pd.Timestamp('2026-12-28'))
    assert marks.usd('AAA',pd.Timestamp('2026-12-25'))==100
    assert marks.usd('AAA',pd.Timestamp('2026-12-28')) is None


@pytest.mark.parametrize('dates,base',[
    (['2026-10-30','2026-11-02'],'2026-10-30'), # month boundary
    (['2026-12-31','2027-01-04'],'2026-12-31'), # year boundary and exchange holiday
])
def test_one_day_uses_previous_official_session(dates,base):
    p=build(*fixture(dates,{'AAA':[100,101]}))['periods']['1D']
    assert p['start']==base and p['observations']==1


def test_cost_and_price_residual_is_not_allocated_to_etfs():
    args=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110]},nav=[1,1.099])
    a=build(*args);p=a['periods']['1D']
    assert p['etf_total']==pytest.approx(.1)
    assert p['strategy_total']==pytest.approx(.099)
    assert p['etf_residual']==pytest.approx(-.001)
    assert p['strategy'][0]['residual']==pytest.approx(-.001)
    p['etf_residual']=0
    with pytest.raises(ValueError,match='reconcile'): validate(a)


def test_future_fill_does_not_change_prior_attribution():
    args=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,101]})
    before=build(*args)['periods']['1D']
    args[0]['a.json']['headline']['trade_history'].append({'date':'2026-11-04','holdings':[{'etf':'BBB','weight':1}]})
    assert build(*args)['periods']['1D']==before


def test_live_tail_uses_drifted_anchor_units():
    b,r,n,p=fixture(['2026-11-02','2026-11-03','2026-11-04'],{'AAA':[100,110,121],'BBB':[100,100,100]},nav=[1,1.05,1.105])
    b['a.json']['headline']['trade_history'][0]['holdings']=[{'etf':'AAA','weight':.5},{'etf':'BBB','weight':.5}]
    b['live_track.json']={'anchor_date':'2026-11-02','anchor_equity':1,'effective_weights':{'AAA':.5,'BBB':.5}}
    result=build(b,r,n,p)['periods']['1D']
    assert result['etf_total']==pytest.approx(.055/1.05)
    assert result['etf'][0]['avg_weight']==pytest.approx(.55/1.05)


def test_missing_history_and_missing_model_day_are_explicitly_unavailable():
    args=fixture(['2026-11-02','2026-11-04'],{'AAA':[100,101]})
    assert build(*args)['periods']['1D']['status']=='unavailable'
    args[0]['a.json']['headline']['trade_history']=[]
    assert build(*args)['periods']['1D']['status']=='unavailable'


def test_gate_event_takes_effect_after_its_close_and_has_separate_owner():
    b,r,n,p=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110],'SHY':[100,101]},nav=[1,1.055])
    b['multi_strategy.json']['strategies']['a']['equity']=[1,1.1]
    b['risk_overlay.json'].update({'events':[{'date':'2026-11-02','direction':'RISK_OFF'}],
                                  'gate_parameters':{'derisk_fraction':.5,'fallback_ticker':'SHY'}})
    result=build(b,r,n,p)['periods']['1D']
    assert {x['code']:x['contrib'] for x in result['strategy']}==pytest.approx({'A':.05,'DEFENSIVE':.005})
    assert result['strategy_residual']==pytest.approx(0)
    b['risk_overlay.json']['events'][0]['date']='2026-11-03'
    result=build(b,r,n,p)['periods']['1D']
    assert [x['code'] for x in result['strategy']]==['A']


def test_incomplete_live_strategy_is_not_reported_as_a_full_return():
    b,r,n,p=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110]},nav=[1,1.1])
    b['live_track.json']={'anchor_date':'2026-11-02','anchor_equity':1,'effective_weights':{'AAA':1.}}
    p['prices']['AAA']=p['prices']['AAA'].iloc[:1]
    result=build(b,r,n,p)['periods']['1D']
    assert result['strategy'][0]['contrib'] is None
    assert result['strategy_residual']==pytest.approx(.1)


def test_tilt_is_funded_from_strategy_allocation_and_missing_mark_is_unknown():
    b,r,n,p=fixture(['2026-11-02','2026-11-03'],{'AAA':[100,110],'EEM':[100,120]},nav=[1,1.11])
    r['sleeves']['A']['alloc_tilt']=.9
    r['sleeves']['TILT']={'name':'EM tilt','alloc_tilt':.1}
    b['multi_strategy.json']['strategies']['a']['equity']=[1,1.1]
    b['risk_overlay.json']['phase22_eem_tilt']={'enabled':True,'initial_state':'EM_TILT_ON','events':[]}
    result=build(b,r,n,p)['periods']['1D']
    assert {x['code']:x['contrib'] for x in result['strategy']}==pytest.approx({'A':.09,'TILT':.02})
    assert result['strategy_residual']==pytest.approx(0)
    p['prices']['EEM']=p['prices']['EEM'].iloc[:1]
    result=build(b,r,n,p)['periods']['1D']
    assert next(x for x in result['strategy'] if x['code']=='TILT')['contrib'] is None
    assert result['strategy_residual']==pytest.approx(.02)
