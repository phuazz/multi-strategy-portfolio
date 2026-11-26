"""Hourly source-change probe for the existing daily-monitor workflow."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

from config import ACTIVE_PORTFOLIO_IDS, dataset_path, load_registry
from source_revision import changed_files, resolve_snapshot


def benchmark_retry(dataset, now):
    """Retry external benchmark tails while the engine NAV is current.

    Python calendar months are 1-indexed. Space attempts by two hours and
    stop two UTC dates after the NAV. Historical gaps have no retry budget.
    """
    health = dataset.get("health", {})
    feeds = health.get("feeds", [])
    nav = dataset.get("meta", {}).get("live_asOf")
    if not nav or not any(f.get("feed") == "Price / NAV (live_track)" and
                          f.get("level") == "ok" and f.get("asOf") == nav for f in feeds):
        return False
    pending = any(f.get("feed", "").startswith("Benchmark ") and
                  f.get("versus") == nav and (f.get("asOf") != nav or f.get("missingNAVValuation"))
                  for f in feeds)
    if not pending:
        return False
    checked = datetime.fromisoformat(health["checked_at_utc"].replace("Z", "+00:00"))
    age = now.date() - date.fromisoformat(nav)
    return timedelta(0) <= age <= timedelta(days=2) and now - checked >= timedelta(hours=2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only-if-changed", action="store_true")
    args = ap.parse_args()
    rebuild = not args.only_if_changed
    vendor_retry = False
    engine_changed = False
    for pid in ACTIVE_PORTFOLIO_IDS:
        reg = load_registry(pid)
        snapshot = resolve_snapshot(reg["source"])
        path = dataset_path(pid)
        dataset = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        meta = dataset.get("meta", {})
        # A legacy SHA stamped after moving-ref downloads is not proof of the
        # bytes consumed. Bootstrap a verified manifest with a fresh build.
        changed = (changed_files(meta, snapshot, reg["source"])
                   if meta.get("source_blobs") else list(snapshot["files"]))
        engine_changed |= bool(changed)
        if args.only_if_changed and not changed and benchmark_retry(dataset, datetime.now(timezone.utc)):
            vendor_retry = True
            print(f"{pid}: retrying a missing benchmark valuation for the published NAV")
        rebuild |= bool(changed) or vendor_retry
        print(f"{pid}: engine {snapshot['commit']}; changed consumed files: {changed or 'none'}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as fh:
            if vendor_retry and not engine_changed:
                fh.write("benchmark_retry=true\n")
            fh.write(f"rebuild={'true' if rebuild else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
