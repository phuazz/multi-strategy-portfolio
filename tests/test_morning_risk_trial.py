"""Trial checkpoints count accepted weekly reviews and compare immutable paper books."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deliver_morning import GitHubLedger, deliver_once
from morning_risk_trial import BASE_BLOB, INITIAL, OPENING_FLAGS, changes, plan


def risk(anchor="2026-11-24"):
    gaps = [dict(ticker=t, weight=.1, review=True, loss=.01) for t in sorted(OPENING_FLAGS)]
    case = dict(name="Down", total=-.05, missing=[], coverage={"shocked": .1},
                positions=[dict(ticker="SHY", pnl=-.05, factor="rates")])
    return dict(status="shadow", anchor=anchor, gateState="RISK_ON", version=2, gaps=gaps,
                scenarios=[case], complete=1, worst=dict(name="Down", total=-.05))


def step(book, state, snapshots, day, blob="next", nav=None):
    meta = dict(live_asOf=nav or day, portfolio_anchor=book["anchor"])
    # Python datetime months are 1-indexed. Test clocks are after NYSE close.
    now = datetime.fromisoformat(day + "T23:00:00+00:00")
    return plan(dict(meta=meta, construction_risk=book), blob, state, snapshots.get, now)


def test_baseline_holds_and_only_counts_four_distinct_weekly_reviews():
    archive = {BASE_BLOB: risk()}
    state = INITIAL
    assert step(risk(), state, archive, "2026-11-25")[0] is None
    for i, day in enumerate(["2026-11-30", "2026-12-07", "2026-12-14", "2026-12-21"], 1):
        book = risk(day)
        section, state = step(book, state, archive, day, day)
        assert f"review {i} of 4" in section["heading"]
        assert state["reviews"] == i
        archive[day] = book
        assert step(book, state, archive, day) == (None, state)
    assert "trial complete" in section["lines"][-1]
    assert step(risk("2027-01-04"), state, archive, "2027-01-04") == (None, state)


@pytest.mark.parametrize("day,anchor,cycle", [
    ("2026-12-01", "2026-12-01", "2026-11-30"),
    ("2027-01-04", "2027-01-04", "2027-01-04"),
    ("2027-01-19", "2027-01-19", "2027-01-19"),  # Monday NYSE holiday
])
def test_late_publication_and_real_calendar_boundaries(day, anchor, cycle):
    _, state = step(risk(anchor), INITIAL, {BASE_BLOB: risk()}, day)
    assert state["cycle"] == cycle and state["reviews"] == 1


def test_intraday_republication_cumulative_threshold_and_daily_deduplication():
    archive = {BASE_BLOB: risk()}
    book = risk("2026-11-25")
    book["scenarios"][0]["total"] -= .0049
    assert step(book, INITIAL, archive, "2026-11-25") == (None, INITIAL)
    book["scenarios"][0]["total"] -= .0001
    section, state = step(book, INITIAL, archive, "2026-11-25")
    assert section["heading"] == "Material portfolio risk change"
    assert "-0.50 pp" in " ".join(section["lines"])
    assert state["reviews"] == 0 and state["weekly"] == BASE_BLOB
    archive["next"] = book
    assert step(book, state, archive, "2026-11-25")[0] is None


def test_unavailable_is_single_notice_and_recovery_can_use_same_cycle():
    archive = {BASE_BLOB: risk()}
    bad = dict(anchor="2026-11-30", status="unavailable")
    notice, state = step(bad, INITIAL, archive, "2026-11-30")
    assert "unavailable" in notice["heading"] and state["reviews"] == 0
    assert step(bad, state, archive, "2026-11-30") == (None, state)
    weekly, state = step(risk("2026-11-30"), state, archive, "2026-12-01")
    assert state["reviews"] == 1 and "available again" in " ".join(weekly["lines"])


def test_weekly_comparison_uses_previous_week_even_after_material_notice():
    archive = {BASE_BLOB: risk()}
    material = risk()
    material["gaps"][0]["review"] = False
    _, state = step(material, INITIAL, archive, "2026-11-25", "daily")
    archive["daily"] = material
    next_book = deepcopy(material)
    next_book["anchor"] = "2026-11-30"
    weekly, state = step(next_book, state, archive, "2026-11-30")
    assert "cleared gap review" in " ".join(weekly["lines"])
    assert state["reviews"] == 1


def test_flag_identity_partial_coverage_and_policy_comparability():
    old = risk()
    new = deepcopy(old)
    new["gaps"][0]["review"] = None
    new["gaps"][1]["review"] = False
    new["gaps"].pop()
    new["gaps"].append(dict(ticker="NEW", weight=.2, review=True))
    new["scenarios"][0].update(total=None, missing=["NEW"])
    new["gateState"] = "RISK_OFF"
    result = " ".join(changes(old, new))
    for phrase in ["assessment became unavailable", "cleared", "left the book", "entered", "Lost pricing coverage", "RISK_OFF"]:
        assert phrase in result
    new = deepcopy(old)
    new["scenarios"][0].update(total=-.5, prices={"rates": -.5})
    result = " ".join(changes(old, new))
    assert "assumptions" in result and "pp of NAV" not in result
    new["version"] += 1
    assert "Comparisons restart" in " ".join(changes(old, new))


def test_pending_claim_carries_checkpoint_but_cannot_be_used():
    responses = iter([{"tree": [{"path": "mail-ledger", "sha": "dir"}]},
                      {"tree": [{"path": "2026-11-30-report.json"}], "truncated": False}])

    class Response:
        def raise_for_status(self): pass
        def json(self): return next(responses)

    class Ledger(GitHubLedger):
        def __init__(self): self.record = None
        def request(self, *args): return Response()
        def read(self, key): return self.record, None
        def write(self, key, value, sha=None): self.record = deepcopy(value); return "sha"

    ledger = Ledger()
    def interrupted(*args): raise TimeoutError()
    with pytest.raises(TimeoutError):
        deliver_once(ledger, "2026-11-30-report", "s", "t", "h", None, interrupted,
                     datetime.fromisoformat("2026-12-01T01:00:00+00:00"), trial=INITIAL)
    assert ledger.record["risk_trial"] == INITIAL and ledger.record["status"] == "sending"
    with pytest.raises(ValueError, match="reconciliation"):
        ledger.trial_state("2026-12-01")
