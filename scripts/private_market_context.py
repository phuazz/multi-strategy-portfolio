"""Read a narrowly selected private mail attachment; never log its contents.

Python datetime months are 1-indexed. The market session follows the NYSE
calendar; the briefing date follows Asia/Singapore. No mailbox writes or sends.
"""
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import imaplib
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from nyse_sessions import last_completed_session, _NYSE

SGT=ZoneInfo('Asia/Singapore')
TOP={'schema_version','privacy','status','briefing_date','market_session',
     'window_start_utc','cutoff_utc','generated_at_utc','developments'}
ITEM={'title','event_time_utc','summary','interpretation','portfolio_relevance',
      'affected_tickers','confidence','sources'}
SOURCE={'url','publisher','published_at_utc','type'}
MAX_BYTES=64_000


class ContextError(ValueError):
    """Only constant, content-free reasons are safe for public runner logs."""


def stamp(value):
    try:
        t=datetime.fromisoformat(value.replace('Z','+00:00'))
        if t.tzinfo is None:raise ValueError()
        return t.astimezone(timezone.utc)
    except (AttributeError,TypeError,ValueError):
        raise ContextError('invalid_timestamp') from None


def plain(value, limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ContextError('invalid_text')
    if any(ord(c)<32 for c in value) or '<' in value or '>' in value:
        raise ContextError('unsafe_text')
    if re.search(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}',value,re.I):
        raise ContextError('private_identifier')


def source_url(value):
    if not isinstance(value,str) or len(value)>800:raise ContextError('invalid_url')
    u=urlparse(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ContextError('invalid_url')
    host=u.hostname.lower()
    if '.' not in host or host.endswith(('.local','.internal')) or host in ('mail.google.com','outlook.live.com','outlook.office.com'):
        raise ContextError('private_url')
    try:ipaddress.ip_address(host)
    except ValueError:pass
    else:raise ContextError('private_url')
    if re.search(r'(token|secret|api.?key|password|signature|credential)=',u.query,re.I):
        raise ContextError('credential_url')


def validate(obj, nav_date, now):
    if not isinstance(obj,dict) or set(obj)!=TOP:raise ContextError('schema_mismatch')
    if type(obj['schema_version']) is not int or obj['schema_version']!=1 or obj['privacy']!='private' or obj['status']!='complete':
        raise ContextError('invalid_status')
    if now.tzinfo is None:raise ContextError('invalid_clock')
    try:
        session=date.fromisoformat(obj['market_session'])
        briefing=date.fromisoformat(obj['briefing_date'])
    except (ValueError,TypeError):raise ContextError('invalid_date') from None
    start,cutoff,generated=map(stamp,(obj['window_start_utc'],obj['cutoff_utc'],obj['generated_at_utc']))
    if not start<cutoff<=generated<=now:raise ContextError('future_or_reversed_time')
    if cutoff-start>timedelta(hours=36) or now-cutoff>timedelta(hours=30):raise ContextError('stale_window')
    if briefing!=cutoff.astimezone(SGT).date():raise ContextError('briefing_date_mismatch')
    if str(session)!=nav_date or session!=last_completed_session(cutoff):raise ContextError('session_mismatch')
    schedule=_NYSE.schedule(start_date=session,end_date=session)
    close=schedule.iloc[0]['market_close'].to_pydatetime()
    if not start<close<=cutoff:raise ContextError('close_outside_window')
    items=obj['developments']
    if not isinstance(items,list) or not 1<=len(items)<=3:raise ContextError('invalid_item_count')
    words=0
    for item in items:
        if not isinstance(item,dict) or set(item)!=ITEM:raise ContextError('item_schema_mismatch')
        for key,limit in [('title',55),('summary',280),('interpretation',160),('portfolio_relevance',160)]:
            plain(item[key],limit);words+=len(item[key].split())
        event=stamp(item['event_time_utc'])
        if not start<=event<=cutoff:raise ContextError('event_outside_window')
        tickers=item['affected_tickers']
        if not isinstance(tickers,list) or len(tickers)>8:raise ContextError('invalid_tickers')
        if any(not isinstance(t,str) or not re.fullmatch(r'[A-Z0-9.^=-]{1,20}',t) for t in tickers):raise ContextError('invalid_tickers')
        if len(set(tickers))!=len(tickers):raise ContextError('invalid_tickers')
        if item['confidence'] not in ('corroborated','reported','uncertain'):raise ContextError('invalid_confidence')
        sources=item['sources']
        if not isinstance(sources,list) or not 1<=len(sources)<=3:raise ContextError('missing_sources')
        for source in sources:
            if not isinstance(source,dict) or set(source)!=SOURCE:raise ContextError('source_schema_mismatch')
            source_url(source['url']);plain(source['publisher'],80)
            if stamp(source['published_at_utc'])>cutoff:raise ContextError('future_source')
            if source['type'] not in ('primary','market_data','report','social'):raise ContextError('invalid_source_type')
        if item['confidence']=='corroborated' and len({s['publisher'].casefold() for s in sources})<2:
            raise ContextError('insufficient_corroboration')
    if words>180:raise ContextError('word_limit')
    return obj


def decode(raw, nav_date, now):
    if len(raw)>MAX_BYTES:raise ContextError('oversized_companion')
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ContextError('duplicate_key')
            out[key]=value
        return out
    try:obj=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
    except (UnicodeError,json.JSONDecodeError):raise ContextError('invalid_json') from None
    return validate(obj,nav_date,now)


def attachment(raw, sender, subject, nav_date, now):
    if len(raw)>25_000_000:raise ContextError('oversized_message')
    message=BytesParser(policy=policy.default).parsebytes(raw)
    addresses=[a.lower() for _,a in getaddresses(message.get_all('From',[]))]
    if addresses!=[sender.lower()] or not str(message.get('Subject','')).startswith(subject):
        raise ContextError('sender_or_subject_mismatch')
    # Gmail prepends its own Authentication-Results; use that first trusted result.
    auth=next((str(v) for v in message.get_all('Authentication-Results',[]) if str(v).lstrip().startswith('mx.google.com;')), '')
    domain=sender.rsplit('@',1)[1]
    if not re.search(r'\bdmarc=pass\b',auth) or not re.search(r'header\.from='+re.escape(domain)+r'(?:[;\s]|$)',auth,re.I):
        raise ContextError('sender_authentication_failed')
    candidates=[]
    for part in message.walk():
        name=part.get_filename() or ''
        if re.fullmatch(r'portfolio-market-context-\d{4}-\d{2}-\d{2}\.json',name):
            obj=decode(part.get_payload(decode=True) or b'',nav_date,now)
            if name!='portfolio-market-context-'+obj['briefing_date']+'.json':raise ContextError('filename_date_mismatch')
            candidates.append(obj)
    if len(candidates)!=1:raise ContextError('missing_or_ambiguous_companion')
    return candidates[0]


def fetch(nav_date, now, local_path=None, environ=None, client_factory=imaplib.IMAP4_SSL):
    """Nonfatal context failure; output contains no mailbox or article text."""
    env=os.environ if environ is None else environ
    try:
        if local_path:
            return decode(Path(local_path).read_bytes(),nav_date,now),'ready'
        sender=env.get('MORNING_BRIEF_SENDER','').strip()
        subject=env.get('MORNING_BRIEF_SUBJECT','').strip()
        user=env.get('GMAIL_USER','').strip();password=env.get('GMAIL_APP_PASSWORD','')
        if not all((sender,subject,user,password)):return None,'not_configured'
        if sender.count('@')!=1 or len(subject)>120 or any(c in sender+subject for c in '\r\n'):
            raise ContextError('invalid_configuration')
        quote=lambda s:'"'+s.replace('\\','\\\\').replace('"','\\"')+'"'
        since=(now-timedelta(days=2)).strftime('%d-%b-%Y')
        with client_factory('imap.gmail.com',993,ssl_context=ssl.create_default_context(),timeout=25) as mail:
            mail.login(user,password)
            status,_=mail.select('INBOX',readonly=True)
            if status!='OK':raise ContextError('mailbox_unavailable')
            status,data=mail.uid('search',None,'SINCE',since,'FROM',quote(sender),'SUBJECT',quote(subject))
            if status!='OK':raise ContextError('search_failed')
            reason='not_received'
            for uid in (data[0] or b'').split()[-3:][::-1]:
                status,parts=mail.uid('fetch',uid,'(RFC822.SIZE)')
                sizes=re.findall(rb'RFC822.SIZE (\d+)',b' '.join(x for x in parts if isinstance(x,bytes)))
                if status!='OK' or not sizes or int(sizes[0])>25_000_000:
                    reason='oversized_message';continue
                status,parts=mail.uid('fetch',uid,'(BODY.PEEK[])')
                if status!='OK':reason='fetch_failed';continue
                raw=next((x[1] for x in parts if isinstance(x,tuple)),b'')
                try:return attachment(raw,sender,subject,nav_date,now),'ready'
                except ContextError as exc:reason=str(exc)
            return None,reason
    except ContextError as exc:return None,str(exc)
    except Exception:return None,'context_read_failed'
