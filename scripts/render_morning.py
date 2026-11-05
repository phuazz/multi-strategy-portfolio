"""HTML email and A4 dossier, rendered from one verified report object."""
from __future__ import annotations

from html import escape
from pathlib import Path
from dataclasses import dataclass
import math

from morning_report import PAGE, URL, fmt
from attribution_presentation import bp, comparison_rows, leaders, bridge_text
from return_context import rows as context_rows
from return_context_visuals import context_html, etf_context_html, RiskMove, ETFMove, LIMIT
from portfolio_commentary import build as build_commentary, html as commentary_html

INK, MUTED, GREEN, RED, BORDER = '#1a1a18', '#5c5c56', '#146c43', '#a93226', '#e2e0d8'
BLUE, CYAN, TRACK = '#1d4ed8', '#0e7490', '#eeeee8'
SPY_LABEL = 'S&P 500 TR proxy'
SPY_BASIS = 'S&P 500 total-return proxy: SPY adjusted close, including distributions and fund expenses; not the exact index return.'


@dataclass(frozen=True)
class ExcessValue:
    """Arithmetic excess in percentage points, without mixing bar scales."""
    value: float | None

    @property
    def text(self):
        return '-' if self.value is None else f'{self.value*100:+.2f}pp'

    @property
    def colour(self):
        return MUTED if self.value is None or self.value == 0 else GREEN if self.value > 0 else RED


def excess(row):
    return ExcessValue(None if row.get('SPY') is None else row['model']-row['SPY'])


def contribution_html(r):
    a=r['attribution']
    body='<h2>Strategy contribution: 1D and 1M</h2>'
    body+='<p class="small">Historical model holdings; USD; contribution in basis points. 100 bp = 1 percentage point.</p>'
    rows=comparison_rows(a,'strategy')
    scale=max([abs(x[h]) for x in rows for h in ('1D','1M') if x[h] is not None]+[.000001])
    body+=table(['Strategy','1D','1M'],[[x['name']]+[BarValue(x[h],scale,label=bp(x[h])+(' *' if x[h+'_coverage']<.999999 else '')) for h in ('1D','1M')] for x in rows])
    body+=f'<p class="small">Strategy bars share a 0-{scale*10000:.1f} bp magnitude scale. *Published strategy return has incomplete underlying ETF price verification.</p>'
    for h in ('1D','1M'):
        p=a['periods'][h]
        body+=f'<h2>{h} ETF contributors and detractors</h2><p class="small">{escape(str(p["start"]))} to {escape(p["end"])}. Source: published historical holdings and adjusted prices.</p>'
        if p['status']=='unavailable':
            body+='<p>'+escape(bridge_text(p))+'</p>';continue
        selected=leaders(a,h)
        for key,title,colour,bg in [('positive','Positive contributors',GREEN,'#edf7f0'),('negative','Negative contributors',RED,'#fdf0ee')]:
            group=selected[key][:3]
            body+=f'<div style="border-left:4px solid {colour};background:{bg};padding:12px;margin:12px 0"><strong style="color:{colour}">{title}</strong>'
            body+=table(['ETF / model label','Contribution'],[[f'{x["name"]} ({x["ticker"]})',BarValue(x['contrib'],selected['scale'],label=bp(x['contrib']))] for x in group]) if group else '<p>None with complete price coverage.</p>'
            body+='</div>'
        body+=f'<p class="small">Top three per sign among fully priced holdings; both groups share a 0-{selected["scale"]*10000:.1f} bp scale for {h}. Exited holdings remain in the monthly calculation.</p>'
        body+='<div style="background:#fff8eb;border-left:4px solid #b45309;padding:12px"><strong>Reconciliation'+(' / review required' if p['status']=='review' else '')+'</strong><p style="margin:6px 0">'+escape(bridge_text(p))+'</p>'
        if p['issues']:body+='<p class="small" style="margin:0">'+escape('; '.join(p['issues']))+'</p>'
        body+='</div>'
    body+='<p class="small">'+escape(a['method'])+' Incomplete ETF rows are excluded from rankings, not treated as zero. Residuals of 5 bp or more are flagged in either direction. This explains absolute model return, not benchmark excess or actual-account P&amp;L. Full ETF and strategy details are in the PDF and dashboard.</p>'
    return body


@dataclass(frozen=True)
class BarValue:
    value: float | None
    scale: float
    kind: str = 'return'
    label: str | None = None

    @property
    def text(self):
        return self.label if self.label is not None else pct(self.value)

    @property
    def fraction(self):
        if self.value is None or not math.isfinite(self.value): return 0
        if self.scale <= 0 or abs(self.value) > self.scale + 1e-12:
            raise ValueError('Bar scale must contain the complete observation')
        return abs(self.value) / self.scale

    @property
    def colour(self):
        if self.kind == 'weight': return BLUE
        if self.kind == 'risk': return CYAN
        if self.value is None or self.value == 0: return MUTED
        return GREEN if self.value > 0 else RED


def bar_html(value):
    label=escape(value.text)
    if value.value is None:
        return f'<span style="color:{MUTED}">{label}</span>'
    return (f'<span style="color:{value.colour};font-weight:bold">{label}</span>'
            f'<div aria-hidden="true" style="height:4px;background:{TRACK};margin-top:5px;width:100%">'
            f'<div style="height:4px;width:{value.fraction*100:.4f}%;background:{value.colour}"></div></div>')


def return_scale(r):
    return max([abs(x[k]) for x in r['performance'] for k in ('model','SPY','AOR')
                if x.get(k) is not None] + [.000001])


def drawdown_bar(r):
    worst=abs(r['risk_rows'][0]['max_dd'])
    return BarValue(r['current_dd'],max(worst,abs(r['current_dd']),.000001),label=pct(r['current_dd']))


def pct(x):
    return fmt(x, True)


def number(x):
    return fmt(x)


def cell(value, header=False):
    tag = 'th' if header else 'td'
    content=bar_html(value) if isinstance(value,BarValue) else (f'<strong style="color:{value.colour}">{value.text}</strong>' if isinstance(value,ExcessValue) else escape(str(value)))
    bg='background:#f5f5f0;' if header else ''
    return f'<{tag} style="{bg}padding:10px 6px;border-bottom:1px solid {BORDER};text-align:left;font-size:14px;line-height:1.45;vertical-align:top">{content}</{tag}>'


def table(headers, rows):
    return '<table style="width:100%;border-collapse:collapse;table-layout:fixed"><thead><tr>' + ''.join(cell(h,True) for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join(cell(x) for x in row)+'</tr>' for row in rows) + '</tbody></table>'


def shell(title, content):
    # Inline properties carry the layout in email clients; CSS adds phone refinements.
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)}</title>
<style>html{{-webkit-text-size-adjust:100%}}body{{margin:0;background:#fafaf8;color:{INK};font:16px/1.6 Arial,sans-serif}}p{{max-width:70ch}}a{{color:#1d4ed8}}.wrap{{max-width:640px;margin:auto;padding:32px 24px}}.card{{border:1px solid {BORDER};border-radius:8px;padding:18px;background:#ffffff}}h1{{font:36px/1.15 Georgia,serif;margin:8px 0 16px}}h2{{font-size:18px;margin:26px 0 8px}}.small{{font-size:13px;color:{MUTED}}}@media(max-width:480px){{.wrap{{padding:22px 14px}}h1{{font-size:30px}}.card{{padding:12px}}th,td{{font-size:13px!important;padding:9px 4px!important}}}}</style></head>
<body style="margin:0;background:#fafaf8;color:{INK};font-family:Arial,sans-serif;font-size:16px;line-height:1.6"><main class="wrap" style="max-width:640px;margin:0 auto;padding:24px 14px">
<p style="font-size:12px;letter-spacing:1.2px;color:{MUTED};margin:0">MULTI-STRATEGY PORTFOLIO / PAPER MODEL</p>{content}
<p class="small" style="font-size:13px;color:{MUTED};border-top:1px solid {BORDER};padding-top:18px"><a href="{PAGE}">Open dashboard</a> &nbsp;|&nbsp; <a href="{URL}">Source data</a><br>Personal model portfolio. USD. Hypothetical returns, not account performance.</p></main></body></html>'''


def delay_html(expected, reasons):
    return shell('Portfolio data is delayed', '<h1 style="font-family:Georgia,serif;font-size:32px;line-height:1.2">The morning report is waiting for verified data.</h1>'
                 +f'<p>Expected US close: <strong>{escape(expected)}</strong>.</p>'
                 +'<div class="card" style="background:#ffffff;border:1px solid #e2e0d8;border-left:5px solid #b45309;padding:18px">'
                 +'<p style="margin-top:0">'+escape('; '.join(reasons))+'</p>'
                 +'<p style="margin-bottom:0">The full report and PDF will follow once the checks pass. No stale performance figures are being presented as overnight returns.</p></div>')


def report_html(r, preview=False):
    perf = r['performance']
    one = perf[0]
    colour = GREEN if one['model'] >= 0 else RED
    ytd = next((x['model'] for x in perf if x['period']=='YTD'),None)
    warning = '<p style="padding:12px;background:#fff4df;color:#92400e;font-weight:bold">DESIGN PREVIEW - sample only; not a scheduled delivery.</p>' if preview else ''
    title = f'Model {pct(one["model"])} for the session'
    body = warning+f'<h1 style="font-family:Georgia,serif;font-size:32px;line-height:1.2">{escape(title)}</h1>'
    body += f'<p style="font-size:14px;color:{MUTED}">Close of <strong>{r["nav_date"]}</strong> &middot; USD &middot; source: published model NAV</p>'
    body += '<table role="presentation" style="width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #e2e0d8"><tr>'
    for label,value,c in [('SESSION',pct(one['model']),colour),('YEAR TO DATE',pct(ytd),GREEN if ytd is not None and ytd>0 else RED if ytd is not None and ytd<0 else MUTED),('DRAWDOWN',pct(r['current_dd']),RED)]:
        body += f'<td style="width:33%;padding:12px 8px;vertical-align:top;border-top:4px solid {c}"><span style="font-size:11px;color:{MUTED}">{label}</span><br><strong style="font-size:25px;color:{c}">{value}</strong></td>'
    body += '</tr></table>'
    if 'SPY' in one:
        diff=(one['model']-one['SPY'])*100
        body += f'<p>The model was <strong style="color:{excess(one).colour}">{abs(diff):.2f} percentage points {"ahead of" if diff >= 0 else "behind"}</strong> the S&amp;P 500 total-return proxy for the same session.</p>'
    body += commentary_html(r)
    body += '<h2>Performance</h2><p class="small">Returns through '+r['nav_date']+'. Matched endpoints; detailed windows in the PDF.</p>'
    scale=return_scale(r)
    body += table(['Period','Model',SPY_LABEL,'Excess (pp)'],[[x['period']]+[BarValue(x.get(k),scale) for k in ('model','SPY')]+[excess(x)] for x in perf])
    body += f'<p class="small">{SPY_BASIS} Excess = model minus proxy on identical endpoints, in percentage points (pp). Green/red excess means outperformance/underperformance, even when both returns are negative.</p>'
    body += f'<p class="small">Return bars share one 0-{scale:.1%} magnitude scale: green = gain; red = loss. The PDF also shows the global 60/40 fund comparator and exact start dates.</p>'
    body += context_html(r.get('return_context'))
    body += contribution_html(r)
    body += etf_context_html(r.get('etf_return_context'))
    body += '<h2>Risk and positioning</h2>'
    w,g=r['weights'],r['regime']
    body += f'<p>{r["underwater_days"]} calendar days below the high-water mark. Top-five concentration: {w["concentration"]["top5"]:.1%}. Defensive allocation: {w["cash_pct"]:.1%}.</p>'
    body += '<div class="card" style="padding:12px;border:1px solid #e2e0d8;background:#ffffff"><strong style="font-size:14px">Current drawdown</strong><br>'+bar_html(drawdown_bar(r))+f'<p class="small" style="margin-bottom:0">Track ends at the historical maximum drawdown of {pct(r["risk_rows"][0]["max_dd"])} through {r["nav_date"]}. Historical context, not a loss limit.</p></div>'
    body += f'<p class="small">Model holdings anchor: {r["meta"].get("portfolio_anchor",r["meta"]["asOf"])}. Gate: {escape(g["state"].replace("_"," ").lower())}. Defensive allocation may include short-duration Treasury funds.</p>'
    body += table(['Window','CAGR','Volatility','Sharpe'],[[{'Full published history (includes backtest)':'Full history','Trailing 3 years':'3 years','Trailing 1 year':'1 year'}[x['period']],pct(x['cagr']),pct(x['vol']),number(x['sharpe'])] for x in r['risk_rows']])
    body += '<p class="small">Through '+r['nav_date']+'. Full history includes backtest. Sharpe uses the published Treasury-bill proxy; annualisation assumes 252 observations. Estimates and methodology in the PDF.</p>'
    risks={x['name']:x['risk_pct'] for x in r['risk_contributors']}
    allocations=sorted(w['rows'],key=lambda x:x['weight'],reverse=True)[:3]
    body += '<h2>Largest allocations</h2>'
    body += table(['Holding','NAV weight','Risk share*'],[[x['name'],BarValue(x['weight'],1,'weight',f'{x["weight"]:.1%}'),BarValue(risks.get(x['name']),1,'risk',f'{risks[x["name"]]:.1%}' if x['name'] in risks else '-')] for x in allocations])
    body += '<p class="small">Blue = share of NAV; teal = estimated share of portfolio risk. Both tracks run from 0 to 100%, with different denominators. *Only the three largest portfolio risk contributors are available here; a dash is not zero.</p>'
    body += '<div class="card" style="background:#ffffff;border:1px solid #e2e0d8;padding:18px;margin-top:24px"><strong>Attached: the portfolio review PDF</strong><p style="margin-bottom:0">Includes the full risk scorecard, attribution, valuation dates and calculation conventions. No portfolio action is implied by this report.</p></div>'
    return shell(title,body)


def report_pdf(r, path, preview=False):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
    class PDFBar(Flowable):
        def __init__(self,value,width):
            super().__init__(); self.value=value; self.width=width; self.height=20
        def draw(self):
            c=self.canv; v=self.value
            c.setFont('Helvetica-Bold',9); c.setFillColor(colors.HexColor(v.colour))
            c.drawString(0,10,v.text)
            if v.value is None: return
            c.setFillColor(colors.HexColor(TRACK)); c.rect(0,1,self.width,3,stroke=0,fill=1)
            c.setFillColor(colors.HexColor(v.colour)); c.rect(0,1,self.width*v.fraction,3,stroke=0,fill=1)
    class PDFRiskMove(Flowable):
        def __init__(self,value,width):
            super().__init__();self.value=value;self.width=width;self.height=43
        def draw(self):
            c=self.canv;v=self.value.value
            c.setFont('Helvetica-Bold',8.5);c.setFillColor(colors.HexColor(INK));c.drawString(0,31,self.value.text)
            if v is None:return
            for lo,hi,bg in [(-LIMIT,LIMIT,'#f5f5f0'),(-2,2,'#edf2f7'),(-1,1,'#dce8f4')]:
                c.setFillColor(colors.HexColor(bg));c.rect((lo+LIMIT)/(2*LIMIT)*self.width,16,(hi-lo)/(2*LIMIT)*self.width,8,stroke=0,fill=1)
            clipped=max(-LIMIT,min(LIMIT,v));a,b=sorted((0,clipped))
            c.setFillColor(colors.HexColor(GREEN if v>=0 else RED));c.rect((a+LIMIT)/(2*LIMIT)*self.width,16,(b-a)/(2*LIMIT)*self.width,8,stroke=0,fill=1)
            c.setFillColor(colors.HexColor(MUTED));c.setStrokeColor(colors.HexColor(MUTED));c.setFont('Helvetica',8.5)
            for tick in [-2,-1,0,1,2]:
                x=(tick+LIMIT)/(2*LIMIT)*self.width;c.line(x,14,x,26);c.drawCentredString(x,2,f'{tick:+d}' if tick else '0')
    class PDFETFMove(Flowable):
        def __init__(self,value,width):
            super().__init__();self.value=value;self.width=width;self.height=48
        def draw(self):
            c=self.canv;r=self.value.detail or {};v=r.get('units')
            c.setFont('Helvetica-Bold',8.5);c.setFillColor(colors.HexColor(INK))
            c.drawString(0,39,bp(self.value.contribution)+' impact')
            ret='-' if r.get('return') is None else f'{r["return"]:+.2%}'
            sd='-' if r.get('one_sd') is None else f'{r["one_sd"]:.2%}'
            c.setFont('Helvetica',8.5);c.drawString(0,29,f'ETF {ret} / SD {sd}')
            if v is None:
                c.drawString(0,20,'Risk units unavailable');return
            c.setFont('Helvetica-Bold',8.5);c.drawString(0,19,RiskMove(v).text)
            for lo,hi,bg in [(-LIMIT,LIMIT,'#f5f5f0'),(-2,2,'#edf2f7'),(-1,1,'#dce8f4')]:
                c.setFillColor(colors.HexColor(bg));c.rect((lo+LIMIT)/(2*LIMIT)*self.width,10,(hi-lo)/(2*LIMIT)*self.width,5,stroke=0,fill=1)
            a,b=sorted((0,max(-LIMIT,min(LIMIT,v))))
            c.setFillColor(colors.HexColor(GREEN if v>=0 else RED));c.rect((a+LIMIT)/(2*LIMIT)*self.width,10,(b-a)/(2*LIMIT)*self.width,5,stroke=0,fill=1)
            c.setFillColor(colors.HexColor(MUTED));c.setStrokeColor(colors.HexColor(MUTED));c.setFont('Helvetica',8.5)
            for tick in [-2,-1,0,1,2]:
                x=(tick+LIMIT)/(2*LIMIT)*self.width;c.line(x,8,x,17);c.drawCentredString(x,0,f'{tick:+d}' if tick else '0')
    styles={
        'title':ParagraphStyle('title',fontName='Times-Roman',fontSize=27,leading=30,textColor=colors.HexColor(INK),spaceAfter=12),
        'h':ParagraphStyle('h',fontName='Helvetica-Bold',fontSize=12,leading=16,spaceBefore=14,spaceAfter=7),
        'p':ParagraphStyle('p',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=7),
        'small':ParagraphStyle('small',fontName='Helvetica',fontSize=8.5,leading=11,textColor=colors.HexColor(MUTED),spaceAfter=6),
        'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=9,leading=12),
    }
    flow=[]
    def p(text,style='p'):
        flow.append(Paragraph(text,styles[style]))
    def t(headers,rows,widths,padding=5):
        # Equal pixel lengths per unit within a table, even if text-column widths differ.
        bar_width=min([widths[i]-12 for row in rows for i,x in enumerate(row) if isinstance(x,BarValue)]+[width])
        data=[[PDFETFMove(x,widths[i]-12) if isinstance(x,ETFMove) else PDFRiskMove(x,widths[i]-12) if isinstance(x,RiskMove) else PDFBar(x,bar_width) if isinstance(x,BarValue) else Paragraph(f'<font color="{x.colour}"><b>{x.text}</b></font>' if isinstance(x,ExcessValue) else escape(str(x)).replace('\n','<br/>'),styles['cell']) for i,x in enumerate(row)] for row in [headers]+rows]
        tb=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        tb.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#f5f5f0')),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor(BORDER)),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),padding),('BOTTOMPADDING',(0,0),(-1,-1),padding)]))
        flow.append(tb)
    width=A4[0]-36*mm
    p('MULTI-STRATEGY PORTFOLIO / PAPER MODEL','small')
    if preview: p('DESIGN PREVIEW - sample only; not a scheduled delivery.','h')
    one=r['performance'][0]
    p(f'Model {pct(one["model"])} for the session','title')
    p(f'USD | Close of {r["nav_date"]} | Published model NAV','small')
    p(f'Current drawdown: <b>{pct(r["current_dd"])}</b>. Time below the high-water mark: <b>{r["underwater_days"]} calendar days</b>.')
    flow.append(PDFBar(drawdown_bar(r),width))
    p(f'Drawdown track: zero to historical maximum {pct(r["risk_rows"][0]["max_dd"])} through {r["nav_date"]}; not a loss limit.','small')
    p('Performance on matched valuation dates','h')
    scale=return_scale(r)
    t(['Period','Model',SPY_LABEL,'Excess (pp)','Global 60/40','Start'],[[x['period']]+[BarValue(x.get(k),scale) for k in ('model','SPY')]+[excess(x),BarValue(x.get('AOR'),scale),x['start']] for x in r['performance']],[width*.12,width*.14,width*.17,width*.15,width*.18,width*.24])
    p(f'All periods end {r["nav_date"]}. Bars show absolute return on a common 0-{scale:.1%} scale; green = gain, red = loss. Global 60/40: balanced-fund proxy. Source: deployed model dataset.','small')
    p(SPY_BASIS+' Excess = model minus proxy, in percentage points.','small')
    commentary=build_commentary(r)
    box_rows=[[Paragraph('Portfolio manager commentary',ParagraphStyle('commentary-h',parent=styles['h'],spaceBefore=0,spaceAfter=3))]]
    for label,text in commentary['paragraphs']:
        box_rows.append([Paragraph('<b>'+escape(label)+'.</b> '+escape(text),styles['cell'])])
    provenance=escape(commentary['provenance'])
    if commentary['sources']:
        # Compact citations keep all three developments and sources on page 1.
        provenance='US session '+r['nav_date']+'; cutoff '+r['market_context']['cutoff_utc']+'. X briefing claims; interpretation is not causal attribution.'
        provenance+=' Sources: '+' '.join('<link href="'+escape(s['url'],quote=True)+'" color="#1d4ed8">['+s['citation']+']</link>' for s in commentary['sources'])+'.'
    box_rows.append([Paragraph(provenance,styles['small'])])
    box=Table(box_rows,colWidths=[width],hAlign='LEFT')
    box.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f5fa')),('BOX',(0,0),(-1,-1),.5,colors.HexColor('#d6e2ed')),('LINEBEFORE',(0,0),(0,-1),3,colors.HexColor(BLUE)),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    flow.append(box)
    p(f'<link href="{PAGE}" color="#1d4ed8">Open dashboard</link> | <link href="{URL}" color="#1d4ed8">Open source dataset</link>','p')
    flow.append(PageBreak())
    p('What drove the return?','title')
    w,g=r['weights'],r['regime']
    p(f'Model holdings anchor: {r["meta"].get("portfolio_anchor",r["meta"]["asOf"])}. Gate: {escape(g["state"])}. Breadth {g["breadth"]:.1%} at {g["panel_end_date"]}. Defensive allocation {w["cash_pct"]:.1%}; top-five weight {w["concentration"]["top5"]:.1%}.','p')
    attr=r['attribution']
    p('Largest ETF contributors and detractors','h')
    p('USD portfolio contribution in bp; up to five contributors and five detractors per horizon, including exits. Fewer names are shown when a side has fewer than five non-zero contributions. Full detail follows in the appendix.','small')
    p(' | '.join(h+': '+(attr['periods'][h]['start'] or 'Unavailable')+' to '+attr['periods'][h]['end'] for h in ('1D','1M')),'small')
    selected={}
    for hz in ('1D','1M'):
        ranked=leaders(attr,hz)
        selected[hz]=ranked['positive'][:5]+ranked['negative'][:5]
    leader_scale=max([abs(x['contrib']) for rows in selected.values() for x in rows]+[.000001])
    leader_rows=[]
    for i in range(max(len(rows) for rows in selected.values())):
        cells=[]
        for hz in ('1D','1M'):
            x=selected[hz][i] if i<len(selected[hz]) else None
            cells.extend([x['name']+' ('+x['ticker']+')' if x else '-',BarValue(x['contrib'],leader_scale,label=bp(x['contrib'])) if x else '-'])
        leader_rows.append(cells)
    t(['1D ETF','Impact','1M ETF','Impact'],leader_rows,[width*.36,width*.14,width*.36,width*.14],padding=3)
    p(f'Common magnitude scale: 0-{leader_scale*10000:.1f} bp. Green adds to return; red detracts. Selection is independent for each horizon.','small')
    p('Historical strategy contribution','h')
    attr=r['attribution']; strategy_rows=comparison_rows(attr,'strategy')
    strategy_scale=max([abs(x[h]) for x in strategy_rows for h in ('1D','1M') if x[h] is not None]+[.000001])
    t(['Strategy','1D','1M'],[[x['name']]+[BarValue(x[h],strategy_scale,label=bp(x[h])+(' *' if x[h+'_coverage']<.999999 else '')) for h in ('1D','1M')] for x in strategy_rows],[width*.6,width*.2,width*.2])
    p(f'Common scale 0-{strategy_scale*10000:.1f} bp. *Published net strategy return; underlying ETF price verification is incomplete.','small')
    for hz in ('1D','1M'):
        ap=attr['periods'][hz]
        flag=' <b>Residual requires review.</b>' if ap['etf_residual'] is not None and abs(ap['etf_residual'])>=.0005 else ''
        p('<b>Reconciliation '+hz+':</b> '+escape(bridge_text(ap))+flag,'small')
    p('Source: historical model holdings and USD price marks. ETF marks are gross; strategy returns include source costs. The selected ETF rows are a subset; reconciliation includes all holdings. Residuals remain unexplained.','small')
    flow.append(PageBreak())
    if r.get('return_context'):
        p('Return context and risk','title')
        p('How large was the move relative to prior risk?','h')
        context=r['return_context']
        t(['Window / measure','Actual','1 s.d.','Move / risk'],[[x['horizon']+' / '+x['label'],
          '-' if x['return'] is None else f'{x["return"]*100:+.2f}'+(' pp' if x['kind']=='active' else '%'),
          '-' if x['one_sd'] is None else f'{x["one_sd"]*100:.2f}'+(' pp' if x['kind']=='active' else '%'),RiskMove(x['units'])] for x in context_rows(context)],
          [width*.31,width*.14,width*.14,width*.41])
        p('Shading marks +/-1 and +/-2; all tracks end at +/-2.5. Full numeric values remain visible beyond the scale. Green/red shows return direction. Active risk is tracking error against the S&P 500 TR proxy.','small')
        for hz,cp in context['periods'].items():
            p(f'{hz}: {cp["start"]} to {cp["end"]}. '+(f'{cp["sessions"]} sessions; {cp["observations"]} prior matched daily returns, {cp["training_start"]} to {cp["training_end"]}; {cp["excluded_gaps"]} gap observations excluded.' if cp['status']=='ok' else cp['reason']),'small')
        p('252 prior matched returns; sample standard deviation scaled by sqrt(actual sessions). Model return uses model volatility; excess uses active-return volatility. No expected return is subtracted: these are not z-scores, probabilities or risk limits. Monthly scaling assumes stable variance and no serial correlation. Source: published model NAV and SPY adjusted-close proxy.','small')
    p('Long-term risk scorecard','h')
    t(['Window','CAGR','Vol.','Sharpe','Sortino','Calmar','Max DD'],[[{'Full published history (includes backtest)':'Full history','Trailing 3 years':'3 years','Trailing 1 year':'1 year'}[x['period']],pct(x['cagr']),pct(x['vol']),number(x['sharpe']),number(x['sortino']),number(x['calmar']),pct(x['max_dd'])] for x in r['risk_rows']],[width*.19]+[width*.135]*6)
    for x in r['risk_rows']: p(f'{escape(x["period"])}: {x["start"]} to {x["end"]}; {x["observations"]} return observations.','small')
    p('Hypothetical model performance. Full history includes backtest; the live extension, where present, is marked to market. Historical statistics are descriptive, not a forecast.','small')
    p('Risk relative to benchmarks - trailing one year','h')
    t(['Benchmark','Beta','Tracking error','Information ratio'],[[SPY_LABEL if x['benchmark']=='S&P 500' else x['benchmark'],number(x['beta']),pct(x['tracking_error']),number(x['information_ratio'])] for x in r['relative_rows']],[width*.40,width*.15,width*.23,width*.22])
    flow.append(PageBreak())
    p('ETF contribution: historical holdings','title')
    p('USD; 1D and trailing 1M. Names include the model label and pricing proxy where different. Avg. wt is the mean beginning-of-session NAV weight over the monthly window; exited positions remain included.','small')
    etfs=sorted(comparison_rows(attr,'etf'),key=lambda x:-abs(x['1M'] if x['1M'] is not None else x['1D'] or 0))
    scale=max([abs(x[h]) for x in etfs for h in ('1D','1M') if x[h] is not None]+[.000001])
    strategy_names={x['code']:x['name'] for ap in attr['periods'].values() for x in ap['strategy']}
    etf_context=r.get('etf_return_context')
    risk_by={h:{x['ticker']:x for x in cp['rows']} for h,cp in etf_context['periods'].items()} if etf_context else {}
    if etf_context:
        # Include a new end-close position even if it earned no historical contribution.
        existing={x['ticker'] for x in etfs}
        for x in etf_context['periods']['1M']['rows']:
            if x['ticker'] not in existing:
                etfs.append({**x,'strategies':[],'avg_weight_1M':0 if attr['periods']['1M']['status']!='unavailable' else None,
                             **{h:risk_by[h][x['ticker']]['contribution'] for h in ('1D','1M')}})
    if etf_context:
        p('Impact is contribution in portfolio bp. ETF is full-window USD price return; SD is its own estimated horizon volatility. Risk tracks end at +/-2.5 with +/-1 and +/-2 ticks. Returns include days not held; income and carry remain in the ratio.','small')
        for h,cp in etf_context['periods'].items():
            p(f'{h}: {cp["start"]} to {cp["end"]}; 252 prior valid USD valuation returns per estimate. Per-ETF estimation dates are available in the dashboard. Missing price/history estimates are unavailable.','small')
    t(['ETF / owning strategy','Avg. wt 1M','1D','1M'],
      [[x['name']+' ('+x['ticker']+')'+(' / priced as '+x['price_symbol'] if x['price_symbol']!=x['ticker'] else '')+'\n'+', '.join(strategy_names.get(c,c) for c in x['strategies']),
        '-' if x['avg_weight_1M'] is None else f'{x["avg_weight_1M"]:.1%}']+[ETFMove(x[h],risk_by[h].get(x['ticker'])) if etf_context else BarValue(x[h],scale,label=bp(x[h])) for h in ('1D','1M')] for x in etfs],
      [width*.40,width*.10,width*.25,width*.25] if etf_context else [width*.49,width*.15,width*.18,width*.18])
    p(('ETF tracks show own-volatility units; contribution figures remain in bp. ' if etf_context else f'All ETF bars share a 0-{scale*10000:.1f} bp magnitude scale. ')+'A dash means the complete period cannot be verified; known partial marks remain in the reconciliation bridge. Zero means no contribution or no position in that period.','small')
    if etf_context:p('ETF risk: 252 prior valid USD valuation returns, sample SD scaled by sqrt(actual sessions); no reported-window observations. FX uses same-date rates; local closes are asynchronous and carry only over verified exchange holidays. Missing open-session marks are not filled. Income and carry remain; not a z-score. Monthly scaling assumes stable variance and no serial correlation.','small')
    for hz in ('1D','1M'):
        ap=attr['periods'][hz]
        p(f'{hz}: {ap["start"]} to {ap["end"]}. '+bridge_text(ap),'small')

    p('Historical holdings are effective after fill-date close. Contributions link using prior official NAV / period-start NAV. ETF marks are gross; strategy returns include source costs. Residuals remain unexplained.','small')
    p('Price acquisition: '+escape(str(attr.get('prices_acquired_at_utc','unavailable')))+'. Absolute contribution, not attribution of benchmark excess. Model history is hypothetical; actual-account fills are not used.','small')
    p('CAGR uses actual calendar days. Volatility, Sharpe and tracking error use 252 observations per year. The common-date panel can contain multi-session gaps, so annualised risk measures are approximations. Sharpe subtracts the published Treasury-bill proxy. Sortino uses the root mean square of negative excess returns over all observations. Calmar is CAGR divided by absolute maximum drawdown. Information ratio is mean active daily return divided by its standard deviation, annualised.','small')
    p(f'No missing benchmark observations are forward-filled. Fund proxies include their own expenses. Source cost assumption: {r["meta"].get("cost_assumption_bps","unavailable")}bp; actual fills, account costs and capacity are not verified. Engine-labelled out-of-sample start: {r["meta"].get("oos_start","unavailable")}; not independent proof of an untouched holdout.','small')
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(18*mm,17*mm,f'Model source {r["meta"]["source_commit"][:12]} | Built {r["meta"]["built_at_utc"]}')
        canvas.drawString(18*mm,12*mm,f'Personal paper portfolio | USD | NAV {r["nav_date"]}')
        canvas.drawRightString(A4[0]-18*mm,12*mm,f'{doc.page}')
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=20*mm).build(flow,onFirstPage=footer,onLaterPages=footer)


def write_bundle(r, directory, preview=False):
    out=Path(directory); out.mkdir(parents=True,exist_ok=True)
    (out/'report.html').write_text(report_html(r,preview),encoding='utf-8')
    (out/'report.txt').write_text(r['body'],encoding='utf-8')
    report_pdf(r,out/'portfolio-review.pdf',preview)
    return out
