"""Calendar, freshness and uncertain-delivery guards; no network or email."""
from copy import deepcopy
from datetime import datetime, timezone
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from deliver_morning import delivery_window, choose_action, freshness, deliver_once
from render_morning import delay_html


def clock(s): return datetime.fromisoformat(s)


@pytest.mark.parametrize('time,yes',[
    ('2026-11-04T00:59:00+00:00',False),
    ('2026-11-04T01:00:00+00:00',True),
    ('2026-10-31T01:00:00+00:00',True), # month boundary
    ('2026-11-01T01:00:00+00:00',False),
    ('2026-12-31T16:30:00+00:00',False), # year boundary in Singapore
    ('2027-01-01T01:00:00+00:00',True),
])
def test_singapore_window(time,yes): assert delivery_window(clock(time)) is yes


def test_deadline_and_later_recovery():
    assert choose_action(clock('2026-11-04T01:00:00+00:00'),False,None,None)=='waiting'
    assert choose_action(clock('2026-11-04T03:00:00+00:00'),False,None,None)=='delay'
    assert choose_action(clock('2026-11-04T04:00:00+00:00'),False,None,{'status':'sent'})=='waiting'
    assert choose_action(clock('2026-11-04T04:00:00+00:00'),True,None,{'status':'sent'})=='report'
    assert choose_action(clock('2026-11-04T05:00:00+00:00'),True,{'status':'sent'},None)=='already-sent'


def test_uncertain_send_blocks_retry():
    with pytest.raises(RuntimeError,match='Uncertain'):
        choose_action(clock('2026-11-04T04:00:00+00:00'),True,{'status':'sending'},None)


def sample():
    return {'meta':{'live_asOf':'2026-11-03','portfolio_anchor':'2026-11-02','strategy_asOf':'2026-11-02'},
            'health':{'level':'ok','consistency_ok':True,'reconcile_ok':True,'benchmark_ok':True},
            'equity':{'dates':['2026-11-02','2026-11-03'],'model':[1,1.01],
                      'benchmarks':{k:{'dates':['2026-11-02','2026-11-03'],'equity':[1,1.01],'asOf':'2026-11-03'} for k in ('SPY','AOR','BIL')}}}


def test_freshness_checks_actual_tail_and_book_not_badge():
    d=sample(); now=clock('2026-11-04T01:00:00+00:00')
    assert freshness(d,now)==[]
    d['equity']['dates'][-1]='2026-11-02'
    assert any('NAV observations' in s for s in freshness(d,now))
    d=sample(); d['meta']['portfolio_anchor']='2026-10-26'
    assert any('Executed book' in s for s in freshness(d,now))
    d=sample(); d['equity']['benchmarks']['AOR']['asOf']='2026-11-02'
    assert any('global 60/40' in s for s in freshness(d,now))


class Ledger:
    def __init__(self): self.values={}
    def read(self,key): return deepcopy(self.values.get(key)),None
    def write(self,key,value,sha=None): self.values[key]=deepcopy(value); return 'sha'


def test_claim_written_before_send_and_duplicate_suppressed():
    ledger=Ledger(); calls=[]
    def send(*args):
        assert ledger.values['session-report']['status']=='sending'
        calls.append(args)
    now=clock('2026-11-04T01:00:00+00:00')
    assert deliver_once(ledger,'session-report','s','b','h',None,send,now)
    assert ledger.values['session-report']['status']=='sent'
    assert not deliver_once(ledger,'session-report','s','b','h',None,send,now)
    assert len(calls)==1


def test_smtp_uncertainty_stays_pending():
    ledger=Ledger()
    def broken(*args): raise TimeoutError('uncertain SMTP')
    with pytest.raises(TimeoutError):
        deliver_once(ledger,'s','s','b','h',None,broken,clock('2026-11-04T01:00:00+00:00'))
    assert ledger.values['s']['status']=='sending'
    with pytest.raises(RuntimeError,match='Pending'):
        deliver_once(ledger,'s','s','b','h',None,broken,clock('2026-11-04T01:15:00+00:00'))


def test_delay_notice_escapes_source_content():
    html=delay_html('2026-11-03',['<script>unsafe</script>'])
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'viewport' in html
