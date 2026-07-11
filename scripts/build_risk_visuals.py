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
    weakest = sorted(held, key=lambda r: r[2])[:3]
    soxx_vs = next((r[2] for r in rows if r[0] == "SOXX"), None)

    triggers = {
        "as_of_prices": json.loads(REGISTRY.read_text(encoding="utf-8")).get("id") and hp.get("SOXX", {}).get("dates", [None])[-1],
        "breadth": round(br, 4),
        "off_threshold": off,
        "on_threshold": on,
        "state": ro["current_state"],
        "buffer_to_derisk_pp": round((br - off) * 100, 1),
        "eem_tilt_active": lt.get("eem_tilt_active"),
        "soxx_pct_above_200dma": round(soxx_vs, 1) if soxx_vs is not None else None,
        "weakest_holdings": [{"ticker": t, "weight_pct": round(w * 100, 1), "pct_above_200dma": round(v, 1), "sleeve": s} for t, w, v, s in weakest],
        "all_above_200dma": all(r[2] >= 0 for r in held),
        "holdings": [{"ticker": t, "weight_pct": round(w * 100, 1), "pct_above_200dma": (round(v, 1) if v is not None else None), "sleeve": s} for t, w, v, s in rows],
    }
    (out / "risk_triggers.json").write_text(json.dumps(triggers, indent=2), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # breadth gauge
    fig, ax = plt.subplots(figsize=(7.4, 1.7))
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
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    plt.savefig(out / "breadth_gauge.png", dpi=150, bbox_inches="tight"); plt.close()

    # proximity to 200-DMA
    p2 = sorted(held, key=lambda r: r[2], reverse=True)
    labels = [f"{t} ({w * 100:.0f}%)" for t, w, v, s in p2]
    vals = [v for t, w, v, s in p2]
    fig, ax = plt.subplots(figsize=(7.4, 5.6))
    ax.barh(range(len(labels)), vals, color="#1a8754", alpha=.85)
    ax.axvline(0, color="#111", lw=1.5)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8); ax.invert_yaxis()
    ax.set_xlabel("% above the 200-day moving average  (0 = trend-rule trigger)", fontsize=9)
    title = "Every holding is above its 200-DMA — the trend rule is nowhere near flipping" if triggers["all_above_200dma"] else "Holdings vs their 200-DMA — proximity to the trend trigger"
    ax.set_title(title, fontsize=10.5, fontweight="bold", loc="left")
    for i, v in enumerate(vals):
        ax.text(v + (0.8 if v >= 0 else -0.8), i, f"{v:+.0f}%", va="center", ha="left" if v >= 0 else "right", fontsize=7.2, color="#222")
    ax.margins(x=0.14)
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
