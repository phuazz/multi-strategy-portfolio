"""Shared numeric selection for the email and PDF; no recalculation of attribution."""
from historical_attribution import validate


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
