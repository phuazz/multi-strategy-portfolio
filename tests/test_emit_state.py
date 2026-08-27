"""Tests for scripts/emit_state.py — the STATE_CONTRACT emission.

IMPORTANT: this repo runs `pytest tests/ -q` BEFORE its commit step, so a
failure here blocks the daily monitor publish. Everything below is therefore
pure and synthetic: no filesystem reads of real data, no network, no dependence
on the date the suite happens to run. `load_portfolio` is monkeypatched in every
test that reaches it.

What is actually being guarded, given the emission is a copy:

  1. It must not emit a guess. A renamed or null key stops the emission rather
     than producing a null that reads downstream as a state.
  2. It must not emit the REGIME. This monitor sits one fetch behind the engine
     by design, so during an engine-side revision the two legitimately disagree
     and the engine is primary. A regime state emitted from here would put a
     second, staler answer into circulation with equal authority.
  3. It must pick the worst feed the same way the consumer does — largest RAW
     bday_lag. Not because that definition is the best one available (it ranks
     3-of-12 above 2-of-2), but because both sides must agree; a unilateral
     improvement here would put them permanently at odds.
  4. It must not churn the repo with no-op commits, or leave a half-written
     file after a failure.

Python datetime months are 1-indexed (January = 1).
"""

from __future__ import annotations

import json

import pytest

import emit_state  # scripts/ is on the path via tests/conftest.py

REQUIRED = {"as_of", "state", "value", "zone", "role", "horizon",
            "evidence_grade", "licence", "action_hint", "source_file"}
OPTIONAL = {"computed_at", "cadence"}
SIGNAL = "monitor_health"


def _feed(name="Price / NAV (live_track)", lag=0, budget=0, level="ok"):
    return {"feed": name, "bday_lag": lag, "budget_bdays": budget, "level": level}


def _portfolio(level="ok", feeds=None, **meta_over):
    meta = {"asOf": "2026-08-25", "live_asOf": "2026-08-25",
            "built_at_utc": "2026-08-26T13:45:20Z", "source_commit": "abc1234"}
    meta.update(meta_over)
    return {
        "meta": meta,
        "health": {"level": level, "ok": level == "ok",
                   "feeds": feeds if feeds is not None else [
                       _feed("Price / NAV (live_track)", 0, 0),
                       _feed("Breadth / regime panel (risk_overlay)", 1, 8),
                       _feed("Strategy equity (multi_strategy)", 2, 12)]},
        # Present in the real file and deliberately NOT emitted.
        "regime": {"state": "RISK_ON", "since": "2026-04-14", "breadth": 0.6068,
                   "panel_end_date": "2026-08-25"},
    }


@pytest.fixture
def store(monkeypatch):
    box = {"d": _portfolio()}
    monkeypatch.setattr(emit_state, "load_portfolio", lambda: box["d"])
    return box


# --- the regime must never be emitted ---------------------------------------

def test_only_monitor_health_is_emitted(store):
    assert set(emit_state.build()["signals"]) == {SIGNAL}


def test_the_regime_block_is_present_in_the_source_but_not_emitted(store):
    """Guards the precedence rule: the engine is primary for regime, and this
    monitor is one fetch behind it by design."""
    assert "regime" in store["d"], "fixture no longer exercises the case"
    payload = emit_state.build()
    # Asserting the substring "regime" is absent would be wrong as well as
    # fragile: a feed is legitimately NAMED "Breadth / regime panel". What must
    # not appear is the regime's own state or its since-date.
    for block in payload["signals"].values():
        rendered = json.dumps(block)
        assert "RISK_ON" not in rendered
        assert "2026-04-14" not in rendered
        assert "panel_end_date" not in rendered


def test_a_changed_regime_does_not_change_the_emission(store):
    before = emit_state.build()["signals"][SIGNAL]
    store["d"]["regime"] = {"state": "RISK_OFF", "since": "1999-01-01",
                            "breadth": 0.01, "panel_end_date": "1999-01-01"}
    after = emit_state.build()["signals"][SIGNAL]
    assert before == after


# --- the worst-feed definition ----------------------------------------------

def test_worst_feed_is_the_largest_raw_lag(store):
    assert emit_state.build()["signals"][SIGNAL]["zone"] == "worst feed lag 2 of 12 bdays"


def test_worst_feed_ranks_by_raw_lag_not_by_headroom(store):
    """3 of 12 is chosen over 2 of 2, although the second is at its limit. This
    pins the CONSUMER'S definition deliberately: both sides must agree, and a
    unilateral improvement here would put them permanently at odds. If the
    definition is ever changed, change it on both sides in the same session."""
    store["d"] = _portfolio(feeds=[_feed("roomy", 3, 12), _feed("at its limit", 2, 2)])
    assert emit_state.build()["signals"][SIGNAL]["zone"] == "worst feed lag 3 of 12 bdays"


def test_a_single_feed_is_its_own_worst(store):
    store["d"] = _portfolio(feeds=[_feed("only", 4, 9)])
    s = emit_state.build()["signals"][SIGNAL]
    assert s["zone"] == "worst feed lag 4 of 9 bdays"
    assert s["value"] == 1


def test_a_non_integer_lag_is_refused_rather_than_sorted_around(store):
    """max() comparing None with an int raises deep inside the sort; a lag that
    is not a number means the health block is not what this expects."""
    store["d"] = _portfolio(feeds=[_feed("a", 1, 8), {"feed": "b", "bday_lag": None,
                                                      "budget_bdays": 8}])
    with pytest.raises(emit_state.EmitError, match="bday_lag"):
        emit_state.build()


def test_a_boolean_lag_is_refused(store):
    """bool is a subclass of int in Python, so a naive isinstance check would
    let True through and sort it as 1."""
    store["d"] = _portfolio(feeds=[_feed("a", 1, 8), {"feed": "b", "bday_lag": True,
                                                      "budget_bdays": 8}])
    with pytest.raises(emit_state.EmitError, match="bday_lag"):
        emit_state.build()


def test_an_empty_feed_list_is_refused(store):
    store["d"] = _portfolio(feeds=[])
    with pytest.raises(emit_state.EmitError, match="empty"):
        emit_state.build()


# --- the state --------------------------------------------------------------

@pytest.mark.parametrize("level,hint", [("ok", "none"), ("warn", "watch"), ("stale", "watch")])
def test_the_level_is_copied_and_drives_the_hint(store, level, hint):
    store["d"] = _portfolio(level=level)
    s = emit_state.build()["signals"][SIGNAL]
    assert s["state"] == level
    assert s["action_hint"] == hint


def test_the_vocabulary_matches_the_ladder_validate_py_declares(store):
    """scripts/validate.py declares 'ok' < 'warn' < 'stale'. The consumer held a
    different list until 2026-08-27 — it included an `error` level this monitor
    cannot emit and omitted `stale`, which it can. The day the monitor first
    went stale, that turned the row into a loud ERROR downstream. Pin the
    vocabulary to the repo that produces it."""
    assert emit_state.LEVELS == ("ok", "warn", "stale")


def test_stale_is_accepted_rather_than_refused(store):
    """The regression test for 2026-08-27: this exact value broke the consumer."""
    store["d"] = _portfolio(level="stale")
    assert emit_state.build()["signals"][SIGNAL]["state"] == "stale"


def test_a_level_outside_the_declared_ladder_is_refused(store):
    store["d"] = _portfolio(level="degraded")
    with pytest.raises(emit_state.EmitError, match="degraded"):
        emit_state.build()


def test_error_is_not_a_level_this_monitor_emits(store):
    """Kept explicit so nobody re-adds it from the consumer's old list."""
    store["d"] = _portfolio(level="error")
    with pytest.raises(emit_state.EmitError, match="error"):
        emit_state.build()


def test_the_feed_count_is_the_headline_value(store):
    assert emit_state.build()["signals"][SIGNAL]["value"] == 3


def test_as_of_is_the_monitors_own_date(store):
    """§2.4: the monitor records its OWN as-of, not the engine's."""
    assert emit_state.build()["signals"][SIGNAL]["as_of"] == "2026-08-25"


def test_computed_at_is_the_build_time(store):
    assert emit_state.build()["signals"][SIGNAL]["computed_at"] == "2026-08-26T13:45:20Z"


# --- shape ------------------------------------------------------------------

def test_the_block_carries_the_required_fields_and_nothing_unknown(store):
    block = emit_state.build()["signals"][SIGNAL]
    assert REQUIRED <= set(block), f"missing {REQUIRED - set(block)}"
    assert set(block) <= REQUIRED | OPTIONAL, f"unknown {set(block) - REQUIRED - OPTIONAL}"


def test_no_score_or_weight_field_is_emitted(store):
    banned = {"score", "weight", "weights", "composite", "rank"}
    assert not (banned & set(emit_state.build()["signals"][SIGNAL]))


def test_the_envelope_names_its_version_and_source(store):
    p = emit_state.build()
    assert p["contract_version"] == "1"
    assert p["emitted_by"] == "multi-strategy-portfolio"


# --- never emit a guess ------------------------------------------------------

@pytest.mark.parametrize("key", ["asOf", "built_at_utc"])
def test_a_missing_meta_key_stops_the_emission(store, key):
    del store["d"]["meta"][key]
    with pytest.raises(emit_state.EmitError, match=key):
        emit_state.build()


@pytest.mark.parametrize("key", ["level", "feeds"])
def test_a_missing_health_key_stops_the_emission(store, key):
    del store["d"]["health"][key]
    with pytest.raises(emit_state.EmitError, match=key):
        emit_state.build()


def test_a_null_as_of_is_refused(store):
    store["d"]["meta"]["asOf"] = None
    with pytest.raises(emit_state.EmitError, match="null"):
        emit_state.build()


def test_a_missing_health_block_entirely_is_refused(store):
    del store["d"]["health"]
    with pytest.raises(emit_state.EmitError, match="health"):
        emit_state.build()


# --- a failed run must not leave a half-written file -------------------------

def test_a_failed_run_writes_nothing_and_exits_non_zero(store, monkeypatch, tmp_path, capsys):
    out = tmp_path / "state.json"
    out.write_text('{"previous": "emission"}', encoding="utf-8")
    monkeypatch.setattr(emit_state, "OUT", out)
    store["d"] = _portfolio(level="nonsense")

    assert emit_state.main([]) == 1
    assert json.loads(out.read_text(encoding="utf-8")) == {"previous": "emission"}
    assert "FAILED" in capsys.readouterr().err


def test_an_unchanged_state_is_not_rewritten(store, monkeypatch, tmp_path):
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main([]) == 0
    first = out.read_text(encoding="utf-8")
    assert emit_state.main([]) == 0
    assert out.read_text(encoding="utf-8") == first, "unchanged state was rewritten"


def test_a_changed_state_IS_rewritten(store, monkeypatch, tmp_path):
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main([]) == 0
    store["d"] = _portfolio(level="warn")
    assert emit_state.main([]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["signals"][SIGNAL]["state"] == "warn"


def test_check_mode_writes_nothing(store, monkeypatch, tmp_path):
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main(["--check"]) == 0
    assert not out.exists()
