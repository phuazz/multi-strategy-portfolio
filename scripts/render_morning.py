"""HTML email and two-page A4 dossier, rendered from one verified report object."""
from __future__ import annotations

from html import escape
from pathlib import Path

from morning_report import PAGE, URL, fmt

INK, MUTED, GREEN, RED, BORDER = '#1a1a18', '#5c5c56', '#146c43', '#a93226', '#e2e0d8'


def pct(x):
    return fmt(x, True)


def number(x):
    return fmt(x)


def cell(value, header=False):
    tag = 'th' if header else 'td'
    return f'<{tag} style="padding:10px 6px;border-bottom:1px solid {BORDER};text-align:left;font-size:14px;line-height:1.45">{escape(str(value))}</{tag}>'


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
                 +'<div class="card" style="background:#ffffff;border:1px solid #e2e0d8;padding:18px">'
                 +'<p style="margin-top:0">'+escape('; '.join(reasons))+'</p>'
                 +'<p style="margin-bottom:0">The full report and PDF will follow once the checks pass. No stale performance figures are being presented as overnight returns.</p></div>')


def report_html(r, preview=False):
    perf = r['performance']
    one = perf[0]
    colour = GREEN if one['model'] >= 0 else RED
    ytd = next((x['model'] for x in perf if x['period']=='YTD'),None)
    warning = '<p style="padding:12px;background:#fff4df;color:#92400e;font-weight:bold">DESIGN PREVIEW - prior-session data; not a current overnight report.</p>' if preview else ''
    title = f'Model {pct(one["model"])} for the session'
    body = warning+f'<h1 style="font-family:Georgia,serif;font-size:32px;line-height:1.2">{escape(title)}</h1>'
    body += f'<p style="font-size:14px;color:{MUTED}">Close of <strong>{r["nav_date"]}</strong> &middot; USD &middot; source: published model NAV</p>'
    body += '<table role="presentation" style="width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #e2e0d8"><tr>'
    for label,value,c in [('SESSION',pct(one['model']),colour),('YEAR TO DATE',pct(ytd),INK),('DRAWDOWN',pct(r['current_dd']),RED)]:
        body += f'<td style="width:33%;padding:12px 8px;vertical-align:top"><span style="font-size:11px;color:{MUTED}">{label}</span><br><strong style="font-size:25px;color:{c}">{value}</strong></td>'
    body += '</tr></table>'
    if 'SPY' in one:
        diff=(one['model']-one['SPY'])*100
        body += f'<p>The model was {abs(diff):.2f} percentage points {"ahead of" if diff >= 0 else "behind"} the S&amp;P 500 for the same session.</p>'
    body += '<h2>Performance</h2><p class="small">Returns through '+r['nav_date']+'. Matched endpoints; detailed windows in the PDF.</p>'
    body += table(['Period','Model','S&P 500','Global 60/40'],[[x['period'],pct(x['model']),pct(x.get('SPY')),pct(x.get('AOR'))] for x in perf])
    body += '<h2>Risk and positioning</h2>'
    w,g=r['weights'],r['regime']
    body += f'<p>{r["underwater_days"]} calendar days below the high-water mark. Top-five concentration: {w["concentration"]["top5"]:.1%}. Defensive allocation: {w["cash_pct"]:.1%}.</p>'
    body += f'<p class="small">Executed book: {r["meta"].get("portfolio_anchor",r["meta"]["asOf"])}. Gate: {escape(g["state"].replace("_"," ").lower())}. Defensive allocation may include short-duration Treasury funds.</p>'
    body += table(['Window','CAGR','Volatility','Sharpe'],[[{'Full published history (includes backtest)':'Full history','Trailing 3 years':'3 years','Trailing 1 year':'1 year'}[x['period']],pct(x['cagr']),pct(x['vol']),number(x['sharpe'])] for x in r['risk_rows']])
    body += '<p class="small">Through '+r['nav_date']+'. Full history includes backtest. Sharpe uses the published Treasury-bill proxy; annualisation assumes 252 observations. Estimates and methodology in the PDF.</p>'
    attrs=r['attribution']
    if attrs:
        low=min(attrs,key=lambda x:x['1D']['contrib']); high=max(attrs,key=lambda x:x['1D']['contrib'])
        body += '<h2>Indicative contributors</h2>'
        body += f'<p>{escape(high["name"])}: {high["1D"]["contrib"]*100:+.2f}pp.<br>{escape(low["name"])}: {low["1D"]["contrib"]*100:+.2f}pp.</p>'
        body += f'<p class="small">Current-weight estimates from build {escape(r["meta"]["built_at_utc"])}; not realised attribution. Residual to model return: {r["attribution_residual"]*100:+.2f}pp. Individual quote dates are not independently stamped.</p>'
    body += '<div class="card" style="background:#ffffff;border:1px solid #e2e0d8;padding:18px;margin-top:24px"><strong>Attached: the portfolio review PDF</strong><p style="margin-bottom:0">Includes the full risk scorecard, attribution, valuation dates and calculation conventions. No portfolio action is implied by this report.</p></div>'
    return shell(title,body)


def report_pdf(r, path, preview=False):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
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
    def t(headers,rows,widths):
        data=[[Paragraph(escape(str(x)),styles['cell']) for x in row] for row in [headers]+rows]
        tb=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        tb.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#f5f5f0')),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor(BORDER)),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        flow.append(tb)
    width=A4[0]-36*mm
    p('MULTI-STRATEGY PORTFOLIO / PAPER MODEL','small')
    if preview: p('DESIGN PREVIEW - prior-session data; not a current overnight report.','h')
    one=r['performance'][0]
    p(f'Model {pct(one["model"])} for the session','title')
    p(f'USD | Close of {r["nav_date"]} | Published model NAV','small')
    p(f'Current drawdown: <b>{pct(r["current_dd"])}</b>. Time below the high-water mark: <b>{r["underwater_days"]} calendar days</b>.')
    p('Performance on matched valuation dates','h')
    t(['Period','Model','S&P 500','Global 60/40','Start'],[[x['period'],pct(x['model']),pct(x.get('SPY')),pct(x.get('AOR')),x['start']] for x in r['performance']],[width*.18,width*.18,width*.18,width*.22,width*.24])
    p(f'All periods end {r["nav_date"]}. Global 60/40 uses the published balanced-fund proxy. Source: deployed model dataset.','small')
    p('Long-term risk scorecard','h')
    t(['Window','CAGR','Vol.','Sharpe','Sortino','Calmar','Max DD'],[[{'Full published history (includes backtest)':'Full history','Trailing 3 years':'3 years','Trailing 1 year':'1 year'}[x['period']],pct(x['cagr']),pct(x['vol']),number(x['sharpe']),number(x['sortino']),number(x['calmar']),pct(x['max_dd'])] for x in r['risk_rows']],[width*.19]+[width*.135]*6)
    for x in r['risk_rows']: p(f'{escape(x["period"])}: {x["start"]} to {x["end"]}; {x["observations"]} return observations.','small')
    p('Risk relative to benchmarks - trailing one year','h')
    t(['Benchmark','Beta','Tracking error','Information ratio'],[[x['benchmark'],number(x['beta']),pct(x['tracking_error']),number(x['information_ratio'])] for x in r['relative_rows']],[width*.40,width*.15,width*.23,width*.22])
    p('Hypothetical model performance. Full history includes backtest; the live extension, where present, is marked to market. Historical statistics are descriptive, not a forecast.','small')
    flow.append(PageBreak())
    p('Exposures, attribution and basis','title')
    w,g=r['weights'],r['regime']
    p(f'Executed book: {r["meta"].get("portfolio_anchor",r["meta"]["asOf"])}. Gate: {escape(g["state"])}. Breadth {g["breadth"]:.1%} at {g["panel_end_date"]}. Defensive allocation {w["cash_pct"]:.1%}; top-five weight {w["concentration"]["top5"]:.1%}.','p')
    p('Largest allocations and estimated risk shares','h')
    risks={x['name']:x['risk_pct'] for x in r['risk_contributors']}
    allocations=sorted(w['rows'],key=lambda x:x['weight'],reverse=True)[:5]
    t(['Portfolio label','Weight','Risk share*'],[[x['name'],f'{x["weight"]:.1%}',f'{risks[x["name"]]:.1%}' if x['name'] in risks else '-'] for x in allocations],[width*.62,width*.18,width*.20])
    p('*Only the three largest risk shares are shown. Current-weight historical covariance estimates; not forecasts. Defensive holdings may include Treasury funds.','small')
    p('Indicative one-session attribution','h')
    attrs=r['attribution']; ordered=sorted(attrs,key=lambda x:x['1D']['contrib'])
    selected=ordered[:2]+ordered[-2:] if len(ordered)>=4 else ordered
    t(['Portfolio label','Contribution'],[[x['name'],f'{x["1D"]["contrib"]*100:+.2f}pp'] for x in selected],[width*.76,width*.24])
    if selected: p(f'Current-weight approximation; residual to official return {r["attribution_residual"]*100:+.2f}pp. Not realised holdings attribution. Build {r["meta"]["built_at_utc"]}; individual rows lack an independent valuation timestamp.','small')
    p('Calculation conventions and provenance','h')
    p('CAGR uses actual calendar days. Volatility, Sharpe and tracking error use 252 observations per year. The common-date panel can contain multi-session gaps, so annualised risk measures are approximations. Sharpe subtracts the published Treasury-bill proxy. Sortino uses the root mean square of negative excess returns over all observations. Calmar is CAGR divided by absolute maximum drawdown. Information ratio is mean active daily return divided by its standard deviation, annualised.','small')
    p(f'No missing benchmark observations are forward-filled. Fund proxies include their own expenses. Source cost assumption: {r["meta"].get("cost_assumption_bps","unavailable")}bp; actual fills, account costs and capacity are not verified. Engine-labelled out-of-sample start: {r["meta"].get("oos_start","unavailable")}; not independent proof of an untouched holdout.','small')
    p(f'Source commit: {r["meta"]["source_commit"]}. Built {r["meta"]["built_at_utc"]}. All dates are source-derived and library-checked; disputed valuation dates require confirmation.','small')
    p(f'<link href="{PAGE}" color="#1d4ed8">Open dashboard</link> | <link href="{URL}" color="#1d4ed8">Open source dataset</link>','p')
    p('Review the data exceptions and portfolio concentrations; no trade instruction is implied.','small')
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(18*mm,12*mm,f'Personal paper portfolio | USD | NAV {r["nav_date"]}')
        canvas.drawRightString(A4[0]-18*mm,12*mm,f'{doc.page}')
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=20*mm).build(flow,onFirstPage=footer,onLaterPages=footer)


def write_bundle(r, directory, preview=False):
    out=Path(directory); out.mkdir(parents=True,exist_ok=True)
    (out/'report.html').write_text(report_html(r,preview),encoding='utf-8')
    (out/'report.txt').write_text(r['body'],encoding='utf-8')
    report_pdf(r,out/'portfolio-review.pdf',preview)
    return out
