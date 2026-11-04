# Daily valuation catch-up

Working directory: `C:\dev\worktrees\multi-strategy-rebalance-sync`.
Context: Personal paper portfolio. Recommended model: GPT-6 Sol, high effort.

## Incident and operational recovery

The published dataset genuinely trailed the last completed NYSE session by one day.
The engine's initial daily mark still ended on `2026-11-02`; the local post-fill
refresh published current `2026-11-03` data after the monitor's latest scheduled
build. No later hourly catch-up run had fired when the warning was investigated.
The monitor's stale banner and weekly-book check were correct. Do not weaken them.

Manual recovery refresh:
https://github.com/phuazz/multi-strategy-portfolio/actions/runs/41787750027

That refresh passed its tests and capture check. The recovery uses the existing
production workflow and changes no upstream strategy or data. The existing hosted
morning-report workflow remains untouched.

Verified live: valuation through Tuesday `2026-11-03`, health OK, all nine consumed
source blobs match the engine, and rebalance remains Monday `2026-11-02`. The latest
Pages build is `a95c9c7b62df6bca35936b3a1640ee36c7661ef4` and completed successfully.
Independent deployed-site sentinel passed:
https://github.com/phuazz/multi-strategy-portfolio/actions/runs/41788657947

## Additional patch, approved for commit and push

The existing hourly poll still depends on best-effort cron delivery. A stale
valuation or core-book capture now has a prepared bounded workflow-dispatch recovery
path: up to eight follow-ups, each with a 20-minute consumed-source wait. A new
source publication rebuilds; unchanged sources avoid another full build. Fresh
coverage stops the chain, and exhaustion fails for operator action. Intermediate
attempts suppress duplicate capture-warning emails. No additional secret is needed;
the existing workflow gains Actions write permission only to dispatch its follow-up.

Changed files: `.github/workflows/daily_monitor.yml`, `scripts/catchup_refresh.py`,
`tests/test_catchup_refresh.py`, `README.md`, and this handoff. No template or
generated output was hand-edited. The existing fleet-watch output and run rows
continue to cover the same workflow; no new scheduler is introduced.

Guards cover a fresh stop, delayed publication, bounded timeout, source API failure,
invalid attempts, exhausted attempts, the dispatch destination and no unnecessary
dispatches. Tests use synthetic clocks and perform no sleeps or GitHub writes.

Full local suite: 198 passed. Workflow YAML parses; git diff --check passes. Vault
and project identifier gates both pass. Static page check has no failures or
warnings. Live rendered checks cover all nine tabs at 390/844/768/1280 px: returned
viewport widths match, minimum text is 11 px, body overflow is zero, the masthead
reading measures are 42/74/74/74 characters, filter targets meet 44 px, pie text
is unclipped and table columns are reachable through their own scrollers.

GitHub documents that scheduled events can be delayed or dropped, while
workflow_dispatch can be triggered from GITHUB_TOKEN:
https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow

Dates were checked using the exchange calendar and datetime libraries. Confirm
before reusing incident dates in a dated external report. The owner has approved
commit and push. Run a normal refresh and a catchup_attempt=1 run against fresh
data, then verify that the follow-up exits promptly without another build or dispatch.
