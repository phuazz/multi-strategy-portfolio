# Rebalance publication sync

Working directory: `C:\dev\worktrees\multi-strategy-rebalance-sync`.
Branch: `codex/rebalance-publication-sync`, based on `fed82f0` from origin/main.
Context: Personal paper-model monitor. Model recommendation: GPT-6 Sol, high effort.
The active model/effort was not independently exposed by the host.

## Objective and status

Prepared a consumer-side fix for current daily prices attached to an old weekly book.
Implemented in local commit `a90024a`. The owner subsequently authorised push,
deployment and live verification. Deployment preparation closes the publication
checks recorded below. The upstream engine and the existing dirty primary monitor
checkout have not been modified. Use git log for the deployment-preparation commit.

## Changes

- Existing Daily monitor refresh workflow gains hourly minute-17 source probes. Full
  nightly and Sunday builds remain. Unchanged consumed blobs skip build/install/commit.
- Source reads are pinned to a resolved engine commit, with Git blob hash verification
  and a nine-file manifest. No moving-ref reads followed by an after-the-fact SHA stamp.
- Executed-book coverage is checked separately from price freshness. The minimum of the
  live anchor and strategy common_end must cover the latest completed Monday NYSE core
  fill, with genuine exchange holidays rolled forward. This is a publication-coverage
  check; it does not generate trades or require a valid HOLD to change its selection.
- The deployed sentinel rechecks book coverage and compares the live dataset manifest
  with current engine blobs. A changed file's own publication commit anchors the
  120-minute sync budget; unrelated engine commits cannot extend it.
- Push rejection is no longer swallowed. Three bounded attempts, then a failing job.
- Friday-fill captions and registry metadata now describe the current Monday schedule.

No cross-repository write token or additional secret is needed. Existing fleet-watch
rows already cover this workflow: multi-strategy monitor (output) and multi-strategy
build (run). Existing email alert channels are retained; no messages were sent in this
session and their secret configuration was not changed.

## Validation

- Full suite: 158 passed, including 31 new publication tests and updated capture tests.
  Use a fresh writable `--basetemp`; the sandbox default temp directory cannot create
  pytest fixtures. This is an environment constraint, not a product failure.
- Live immutable engine bundle `9127c717faa68ee443a71354b55059b40852e300`:
  all nine consumed blobs verified. Local full benchmark-enabled preview reconciles to
  the engine, shows book/rebalance coverage `2026-11-02`, and health OK.
- A later live engine HEAD `34e921af4603a28b363ac84827e023ac70935d4d` changed none
  of the consumed blobs; the new probe correctly reported no rebuild required.
- Calendar regressions include a month boundary, year boundary, pre/post-close checks,
  a Monday holiday rolled forward, and standard/daylight saving close times.
- Workflow YAML parses and git diff --check passes. No GitHub workflow was dispatched.
- Static page check: zero failures and zero warnings after declaring the existing
  light-only design. The rendered masthead measure and 44 px control targets are
  corrected in the deployment-preparation commit.
- Real viewport audit covered all nine tabs at 390/844/768/1280 px: returned client
  widths match, uncontained overflow is zero, minimum rendered font is 11 px, and
  there are no JavaScript page errors. Final masthead reading measures are
  42/74/74/74 characters per line using a canvas alphabet sample. Visible filter
  controls meet 44 px targets; the checkbox uses its clickable label. Wide tables'
  last columns remain reachable inside their own scrollers. Pie margins reserve
  space for outside labels, correcting the clipped bottom label found in the
  rendered review.

Incident and preview dates above were checked with date libraries; obtain owner
confirmation before reusing them in an externally dated report.

## Artefacts and open decisions

Local generated preview: `.preview/index.html` and `.preview/data/` (do not stage).
Viewport evidence and health screenshot are in this chat's visualisation directory.
Design tokens are unchanged. Publication preparation narrows the masthead prose,
enlarges filter targets and reserves space for pie labels.
The final rendered recheck also verifies the corrected Monday-fill captions and the
new health explanation. All 36 tab/viewport combinations retain zero uncontained
overflow, minimum 11 px text and no JavaScript page errors.

The owner approved the local commit, then explicitly authorised push and deployment.
This worktree tracks origin/main; deployment uses an ordinary fast-forward push to
that tracking branch, without force.

After deployment, verify the live book date, source blob manifest, hourly skip/rebuild path,
capture result, sentinel result and latest Pages deployment. The GitHub cron remains
best-effort; hourly is a target cadence, not a guaranteed latency.

Do not touch the original checkout's uncommitted executed-allocation work, generated
data or unrelated untracked scripts. Do not rerun or retune the upstream strategy.

Next prompt: Use GPT-6 Sol high. Check the deployment verification evidence in this
chat's local .preview directory, then verify the deployed engine-to-monitor lineage,
book date and freshness sentinel if further changes are required. Do not republish
without repeating the publication checks.
