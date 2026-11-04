"""Protect quantitative bar encodings from silently misleading comparisons."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_morning import BarValue, GREEN, RED, bar_html, return_scale, excess, contribution_summary, contribution_html


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
    attrs=[{'name':f'holding {i}','weight':1/len(contributions),'1D':{'contrib':v}} for i,v in enumerate(contributions)]
    return {'attribution':attrs,'performance':[{'model':sum(contributions)-.001}],
            'attribution_residual':-.001,'meta':{'built_at_utc':'2026-11-04T03:00:00Z'}}


def test_contributions_rank_signs_separately_and_reconcile_all_rows():
    r=sample([.003,-.002,.001,-.004,.002,-.003,.004,-.001,0])
    s=contribution_summary(r)
    assert [a['1D']['contrib'] for a in s['positive'][:3]]==[.004,.003,.002]
    assert [a['1D']['contrib'] for a in s['negative'][:3]]==[-.004,-.003,-.002]
    assert s['positive_total']==pytest.approx(.01)
    assert s['negative_total']==pytest.approx(-.01)
    assert s['net']+s['residual']==pytest.approx(r['performance'][0]['model'])
    html=contribution_html(r)
    assert html.count('height:4px;background:')==6
    assert 'holding 2' not in html and 'holding 7' not in html
    assert 'Reconciliation review' in html
    assert '11.1% of NAV' in html


@pytest.mark.parametrize('values',[[.001,.002],[-.001,-.002],[0,0]])
def test_one_sided_or_zero_contributions_never_invent_opposite_sign(values):
    r=sample(values)
    html=contribution_html(r)
    assert html.count('height:4px;background:')==sum(v!=0 for v in values)
    assert 'None in the supplied estimates.' in html


def test_bad_attribution_cannot_be_presented_as_reconciled():
    r=sample([.001,-.002])
    r['attribution_residual']=0
    with pytest.raises(ValueError,match='reconcile'):
        contribution_html(r)
    r['attribution'][0]['1D']['contrib']=float('nan')
    with pytest.raises(ValueError,match='Non-finite'):
        contribution_html(r)
