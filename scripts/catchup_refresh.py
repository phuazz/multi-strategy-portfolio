"""Report stale upstream data without starting a second recovery scheduler.

The existing hourly sync_source probe detects changes to consumed blobs, even
after repeated stale sessions. Unchanged inputs do not build, sleep or dispatch.
The sentinel and capture checks retain their independent freshness verdicts.
Legacy wait/schedule arguments remain accepted so queued follow-ups drain safely.
"""
from __future__ import annotations

import argparse
import json

from config import ACTIVE_PORTFOLIO_IDS, dataset_path

# Accepted only for compatibility with follow-ups queued by the former workflow.
MAX_ATTEMPTS = 8
RECOVERABLE_FEEDS = {"Price / NAV (live_track)", "Executed portfolio (engine anchor)"}


def needs_catchup(dataset: dict) -> bool:
    return any(f.get("feed") in RECOVERABLE_FEEDS and f.get("level") == "stale"
               for f in dataset.get("health", {}).get("feeds", []))


def load_dataset(pid: str) -> dict:
    return json.loads(dataset_path(pid).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["wait", "schedule"])
    parser.add_argument("--attempt", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.attempt <= MAX_ATTEMPTS:
        raise ValueError("Invalid catch-up attempt")
    for pid in ACTIVE_PORTFOLIO_IDS:
        if needs_catchup(load_dataset(pid)):
            print(f"{pid}: upstream price/portfolio data remains stale; "
                  "hourly consumed-blob probes will detect a later publication. "
                  "No wait or follow-up dispatched.")
        else:
            print(f"{pid}: no stale price/portfolio feed reported; no follow-up dispatched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
