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
    html=Path(html_path).read_text(encoding='utf-8')
    from html import unescape
    email=' '.join(unescape(re.sub('<[^>]+>', ' ', html)).split())
    attribution=report['attribution']
    etfs=comparison_rows(attribution,'etf')
    for row in etfs:
        assert '('+row['ticker']+')' in text, f'PDF holding missing: {row["ticker"]}'
        for horizon in ('1D','1M'):
            assert bp(row[horizon]) in text, f'PDF contribution missing: {row["ticker"]} {horizon}'
    for row in comparison_rows(attribution,'strategy'):
        assert row['name'] in text and row['name'] in email, f'Strategy missing: {row["name"]}'
    for horizon in ('1D','1M'):
        assert horizon in text and horizon in email
        for side in ('positive','negative'):
            for row in leaders(attribution,horizon)[side][:3]:
                assert row['ticker'] in email and bp(row['contrib']) in email, 'Email leader missing'
    if report.get('return_context'):
        from return_context import rows
        from return_context_visuals import RiskMove
        assert 'Return context and risk' in text and 'How large was the move relative to risk?' in email
        for row in rows(report['return_context']):
            assert RiskMove(row['units']).text in text and RiskMove(row['units']).text in email,'Risk-unit label missing'
    return {'etf_rows':len(etfs),'horizons':['1D','1M'],'rendered_content':'pass'}


if __name__=='__main__':
    target=Path(sys.argv[1])
    print(json.dumps(verify_pdf(target) if target.suffix=='.pdf' else verify_html(target),indent=2))
