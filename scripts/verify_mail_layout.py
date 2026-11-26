"""Real browser viewport and PDF bounds guards before any email is sent."""
from __future__ import annotations
import functools
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


def verify_html(path):
    from playwright.sync_api import sync_playwright
    path=Path(path).resolve()
    subprocess.run([sys.executable,str(Path(__file__).with_name('check_mail_page.py')),str(path)],check=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(path.parent)))
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    measurements=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('MORNING_CHROME_PATH') or None)
            for width,height in [(390,844),(844,390),(768,1024),(1280,900)]:
                context=browser.new_context(viewport={'width':width,'height':height},is_mobile=True,device_scale_factor=1)
                page=context.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/{path.name}',wait_until='networkidle')
                gauges=page.evaluate('''()=>[...document.querySelectorAll('[data-risk-gauge]')].map(e=>({units:Number(e.dataset.units),width:e.getBoundingClientRect().width,fill:[...e.querySelectorAll('[data-risk-segment]')].reduce((a,b)=>a+b.getBoundingClientRect().width,0)}))''')
                for gauge in gauges:
                    assert abs(gauge['fill']/gauge['width']-min(2.5,abs(gauge['units']))/5)<.015,gauge
                m=page.evaluate('''() => {
                    const width=document.documentElement.clientWidth;
                    const visible=[...document.querySelectorAll('body *')].filter(e=>e.checkVisibility());
                    const text=visible.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
                    const smallest=Math.min(...text.map(e=>parseFloat(getComputedStyle(e).fontSize)));
                    const overflow=visible.filter(e=>e.getBoundingClientRect().right>width+1 || e.getBoundingClientRect().left < -1).length;
                    const prose=[...document.querySelectorAll('p')].filter(e=>e.textContent.length>100);
                    const chars=prose.map(e=>{const c=document.createElement('canvas').getContext('2d');c.font=getComputedStyle(e).font;return e.clientWidth/(c.measureText('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').width/62)});
                    return {width,scrollWidth:document.documentElement.scrollWidth,smallestFont:smallest,overflowCount:overflow,charsPerLine:chars.length?Math.max(...chars):null};
                }''')
                assert m['width']==width,m
                assert m['scrollWidth'] <= width+1 and m['overflowCount']==0,m
                assert m['smallestFont'] >= 11,m
                # Line measure is checked on body prose; tables have their own cell widths.
                if m['charsPerLine'] is not None:
                    assert m['charsPerLine'] <= (55 if width==390 else 80),m
                page.screenshot(path=str(path.with_name(f'{path.stem}-{width}.png')),full_page=True)
                measurements.append(m)
                context.close()
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    path.with_suffix('.layout.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')
    return measurements


def verify_pdf(path):
    import fitz
    doc=fitz.open(path)
    assert 3 <= len(doc) <= 6, f'PDF has {len(doc)} pages, expected 3-6 for the complete holdings dossier'
    for page in doc:
        assert abs(page.rect.width-595.276)<1 and abs(page.rect.height-841.89)<1,'PDF is not A4'
        assert page.get_text().strip(),'Empty PDF page'
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    assert x0>=20 and x1<=page.rect.width-20 and y0>=20 and y1<=page.rect.height-15,span
                    assert span['size']>=8.25,span
        page.get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(str(Path(path).with_name(f'pdf-page-{page.number+1}.png')))
    assert sum(len(list(p.links())) for p in doc)>=2,'PDF source links missing'
    return {'pages':len(doc),'format':'A4','bounds':'pass','links':'pass'}


def verify_attribution_content(report, pdf_path, html_path):
    """Check the rendered PDF contains every historical holding and both horizons."""
    import fitz
    import re
    from attribution_presentation import comparison_rows, bp, leaders
    with fitz.open(pdf_path) as doc:
        text=' '.join(' '.join(p.get_text() for p in doc).split())
        page_one=' '.join(doc[0].get_text().split())
        page_two=' '.join(doc[1].get_text().split())
        links=[link.get('uri') for page in doc for link in page.get_links()]
    assert 'What drove the return?' in page_two and 'Reconciliation 1D:' in page_two and 'Reconciliation 1M:' in page_two,'Attribution summary must fit page 2'
    for horizon in ('1D','1M'):
        for side in ('positive','negative'):
            for row in leaders(report['attribution'],horizon)[side][:5]:
                assert '('+row['ticker']+')' in page_two and bp(row['contrib']) in page_two,'Page 2 ETF leader missing'
    for row in comparison_rows(report['attribution'],'strategy'):
        assert row['name'] in page_two,'Page 2 strategy missing'
    html=Path(html_path).read_text(encoding='utf-8')
    from html import unescape, escape
    email=' '.join(unescape(re.sub('<[^>]+>', ' ', html.split('</head>',1)[1])).split())
    plain=Path(html_path).with_suffix('.txt').read_text(encoding='utf-8')
    from portfolio_commentary import build as build_commentary
    commentary=build_commentary(report)
    assert 'Portfolio manager commentary' in page_one
    for label,paragraph in commentary['paragraphs']:
        expected=' '.join((label+'. '+paragraph).split())
        assert expected in page_one,'Commentary text missing or split beyond page 1'
    for source in commentary['sources']:
        assert source['url'] in links,'PDF market source link missing'
    spotlight=commentary.get('spotlight')
    if spotlight:
        for value in (spotlight['title'], spotlight['summary'], spotlight['view'], spotlight['confidence']):
            assert value in email and value in plain,'Email market insight missing'
        for source in spotlight['sources']:
            assert escape(source['url'],quote=True) in html and source['url'] in plain
    assert len(email.split()) <= 300 and len(html.encode('utf-8')) < 25_000,'Morning email exceeds digest budget'
    from render_morning import excess, pct
    for value in (report['nav_date'], 'Attached PDF'):
        assert value in email and value in plain,'Email session readout missing'
    for key,label in [('1 session','1D'), ('1 week','1W'), ('YTD','YTD')]:
        row=next((row for row in report['performance'] if row['period']==key), {})
        values=(label, pct(row['model']) if 'model' in row else '–',
                pct(row['SPY']) if row.get('SPY') is not None else '–', excess(row).text)
        assert ' '.join(values) in email and ' · '.join(values) in plain,'Email performance row mismatch'
    attribution=report['attribution']
    etfs=comparison_rows(attribution,'etf')
    for row in etfs:
        assert '('+row['ticker']+')' in text, f'PDF holding missing: {row["ticker"]}'
        for horizon in ('1D','1M'):
            assert bp(row[horizon]) in text, f'PDF contribution missing: {row["ticker"]} {horizon}'
    for row in comparison_rows(attribution,'strategy'):
        assert row['name'] in text, f'Strategy missing: {row["name"]}'
    for horizon in ('1D','1M'):
        assert horizon in text
    from attribution_presentation import daily_drivers, etf_label
    one=next(row for row in report['performance'] if row['period']=='1 session')
    drivers,bridge=daily_drivers(attribution,report.get('etf_return_context'),one)
    if bridge:
        for label,key in [('Shown','shown'),('other priced','other'),('unassigned','unassigned'),('model excess','total')]:
            assert label+' '+bp(bridge[key]) in email and label+' '+bp(bridge[key]) in plain
    for row in drivers:
        values=(etf_label(row['ticker'], row['name']), pct(row['usd_return']) if row['usd_return'] is not None else '–',
                f'{row["avg_weight"]:.2%}', bp(row['contrib'])) + ((bp(row['active']),) if bridge else ())
        assert ' '.join(values) in email and ' · '.join(values) in plain, 'Email driver row mismatch'
    if report.get('return_context'):
        from return_context import rows
        from return_context_visuals import RiskMove
        assert 'Return context and risk' in text
        for row in rows(report['return_context']):
            assert RiskMove(row['units']).text in text,'Risk-unit label missing'
    if report.get('etf_return_context'):
        from return_context_visuals import RiskMove
        context=report['etf_return_context']
        for hz,p in context['periods'].items():
            for row in p['rows']:
                assert '('+row['ticker']+')' in text,'ETF risk row absent from PDF'
                label=RiskMove(row['units']).text if row['units'] is not None else 'Risk units unavailable'
                assert label in text,'ETF risk-unit label absent from PDF'
    return {'etf_rows':len(etfs),'horizons':['1D','1M'],'rendered_content':'pass'}


if __name__=='__main__':
    target=Path(sys.argv[1])
    print(json.dumps(verify_pdf(target) if target.suffix=='.pdf' else verify_html(target),indent=2))
