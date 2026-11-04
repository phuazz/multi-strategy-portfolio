"""Protect quantitative bar encodings from silently misleading comparisons."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_morning import BarValue, GREEN, RED, bar_html, return_scale, excess, contribution_html
from attribution_presentation import leaders, comparison_rows


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
    return {'attribution':{'version':2,'asOf':'2026-11-03','method':'Historical holdings',
                           'periods':{'1D':p,'1M':p}}}


def test_contributors_rank_signs_separately_and_exclude_missing_prices():
    r=sample([.003,-.002,.001,-.004,.002,-.003,.004,-.001,0])
    s=leaders(r['attribution'],'1M')
    assert [a['contrib'] for a in s['positive'][:3]]==[.004,.003,.002]
    assert [a['contrib'] for a in s['negative'][:3]]==[-.004,-.003,-.002]
    r['attribution']['periods']['1D']['etf'][0]['contrib']=None
    html=contribution_html(r)
    assert 'holding 0' not in html
    assert '1D ETF contributors' in html and '1M ETF contributors' in html
    assert 'not treated as zero' in html


@pytest.mark.parametrize('values',[[.001,.002],[-.001,-.002],[0,0]])
def test_one_sided_or_zero_contributions_never_invent_opposite_sign(values):
    html=contribution_html(sample(values))
    assert 'None with complete price coverage.' in html


def test_bad_attribution_cannot_be_presented_as_reconciled():
    r=sample([.001,-.002])
    r['attribution']['periods']['1D']['etf_residual']=0
    with pytest.raises(ValueError,match='reconcile'):
        contribution_html(r)
    r['attribution']['periods']['1D']['etf'][0]['known_contrib']=float('nan')
    with pytest.raises(ValueError,match='Non-finite'):
        contribution_html(r)


def test_absent_position_is_zero_but_incomplete_period_is_missing():
    from copy import deepcopy
    a=sample([.001])['attribution']; a['periods']['1D']=deepcopy(a['periods']['1M'])
    p=a['periods']['1D'];p['etf']=[];p['etf_total']=0;p['etf_residual']=p['model_return']
    p['strategy'][0]['residual']=p['strategy_total']
    assert comparison_rows(a,'etf')[0]['1D']==0
    p['status']='unavailable'
    assert comparison_rows(a,'etf')[0]['1D'] is None
