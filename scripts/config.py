"""Shared configuration for the Multi-Strategy Portfolio monitor.

Loads the active portfolio registry (portfolios/<id>.json) and exposes a small
set of paths and constants used across the pipeline. Keeping portfolio-specific
data in the registry JSON (not here) is what makes the monitor multi-portfolio:
a second strategy is added by dropping in another registry file, not by editing
code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Repository layout ---------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
PORTFOLIOS_DIR = ROOT / "portfolios"
DATA_DIR = ROOT / "data"            # local normalised-dataset cache (gitignored)
DOCS_DIR = ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"   # client fetches the dataset from here (committed)
TEMPLATE = ROOT / "template.html"
DOCS_INDEX = DOCS_DIR / "index.html"

# The single portfolio shipped in v1. The pipeline is written to loop over a
# list, so adding ids here (each with a portfolios/<id>.json) extends coverage.
ACTIVE_PORTFOLIO_IDS = ["multi-strategy-portfolio"]

# Trading-day convention: ~252 sessions a year. Stated once, reused everywhere.
TRADING_DAYS_PER_YEAR = 252

# Valuation layer (DESIGN.md Phase 1) — the monitor's own daily mark-to-market.
# DEFAULT OFF: the production path stays the thin renderer of the engine's
# live_track, byte-for-byte. When enabled, the pipeline additionally computes
# the monitor's independent mark and reconciles it against the engine's live_equity,
# attaching the result under a distinct dataset "valuation" key (it never
# overwrites the headline). Flip via the MSP_VALUATION_LAYER env var
# (1/true/yes/on) without editing code.
VALUATION_LAYER_ENABLED = (
    os.environ.get("MSP_VALUATION_LAYER", "false").strip().lower()
    in ("1", "true", "yes", "on")
)

# Benchmark tail wait (2026-09-09). yfinance posts the day's US daily bar at an
# unpredictable point after the close, and the 23:40 UTC cron lands 00:40-01:30
# UTC (20:40-21:30 ET) — inside that window. On 2026-09-08 the bar arrived
# between 01:30 and 02:03 UTC: the build baked a 2026-09-08 NAV against a
# 2026-09-04 benchmark, warned by email, and every S&P-relative figure on the
# page mixed dates until the operator re-ran the workflow by hand. The build now
# re-fetches while the benchmark trails the NAV rather than publishing the mixed
# basis and correcting it afterwards. Four retries at six minutes is a 24-minute
# ceiling, which covers the observed gap with room; the workflow timeout is set
# above it. Fail-open by construction: attempts exhausted, the build publishes
# with the warn exactly as it did before.
BENCH_TAIL_WAIT_ATTEMPTS = int(os.environ.get("MSP_BENCH_TAIL_ATTEMPTS", "4"))
BENCH_TAIL_WAIT_SECONDS = int(os.environ.get("MSP_BENCH_TAIL_SLEEP_S", "360"))


def load_registry(portfolio_id: str) -> dict:
    """Return the parsed portfolio registry for the given id."""
    path = PORTFOLIOS_DIR / f"{portfolio_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Portfolio registry not found: {path}. "
            f"Known: {[p.stem for p in PORTFOLIOS_DIR.glob('*.json')]}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_path(portfolio_id: str, *, docs: bool = True) -> Path:
    """Path to the baked dataset for a portfolio."""
    base = DOCS_DATA_DIR if docs else DATA_DIR
    return base / f"portfolio-{portfolio_id}.json"
