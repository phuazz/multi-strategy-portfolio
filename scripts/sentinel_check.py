"""Deployed-monitor sentinel: does the LIVE dashboard show what the
calendar says it should?

Outside-in counterpart to check_capture_integrity.py, ported from the
upstream breadth-thrust-etf ops stack (2026-07-03). It shares no state
with the build pipeline: it fetches the DEPLOYED dataset from GitHub
Pages and compares its live as-of against the true NYSE calendar. That
catches every failure the pipeline cannot see about itself — a green run
that published stale artefacts, a Pages deploy that never happened, a
cron that silently stopped firing.

Alert conditions (exit 1 -> the workflow's failure email):
  - deployed live as-of lags the last completed NYSE session, or
  - the deployed health level is 'stale' (the site is loudly stale —
    correct rendering, but the operator should not need to open the
    page to learn it).

A deployed health level of 'warn' prints but does not alert: warn states
are surfaced on the Data Health tab by design.

Python datetime months are 1-indexed (January = 1).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Allow importing sibling scripts/ modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ACTIVE_PORTFOLIO_IDS  # noqa: E402
from check_capture_integrity import evaluate_dataset  # noqa: E402
from nyse_sessions import last_completed_session  # noqa: E402

# The one Pages site this repo publishes. docs/ is served at the root.
PAGES_BASE = "https://phuazz.github.io/navigo-systematic-trend"

FETCH_ATTEMPTS = 3
FETCH_RETRY_SECONDS = 30
FETCH_TIMEOUT_SECONDS = 30


def fetch_deployed_dataset(pid: str) -> dict:
    """Fetch the deployed dataset with retries. The cache-buster query
    defeats any intermediate cache serving a pre-publish copy."""
    url = (f"{PAGES_BASE}/data/portfolio-{pid}.json"
           f"?sentinel={int(time.time())}")
    last_exc: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — any fetch error retries
            last_exc = exc
            print(f"  fetch attempt {attempt}/{FETCH_ATTEMPTS} failed: {exc}")
            if attempt < FETCH_ATTEMPTS:
                time.sleep(FETCH_RETRY_SECONDS)
    raise RuntimeError(f"could not fetch deployed dataset for {pid}: {last_exc}")


def main() -> int:
    expected = last_completed_session(datetime.now(timezone.utc))
    print(f"expected last completed NYSE session: {expected.isoformat()}")
    failures = []
    for pid in ACTIVE_PORTFOLIO_IDS:
        try:
            blob = fetch_deployed_dataset(pid)
        except Exception as exc:
            print(f"FAIL  {pid}: {exc}")
            failures.append(pid)
            continue
        verdict = evaluate_dataset(blob, expected)
        # Alert on corruption, any session lag, or a loudly-stale
        # deployment; tolerate health 'warn' (surfaced on-page by design).
        alert = (verdict["status"] == "fail"
                 or (verdict["lag"] or 0) >= 1
                 or verdict["health_level"] == "stale")
        tag = "FAIL" if alert else "ok  "
        print(f"{tag}  {pid}: {verdict['evidence']}")
        if alert:
            failures.append(pid)
    if failures:
        print(f"sentinel breach: {', '.join(failures)}")
        return 1
    print("sentinel ok: deployed dashboard matches the calendar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
