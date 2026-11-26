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

If a scheduled email check finds that the engine has published new inputs, it
requests one source-change probe when the monitor is idle. The monitor verifies
the inputs again before rebuilding. Completion triggers a new delivery check.
Completion-triggered checks cannot start further probes.

An isolated historical valuation gap in a dashboard-only comparator appears as a
footnote in the email and PDF. This exception requires a successful benchmark
fetch, current comparator marks and confirmation from the monitor that every
warning has that cause. Required benchmark gaps, stale model inputs, inconsistent
state, reconciliation failures and unclassified warnings still hold delivery.

A missing recent Singapore comparator close is recoverable when Yahoo and SGX
identify the same completed session and SGD price and the prior adjusted basis
matches. The monitor archives the observation in `docs/data/sgx-observations/`
and checks it on reuse. The existing hourly source probe also retries missing
benchmark tails when the published engine NAV is current, at least two hours
after the prior build and within two UTC dates of the NAV. Each such retry
makes one benchmark fetch. An unresolved historical gap alone has no retry.

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

The HTML and plain-text email show 1D, trailing 1W and YTD returns for the
model and S&P 500 total-return proxy, with arithmetic excess on matched dates.
The body ranks up to five priced ETFs by absolute daily contribution. Each row
pairs the ETF’s matched USD return with its beginning-of-session NAV weight
and signed portfolio impact in basis points. The summary compares their combined
impact with the full model return and flags attribution
exceptions. Equal magnitudes are ordered by ticker. It includes one sourced development when
the validated briefing identifies a current holding. Selection uses the greatest
combined current weight of matched holdings, with briefing order breaking ties.

The email uses a fluid, centred layout up to 800 pixels wide. The attached A4
PDF contains the full performance, risk, attribution and market review.

Colour and data bars support scanning: green/red for signed returns and contributions,
blue for NAV weights and teal for estimated risk shares. Absolute-return bars use one
common scale across the performance table, with equal rendered track lengths; signs
remain explicit. Weight and risk tracks each span 0-100%, with their distinct
denominators stated. Missing risk shares have no bar. The drawdown track ends at the
historical maximum, labelled as context rather than a risk limit. A delayed-data notice
uses amber. Colours do not substitute for numbers or state labels.

A separate 1D/1M return-context panel shows actual return and estimated one-standard-
deviation moves on a common -2.5 to +2.5 risk-unit scale, with +/-1 and +/-2 markers.
Portfolio return uses model volatility; benchmark excess uses tracking error.
The estimate uses 252 prior matched single-session returns, excludes calendar gaps
and does not use the reported window. Training dates and gap counts travel with
the figures. This is descriptive risk context, not a z-score or probability band.
See [RETURN_CONTEXT.md](RETURN_CONTEXT.md). Attribution bars remain in basis points.

ETF-level risk context uses each instrument's full-window USD adjusted return
and own prior volatility, independently of portfolio weights. The PDF includes
the complete ETF comparison. Exited positions retain full-window price context.
Income and carry are included, so the
ratio is not statistical surprise. Per-ETF price and estimation details are
available on the dashboard; unavailable estimates are not shown as zero.

PDF page 2 is a compact attribution summary: up to five positive and five negative
ETF contributors for each horizon, all strategy contributions and compact
reconciliation footnotes. Non-zero contributions are selected separately for each
sign; no zero-impact names are added to fill a quota. Material unexplained
residuals remain explicitly flagged. Positioning is condensed to the model state and largest current weights.
Portfolio risk context follows on page 3; the complete ETF table and own-volatility
gauges remain in the appendix. A rendered-content guard requires the selected ETF
leaders and all strategies to fit page 2.

The full private portfolio-manager commentary appears on PDF page 1.
The existing X briefing producer attaches a small structured JSON
companion to its existing private email. The portfolio job reads the newest three
matching INBOX messages through Gmail IMAP, using read-only selection and
BODY.PEEK so it does not mark mail as read. It verifies the exact sender, subject
prefix, Gmail DMARC result, attachment name, schema, timestamps and NYSE session.
Only a companion matching the official NAV date can appear. Text is escaped;
source links are HTTPS. Reported claims, interpretations and qualitative relevance
remain distinct from the official portfolio contribution calculations.

Configure private secrets `MORNING_BRIEF_SENDER` and `MORNING_BRIEF_SUBJECT`.
The reader reuses existing `GMAIL_USER` / `GMAIL_APP_PASSWORD`; no new token or
storage service is required. Missing, stale, malformed or wrong-date context is
nonfatal: the quantitative report proceeds with context marked unavailable.
If a valid companion causes a rendering/content-guard failure, the job retries
once without commentary, reruns every report guard, and records the omission.
The existing producer runs Monday-Saturday around 07:00 Singapore time, covering
the Saturday review of the Friday US close. No prior news is recycled.
The 09:00 target, 11:00 delay notice and durable send ledger remain unchanged.

Contract and producer rules: [X_BRIEFING_CONTRACT.md](X_BRIEFING_CONTRACT.md).
Preview with `python scripts/deliver_morning.py --preview --market-context
data/x-briefing/inbox/portfolio-market-context-YYYY-MM-DD.json`.
Keep all actual companions and previews in ignored `data/`. Never commit them,
add them to the public dataset/dashboard, upload them as Actions artifacts or
print them in runner logs. The workflow uploads only content-free `check.json`.
Use the manual workflow input `context_check_only` for a read-only transport
check with no email or ledger mutation. It reports a status code only.
Content guards check all commentary and sources in the PDF and the selected
development, figures and sources in both email formats.
A producer schema pass establishes structure and timing, not the truth
of market claims; source confidence remains visible.

Holding contributions use historical published model holdings, effective after
their fill-date close. Daily USD contributions are linked using prior official NAV
divided by period-start NAV. Sold positions remain included. ETF marks are gross
of trading costs; strategies use published net sleeve returns through the engine
anchor and fixed-book marks thereafter. Separate residuals reconcile each level
to the official model return. See [ATTRIBUTION.md](ATTRIBUTION.md).
The primary comparator is labelled S&P 500 TR proxy (SPY adjusted close), with an
explicit arithmetic excess-return column in percentage points for every period.
This is a fund total-return proxy, not literal SPX price return or exact index return.
The global 60/40 comparator remains in the PDF. Its attribution summary shows
up to five positive and five negative holdings for both 1D and 1M. A strategy table compares the
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
