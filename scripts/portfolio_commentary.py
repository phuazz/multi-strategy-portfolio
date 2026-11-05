"""Private, date-matched briefing commentary. No news in public datasets.

Python datetime months are 1-indexed. Source claims remain labelled; the
companion never replaces quantitative returns or supplies causal attribution.
"""
from html import escape
from private_market_context import ContextError, validate, stamp, _NYSE


def build(report):
    context=report.get('market_context')
    if context:
        try:validate(context,report['nav_date'],stamp(report['generated_at_utc']))
        except (ContextError,TypeError,ValueError,KeyError):context=None
    if not context:
        return {'asOf':report['nav_date'],'paragraphs':[
            ('Market context unavailable','No usable date-matched X briefing is included. Portfolio figures and attribution are shown separately.')],
            'sources':[], 'provenance':'Portfolio close '+report['nav_date']+'. No earlier briefing has been reused.'}
    rows=report.get('etf_return_context',{}).get('periods',{}).get('1D',{}).get('rows',[])
    held={r['ticker'] for r in rows if (r.get('current_weight') or 0)>0}
    close=_NYSE.schedule(start_date=report['nav_date'],end_date=report['nav_date']).iloc[0]['market_close'].to_pydatetime()
    paragraphs=[];sources=[]
    for i,item in enumerate(context['developments'],1):
        timing=' After US close.' if stamp(item['event_time_utc'])>close else ''
        matched=sorted(held.intersection(item['affected_tickers']))
        exposure=' Current holdings: '+', '.join(matched)+'.' if matched else ' No current holding matched.'
        text=(item['summary']+' Interpretation: '+item['interpretation']+
              ' Relevance: '+item['portfolio_relevance']+exposure+timing)
        paragraphs.append((item['title']+' ['+str(i)+'; '+item['confidence']+']',text))
        sources.extend(dict(s,number=i,citation=str(i)+chr(97+j)) for j,s in enumerate(item['sources']))
    return {'asOf':report['nav_date'],'paragraphs':paragraphs,'sources':sources,
            'provenance':'US session '+report['nav_date']+'; briefing cutoff '+context['cutoff_utc']+
            '. X briefing claims; interpretations are hypotheses, not causal attribution. Post-close developments cannot explain that close.'}


def html(report):
    c=build(report)
    body='<div style="background:#f0f5fa;border:1px solid #d6e2ed;border-left:4px solid #1d4ed8;padding:14px;margin:18px 0"><h2 style="margin-top:0">Portfolio manager commentary</h2>'
    body+=''.join('<p style="margin:7px 0"><strong>'+escape(label)+'.</strong> '+escape(text)+'</p>' for label,text in c['paragraphs'])
    body+='<p class="small">'+escape(c['provenance'])+'</p>'
    if c['sources']:
        body+='<p class="small">Source links by development: '+' · '.join('<a href="'+escape(s['url'],quote=True)+'" title="'+escape(s['publisher']+' ('+s['type']+')',quote=True)+'">['+s['citation']+']</a>' for s in c['sources'])+'</p>'
    return body+'</div>'
