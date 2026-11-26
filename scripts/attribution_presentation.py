"""Shared numeric selection for the email and PDF; no recalculation of attribution."""
from historical_attribution import validate
import math


def etf_label(ticker, name=None):
    """Use the reserve role in prose and include its maturity range in tables."""
    if ticker == 'SHY':
        return 'US Treasury reserve, 1–3 years (SHY)' if name is not None else 'Treasury reserve (SHY)'
    return f'{name} ({ticker})' if name is not None else ticker


def bp(value):
    return '-' if value is None else f'{value*10000:+.1f} bp'


def comparison_rows(attribution, kind):
    validate(attribution)
    periods=attribution['periods']; key='ticker' if kind=='etf' else 'code'
    indexes={h:{r[key]:r for r in p[kind]} for h,p in periods.items()}
    rows=[]
    for identifier in sorted(set(indexes['1D'])|set(indexes['1M'])):
        base=indexes['1M'].get(identifier) or indexes['1D'][identifier]
        row={**base,'id':identifier}
        row['avg_weight_1M']=None if periods['1M']['status']=='unavailable' else indexes['1M'].get(identifier,{}).get('avg_weight',0.)
        for h in ('1D','1M'):
            p=periods[h]; source=indexes[h].get(identifier)
            row[h]=None if p['status']=='unavailable' else source['contrib'] if source else 0.
            row[h+'_coverage']=source.get('coverage',1) if source else 1.
        rows.append(row)
    return rows


def leaders(attribution, horizon):
    validate(attribution)
    p=attribution['periods'][horizon]
    rows=[r for r in p['etf'] if r['contrib'] is not None]
    positive=sorted([r for r in rows if r['contrib']>0],key=lambda r:-r['contrib'])
    negative=sorted([r for r in rows if r['contrib']<0],key=lambda r:r['contrib'])
    return {'positive':positive,'negative':negative,
            'scale':max([abs(r['contrib']) for r in rows]+[.000001])}


def bridge_text(p):
    if p['status']=='unavailable': return '; '.join(p['issues'])
    return (f'Known ETF marks {bp(p["etf_total"])} + unexplained residual {bp(p["etf_residual"])} '
            f'= model {bp(p["model_return"])}. Strategy residual {bp(p["strategy_residual"])}. '
            f'Price coverage {p["coverage"]:.1%} of held weight-days. Displayed sums may differ through rounding.')


def daily_drivers(attribution, etf_context=None, session=None):
    validate(attribution)
    period = attribution['periods']['1D']
    if period['status'] == 'unavailable':
        return [], None
    proxy = None
    if (session and session.get('SPY') is not None
            and (session.get('start'), session.get('end')) == (period['start'], period['end'])
            and period.get('observations') == 1
            and math.isclose(period['model_return'], session['model'], abs_tol=1e-10)):
        proxy = session['SPY']
    returns = {}
    if etf_context:
        window = etf_context['periods']['1D']
        if (window['start'], window['end']) != (period['start'], period['end']):
            raise ValueError('Daily ETF return dates differ from contribution dates')
        returns = {row['ticker']: row['return'] for row in window['rows']}
    priced = []
    for row in period['etf']:
        if row['contrib'] is None:
            continue
        active = None if proxy is None else row['contrib'] - row['avg_weight'] * proxy
        priced.append(dict(row, usd_return=returns.get(row['ticker']), active=active))
    rank = 'active' if proxy is not None else 'contrib'
    ranked = sorted((row for row in priced if abs(row[rank]) > 1e-12),
                    key=lambda row: (-abs(row[rank]), row['ticker']))
    selected = ranked[:5]
    if proxy is None:
        return selected, None
    total = session['model'] - proxy
    known = sum(row['active'] for row in priced)
    shown = sum(row['active'] for row in selected)
    return selected, dict(shown=shown, other=known-shown, unassigned=total-known, total=total)
