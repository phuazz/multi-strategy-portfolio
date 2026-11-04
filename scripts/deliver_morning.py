"""Freshness-gated GitHub email with a durable, fail-closed delivery ledger.

Python months are 1-indexed; weekday Monday=0. All scheduling uses Asia/Singapore.
The state branch contains only session dates, status, hashes and workflow run IDs.
No recipient, credential, email body or personal identifier is committed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config import load_registry
from morning_report import URL, PAGE, build, series
from nyse_sessions import last_completed_session
from portfolio_freshness import evaluate_book
from render_morning import write_bundle, delay_html
from source_revision import changed_files, resolve_snapshot

SGT=ZoneInfo('Asia/Singapore')
STATE_BRANCH='morning-mail-state'


def delivery_window(now):
    if now.tzinfo is None:
        raise ValueError('A timezone-aware clock is required')
    local=now.astimezone(SGT)
    return local.weekday() in (1,2,3,4,5) and local.hour >= 9


def freshness(d, now):
    expected=last_completed_session(now).isoformat()
    reasons=[]
    meta=d.get('meta',{})
    if meta.get('live_asOf') != expected:
        reasons.append(f'Official NAV ends {meta.get("live_asOf","unknown")}; expected {expected}')
    if d.get('health',{}).get('level') != 'ok':
        reasons.append('Dataset health is not OK')
    for field in ('consistency_ok','reconcile_ok','benchmark_ok'):
        if d.get('health',{}).get(field) is not True:
            reasons.append(f'Dataset check {field} is not confirmed')
    book=evaluate_book(meta.get('portfolio_anchor'),meta.get('strategy_asOf'),now)
    if book['level'] != 'ok':
        reasons.append(f'Executed book covers {book["asOf"]}; required {book["expected"]}')
    for key,label in [('SPY','S&P 500'),('AOR','global 60/40'),('BIL','Treasury-bill proxy')]:
        b=d.get('equity',{}).get('benchmarks',{}).get(key,{})
        if not b.get('dates') or b['dates'][-1] != expected or b.get('asOf') != expected:
            reasons.append(f'{label} does not end on the required valuation date')
        else:
            series(b['dates'],b['equity'])
    # Do not trust the badge when the NAV array differs from its metadata.
    eq=d.get('equity',{})
    dates=(eq.get('live') or {}).get('dates') or eq.get('dates',[])
    if not dates or dates[-1] != expected:
        reasons.append('Published NAV observations do not reach the required close')
    return reasons


def choose_action(now, ready, report_record, delay_record):
    if not delivery_window(now): return 'outside-window'
    for record in (report_record,delay_record):
        if record and record.get('status') != 'sent':
            raise RuntimeError('Uncertain prior send: review Gmail and the ledger before retrying')
    if report_record: return 'already-sent'
    if ready: return 'report'
    if now.astimezone(SGT).hour >= 11 and not delay_record: return 'delay'
    return 'waiting'


class GitHubLedger:
    def __init__(self):
        self.repo=os.environ['GITHUB_REPOSITORY']
        self.api=f'https://api.github.com/repos/{self.repo}'
        self.http=requests.Session()
        self.http.headers.update({'Authorization':f'Bearer {os.environ["GITHUB_TOKEN"]}',
                                  'Accept':'application/vnd.github+json'})

    def request(self,method,path,**kwargs):
        r=self.http.request(method,self.api+path,timeout=30,**kwargs)
        return r

    def ensure_branch(self):
        r=self.request('GET',f'/git/ref/heads/{STATE_BRANCH}')
        if r.status_code==404:
            head=self.request('GET','/git/ref/heads/main'); head.raise_for_status()
            r=self.request('POST','/git/refs',json={'ref':f'refs/heads/{STATE_BRANCH}','sha':head.json()['object']['sha']})
        r.raise_for_status()

    def read(self,key):
        r=self.request('GET',f'/contents/mail-ledger/{key}.json',params={'ref':STATE_BRANCH})
        if r.status_code==404: return None,None
        r.raise_for_status(); obj=r.json()
        return json.loads(base64.b64decode(obj['content'])),obj['sha']

    def write(self,key,value,sha=None):
        payload={'message':f'Morning email {key}: {value["status"]}', 'branch':STATE_BRANCH,
                 'content':base64.b64encode(json.dumps(value,indent=2).encode()).decode()}
        if sha: payload['sha']=sha
        r=self.request('PUT',f'/contents/mail-ledger/{key}.json',json=payload)
        r.raise_for_status()
        return r.json()['content']['sha']


def deliver_once(ledger,key,subject,body,html,pdf,send,now):
    record,sha=ledger.read(key)
    if record:
        if record.get('status')=='sent': return False
        raise RuntimeError('Pending send exists; automatic resend is prohibited')
    digest=hashlib.sha256((subject+'\n'+body+'\n'+html).encode()).hexdigest()
    if pdf: digest=hashlib.sha256((digest+hashlib.sha256(Path(pdf).read_bytes()).hexdigest()).encode()).hexdigest()
    message_id=f'<msp-{hashlib.sha256(key.encode()).hexdigest()[:24]}@portfolio-monitor.local>'
    record={'status':'sending','attempted_at_utc':now.isoformat(),'content_sha256':digest,
            'run_id':os.environ.get('GITHUB_RUN_ID','local-validation')}
    claim=ledger.write(key,record,sha)
    # A crash after the claim or an uncertain SMTP result fails closed. Operators
    # inspect the deterministic Message-ID in Gmail before repairing the ledger.
    send(subject,body,html,pdf,message_id)
    record.update(status='sent',accepted_at_utc=datetime.now(timezone.utc).isoformat())
    ledger.write(key,record,claim)
    return True


def send_smtp(subject,body,html,pdf,message_id):
    sender=os.environ['GMAIL_USER'].strip()
    recipient=os.environ['MORNING_REPORT_TO'].strip()
    if any(any(c in value for c in ',;\r\n') or value.count('@') != 1 for value in (sender,recipient)):
        raise ValueError('Sender and recipient must each identify one mailbox')
    msg=EmailMessage()
    msg['From']=f'Multi-Strategy Portfolio <{sender}>'
    msg['To']=recipient
    msg['Subject']=subject
    msg['Message-ID']=message_id
    msg.set_content(body)
    msg.add_alternative(html,subtype='html')
    if pdf:
        msg.add_attachment(Path(pdf).read_bytes(),maintype='application',subtype='pdf',filename='Portfolio-review.pdf')
    with smtplib.SMTP_SSL('smtp.gmail.com',465,context=ssl.create_default_context(),timeout=45) as smtp:
        smtp.login(sender,os.environ['GMAIL_APP_PASSWORD'])
        rejected=smtp.send_message(msg)
        if rejected: raise RuntimeError('SMTP rejected the recipient')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--send',action='store_true')
    ap.add_argument('--preview',action='store_true')
    ap.add_argument('--output',default='data/morning-email')
    args=ap.parse_args()
    if args.send and args.preview: raise ValueError('Preview and send are mutually exclusive')
    now=datetime.now(timezone.utc)
    if args.send and not delivery_window(now):
        print('outside-window'); return
    expected=last_completed_session(now).isoformat()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    ledger=GitHubLedger() if args.send else None
    report_record=delay_record=None
    if ledger:
        ledger.ensure_branch()
        report_record,_=ledger.read(expected+'-report')
        delay_record,_=ledger.read(expected+'-delay')
        if report_record and report_record.get('status')=='sent':
            print('already-sent'); return
    d=None; report=None
    try:
        response=requests.get(URL,params={'mail_check':now.isoformat()},timeout=45)
        response.raise_for_status(); d=response.json()
        reasons=freshness(d,now)
        source=load_registry('multi-strategy-portfolio')['source']
        snapshot=resolve_snapshot(source)
        if changed_files(d['meta'],snapshot,source):
            reasons.append('The deployed page has not yet consumed the latest engine publication')
        # Normal report generation itself guards malformed levels and live anchors.
        if not reasons or args.preview:
            report=build(d,now)
    except Exception as exc:
        reasons=[f'Data verification failed ({type(exc).__name__})']
        if args.preview: raise
    action=choose_action(now,not reasons,report_record,delay_record)
    if args.preview:
        write_bundle(report,out,preview=True)
        (out/'delay.html').write_text(delay_html(expected,reasons or ['Illustrative delayed-data notice']),encoding='utf-8')
        (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Preview only; no email sent'); return
    result={'action':action,'expected_session':expected,'reasons':reasons,'checked_at_utc':now.isoformat()}
    (out/'check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    if not args.send or action not in ('report','delay'): return
    if action=='report':
        write_bundle(report,out)
        from verify_mail_layout import verify_html, verify_pdf, verify_attribution_content
        verify_html(out/'report.html')
        verify_pdf(out/'portfolio-review.pdf')
        verify_attribution_content(report,out/'portfolio-review.pdf',out/'report.html')
        html=(out/'report.html').read_text(encoding='utf-8')
        from pypdf import PdfReader
        pdf=out/'portfolio-review.pdf'
        reader=PdfReader(pdf)
        if not 3 <= len(reader.pages) <= 6 or not all(page.extract_text().strip() for page in reader.pages):
            raise ValueError('PDF must contain 3-6 nonempty A4 pages including full attribution')
        subject=f'Multi-Strategy | {report["performance"][0]["model"]:+.2%} | Close {expected}'
        deliver_once(ledger,expected+'-report',subject,report['body'],html,pdf,send_smtp,now)
    else:
        subject=f'Multi-Strategy | data delayed | Expected close {expected}'
        body=f'The morning report is waiting for verified data for the US close {expected}.\n'+'\n'.join(reasons)+f'\nThe full report and PDF will follow when the checks pass.\n{PAGE}'
        html=delay_html(expected,reasons)
        (out/'delay.html').write_text(html,encoding='utf-8')
        from verify_mail_layout import verify_html
        verify_html(out/'delay.html')
        deliver_once(ledger,expected+'-delay',subject,body,html,None,send_smtp,now)


if __name__=='__main__': main()
