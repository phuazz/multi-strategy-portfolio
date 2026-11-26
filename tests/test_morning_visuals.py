"""Protect quantitative bar encodings from silently misleading comparisons."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_morning import BarValue, GREEN, RED, bar_html, return_scale, excess, email_digest
from attribution_presentation import leaders, comparison_rows, daily_drivers


def test_positive_negative_use_symmetric_magnitude_scale():
    gain,loss=BarValue(.1,.2),BarValue(-.1,.2)
    assert gain.fraction == loss.fraction == .5
    assert gain.colour==GREEN and loss.colour==RED
    assert '+10.00%' in bar_html(gain) and '-10.00%' in bar_html(loss)


def test_missing_value_is_not_rendered_as_zero_bar():
    assert 'height:4px' not in bar_html(BarValue(None,1,label='-'))
    assert 'height:4px' in bar_html(BarValue(0,1))


def test_scale_includes_benchmarks_and_both_signs():
    assert return_scale({'performance':[{'model':.1,'SPY':-.3,'AOR':.2}]})==.3
    with pytest.raises(ValueError,match='complete observation'):
        _=BarValue(.4,.3).fraction


def test_excess_can_be_positive_when_portfolio_loses():
    value=excess({'model':-.01,'SPY':-.03})
    assert value.text=='+2.00pp' and value.colour==GREEN
    assert excess({'model':.03,'SPY':.05}).colour==RED
    assert excess({'model':.03}).text=='-'


def sample(contributions):
    attrs=[{'ticker':f'T{i}','name':f'holding {i}','strategies':['A'],'avg_weight':1/len(contributions),
            'contrib':v,'known_contrib':v,'coverage':1} for i,v in enumerate(contributions)]
    total=sum(contributions)
    p={'status':'ok','start':'2026-11-02','end':'2026-11-03','issues':[],
       'etf':attrs,'strategy':[{'code':'A','name':'Strategy A','contrib':total,'residual':0,'coverage':1}],
       'model_return':total-.001,'etf_total':total,'strategy_total':total,
       'etf_residual':-.001,'strategy_residual':-.001,'coverage':1}
    return {'performance':[{'period':'1 session','model':p['model_return'],'SPY':0}],
            'nav_date':p['end'],'attribution':{'version':2,'asOf':'2026-11-03','method':'Historical holdings',
                           'periods':{'1D':p,'1M':p}}}


def test_contributors_rank_signs_separately_and_exclude_missing_prices():
    r=sample([.003,-.002,.001,-.004,.002,-.003,.004,-.001,0])
    s=leaders(r['attribution'],'1M')
    assert [a['contrib'] for a in s['positive'][:3]]==[.004,.003,.002]
    assert [a['contrib'] for a in s['negative'][:3]]==[-.004,-.003,-.002]
    r['attribution']['periods']['1D']['etf'][0]['contrib']=None
    html,plain=email_digest(r)
    for body in (html,plain):
        assert 'holding 0' not in body
        assert 'holding 6 (T6)' in body and 'holding 3 (T3)' in body
        assert 'holding 2' not in body and 'Market watch' not in body


@pytest.mark.parametrize('values',[[.001,.002],[-.001,-.002],[0,0]])
def test_one_sided_or_zero_contributions_never_invent_opposite_sign(values):
    html,plain=email_digest(sample(values))
    for body in (html,plain):
        for i,value in enumerate(values):
            assert (f'holding {i} (T{i})' in body) == (value != 0)
        assert ('No signed contribution' in body) == all(v == 0 for v in values)


def test_daily_drivers_cap_and_performance_windows():
    r=sample([-.004,.003,-.002,.001,-.0005,.0001])
    r['etf_return_context']={'periods':{'1D':{'start':'2026-11-02','end':'2026-11-03',
        'rows':[{'ticker':'T0','return':-.024,'current_weight':.05}]}}}
    r['performance'].extend([{'period':'1 week','model':-.01,'SPY':-.02},
                             {'period':'YTD','model':.12}])
    html,plain=email_digest(r)
    for body in (html,plain):
        assert body.index('holding 0') < body.index('holding 1') < body.index('holding 2')
        assert 'holding 4' in body and 'holding 5' not in body
        assert 'Combined impact -25.0 bp' in body
    assert 'holding 0 (T0) · -2.40% · 16.67% · -40.0 bp' in plain
    assert 'holding 1 (T1) · – · 16.67% · +30.0 bp' in plain
    assert '1W · -1.00% · -2.00% · +1.00pp' in plain
    assert 'YTD · +12.00% · – · -' in plain
    r['etf_return_context']['periods']['1D']['start']='2026-11-01'
    with pytest.raises(ValueError,match='dates differ'):
        email_digest(r)


def test_bad_attribution_cannot_be_presented_as_reconciled():
    r=sample([.001,-.002])
    r['attribution']['periods']['1D']['etf_residual']=0
    with pytest.raises(ValueError,match='reconcile'):
        email_digest(r)
    r['attribution']['periods']['1D']['etf'][0]['known_contrib']=float('nan')
    with pytest.raises(ValueError,match='Non-finite'):
        email_digest(r)


def test_active_drivers_rank_priced_exposures_and_bridge_incomplete_coverage():
    r=sample([0, -.001, .002, -.002, .003, .0001, 0])
    period=r['attribution']['periods']['1D']
    period.update(observations=1)
    period['etf'][-1]['contrib']=None
    session=dict(r['performance'][0], start=period['start'], end=period['end'], SPY=-.014)
    selected, bridge=daily_drivers(r['attribution'], session=session)
    assert [row['ticker'] for row in selected]==['T4','T2','T5','T0','T1']
    assert selected[-1]['active']==pytest.approx(.001)  # Lost money, beat the proxy.
    assert bridge['unassigned']==pytest.approx(period['etf_residual'] - session['SPY']/7)
    assert bridge['shown']+bridge['other']+bridge['unassigned']==pytest.approx(session['model']-session['SPY'])
    assert daily_drivers(r['attribution'], session=dict(session,start='2026-10-30'))[1] is None
    assert daily_drivers(r['attribution'], session=dict(session,SPY=None))[1] is None


def test_absent_position_is_zero_but_incomplete_period_is_missing():
    from copy import deepcopy
    a=sample([.001])['attribution']; a['periods']['1D']=deepcopy(a['periods']['1M'])
    p=a['periods']['1D'];p['etf']=[];p['etf_total']=0;p['etf_residual']=p['model_return']
    p['strategy'][0]['residual']=p['strategy_total']
    assert comparison_rows(a,'etf')[0]['1D']==0
    p['status']='unavailable'
    assert comparison_rows(a,'etf')[0]['1D'] is None
