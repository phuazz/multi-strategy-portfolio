"""Hourly source-change probe for the existing daily-monitor workflow."""
from __future__ import annotations

import argparse
import json
import os

from config import ACTIVE_PORTFOLIO_IDS, dataset_path, load_registry
from source_revision import changed_files, resolve_snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only-if-changed", action="store_true")
    args = ap.parse_args()
    rebuild = not args.only_if_changed
    for pid in ACTIVE_PORTFOLIO_IDS:
        reg = load_registry(pid)
        snapshot = resolve_snapshot(reg["source"])
        path = dataset_path(pid)
        meta = json.loads(path.read_text(encoding="utf-8"))["meta"] if path.exists() else {}
        # A legacy SHA stamped after moving-ref downloads is not proof of the
        # bytes consumed. Bootstrap a verified manifest with a fresh build.
        changed = (changed_files(meta, snapshot, reg["source"])
                   if meta.get("source_blobs") else list(snapshot["files"]))
        rebuild |= bool(changed)
        print(f"{pid}: engine {snapshot['commit']}; changed consumed files: {changed or 'none'}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"rebuild={'true' if rebuild else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
