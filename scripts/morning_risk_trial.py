"""Four weekly paper-book reviews. Comparisons use immutable published datasets."""
from datetime import date
from hashlib import sha1

from portfolio_freshness import expected_book_session

# Git blob of the public portfolio JSON verified at the 25 November close.
BASE_BLOB = "a38452000b53eabed160e49387f00126a2139592"
BASE_DATE = "2026-11-25"
OPENING_FLAGS = {"SHY", "IUHC", "IUCS", "EXV1", "EXH9", "EXH1"}
INITIAL = dict(reviews=0, cycle="2026-11-23", weekly=BASE_BLOB, last=BASE_BLOB, unavailable=False)
MATERIAL = 0.005  # Fraction of NAV, or 0.50 percentage points.
LIMIT = 4


def git_blob(raw):
    return sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def panel(dataset):
    risk = dataset.get("construction_risk") or {}
    meta = dataset["meta"]
    if (risk.get("status") != "shadow" or risk.get("anchor") != meta["portfolio_anchor"]
            or not risk.get("scenarios") or not risk.get("gaps")):
        return None
    return risk


def scenarios(risk):
    return {row["name"]: row for row in risk["scenarios"]}


def comparable(old, new):
    fields = ("prices", "flat", "unpriced", "compareDefensiveGate")
    if any(old.get(key) != new.get(key) for key in fields):
        return False
    before = {row["ticker"]: row["factor"] for row in old["positions"]}
    return all(before.get(row["ticker"], row["factor"]) == row["factor"] for row in new["positions"])


def changes(prior, current):
    lines = []
    if current["gateState"] != prior["gateState"]:
        lines.append(f'Regime {prior["gateState"]} → {current["gateState"]}.')
    if current["version"] != prior["version"]:
        lines.append(f'Shadow policy changed from v{prior["version"]} to v{current["version"]}. '
                     'Comparisons restart on the new assumptions.')
        return lines
    before = {r["ticker"]: r for r in prior["gaps"]}
    after = {r["ticker"]: r for r in current["gaps"]}
    for ticker in sorted(before.keys() | after.keys()):
        old, new = before.get(ticker), after.get(ticker)
        if old and new and old.get("shock") != new.get("shock"):
            lines.append(f'{ticker} adverse gap assumption changed.')
        if old and old["review"] is True and new is None:
            lines.append(f'{ticker} left the book and its gap flag closed.')
        elif new and new["review"] is None and (not old or old["review"] is not None):
            lines.append(f'{ticker} gap assessment became unavailable.')
        elif new and new["review"] is True and (not old or old["review"] is not True):
            lines.append(f'{ticker} entered gap review at {new["weight"]:.2%} weight.')
        elif new and new["review"] is False and old and old["review"] is True:
            lines.append(f'{ticker} cleared gap review at {new["weight"]:.2%} weight.')
        elif new and new["review"] is False and old and old["review"] is None:
            lines.append(f'{ticker} gap assessment resumed below its shadow ceiling.')
    old_cases, new_cases = scenarios(prior), scenarios(current)
    lost, moves = [], []
    for name, old in old_cases.items():
        new = new_cases.get(name)
        if old["total"] is not None and (not new or new["total"] is None):
            lost.append(name)
        elif new and not comparable(old, new):
            lines.append(f'{name}: scenario assumptions or factor mapping changed. Comparison restarts.')
        elif new and new["total"] is not None and old["total"] is not None:
            delta = new["total"] - old["total"]
            if abs(delta) >= MATERIAL - 1e-12:
                moves.append((abs(delta), name, delta))
            old_gate, new_gate = old.get("gateComparison"), new.get("gateComparison")
            if old_gate and new_gate:
                gate_move = new_gate["total"] - old_gate["total"]
                if abs(gate_move) >= MATERIAL - 1e-12:
                    lines.append(f'Hypothetical defensive gate under {name}: '
                                 f'{gate_move * 100:+.2f} pp to {new_gate["total"]:+.2%}.')
            elif old_gate and not new_gate:
                lines.append(f'Hypothetical defensive comparison unavailable under {name}.')
        elif new and set(new["missing"]) - set(old["missing"]):
            lost.append(name)
    if lost:
        names = ", ".join(sorted(lost)[:3])
        lines.append(f'Lost pricing coverage in {len(lost)} scenario(s), including {names}.')
    if moves:
        _, name, delta = max(moves)
        lines.append(f'Comparable scenarios moving at least 0.50 pp of NAV: {len(moves)}. '
                     f'Largest: {name}, {delta * 100:+.2f} pp to {new_cases[name]["total"]:+.2%}.')
    return lines


def weekly_lines(old, new):
    rows = new["scenarios"]
    flat = sum(r["total"] is not None and r["coverage"]["shocked"] == 0 for r in rows)
    lines = [f'{new["gateState"]}. {new["complete"]}/{len(rows)} scenarios fully priced. '
             f'{flat} fully priced shocks touch no held exposure. '
             f'{sum(r["review"] is True for r in new["gaps"])} shadow gap flags across '
             f'{len(new["gaps"])} holdings, {sum(r["review"] is None for r in new["gaps"])} indeterminate.']
    worst = new["worst"]
    if worst:
        name, loss = worst["name"], worst["total"]
        case = scenarios(new)[name]
        line = f'Worst fully priced scenario: {name}, {loss:+.2%} of NAV.'
        prior = scenarios(old).get(name)
        if prior and prior["total"] is not None and old["version"] == new["version"] and comparable(prior, case):
            line += f' Change on the same shock {(loss - prior["total"]) * 100:+.2f} pp.'
            previous = {r["ticker"]: r["pnl"] for r in prior["positions"]}
            current = {r["ticker"]: r["pnl"] for r in case["positions"]}
            drivers = [(current.get(t, 0) - previous.get(t, 0), t) for t in sorted(current.keys() | previous.keys())]
            if drivers:
                delta, ticker = max(drivers, key=lambda pair: abs(pair[0]))
                if abs(delta) >= 0.00005:
                    line += f' Largest change in contribution: {ticker}, {delta * 100:+.2f} pp.'
        lines.append(line)
    flags = [r for r in new["gaps"] if r["review"] is True]
    if flags:
        lines.append("Flags for review: " + ", ".join(sorted(r["ticker"] for r in flags)) + ".")
    priced_flags = [r for r in flags if r["loss"] is not None]
    if priced_flags:
        largest = max(priced_flags, key=lambda r: r["loss"])
        lines.append(f'Largest modelled gap loss among flagged holdings: {largest["ticker"]}, '
                     f'{largest["loss"]:.2%} of NAV on {largest["weight"]:.2%} weight.')
    recovery = next((r for r in rows if r.get("compareDefensiveGate")), None)
    if recovery and recovery["total"] is not None:
        line = f'Recovery on model weights {recovery["total"]:+.2%} of NAV.'
        gate = recovery.get("gateComparison")
        if gate:
            line += f' Hypothetical defensive gate {gate["total"]:+.2%}.'
        lines.append(line)
    else:
        lines.append('Recovery on model weights is unavailable.')
    return lines


def plan(dataset, blob, state, read_panel, now):
    """Return the email section and candidate state; only SMTP acceptance advances it."""
    if state["reviews"] == LIMIT:
        return None, state
    meta = dataset["meta"]
    # Python datetime months are 1-indexed. The existing NYSE calendar rolls holiday fills.
    anchor = date.fromisoformat(meta["portfolio_anchor"])
    nav = date.fromisoformat(meta["live_asOf"])
    cycle = expected_book_session(now)
    if nav < date.fromisoformat(BASE_DATE) or not cycle <= anchor <= nav or cycle.isoformat() < state["cycle"]:
        raise ValueError("Trial book dates disagree with verified delivery")
    risk = panel(dataset)
    if not risk:
        if state["unavailable"]:
            return None, state
        return {"heading": "Shadow risk data unavailable", "lines": [
            f'Paper book {anchor.isoformat()} · NAV {nav.isoformat()}. Weekly review awaits verified risk data.'
        ]}, {**state, "unavailable": True}
    weekly = cycle.isoformat() > state["cycle"]
    prior = read_panel(state["weekly" if weekly else "last"])
    if not prior:
        raise ValueError("The previous verified risk comparison is missing")
    if state["weekly" if weekly else "last"] == BASE_BLOB:
        flags = {r["ticker"] for r in prior["gaps"] if r["review"] is True}
        if flags != OPENING_FLAGS or prior["anchor"] != "2026-11-24":
            raise ValueError("Six-flag baseline does not reconcile")
    lines = changes(prior, risk)
    if state["unavailable"]:
        lines.insert(0, "Shadow risk data are available again.")
    if not weekly and not lines:
        return None, state
    next_state = {**state, "last": blob, "unavailable": False}
    if weekly:
        number = state["reviews"] + 1
        heading = f'Weekly portfolio risk · review {number} of {LIMIT}'
        summary = weekly_lines(prior, risk)
        if not lines:
            lines = ["No material change from the previous weekly book."]
        next_state.update(reviews=number, cycle=cycle.isoformat(), weekly=blob)
    else:
        heading = "Material portfolio risk change"
        summary = []
    basis = f'Paper book {anchor.isoformat()} · NAV {nav.isoformat()} · shadow policy v{risk["version"]}.'
    visible = [basis, *summary]
    words = len((" ".join([heading, *visible])).split())
    for index, line in enumerate(lines):
        words += len(line.split())
        if words > 165:
            visible.append(f'{len(lines) - index} further observations. See Risk & Regime for the current book.')
            break
        visible.append(line)
    if weekly and number == LIMIT:
        visible.append("Four-rebalance shadow trial complete.")
    return {"heading": heading, "lines": visible}, next_state
