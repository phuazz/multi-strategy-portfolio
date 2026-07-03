# VERIFY_DASHBOARD.md — freshness + refresh integrity audit

Reusable prompt for auditing the live monitor at
https://phuazz.github.io/navigo-systematic-trend/. Paste the block
between the rules into a Claude Code session at this project root. The
audit is read-only — it changes nothing and proposes fixes rather than
applying them.

Ported from the upstream breadth-thrust-etf audit (2026-07-03) and
adapted to this repo's thin-consumer architecture. Keep the checklist in
sync with `.github/workflows/*.yml`, `scripts/validate.py` and
`portfolios/<id>.json` when those change.

---

```
[CONTEXT]
- Dashboard: Navigo Systematic Trend model-portfolio monitor (Navigo
  context — paper model, public GitHub Pages).
- Architecture: READ-ONLY consumer of the breadth-thrust-etf engine.
  Daily it fetches the engine's data/*.json from raw.githubusercontent
  @main (with commit-SHA provenance), normalises, recomputes analytics,
  validates, and bakes template.html (~105 KB, safe to read) +
  docs/data/portfolio-<id>.json (~450 KB — read structure, not blindly)
  to GitHub Pages. It never re-runs the strategy, and sessions in this
  repo never modify the engine repo.
- Refresh surface:
  1. .github/workflows/daily_monitor.yml — cron '40 23 * * 1-5'
     (Mon-Fri 23:40 UTC): fetch engine sources -> build dataset + bake ->
     pytest -> capture-integrity check -> commit docs/ -> Pages.
     The cron sits PAST the engine's measured publish tail (its 21:30
     UTC daily has landed 22:35-23:18 UTC) — the fetch-before-publish
     race is the monitor's characteristic silent failure.
  2. .github/workflows/sentinel.yml — daily 05:05 UTC: fetches the
     DEPLOYED dataset, alerts on session lag or health level 'stale'.
     Sized to the cron-delay tail; do not move earlier than ~04:30 UTC.
- In-build gates (scripts/validate.py, surfaced on the Data Health tab
  and baked into the dataset's health object): per-feed business-day
  budgets (price 4 / regime 8 / strategy 12, warn from budget-2),
  regime since-date vs latest event, recomputed-vs-engine stats
  reconciliation, benchmark availability. DELIBERATELY nothing in the
  build hard-stops on upstream staleness — a stale-bannered dashboard
  beats a dark one. Only a corrupt baked artefact stops the publish
  (capture-integrity check).
- Ops alerting (2026-07-03): daily_monitor emails on failure and on
  capture warn; the sentinel emails on deployed staleness. All alerts go
  to GMAIL_USER. The GMAIL_USER / GMAIL_APP_PASSWORD repository secrets
  must exist — if `gh secret list` is empty, every alert channel is
  DARK and that is itself a FAIL finding.
- Cadence rule (Zhenghao, 2026-07-03): publishes follow the engine —
  every Friday after the US close even on US market holidays, using the
  latest populated close. A Friday-holiday dashboard dated Thursday is
  correct, not stale.

[TASK]
Audit two things: (a) the DEPLOYED monitor shows the latest engine data
it should as of now, and (b) the refresh chain (engine -> fetch -> bake
-> Pages) is healthy, with enough headroom that it stays healthy through
the next several scheduled runs. Read-only. Propose fixes; do not apply
them. Do not modify the engine repo from this session.

Before running any check, state the three ways this audit could be
silently wrong, and design around each:
1. Auditing the repo instead of the site. Local files and even committed
   files can lead or lag what Pages serves. Every claim about "the
   dashboard" must be evidenced from the deployed URL or the Pages
   deployment SHA, never from the working tree alone.
2. Wrong calendar. On a weekend or NYSE holiday, "no new datapoint" is
   correct. Derive the last completed NYSE session with
   pandas_market_calendars (pinned in requirements.txt; use
   scripts/nyse_sessions.py). Never compute weekdays or holidays from
   memory. Distinguish the three lag conventions in play: true NYSE
   sessions (nyse_sessions.py), plain business days (validate.py
   budgets), and plain weekdays (the ENGINE's hard guard).
3. Green run does not mean fresh data. The monitor's characteristic
   silent failure is fetching BEFORE the engine's delayed publish and
   baking yesterday-as-latest inside the price budget — health 'ok', no
   banner. A cron can also silently stop firing (no run, no failure to
   see). Verify data as-ofs and commit heartbeats against the calendar,
   never run status alone.

[CHECKS — run all nine; report each with evidence]

1. Reference dates. With scripts/nyse_sessions.py: the last completed
   NYSE session as of now (UTC), the next session, and any holiday in
   the past 7 calendar days. Every later check compares against these.

2. Deployed as-of. Fetch (cache-busted)
   https://phuazz.github.io/navigo-systematic-trend/data/portfolio-navigo-systematic-trend.json
   and read meta.live_asOf, meta.asOf, meta.built_at_utc, health.level.
   live_asOf must equal the last completed session (check 1); health
   feeds' levels must be consistent with their budgets. Tolerance: if
   now (UTC) is before ~01:30 UTC following a session day, the nightly
   publish may legitimately not have landed yet — report PASS with the
   cutover noted.

3. Deployed = HEAD. gh api repos/phuazz/navigo-systematic-trend/pages/builds/latest
   — status "built" and sha equal to origin/main HEAD. A failed LATEST
   Pages build is a FAIL even if an earlier build succeeded.

4. Scheduled-run health, both workflows.
   gh run list --workflow=daily_monitor.yml --limit 10
   gh run list --workflow=sentinel.yml --limit 7
   Every scheduled run on a session day should be success. For any
   failure: gh run view <id> --log-failed, quote the actual exception,
   and classify — engine fetch failure / capture fail / test failure /
   yfinance benchmarks / email step. Also confirm the daily cron
   actually FIRED on each of the last 5 session days, and confirm the
   alert secrets exist (gh secret list — GMAIL_USER, GMAIL_APP_PASSWORD).

5. Commit heartbeat. git log --grep "Daily monitor refresh" on main:
   the latest must carry the date of the last NYSE session (no commit on
   a holiday weekend is correct — do not flag).

6. Feed anchor table. From the DEPLOYED health object (not the working
   tree), report per feed: asOf, bday_lag vs budget, level — and
   recompute the true NYSE-session lag with nyse_sessions.py alongside.
   Feeds: Price/NAV (live_track), Breadth/regime panel (risk_overlay),
   Strategy equity (multi_strategy). Flag any feed within 2 business
   days of its budget as a watch item.

7. Race + provenance check. For the last 5 monitor runs: compare each
   run's start time (gh run list) against the ENGINE's corresponding
   "Daily live track refresh" commit time (git log in the engine repo or
   gh api) — every monitor run must START after the engine's publish
   COMMITTED. Then verify the deployed dataset's health.source_commit is
   an ancestor of the engine's origin/main and no older than the
   engine's last publish at monitor run time. A monitor that ran early
   shows here even when every banner is green.

8. Upstream headroom forecast. The regime feed (risk_overlay
   panel_end_date, budget 8 business days) and strategy feed
   (multi_strategy common_end, budget 12) only advance when the ENGINE's
   local heavy refresh runs. Using their deployed as-ofs, forecast the
   date each breaches its budget (STALE banner) if the engine's
   refresh_all.py does not run — and note the engine's own hard guard
   (5 weekday budget on breadth_csp1) will freeze the whole chain
   earlier. Name the binding date. An audit that only says "green today"
   has not done this check.

9. Rendered page + cross-consistency. Fetch the deployed index.html
   (~105 KB — safe to grep) and confirm: it references the dataset the
   audit checked; the STALE banner markup activates on health.level
   'stale' consistently with check 6; the disclaimer footer is present
   (paper model — compliance). Cross-check docs/data/rebalance-*.json
   "updated" equals meta.asOf, and that deployed health.checked_at is
   the latest build date.

[SUCCESS CRITERIA]
- Must: every check gets PASS / WARN / FAIL / UNVERIFIED with a command
  output or URL as evidence — no verdict from memory or assumption.
- Must: a one-line overall verdict first — is the deployed monitor
  showing the latest engine data it should, yes or no, as of which
  session.
- Must: an "actions required" list with deadlines in UTC and SGT,
  distinguishing monitor-side actions from engine-side actions (engine
  fixes happen in the engine repo, never from here).
- Must: flag every date in the report for user confirmation (house rule).
- Out of scope: applying fixes, dispatching workflows, editing anything,
  touching the engine repo.

[CONSTRAINTS — house rules]
- Never edit docs/index.html (baked); template.html is the source and at
  ~105 KB is safe to read whole. The ~450 KB dataset: read structure via
  python, never blindly into context.
- All date arithmetic via nyse_sessions.py / a date library; never
  weekday or holiday reasoning from memory.
- Read-only: no writes outside the scratchpad; discard any accidental
  docs/ changes (git checkout -- docs/ data/) before ending.
- If gh is unauthenticated or an API call is denied, mark the affected
  checks UNVERIFIED and say so — do not silently narrow the audit.

[OUTPUT FORMAT]
1. Verdict line.
2. Check table: check / status / one-line evidence.
3. Incidents found, each with the root cause quoted from logs.
4. Actions required, with deadlines (UTC + SGT), split monitor-side vs
   engine-side.
5. Watch items — what goes stale next, and on which date.
```
