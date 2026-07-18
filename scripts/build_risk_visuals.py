r"""Build the Multi-Strategy Portfolio risk visuals + trigger numbers for the digest.

Produces, in the output directory:
  - breadth_gauge.png       : S&P 500 breadth vs the de-risk / re-engage thresholds
  - proximity_200dma.png    : every holding's % distance above its 200-day MA
  - risk_triggers.json      : the computed numbers, so the digest can populate the
                              "Triggers to watch" panel from real data (never by hand)

Why this exists: the weekly digest scheduled task must show real trigger levels, not
prose. This encapsulates two easy-to-get-wrong details:
  1. holdings_prices_1y.json's `vs_ma200` is a FRACTION (0.60 = +60% above the MA),
     not a percentage. Multiply by 100.
  2. Several book tickers are not keyed directly in the price panel: the LSE-listed
     iShares use US proxies (IUES->XLE, IUUS->XLU, IUSP->XLRE, IUMS->XLB) and the
     Xetra lines use a .DE suffix (EXH1->EXH1.DE). Map before reading.

Usage:
    python build_risk_visuals.py --out <dir>                     # fetch engine data @main
    python build_risk_visuals.py --out <dir> --local ../breadth-thrust-etf   # read off disk
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/phuazz/breadth-thrust-etf/main/data"
FILES = ["risk_overlay.json", "live_track.json", "holdings_prices_1y.json"]
PROXY = {"IUES": "XLE", "IUUS": "XLU", "IUSP": "XLRE", "IUMS": "XLB"}
REGISTRY = Path(__file__).resolve().parent.parent / "portfolios" / "multi-strategy-portfolio.json"


def load(name, local):
    if local:
        p = Path(local) / "data" / name
        return json.loads(p.read_text(encoding="utf-8"))
    with urllib.request.urlopen(f"{RAW}/{name}", timeout=30) as r:  # noqa: S310 (trusted host)
        return json.loads(r.read().decode("utf-8"))


def price_key(tk, prices, meta):
    if tk in prices:
        return tk
    if tk + ".DE" in prices:
        return tk + ".DE"
    tr = meta.get(tk, {}).get("tradeAs")
    if tr and tr in prices:
        return tr
    if tk in PROXY and PROXY[tk] in prices:
        return PROXY[tk]
    return None


def prox_pct(rec, at=-1):
    """% above the 200-DMA at series index `at` (-1 = latest). None if unavailable."""
    ps, ma = rec.get("prices"), rec.get("ma200")
    if not ps or not ma:
        return None
    try:
        p, m = ps[at], ma[at]
    except IndexError:
        return None
    if p is None or m in (None, 0):
        return None
    return (p / m - 1.0) * 100.0


def prox_pct_week_ago(rec, ref_days=7):
    """% above the 200-DMA as of ~ref_days ago (last session on/before asof-ref_days).

    Uses each holding's OWN trading calendar so US, Xetra and Shenzhen lines are each
    compared against a genuine ~1-week-earlier point, not a shared bar offset."""
    from datetime import datetime, timedelta
    dts = rec.get("dates")
    if not dts:
        return None, None
    last = datetime.strptime(dts[-1], "%Y-%m-%d")
    target = last - timedelta(days=ref_days)
    idx = None
    for i, ds in enumerate(dts):
        if datetime.strptime(ds, "%Y-%m-%d") <= target:
            idx = i
    if idx is None:
        return None, None
    return prox_pct(rec, at=idx), dts[idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--local", help="path to a local breadth-thrust-etf checkout")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ro = load("risk_overlay.json", args.local)
    lt = load("live_track.json", args.local)
    hp = load("holdings_prices_1y.json", args.local)["prices"]
    meta = json.loads(REGISTRY.read_text(encoding="utf-8"))["etf_meta"]

    br = ro["current_breadth"]
    off = ro["gate_parameters"]["off_threshold"]
    on = ro["gate_parameters"]["on_threshold"]

    rows = []  # (ticker, weight, pct_above_200dma, sleeve)
    for tk, w in lt["effective_weights"].items():
        k = price_key(tk, hp, meta)
        vs = hp[k]["vs_ma200"] * 100.0 if (k and hp[k].get("vs_ma200") is not None) else None
        rows.append((tk, w, vs, meta.get(tk, {}).get("sleeve", "-")))

    fallback = ro["gate_parameters"].get("fallback_ticker", "SHY")  # cash leg — not a trend position
    held = [r for r in rows if r[2] is not None and r[1] > 0 and r[0] != fallback]
    # Coverage guard (2026-07-18 audit): a holding whose price series cannot be
    # resolved silently vanished from the proximity chart AND from the
    # all_above_200dma verdict — at one point 11 of 23 holdings (~25% of NAV).
    # Any such name is now reported loudly and carried in the JSON so the
    # digest can show the gap instead of implying full coverage.
    uncovered = [(r[0], round(r[1] * 100, 1)) for r in rows
                 if r[2] is None and r[1] > 0 and r[0] != fallback]
    if uncovered:
        print("WARN: proximity panel missing price series for "
              + ", ".join(f"{t} ({w}% NAV)" for t, w in uncovered)
              + " — chart and all_above_200dma cover the REMAINING book only")
    weakest = sorted(held, key=lambda r: r[2])[:3]
    soxx_vs = next((r[2] for r in rows if r[0] == "SOXX"), None)

    # As-of dates — dated SEPARATELY and honestly: prices refresh daily, but the
    # breadth panel regenerates only in the weekly run, so the gauge (breadth) and
    # the proximity chart (prices) can legitimately carry different dates.
    # Canonical prices date = the live model's latest session (live_track). Do NOT
    # use "first holding's last date" — individual price series in holdings_prices
    # can lag, which would mis-stamp the chart with a stale date.
    ld = lt.get("live_dates") or []
    prices_asof = ld[-1] if ld else max(
        (hp[price_key(tk, hp, meta)]["dates"][-1]
         for tk, w, v, s in rows
         if price_key(tk, hp, meta) and hp[price_key(tk, hp, meta)].get("dates")),
        default=None)
    breadth_asof = ro.get("panel_end_date")

    # Prior-week proximity per holding (for the "where it was last week" markers).
    week_ago = {}   # ticker -> (pct, date)
    for tk, w, v, s in rows:
        k = price_key(tk, hp, meta)
        week_ago[tk] = prox_pct_week_ago(hp[k]) if k else (None, None)

    triggers = {
        "as_of_prices": prices_asof,
        "breadth_as_of": breadth_asof,
        "breadth": round(br, 4),
        "off_threshold": off,
        "on_threshold": on,
        "state": ro["current_state"],
        "buffer_to_derisk_pp": round((br - off) * 100, 1),
        "eem_tilt_active": lt.get("eem_tilt_active"),
        "soxx_pct_above_200dma": round(soxx_vs, 1) if soxx_vs is not None else None,
        "soxx_pct_above_200dma_1w_ago": (round(week_ago["SOXX"][0], 1) if week_ago.get("SOXX", (None,))[0] is not None else None),
        "weakest_holdings": [{"ticker": t, "weight_pct": round(w * 100, 1), "pct_above_200dma": round(v, 1), "sleeve": s} for t, w, v, s in weakest],
        "all_above_200dma": all(r[2] >= 0 for r in held),
        "uncovered_holdings": [{"ticker": t, "weight_pct": w} for t, w in uncovered],
        "holdings": [{"ticker": t, "weight_pct": round(w * 100, 1), "pct_above_200dma": (round(v, 1) if v is not None else None),
                      "pct_above_200dma_1w_ago": (round(week_ago[t][0], 1) if week_ago.get(t, (None,))[0] is not None else None),
                      "sleeve": s} for t, w, v, s in rows],
    }
    (out / "risk_triggers.json").write_text(json.dumps(triggers, indent=2), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # breadth gauge
    fig, ax = plt.subplots(figsize=(6.6, 1.75))
    ax.axhspan(0, 1, xmin=0, xmax=off, color="#d64533", alpha=.16)
    ax.axhspan(0, 1, xmin=off, xmax=on, color="#e8b53a", alpha=.16)
    ax.axhspan(0, 1, xmin=on, xmax=1, color="#1a8754", alpha=.16)
    ax.axvline(br, color="#0f5132", lw=3.5)
    ax.text(br, 1.30, f"now {br:.3f} · {ro['current_state']}", ha="center", fontsize=10.5, fontweight="bold", color="#0f5132")
    for x, lab in [(off, f"de-risk < {off:.2f}"), (on, f"re-engage > {on:.2f}")]:
        ax.axvline(x, color="#555", lw=1, ls="--")
        ax.text(x, -0.42, lab, ha="center", va="top", fontsize=8.5, color="#555")
    ax.annotate("", xy=(off, 0.5), xytext=(br, 0.5), arrowprops=dict(arrowstyle="<->", color="#0f5132", lw=1))
    ax.text((br + off) / 2, 0.60, f"{(br - off) * 100:.0f}pp buffer", ha="center", fontsize=8, color="#0f5132")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_yticks([]); ax.set_xticks([0, .2, .5, .8, 1.0]); ax.tick_params(labelsize=8.5)
    ax.set_title("De-risk gate — S&P 500 breadth vs its thresholds", fontsize=10.5, fontweight="bold", loc="left")
    # Date stamp — the breadth panel trails the daily prices, so say so on the chart.
    # Placed BELOW the axis (right) to avoid colliding with the "now" label on top.
    stale = bool(breadth_asof and prices_asof and breadth_asof < prices_asof)
    date_lbl = f"breadth as of {breadth_asof or 'n/a'}" + (f"  ·  prices {prices_asof} (panel trails)" if stale else "")
    ax.text(1.0, -0.66, date_lbl, ha="right", va="top", fontsize=7.5, color="#b45309" if stale else "#999")
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    plt.savefig(out / "breadth_gauge.png", dpi=150, bbox_inches="tight"); plt.close()

    # proximity to 200-DMA
    p2 = sorted(held, key=lambda r: r[2], reverse=True)
    labels = [f"{t} ({w * 100:.0f}%)" for t, w, v, s in p2]
    vals = [v for t, w, v, s in p2]
    wk = [week_ago.get(t, (None, None))[0] for t, w, v, s in p2]
    # Representative "prior week" date for the legend: prefer SOXX (fresh, US calendar),
    # else any holding with a week-ago point.
    wk_ref = week_ago.get("SOXX", (None, None))[1] or next(
        (week_ago[t][1] for t, w, v, s in p2 if week_ago.get(t, (None, None))[1]), None)
    n = len(labels)
    # Compact, email-friendly canvas: narrower and ~0.24in per bar so the block
    # sits neatly in a mail client rather than dominating the message.
    fig, ax = plt.subplots(figsize=(6.5, max(3.0, 0.24 * n + 1.15)))
    ax.barh(range(n), vals, color="#1a8754", alpha=.85, height=.62, zorder=3)
    ax.axvline(0, color="#111", lw=1.5)
    # "Where it was a week ago": travel line + hollow diamond marker per holding.
    for i, (now_v, was_v) in enumerate(zip(vals, wk)):
        if was_v is None:
            continue
        ax.plot([was_v, now_v], [i, i], color="#9aa0a6", lw=0.9, zorder=4)
        ax.scatter(was_v, i, marker="D", s=15, facecolors="white", edgecolors="#444", linewidths=0.9, zorder=6)
    ax.set_yticks(range(n)); ax.set_yticklabels(labels, fontsize=7.5); ax.invert_yaxis()
    ax.set_xlabel("% above the 200-day moving average  (0 = trend-rule trigger)", fontsize=8.5)
    title = "Every holding is above its 200-DMA — the trend rule is nowhere near flipping" if triggers["all_above_200dma"] else "Holdings vs their 200-DMA — proximity to the trend trigger"
    ax.set_title(title, fontsize=10, fontweight="bold", loc="left", pad=16)
    for i, (v, was_v) in enumerate(zip(vals, wk)):
        # Place the % label BEYOND both the bar tip and the prior-week marker, so the
        # label's white box never paints over the diamond (which was hiding the marker
        # for small week-over-week moves, e.g. IUUS/SPY/EFA).
        if v >= 0:
            outer = max(v, was_v) if was_v is not None else v
            ax.text(outer + 0.9, i, f"{v:+.0f}%", va="center", ha="left", fontsize=7, color="#222", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.08", facecolor="white", edgecolor="none"))
        else:
            outer = min(v, was_v) if was_v is not None else v
            ax.text(outer - 0.9, i, f"{v:+.0f}%", va="center", ha="right", fontsize=7, color="#222", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.08", facecolor="white", edgecolor="none"))
    ax.margins(x=0.16)
    # Legend for the marker + as-of stamp (prices date; the week-ago reference date).
    from matplotlib.lines import Line2D
    if wk_ref:
        ax.legend([Line2D([0], [0], marker="D", markerfacecolor="white", markeredgecolor="#444",
                          color="#9aa0a6", lw=0.9, markersize=5)],
                  [f"prior week ({wk_ref})"], loc="lower right", fontsize=7, frameon=False)
    ax.text(1.0, 1.015, f"as of {prices_asof or 'n/a'}", transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color="#999")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    plt.tight_layout(); plt.savefig(out / "proximity_200dma.png", dpi=150, bbox_inches="tight"); plt.close()

    print(f"OK: wrote breadth_gauge.png, proximity_200dma.png, risk_triggers.json to {out}")
    # Guard the cosmetic summary line against None: when SOXX (or any weakest
    # holding) is absent from the price panel — exactly the stale-panel failure
    # this script must survive — soxx_vs / pct_above_200dma are None and the
    # old f-string format specs raised TypeError AFTER the PNGs/JSON were
    # already written. Format defensively so the run still exits cleanly.
    soxx_txt = f"+{soxx_vs:.0f}%" if soxx_vs is not None else "n/a"
    weak_txt = [
        f"{w['ticker']} " + (f"+{w['pct_above_200dma']}%" if w["pct_above_200dma"] is not None else "n/a")
        for w in triggers["weakest_holdings"]
    ]
    print(f"breadth {br:.4f} {ro['current_state']} buffer {triggers['buffer_to_derisk_pp']}pp | SOXX {soxx_txt} | weakest {weak_txt}")


if __name__ == "__main__":
    main()
