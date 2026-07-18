"""D5 — blend-weights contract on the consumer side (2026-07-04 audit).

The registry restates the engine's 35/35/10/20 blend and 10% tilt as
``sleeves[*].alloc`` / ``alloc_tilt``, and ``build_weight_history``
restates them once more as literals. This pins every restatement to ONE
parse of the registry's own ``source.deployed_key`` string, so a future
engine reweight that misses this repo fails loudly here instead of
publishing silently wrong attributions.
"""

from __future__ import annotations

import re

import pytest

from config import load_registry

REG = load_registry("multi-strategy-portfolio")


def _parse_blend_key(key: str) -> dict[str, float]:
    m = re.match(r"blend_(\d+)_(\d+)_(\d+)_(\d+)", key)
    assert m, f"deployed key {key!r} does not carry a 4-way weight signature"
    vals = [int(g) / 100.0 for g in m.groups()]
    assert abs(sum(vals) - 1.0) < 1e-9
    return dict(zip("ABCD", vals))


def test_registry_allocs_match_the_deployed_key_string():
    want = _parse_blend_key(REG["source"]["deployed_key"])
    sleeves = REG["sleeves"]
    for code, alloc in want.items():
        assert sleeves[code]["alloc"] == pytest.approx(alloc), code
    # Tilt-state allocations: B funds the tilt, everyone else unchanged.
    tilt = sleeves["TILT"]["alloc_tilt"]
    assert tilt > 0
    assert sleeves["B"]["alloc_tilt"] == pytest.approx(want["B"] - tilt)
    for code in ("A", "C", "D"):
        assert sleeves[code]["alloc_tilt"] == pytest.approx(want[code]), code
    assert sleeves["TILT"]["alloc"] == pytest.approx(0.0)


def test_weight_history_literals_match_the_registry():
    """build_weight_history hard-codes the per-week allocation map; parse
    the literals from its source so they cannot drift from the registry."""
    import inspect

    import adapter

    src = inspect.getsource(adapter.build_weight_history)
    m = re.search(
        r'alloc\s*=\s*\{"A":\s*([0-9.]+),\s*"B":\s*([0-9.]+)\s+if\s+ton\s+'
        r'else\s+([0-9.]+),\s*"C":\s*([0-9.]+),\s*"D":\s*([0-9.]+)\}', src)
    assert m, "allocation literal map not found in build_weight_history"
    a, b_tilt, b_base, c, d = (float(g) for g in m.groups())
    sleeves = REG["sleeves"]
    assert a == pytest.approx(sleeves["A"]["alloc"])
    assert b_base == pytest.approx(sleeves["B"]["alloc"])
    assert b_tilt == pytest.approx(sleeves["B"]["alloc_tilt"])
    assert c == pytest.approx(sleeves["C"]["alloc"])
    assert d == pytest.approx(sleeves["D"]["alloc"])
    tilt_lit = re.search(r'w\["EEM"\]\s*=\s*w\.get\("EEM",\s*0\.0\)\s*\+\s*([0-9.]+)',
                         src)
    assert tilt_lit, "tilt-weight literal not found in build_weight_history"
    assert float(tilt_lit.group(1)) == pytest.approx(
        sleeves["TILT"]["alloc_tilt"])


def test_etf_meta_covers_every_sleeve_code_it_references():
    """Every etf_meta sleeve code must exist in the sleeves table (plus the
    CASH pseudo-sleeve), so grouping can never route a holding nowhere."""
    codes = {m["sleeve"] for m in REG["etf_meta"].values()}
    known = set(REG["sleeves"]) | {"CASH"}
    assert codes <= known, f"unknown sleeve codes in etf_meta: {codes - known}"
