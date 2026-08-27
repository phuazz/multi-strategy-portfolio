"""emit_state.py — publish this monitor's data health in the STATE_CONTRACT shape.

WHAT THIS IS FOR
----------------
A private consumer (the command centre) renders this monitor's health beside
signals from seven other projects. Until now it did that by reaching INTO this
repo and reading exact JSON pointers out of the baked portfolio JSON from its
own side. That works, and it is guarded there, but it puts knowledge of THIS
repo's field names in somebody else's codebase: rename a key here and the break
surfaces over there, days later, in a file nobody was editing at the time.

This writes `docs/data/state.json` beside the file it describes, so a rename
breaks here, in this repo's CI, at the moment of the rename.

ONLY HEALTH IS EMITTED. THE REGIME IS NOT.
-------------------------------------------
The baked JSON also carries a `regime` block, and it would be easy to emit. It
must not be. This monitor is a display layer that sits one fetch behind the
engine by design, so during an engine-side revision the two legitimately
disagree — and the consumer's contract is explicit that the ENGINE is primary
and that this repo's row records only its own health and as-of. Emitting a
regime state from here would put a second, staler answer to the same question
into circulation wearing equal authority. The regime stays in the baked JSON
for the dashboard to display, and out of the contract.

WHAT "WORST FEED" MEANS HERE, AND WHAT IT DOES NOT
---------------------------------------------------
The sub-state line names the feed with the largest RAW `bday_lag`, which is the
definition the consumer already uses and is reproduced here exactly. Note what
that does not do: it does not rank by headroom against each feed's own budget.
A feed at 3 of 12 budgeted days is chosen over one at 2 of 2, although the
second is the one actually at its limit. That is a shared limitation of the
description, not of the health VERDICT — `health.level` is computed upstream
per feed and is what the state itself reports. Changing the definition here
alone would put the two sides permanently at odds, so it is reproduced and
recorded rather than quietly improved.

WHAT IT IS NOT
--------------
  * NOT a new signal and not a recomputation of health. Every value is copied
    from a file this repo already publishes. If this and the baked JSON ever
    disagree, the baked JSON is right and this is broken.
  * NOT load-bearing here. Nothing in this repo reads docs/data/state.json,
    which is why it runs in its own workflow rather than as a step in the daily
    monitor: that workflow gates its publish on the test suite, and this must
    never be able to hold up the monitor.

Usage:
    python scripts/emit_state.py           # write docs/data/state.json
    python scripts/emit_state.py --check   # validate and print, write nothing
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parent.parent
SOURCE_JSON = REPO / "docs" / "data" / "portfolio-multi-strategy-portfolio.json"
OUT = REPO / "docs" / "data" / "state.json"

CONTRACT_VERSION = "1"
SOURCE = "multi-strategy-portfolio"
SIGNAL = "monitor_health"

# The health vocabulary the consumer holds frozen. A level outside it is a
# rejection there; catching it here names the file it came from.
LEVELS = ("ok", "warn", "error")


class EmitError(Exception):
    """A required input was missing or malformed. Never emit a guess."""


def require(obj, path: str, kind=None):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise EmitError(f"missing key `{part}` at pointer `{path}`")
        cur = cur[part]
    if cur is None:
        raise EmitError(f"pointer `{path}` is null")
    if kind is not None and not isinstance(cur, kind):
        # `kind` is often a tuple of accepted types, which has no __name__.
        want = kind.__name__ if isinstance(kind, type) else "/".join(k.__name__ for k in kind)
        raise EmitError(f"pointer `{path}` is {type(cur).__name__}, expected {want}")
    return cur


def load_portfolio():
    if not SOURCE_JSON.exists():
        raise EmitError(f"source file not found: {SOURCE_JSON}")
    try:
        return json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmitError(f"the baked portfolio JSON is not valid JSON: {exc}") from exc


def worst_feed(feeds: list) -> dict:
    """The feed carrying the largest raw bday_lag. See the module docstring for
    why this is raw lag rather than headroom against budget.

    A non-integer lag is refused rather than sorted around: comparing None with
    an int raises inside max(), and a lag that is not a number means the health
    block is not what this expects.
    """
    for f in feeds:
        if not isinstance(f, dict):
            raise EmitError(f"health.feeds carries a {type(f).__name__}, expected objects")
        lag = f.get("bday_lag")
        if not isinstance(lag, int) or isinstance(lag, bool):
            raise EmitError(
                f"health.feeds[{f.get('feed')!r}].bday_lag is {lag!r}, expected an integer")
    return max(feeds, key=lambda f: f["bday_lag"])


def build() -> dict:
    d = load_portfolio()

    as_of = require(d, "meta.asOf", str)
    built_at = require(d, "meta.built_at_utc", str)
    level = require(d, "health.level", str)
    if level not in LEVELS:
        raise EmitError(f"health.level {level!r} outside {LEVELS}")

    feeds = require(d, "health.feeds", list)
    if not feeds:
        raise EmitError("health.feeds is empty — there is nothing to report health on")
    worst = worst_feed(feeds)

    return {
        "contract_version": CONTRACT_VERSION,
        "emitted_by": SOURCE,
        "emitted_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "signals": {
            SIGNAL: {
                "as_of": as_of,
                "state": level,
                "value": len(feeds),
                "zone": (f"worst feed lag {worst['bday_lag']} of "
                         f"{worst.get('budget_bdays')} bdays"),
                "role": "view-only",
                "horizon": "daily",
                "evidence_grade": "deployed-engine",
                "licence": "public",
                "action_hint": "watch" if level != "ok" else "none",
                "source_file": "docs/data/portfolio-multi-strategy-portfolio.json",
                "computed_at": built_at,
                "cadence": "daily",
            }
        },
    }


def unchanged(payload: dict) -> bool:
    """Same emission as the one on disk, apart from the run's own timestamp?

    `emitted_at` moves every run, so writing unconditionally would leave a diff
    every time and the workflow would commit a no-op on every run. Liveness does
    not need that commit: the consumer judges freshness from `as_of`, so a dead
    emitter still shows up there as a stale state.
    """
    if not OUT.exists():
        return False
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "emitted_at"}
    return strip(prev) == strip(payload)


def main(argv: list[str]) -> int:
    try:
        payload = build()
    except EmitError as exc:
        print(f"emit_state: FAILED — {exc}", file=sys.stderr)
        print("emit_state: nothing written; the previous state.json is left as it was.",
              file=sys.stderr)
        return 1

    s = payload["signals"][SIGNAL]
    print(f"emit_state: health {s['state']} @ {s['as_of']} — "
          f"{s['value']} feed(s), {s['zone']}")

    if "--check" in argv:
        print("emit_state: --check, nothing written.")
        return 0

    if unchanged(payload):
        print("emit_state: state unchanged since the last emission — leaving it as it is.")
        return 0

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        shown = OUT.relative_to(REPO)
    except ValueError:
        shown = OUT
    print(f"emit_state: wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
