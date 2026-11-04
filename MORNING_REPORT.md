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
a compact risk table, positioning and historical 1D/1M attribution. The A4 PDF
adds full risk ratios, benchmark-relative statistics, every historical ETF row,
valuation windows, sources and methodology (normally four pages; guarded at three
to six). Both derive from the same report object. Source and dashboard links are
clickable. The plain-text alternative remains available for email clients.

Colour and data bars support scanning: green/red for signed returns and contributions,
blue for NAV weights and teal for estimated risk shares. Absolute-return bars use one
common scale across the performance table, with equal rendered track lengths; signs
remain explicit. Weight and risk tracks each span 0-100%, with their distinct
denominators stated. Missing risk shares have no bar. The drawdown track ends at the
historical maximum, labelled as context rather than a risk limit. A delayed-data notice
uses amber. Colours do not substitute for numbers or state labels.

Holding contributions use historical published model holdings, effective after
their fill-date close. Daily USD contributions are linked using prior official NAV
divided by period-start NAV. Sold positions remain included. ETF marks are gross
of trading costs; strategies use published net sleeve returns through the engine
anchor and fixed-book marks thereafter. Separate residuals reconcile each level
to the official model return. See [ATTRIBUTION.md](ATTRIBUTION.md).
The primary comparator is labelled S&P 500 TR proxy (SPY adjusted close), with an
explicit arithmetic excess-return column in percentage points for every period.
This is a fund total-return proxy, not literal SPX price return or exact index return.
The global 60/40 comparator remains in the PDF. Positive and negative contribution
panels show the largest three verified holdings in each direction for both 1D and
1M on a common basis-point scale within each period. A strategy table compares the
two horizons. The PDF includes all ETF names and owning strategies, monthly average
weights and both contributions. Missing open-session prices produce a dash, never
a fabricated zero; known partial marks remain in the reconciliation bridge. Coverage
is disclosed as the share of held weight-days. Rows plus residual must reconcile
to model return; a mismatch blocks rendering. Absolute residuals of at least 5 bp
are flagged for review symmetrically. These are absolute-return contributions,
not attribution of benchmark excess; no cause is assigned to the residual.
Backtested history, engine-labelled out-of-sample performance and a live extension
are kept distinct. Risk statistics use the published common-date panel and its
calendar gaps are disclosed.

Before each send, the workflow runs the delivery tests, the vendored vault static
HTML checker, a real headless Chromium check at 390/844/768/1280 pixels, and PDF
page-count, A4, text-bounds, hyperlink and rendered-attribution content guards.
A layout or content failure blocks sending.
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
