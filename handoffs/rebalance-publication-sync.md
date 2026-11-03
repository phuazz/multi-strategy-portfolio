# Rebalance publication sync

Working directory: `C:\dev\worktrees\multi-strategy-rebalance-sync`.
Branch: `codex/rebalance-publication-sync`, based on `fed82f0` from origin/main.
Context: Personal paper-model monitor. Model recommendation: GPT-6 Sol, high effort.
The active model/effort was not independently exposed by the host.

## Objective and status

Prepared a consumer-side fix for current daily prices attached to an old weekly book.
Implemented locally and approved by the owner for a local commit. Push, merge and
deployment remain unauthorised. The upstream engine and the existing dirty primary
monitor checkout have not been modified. The commit carrying this handoff records
the reviewed patch; use git log for its final identifier.

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
- Static page check: zero failures, existing warning for no dark-theme handling.
- Real viewport audit covered all nine tabs at 390/844/768/1280 px: returned client
  widths match, uncontained overflow is zero, minimum rendered font is 11 px, and
  there are no JavaScript page errors. Masthead reading measures were 42/84/76/89
  characters per line using a canvas alphabet sample. The three larger measures
  exceed the house 75-character masthead ceiling; this is pre-existing and remains
  a publication-check exception, not a claimed full MOBILE_CHECK pass.

Incident and preview dates above were checked with date libraries; obtain owner
confirmation before reusing them in an externally dated report.

## Artefacts and open decisions

Local generated preview: `.preview/index.html` and `.preview/data/` (do not stage).
Viewport evidence and health screenshot are in this chat's visualisation directory.
No change to the layout or design tokens was made.
The final rendered recheck also verifies the corrected Monday-fill captions and the
new health explanation. All 36 tab/viewport combinations retain zero uncontained
overflow, minimum 11 px text and no JavaScript page errors.

The owner approved the local commit. Push needs separate approval under the vault
AGENTS.md. A push to a
non-tracking branch also needs explicit approval: this worktree currently tracks
origin/main, while its local branch is codex/rebalance-publication-sync.

Before public deployment, resolve or explicitly review the existing masthead measure
exception and dark-theme warning, then rebuild from current upstream inputs. After
deployment, verify the live book date, source blob manifest, hourly skip/rebuild path,
capture result, sentinel result and latest Pages deployment. The GitHub cron remains
best-effort; hourly is a target cadence, not a guaranteed latency.

Do not touch the original checkout's uncommitted executed-allocation work, generated
data or unrelated untracked scripts. Do not rerun or retune the upstream strategy.

Next prompt: Review the publication-sync patch and its handoff in this worktree. Use
GPT-6 Sol high. Resolve the recorded publication-check exception, request the required
push approval, then verify the deployed engine-to-monitor lineage and book date.
