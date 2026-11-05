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


@dataclass(frozen=True)
class ETFMove:
    contribution: float | None
    detail: dict | None


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


def etf_context_html(context):
    if not context:return ''
    from etf_return_context import leaders
    from attribution_presentation import bp
    body='<h2>ETF moves relative to their own risk</h2><p class="small">Three largest absolute volatility-unit moves among current holdings, separately for 1D and 1M. ETF return covers the full window; contribution reflects historical holdings. Income and carry remain in the ratio: this is not a surprise score. Tracks use the same ±2.5 scale, with ±1 and ±2 markers.</p>'
    for hz,p in context['periods'].items():
        selected=leaders(context,hz)
        body+=f'<h3 style="font-size:16px">{hz} · {escape(str(p["start"]))} to {escape(p["end"])}</h3>'
        current=[x for x in p['rows'] if x['current_weight']>0]
        available=sum(x['units'] is not None for x in current)
        body+=f'<p class="small">Risk estimates available for {available} of {len(current)} current holdings. Missing estimates are excluded from ranking.</p>'
        for r in selected:
            proxy='; priced as '+r['price_symbol'] if r['price_symbol']!=r['ticker'] else ''
            body+=f'<div style="background:#ffffff;border:1px solid #e2e0d8;padding:12px;margin:12px 0"><strong>{escape(r["name"])} ({escape(r["ticker"])})</strong><p style="margin:4px 0">ETF {r["return"]:+.2%} · 1 s.d. {r["one_sd"]:.2%} · <strong>{RiskMove(r["units"]).text}</strong><br>Portfolio contribution: {bp(r["contribution"])}</p>'+gauge(r['units'])
            body+=f'<p class="small" style="margin-bottom:0">252 prior USD valuation returns: {r["training_start"]} to {r["training_end"]}; {r["excluded_gaps"]} gaps excluded{escape(proxy)}.</p></div>'
        if not selected:body+='<p>No current holding has a verified risk estimate for this window.</p>'
    body+='<p class="small">Source: adjusted ETF/proxy closes and same-date FX, on the NYSE valuation clock. Local closes are asynchronous. Full ETF detail, including exits and unavailable estimates, is in the PDF and dashboard. '+escape(context['method'])+'</p>'
    return body
