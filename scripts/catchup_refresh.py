"""Bounded recovery when the engine publishes after a monitor refresh.

Only stale Price/NAV or executed-book coverage can request another refresh.
Follow-ups use workflow_dispatch, rather than waiting for another cron delivery.
No strategy, target allocation or stale-health threshold is changed here.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

from config import ACTIVE_PORTFOLIO_IDS, dataset_path, load_registry
from source_revision import changed_files, resolve_snapshot

MAX_ATTEMPTS = 8
WAIT_SECONDS = 20 * 60
POLL_SECONDS = 60
RECOVERABLE_FEEDS = {"Price / NAV (live_track)", "Executed portfolio (engine anchor)"}


def needs_catchup(dataset: dict) -> bool:
    return any(f.get("feed") in RECOVERABLE_FEEDS and f.get("level") == "stale"
               for f in dataset.get("health", {}).get("feeds", []))


def load_dataset(pid: str) -> dict:
    return json.loads(dataset_path(pid).read_text(encoding="utf-8"))


def wait_for_publication(pid: str, timeout: int = WAIT_SECONDS,
                         *, clock=None, sleep=None) -> str:
    """Wait only while a stale book/valuation has no newer consumed source blobs."""
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    dataset = load_dataset(pid)
    if not needs_catchup(dataset):
        return "already-fresh"
    source = load_registry(pid)["source"]
    while True:
        snapshot = resolve_snapshot(source)
        if changed_files(dataset["meta"], snapshot, source):
            return "source-changed"
        remaining = deadline - clock()
        if remaining <= 0:
            return "wait-budget-exhausted"
        sleep(min(POLL_SECONDS, remaining))


def next_attempt(dataset: dict, attempt: int) -> int | None:
    if not 0 <= attempt <= MAX_ATTEMPTS:
        raise ValueError(f"catch-up attempt must be between 0 and {MAX_ATTEMPTS}")
    if not needs_catchup(dataset):
        return None
    if attempt == MAX_ATTEMPTS:
        raise RuntimeError("Catch-up limit reached with stale price/portfolio data; operator action required")
    return attempt + 1


def dispatch(attempt: int) -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    url = (f"https://api.github.com/repos/{repository}/actions/workflows/"
           "daily_monitor.yml/dispatches")
    body = json.dumps({"ref": "main", "inputs": {"catchup_attempt": str(attempt)}}).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        "Content-Type": "application/json", "User-Agent": "portfolio-monitor",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 204:
            raise RuntimeError(f"Catch-up dispatch returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["wait", "schedule"])
    parser.add_argument("--attempt", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.attempt <= MAX_ATTEMPTS:
        raise ValueError("Invalid catch-up attempt")
    if args.mode == "wait":
        if args.attempt == 0:
            return 0
        for pid in ACTIVE_PORTFOLIO_IDS:
            print(f"{pid}: catch-up {args.attempt}/{MAX_ATTEMPTS}: {wait_for_publication(pid)}")
        return 0
    attempts = [next_attempt(load_dataset(pid), args.attempt) for pid in ACTIVE_PORTFOLIO_IDS]
    followup = max((n for n in attempts if n is not None), default=None)
    if followup is not None:
        dispatch(followup)
        print(f"Requested catch-up refresh {followup}/{MAX_ATTEMPTS}")
    else:
        print("No catch-up needed: price and portfolio coverage are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
