"""Private commentary uses exact dates, source links and verified holdings only."""
from copy import deepcopy
from private_market_context import stamp
from test_private_market_context import companion, NOW
from portfolio_commentary import build, html


def report():
    return dict(nav_date='2026-11-04',generated_at_utc=NOW.isoformat(),
                market_context=companion(),etf_return_context={'periods':{'1D':{'rows':[
                    dict(ticker='SPY',current_weight=.1),dict(ticker='QQQ',current_weight=0)]}}})


def test_sources_and_qualitative_context_without_portfolio_estimates():
    r=report();c=build(r)
    assert 'Current holdings: SPY' in c['paragraphs'][0][1]
    assert c['sources'][0]['url']=='https://example.org/market'
    assert '[1; reported]' in html(r) and 'Interpretation:' in html(r)
    assert 'not causal attribution' in html(r)


def test_invalid_or_wrong_date_companion_is_not_rendered():
    r=report();r['nav_date']='2026-11-03'
    assert build(r)['sources']==[]
    assert 'Synthetic market development' not in html(r)
    r=report();r['market_context']['developments'][0]['summary']='<b>unsafe</b>'
    assert 'unsafe' not in html(r)


def test_after_close_label_and_exited_holdings_are_explicit():
    r=report();item=r['market_context']['developments'][0]
    item['event_time_utc']='2026-11-04T22:00:00Z';item['affected_tickers']=['QQQ']
    text=build(r)['paragraphs'][0][1]
    assert 'After US close' in text and 'No current holding matched' in text


def test_html_escapes_non_markup_text():
    r=report();r['market_context']['developments'][0]['title']='Supply & demand'
    assert 'Supply &amp; demand' in html(r)
