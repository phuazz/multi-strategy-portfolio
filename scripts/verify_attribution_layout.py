"""Real viewport and rendered-data checks for every attribution view.

Runs against locally served canonical pipeline output, never an iframe.
"""
from __future__ import annotations
import functools
import http.server
import json
import os
from pathlib import Path
import threading


def verify(root, output):
    from playwright.sync_api import sync_playwright
    root=Path(root).resolve(); output=Path(output);output.mkdir(parents=True,exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    measurements=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('MORNING_CHROME_PATH') or None)
            for width,height in [(390,844),(844,390),(768,1024),(1280,900)]:
                context=browser.new_context(viewport={'width':width,'height':height},is_mobile=True,device_scale_factor=1)
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html',wait_until='networkidle')
                page.wait_for_function('typeof DS !== "undefined" && DS && DS.attribution.version === 2')
                # Smoke-test the shared dataset across every tab before attribution.
                for tab in page.evaluate('TABS.map(x=>x[0])'):
                    page.evaluate('(tab)=>setTab(tab)',tab)
                    page.wait_for_timeout(100)
                    dimensions=page.evaluate('({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
                    assert dimensions['width']==width and dimensions['scroll']<=width+1,(tab,dimensions)
                    assert not errors,(tab,errors)
                page.evaluate("setTab('attribution')")
                page.wait_for_function('document.fonts.status === "loaded"')
                for horizon in ('1D','1M'):
                    for view in ('etf','sleeve','theme'):
                        page.evaluate('([h,v])=>{setAttrHz(h);setAttrView(v)}',[horizon,view])
                        m=page.evaluate('''() => {
                            const width=document.documentElement.clientWidth;
                            const visible=[...document.querySelectorAll('#tabContent *')].filter(e=>e.checkVisibility());
                            const text=visible.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
                            const overflow=visible.filter(e=>e.getBoundingClientRect().right>width+1||e.getBoundingClientRect().left< -1).length;
                            const prose=[...document.querySelectorAll('.attr-prose')].filter(e=>e.textContent.length>100);
                            const chars=prose.map(e=>{const c=document.createElement('canvas').getContext('2d');c.font=getComputedStyle(e).font;return e.clientWidth/(c.measureText('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').width/62)});
                            const period=DS.attribution.periods[state.attrHorizon];
                            const expected=state.attrView==='etf'?period.etf.length:state.attrView==='sleeve'?period.strategy.length:attrRows().length;
                            const values=[...document.querySelectorAll('#attrChart .attr-bar-value span')].map(e=>e.textContent);
                            const source=attrRows().sort((a,b)=>(b.contrib??-Infinity)-(a.contrib??-Infinity)).map(r=>attrBp(r.contrib));
                            return {width,scrollWidth:document.documentElement.scrollWidth,smallestFont:Math.min(...text.map(e=>parseFloat(getComputedStyle(e).fontSize))),overflowCount:overflow,
                            charsPerLine:Math.max(...chars),barRows:values.length,expectedRows:expected,valuesMatch:JSON.stringify(values)===JSON.stringify(source),etfTableRows:document.querySelectorAll('#attrTbl tbody tr').length};
                        }''')
                        assert m['width']==width and m['scrollWidth']<=width+1 and m['overflowCount']==0,m
                        assert m['smallestFont']>=11 and m['charsPerLine']<=(55 if width==390 else 80),m
                        assert m['barRows']==m['expectedRows'] and m['valuesMatch'],m
                        assert not errors,errors
                        measurements.append({'horizon':horizon,'view':view,**m})
                        if view=='etf':page.screenshot(path=str(output/f'attribution-{horizon}-{width}.png'),full_page=True)
                context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
    (output/'dashboard-layout.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')
    return measurements


if __name__=='__main__':
    import sys
    print(json.dumps(verify(sys.argv[1],sys.argv[2]),indent=2))
