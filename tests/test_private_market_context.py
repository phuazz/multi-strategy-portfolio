"""Private transport, session alignment and nonfatal context guard tests.

Python datetime months are 1-indexed; all dates below are synthetic test inputs.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
from pathlib import Path
import pytest
from private_market_context import validate, decode, attachment, fetch, ContextError


def companion(session='2026-11-04', cutoff='2026-11-04T23:00:00+00:00'):
    end=datetime.fromisoformat(cutoff)
    return dict(schema_version=1,privacy='private',status='complete',
                briefing_date=(end+timedelta(hours=8)).date().isoformat(),market_session=session,
                window_start_utc=(end-timedelta(hours=24)).isoformat(),cutoff_utc=cutoff,
                generated_at_utc=(end+timedelta(minutes=30)).isoformat(),developments=[dict(
                    title='Synthetic market development',event_time_utc=(end-timedelta(hours=3)).isoformat(),
                    summary='A test source reported a market move.',interpretation='A possible sector rotation.',
                    portfolio_relevance='Potential context for the broad equity holding.',affected_tickers=['SPY'],
                    confidence='reported',sources=[dict(url='https://example.org/market',publisher='Test source',
                                                       published_at_utc=(end-timedelta(hours=2)).isoformat(),type='report')])])


NOW=datetime(2026,11,5,1,tzinfo=timezone.utc)


@pytest.mark.parametrize('session,cutoff',[
    ('2026-10-30','2026-10-30T23:00:00+00:00'),
    ('2026-12-31','2026-12-31T23:00:00+00:00'),
    ('2026-11-27','2026-11-27T19:00:00+00:00')])
def test_calendar_boundaries_and_early_close(session,cutoff):
    c=companion(session,cutoff);now=datetime.fromisoformat(cutoff)+timedelta(hours=2)
    assert validate(c,session,now)==c
    with pytest.raises(ContextError,match='session_mismatch'):
        validate(c,(datetime.fromisoformat(session)+timedelta(days=1)).date().isoformat(),now)


@pytest.mark.parametrize('mutate,reason',[
    (lambda c:c.update(market_session='2026-11-03'),'session_mismatch'),
    (lambda c:c.update(briefing_date='2026-11-04'),'briefing_date_mismatch'),
    (lambda c:c.update(generated_at_utc='2026-11-05T03:00:00Z'),'future_or_reversed_time'),
    (lambda c:c.update(window_start_utc='2026-11-04T22:00:00Z'),'close_outside_window'),
    (lambda c:c.update(privacy='public'),'invalid_status'),
    (lambda c:c['developments'][0].update(summary='<script>bad</script>'),'unsafe_text'),
    (lambda c:c['developments'][0].update(summary='user@example.org'),'private_identifier'),
    (lambda c:c['developments'][0].update(confidence='corroborated'),'insufficient_corroboration'),
    (lambda c:c['developments'][0]['sources'][0].update(url='https://example.org/?token=private'),'credential_url'),
    (lambda c:c['developments'][0]['sources'][0].update(published_at_utc='2026-11-05T00:00:00Z'),'future_source'),
    (lambda c:c['developments'][0].update(event_time_utc='2026-11-05T00:00:00Z'),'event_outside_window'),
    (lambda c:c.update(extra='not allowed'),'schema_mismatch')])
def test_invalid_input_fails_closed(mutate,reason):
    c=companion();mutate(c)
    with pytest.raises(ContextError,match=reason):validate(c,'2026-11-04',NOW)


def test_holiday_does_not_create_a_session_and_stale_news_expires():
    c=companion('2027-01-01','2027-01-01T23:00:00+00:00')
    with pytest.raises(ContextError,match='session_mismatch'):
        validate(c,'2027-01-01',datetime(2027,1,2,1,tzinfo=timezone.utc))
    with pytest.raises(ContextError,match='stale_window'):validate(companion(),'2026-11-04',NOW+timedelta(days=2))


def message(c=None,auth=True):
    c=c or companion();m=EmailMessage()
    m['From']='briefing@example.org';m['Subject']='Private market briefing'
    if auth:m['Authentication-Results']='mx.google.com; dmarc=pass header.from=example.org;'
    m.set_content('Private evidence is in the attachment.')
    m.add_attachment(json.dumps(c).encode(),maintype='application',subtype='json',
                     filename='portfolio-market-context-'+c['briefing_date']+'.json')
    return m


def test_sender_auth_filename_and_duplicate_attachment_guards():
    m=message();args=('briefing@example.org','Private market briefing','2026-11-04',NOW)
    assert attachment(m.as_bytes(),*args)==companion()
    with pytest.raises(ContextError,match='authentication'):attachment(message(auth=False).as_bytes(),*args)
    with pytest.raises(ContextError,match='sender_or_subject'):attachment(m.as_bytes(),'other@example.org',*args[1:])
    part=list(m.iter_attachments())[0]
    part.replace_header('Content-Disposition','attachment; filename="portfolio-market-context-2026-11-04.json"')
    with pytest.raises(ContextError,match='filename_date'):attachment(m.as_bytes(),*args)
    m=message();m.attach(deepcopy(list(m.iter_attachments())[0]))
    with pytest.raises(ContextError,match='ambiguous'):attachment(m.as_bytes(),*args)


def test_duplicate_json_keys_and_size():
    with pytest.raises(ContextError,match='duplicate_key'):decode(b'{"a":1,"a":2}','2026-11-04',NOW)
    with pytest.raises(ContextError,match='oversized'):decode(b' '*64001,'2026-11-04',NOW)


def test_imap_is_read_only_peek_and_narrow_search():
    calls=[];raw=message().as_bytes()
    class Mail:
        def __init__(self,*args,**kwargs):assert kwargs['ssl_context'].check_hostname
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def login(self,*args):pass
        def select(self,box,readonly):assert box=='INBOX' and readonly;return 'OK',[]
        def uid(self,*args):
            calls.append(args)
            if args[0]=='search':return 'OK',[b'1 2 3 4 5']
            if args[2]=='(RFC822.SIZE)':return 'OK',[b'5 (RFC822.SIZE 3000)']
            assert args[2]=='(BODY.PEEK[])';return 'OK',[(b'',raw)]
    env=dict(GMAIL_USER='owner@example.org',GMAIL_APP_PASSWORD='fake',MORNING_BRIEF_SENDER='briefing@example.org',MORNING_BRIEF_SUBJECT='Private market briefing')
    c,status=fetch('2026-11-04',NOW,environ=env,client_factory=Mail)
    assert status=='ready' and c==companion()
    assert 'FROM' in calls[0] and 'SUBJECT' in calls[0] and 'SINCE' in calls[0]
    assert calls[1][1]==b'5'


def test_missing_or_bad_local_context_is_nonfatal(tmp_path):
    assert fetch('2026-11-04',NOW,environ={})==(None,'not_configured')
    path=tmp_path/'private.json';path.write_text(json.dumps(companion()))
    assert fetch('2026-11-03',NOW,local_path=path)==(None,'session_mismatch')


def test_workflow_uploads_only_content_free_status():
    root=Path(__file__).resolve().parents[1]
    workflow=(root/'.github/workflows/morning_email.yml').read_text()
    upload=workflow.split('uses: actions/upload-artifact@v4')[1]
    assert 'path: data/morning-email/check.json' in upload
    assert not (root/'market_context.json').exists()
    assert 'private_market_context' not in (root/'scripts/pipeline.py').read_text()


def test_context_render_failure_falls_back_to_verified_quantitative_report(monkeypatch,tmp_path):
    import deliver_morning as delivery
    import verify_mail_layout as layout
    calls=[]
    def render(r,out):
        calls.append(r)
        if r.get('market_context'):raise RuntimeError('Private text must not be logged')
    monkeypatch.setattr(delivery,'write_bundle',render)
    monkeypatch.setattr(delivery,'build',lambda d,now:{'body':'verified quantitative report'})
    monkeypatch.setattr(layout,'verify_html',lambda path:None)
    monkeypatch.setattr(layout,'verify_pdf',lambda path:None)
    monkeypatch.setattr(layout,'verify_attribution_content',lambda *args:None)
    r,status=delivery.verified_bundle({'market_context':companion()},tmp_path,{},NOW)
    assert status=='omitted_after_render_check' and len(calls)==2
    assert r=={'body':'verified quantitative report'}
