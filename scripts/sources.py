"""Fetch the engine's raw outputs from the breadth-thrust-etf repository.

The engine (phuazz/breadth-thrust-etf) bakes its dashboard daily but does NOT
publish its data/*.json as standalone files on GitHub Pages, so we read them
from the repository's raw endpoint instead. Each file is the engine's own
output contract; we treat the fetched bundle as read-only upstream data.

Provenance: resolve a commit first, fetch every file at that immutable SHA,
and verify its Git blob hash before parsing. The dataset carries both the commit
and the consumed blob manifest for the change probe and deployed sentinel.

For offline development, --local <path-to-breadth-thrust-etf> reads the files
straight off disk instead of the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

from source_revision import resolve_snapshot

REQUEST_TIMEOUT = 30


def _fetch_url(url: str) -> bytes:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def load_sources(registry: dict, *, local: str | None = None) -> dict:
    """Return {filename: parsed_json, ...} plus a 'source_commit' key.

    Raises on any required file that cannot be loaded — a missing upstream feed
    must stop the build loudly rather than silently bake a partial dashboard.
    """
    src = registry["source"]
    files = src["files"]
    hist_files = src.get("history_files", [])   # optional — for the weight-history reconstruction
    out: dict = {}

    if local:
        base = Path(local) / "data"
        print(f"  [sources] reading local: {base}")
        for fn in files:
            path = base / fn
            if not path.exists():
                raise FileNotFoundError(f"Local source missing: {path}")
            out[fn] = json.loads(path.read_text(encoding="utf-8"))
        for fn in hist_files:
            path = base / fn
            try:
                out[fn] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"  [sources] optional history file {fn} unavailable ({exc!r})", file=sys.stderr)
        out["source_commit"] = "LOCAL"
        return out

    # Resolve BEFORE reading any file. A moving @main fetch followed by a SHA
    # lookup can stamp a mixed bundle with a commit it never actually consumed.
    snapshot = resolve_snapshot(src)
    raw_base = f"https://raw.githubusercontent.com/{src['repo']}/{snapshot['commit']}/data"

    def read_file(fn):
        content = _fetch_url(f"{raw_base}/{fn}")
        git_blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if git_blob != snapshot["files"][fn]:
            raise ValueError(f"Engine blob verification failed for {fn}")
        return json.loads(content)

    print(f"  [sources] fetching raw: {raw_base}")
    for fn in files:
        url = f"{raw_base}/{fn}"
        try:
            out[fn] = read_file(fn)
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch required source {url}: {exc}") from exc
        print(f"    ok  {fn} ({len(json.dumps(out[fn]))//1024} KB)")
    for fn in hist_files:
        if snapshot["files"][fn] is None:
            continue                            # genuinely absent at the pinned commit
        # A published history file failing to download must not silently switch
        # the rendered rebalance ledger to a different reconstruction basis.
        out[fn] = read_file(fn)
        print(f"    ok  {fn} (history, {len(json.dumps(out[fn]))//1024} KB)")

    out["source_commit"] = snapshot["commit"]
    out["source_blobs"] = snapshot["files"]
    return out


def _cli() -> None:
    from config import load_registry

    ap = argparse.ArgumentParser(description="Fetch engine sources (debug).")
    ap.add_argument("--portfolio", default="multi-strategy-portfolio")
    ap.add_argument("--local", default=None, help="path to a local breadth-thrust-etf checkout")
    args = ap.parse_args()

    reg = load_registry(args.portfolio)
    bundle = load_sources(reg, local=args.local)
    print("commit:", bundle.get("source_commit"))
    for fn in reg["source"]["files"]:
        d = bundle[fn]
        print(fn, "->", d.get("computed_at_utc", "?"))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    _cli()
