# Hosted morning portfolio report

This is a personal paper-portfolio dossier, delivered through the GitHub Actions
workflow `morning_email.yml`. The local Codex email automation is paused.

## Delivery rule

Singapore time, Tuesday-Saturday: 09:00 is the earliest target, with checks every
15 minutes until 11:00. If verification still fails at or after 11:00, send one short
delay notice without stale performance figures or a stale PDF. Continue hourly
through 23:00 and send the full report once ready. Successful dashboard refresh and
Pages workflows also trigger a readiness check within the delivery window.
GitHub can delay or drop cron jobs; these are targets, not exact-time guarantees.

The gate fetches the **deployed** dataset, then requires the official NAV observations
and the S&P 500, global balanced-fund and Treasury-bill proxy series to end on the
last completed NYSE session. Health, consistency and reconciliation must pass.
Executed portfolio coverage must reach the latest required weekly core fill. The
deployed engine blob manifest must match the current engine publication. A successful
refresh job or a green badge alone does not satisfy the gate. The NYSE calendar
handles holidays and daylight saving; there is no invented return on a closed day.

## Delivery and duplicate protection

Required repository secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MORNING_REPORT_TO`.
The first two already support dashboard operations. The third fixes the single
authorised recipient without publishing an address. No CC/BCC or inherited digest
recipient list is used.

All invocations share one Actions concurrency group. The `morning-mail-state` branch
holds one ledger record per valuation date and message type (report or delay).
It contains status, content hash, timestamps and workflow run ID only. It never
contains a recipient, password, body, attachment or personal identifier. A pending
claim is committed before SMTP submission; confirmed acceptance changes it to sent.
Reports are deduplicated by valuation date, including holiday repeats.

SMTP cannot provide an atomic transaction with GitHub. If a run stops after its
claim, automatic retries fail closed. Inspect the originating run and Gmail Sent
before changing a pending record: a timeout may occur after acceptance. The
deterministic Message-ID is `msp-<first 24 hex characters of SHA256(ledger key)>`
at `portfolio-monitor.local`. Repair to sent after verifying acceptance, or remove
the claim only after verifying it did not send. Do not blindly rerun an uncertain send.

## Report and publication checks

The HTML email contains the session/YTD/drawdown figures, matched-period returns,
a compact risk table, positioning and indicative contributors. The two-page A4 PDF
adds full risk ratios, benchmark-relative statistics, valuation windows, sources and
methodology. Both derive from the same report object. Source and dashboard links are
clickable. The plain-text alternative remains available for email clients.

Holding contributions use current weights and are explicitly approximate. Their
residual is shown; quote-date and FX differences are not attributed to trading skill.
Backtested history, engine-labelled out-of-sample performance and a live extension
are kept distinct. Risk statistics use the published common-date panel and its
calendar gaps are disclosed.

Before each send, the workflow runs the delivery tests, the vendored vault static
HTML checker, a real headless Chromium check at 390/844/768/1280 pixels, and PDF
page-count, A4, text-bounds and hyperlink guards. A layout failure blocks sending.
The evidence is retained as a GitHub Actions artifact for seven days. Evidence has
no recipient addresses or credentials. `data/` remains ignored by Git.

Local preview: `python scripts/deliver_morning.py --preview --output data/morning-email-preview`.
This is labelled DESIGN PREVIEW and cannot send. Install `requirements-mail.txt`
and Chromium with `python -m playwright install chromium` for local layout checks.
Set `MORNING_CHROME_PATH` only when deliberately using an installed local browser.

## Monitoring and recovery

The vault fleet watch covers the hosted workflow and its sent-ledger heartbeat.
The existing deployed-dashboard sentinel separately monitors data freshness. A
delay notice does not make the data fresh. Tests and layout failures appear as failed
Actions runs; missing sent receipts eventually breach the fleet heartbeat budget.

No strategy logic or engine output is changed by the reporting workflow. Changes
to production schedules, delivery rules or the recipient require owner authority.
