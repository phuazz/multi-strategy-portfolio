"""Capture-integrity check: did this build capture the session it should
have, and is the baked dataset structurally sound?

Closes the silent class the existing gates cannot reach. validate.py
budgets are deliberately wide (price 4 business days), so a build that
fetches the engine BEFORE the engine's delayed nightly publish bakes
yesterday-as-latest with health level 'ok' — green run, no banner, wrong
expectation. This check anchors the BAKED dataset's live as-of to the
true NYSE calendar (scripts/nyse_sessions.py) and reports through the
workflow's email steps.

Verdict policy — this repo surfaces upstream problems, it does not go
dark on them (see CLAUDE.md), so upstream staleness NEVER blocks the
publish:
  warn  live as-of is 1+ session(s) behind the last completed NYSE
        session, or the baked health level is not 'ok' -> the dashboard
        still publishes (with its own banners); the operator gets an
        email naming the lag
  fail  the baked dataset itself is corrupt (missing, unparseable, no
        usable as-of) -> exit 1 BEFORE the commit step, so a broken
        artefact is never published

Python datetime months are 1-indexed (January = 1). Printed strings are
plain ASCII (local consoles may not be UTF-8).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Allow importing sibling scripts/ modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ACTIVE_PORTFOLIO_IDS, dataset_path  # noqa: E402
from nyse_sessions import last_completed_session, sessions_behind  # noqa: E402


def evaluate_dataset(blob: dict, expected: date) -> dict:
    """Verdict for one baked dataset:
    {status, lag, health_level, evidence}. ``lag`` is None when the
    dataset is too corrupt to compute one.

    Pure function (expected session injected) so tests can pin the
    calendar without monkeypatching the clock.
    """
    meta = blob.get("meta", {})
    live_asof = meta.get("live_asOf") or meta.get("asOf")
    health_level = blob.get("health", {}).get("level", "missing")
    if not live_asof:
        return {"status": "fail", "lag": None, "health_level": health_level,
                "evidence": "baked meta has no live_asOf/asOf field"}
    try:
        live_date = date.fromisoformat(str(live_asof)[:10])
    except ValueError as exc:
        return {"status": "fail", "lag": None, "health_level": health_level,
                "evidence": f"unparseable live_asOf {live_asof!r} ({exc})"}
    lag = sessions_behind(live_date, expected)

    if lag >= 1 or health_level != "ok":
        status = "warn"
    else:
        status = "ok"
    return {"status": status, "lag": lag, "health_level": health_level,
            "evidence": (f"live as-of {live_date.isoformat()}, {lag} session(s) "
                         f"behind expected {expected.isoformat()}; baked health "
                         f"level '{health_level}'")}


def write_github_output(values: dict[str, str], detail: str) -> None:
    """Append step outputs for the conditional warn-email step. No-op
    outside GitHub Actions."""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as fh:
        for key, val in values.items():
            fh.write(f"{key}={val}\n")
        fh.write("detail<<CAPTURE_DETAIL_EOF\n")
        fh.write(detail.rstrip("\n") + "\n")
        fh.write("CAPTURE_DETAIL_EOF\n")


def main() -> int:
    expected = last_completed_session(datetime.now(timezone.utc))
    results = []
    for pid in ACTIVE_PORTFOLIO_IDS:
        path = dataset_path(pid)
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            verdict = evaluate_dataset(blob, expected)
        except Exception as exc:
            verdict = {"status": "fail",
                       "evidence": f"unreadable dataset {path.name}: {exc}"}
        verdict["portfolio"] = pid
        results.append(verdict)

    worst = ("ok" if all(r["status"] == "ok" for r in results)
             else "fail" if any(r["status"] == "fail" for r in results)
             else "warn")
    lines = [f"expected last completed NYSE session: {expected.isoformat()}"]
    lines += [f"{r['status'].upper():5s} {r['portfolio']}: {r['evidence']}"
              for r in results]
    detail = "\n".join(lines)
    print(detail)

    flagged = [r["portfolio"] for r in results if r["status"] != "ok"]
    summary = (f"capture {worst}: {', '.join(flagged)}" if flagged
               else "capture ok")
    write_github_output(
        {"capture_warn": "true" if worst == "warn" else "false",
         "capture_status": worst, "summary": summary},
        detail,
    )
    # fail -> the job stops before the commit step, so a corrupt artefact
    # is never published; the failure-alert email then fires. warn/ok
    # publish normally (upstream staleness is surfaced, never hidden).
    return 1 if worst == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
