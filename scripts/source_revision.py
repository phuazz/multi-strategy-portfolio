"""Resolve one immutable engine publication and compare its consumed files.

Standard library only: the hourly probe runs before installing build dependencies.
Unrelated engine commits do not trigger a rebuild. API failures are errors, never
interpreted as an unchanged source. Python datetime months are 1-indexed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone


def api_json(url: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "portfolio-monitor"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
        return json.load(resp)


def resolve_snapshot(source: dict, ref: str | None = None) -> dict:
    api = source["api_base"]
    commit = api_json(f"{api}/commits/{ref or source['ref']}")
    sha = commit["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Engine did not return an immutable commit SHA")
    root = api_json(f"{api}/git/trees/{sha}")
    data_sha = next(x["sha"] for x in root["tree"]
                    if x["path"] == "data" and x["type"] == "tree")
    tree = api_json(f"{api}/git/trees/{data_sha}")
    if tree.get("truncated"):
        raise ValueError("Engine data tree was truncated")
    blobs = {x["path"]: x["sha"] for x in tree["tree"] if x["type"] == "blob"}
    names = source["files"] + source.get("history_files", [])
    missing = set(source["files"]) - blobs.keys()
    if missing:
        raise ValueError(f"Engine required files missing: {sorted(missing)}")
    return {"commit": sha, "files": {fn: blobs.get(fn) for fn in names}}


def changed_files(meta: dict, snapshot: dict, source: dict) -> list[str]:
    previous = meta.get("source_blobs")
    if not previous:
        # Bootstrap existing deployed datasets without inventing provenance.
        previous = resolve_snapshot(source, meta["source_commit"])["files"]
    return [fn for fn, sha in snapshot["files"].items() if previous.get(fn) != sha]


def overdue_source_files(meta: dict, snapshot: dict, source: dict,
                         now: datetime, grace_minutes: int = 120) -> list[str]:
    """Only alert after a changed consumed file has waited beyond the sync budget.

    Query each changed file's commit, not HEAD time: unrelated probe commits must
    never reset the grace period. The query is pinned to the inspected snapshot.
    """
    overdue = []
    for fn in changed_files(meta, snapshot, source):
        commits = api_json(f"{source['api_base']}/commits?path=data/{fn}"
                           f"&sha={snapshot['commit']}&per_page=1")
        if not commits:
            raise ValueError(f"No publication commit found for {fn}")
        published = datetime.fromisoformat(commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00"))
        if (now.astimezone(timezone.utc) - published).total_seconds() > grace_minutes * 60:
            overdue.append(fn)
    return overdue
