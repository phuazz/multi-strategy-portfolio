"""Email-safe, zero-centred risk scales with explicit clipping labels."""
from dataclasses import dataclass
from html import escape
from return_context import units, rows

LIMIT=2.5


@dataclass(frozen=True)
class RiskMove:
    value: float | None

    @property
    def text(self):
        return units(self.value)+(' (beyond scale)' if self.value is not None and abs(self.value)>LIMIT else '')


def segments(value):
    capped=max(-LIMIT,min(LIMIT,value))
    left,right=sorted((0,capped))
    result=[]
    for i in range(10):
        lo=-LIMIT+i*.5;hi=lo+.5
        a=max(lo,left);b=min(hi,right)
        filled=max(0,b-a)/.5
        before=(a-lo)/.5 if filled else 0
        result.append((before,filled,1-before-filled))
    return result


def gauge(value):
    if value is None: return '<span>Unavailable</span>'
    colour='#146c43' if value>=0 else '#a93226'
    body=f'<table data-risk-gauge data-units="{value}" role="presentation" aria-hidden="true" style="width:100%;table-layout:fixed;border-collapse:collapse;margin:8px 0 0"><tr>'
    for i,parts in enumerate(segments(value)):
        bg='#dce8f4' if 3<=i<=6 else '#edf2f7' if 1<=i<=8 else '#f5f5f0'
        border='1px solid #7c8794' if i in (0,2,4,6,8) else '0'
        body+=f'<td style="width:10%;padding:0!important;background:{bg};border-right:{border}"><table role="presentation" style="width:100%;table-layout:fixed;border-collapse:collapse"><tr>'
        for j,width in enumerate(parts):
            if width>0:
                marker=' data-risk-segment' if j==1 else ''
                body+=f'<td{marker} style="width:{width*100:.8f}%;height:8px;padding:0!important;background:{colour if j==1 else bg}"></td>'
        body+='</tr></table></td>'
    body+='</tr></table><table role="presentation" aria-hidden="true" style="width:100%;table-layout:fixed;border-collapse:collapse"><tr>'
    body+=''.join(f'<td style="width:20%;padding:2px 0!important;text-align:center;font-size:11px!important;color:#5c5c56">{label}</td>' for label in ['-2','-1','0','+1','+2'])
    return body+'</tr></table>'


def context_html(context):
    if not context: return ''
    body='<h2>How large was the move relative to risk?</h2><p class="small">Same scale for both horizons: multiples of prior estimated horizon risk. Shading marks ±1 and ±2; the track ends at ±2.5. Green/red shows return direction, not statistical significance.</p>'
    for hz,p in context['periods'].items():
        body+=f'<div style="background:#ffffff;border:1px solid #e2e0d8;padding:12px;margin:12px 0"><strong>{hz} · {escape(str(p["start"]))} to {escape(p["end"])}</strong>'
        if p['status']!='ok':
            body+='<p>'+escape(p['reason'])+'</p></div>';continue
        for row in [x for x in rows(context) if x['horizon']==hz]:
            actual=f'{row["return"]*100:+.2f}'+(' pp' if row['kind']=='active' else '%')
            risk=f'{row["one_sd"]*100:.2f}'+(' pp' if row['kind']=='active' else '%')
            body+=f'<p style="margin-bottom:4px"><strong>{escape(row["label"])}</strong><br>{actual} · 1 s.d. {risk} · <strong>{RiskMove(row["units"]).text}</strong></p>'+gauge(row['units'])
        body+=f'<p class="small">{p["sessions"]} session(s). Estimate: {p["observations"]} matched daily returns, {p["training_start"]} to {p["training_end"]}; {p["excluded_gaps"]} missing or multi-session observations excluded. Source: published model NAV and SPY adjusted-close proxy.</p></div>'
    return body+'<p class="small">'+escape(context['method'])+'</p>'
