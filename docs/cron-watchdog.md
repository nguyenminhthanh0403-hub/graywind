# Cron watchdog — keeping the live trading cycle alive

## The failure this exists to catch

On **2026-08-31** the `live-trading.yml` cron (`*/15 13-20 * * 1-5`) stopped
firing. Not "failed" — *stopped*. The last genuine `schedule`-triggered run was
**2026-08-28** (run #97). Three market days of 15-minute ticks produced **zero
run objects**: nothing in the Actions tab, no failed runs, no alarm, no email.
The trading cycle simply stopped and `state/*.csv` quietly went stale while the
dashboard kept serving the last values it had.

That is the dangerous shape of this bug. The existing `pipeline-alarm` issue
machinery in `live-trading.yml` is excellent at reporting **a run that failed**
and completely blind to **a run that never happened**. Silence reads as health.

GitHub does not guarantee cron punctuality and does not retry dropped ticks.
The `schedule` event is explicitly best-effort, and `*/15` schedules landing on
`:00/:15/:30/:45` compete with every other repo on the platform doing the same.

## The three layers

Defence in depth, because each layer has a failure mode the next one covers.

| Layer | Lives in | Catches | Blind to |
|---|---|---|---|
| 1. Native cron | `live-trading.yml` | normal operation | its own silence |
| 2. Watchdog workflow | `cron-watchdog.yml` | a dropped tick | GitHub scheduler down repo-wide |
| 3. Out-of-band monitor | Claude routine (outside GitHub) | everything above being dead | nothing — it is the backstop |

**Layer 2 is not sufficient on its own, and it is important to be honest about
why.** `cron-watchdog.yml` is itself a `schedule` workflow. If GitHub's
scheduler drops triggers repo-wide, it drops the watchdog's too — correlated
failure, exactly when it is needed. It helps because the observed failure mode
looks *per-workflow* (a stale schedule registration on one file), and a
separate workflow file carries its own registration. Layer 3 is the only part
that runs on infrastructure GitHub does not control, and is therefore the only
part that actually closes the hole.

## Layer 2: `cron-watchdog.yml`

Runs at `4,14,24,34,44,54` past the hour — deliberately **off** the quarter
hour, where scheduler congestion and dropped ticks concentrate.

Each run:
1. Resolves the real `America/New_York` wall clock (GitHub cron is UTC-only and
   cannot track DST). Outside 9:30–16:00 ET on a weekday it exits immediately.
2. Lists recent `live-trading.yml` runs. If the most recent run of **any**
   event type is older than `STALE_MINUTES` (25), a tick was dropped.
3. Dispatches `live-trading.yml` to cover the gap.
4. Comments on a single rolling issue labelled `cron-watchdog`.

It tracks "last run of any type" and "last `schedule` run" **separately**, on
purpose. Healing the cycle must never disguise the diagnosis: *"cron is dead
but the watchdog is covering"* and *"cron is healthy"* have to stay
distinguishable, or the watchdog quietly becomes load-bearing forever.

### Required setup: the `WATCHDOG_PAT` secret

**The watchdog cannot heal anything until this exists.**

GitHub refuses to start a workflow run from an event raised with
`GITHUB_TOKEN`. It is their recursion guard, it applies to `workflow_dispatch`,
and — the part that matters — **it fails silently**: the API returns `204 No
Content` exactly as if it had worked, and no run is created. A watchdog built
on `GITHUB_TOKEN` would log "Dispatched." on every miss, forever, while doing
absolutely nothing. That is worse than no watchdog, because it manufactures
false confidence.

So the dispatch needs a PAT:

1. GitHub → Settings → Developer settings → **Fine-grained personal access
   tokens** → Generate new token.
2. Repository access: **only** `nguyenminhthanh0403-hub/graywind`.
3. Repository permissions: **Actions: Read and write**. Nothing else.
4. Set an expiry you will actually renew (90 days), and put a calendar reminder
   on it — a silently expired PAT restores the exact failure this was built to
   prevent.
5. Repo → Settings → Secrets and variables → Actions → New repository secret,
   named `WATCHDOG_PAT`.

Until then the watchdog still **detects** dropped ticks and fails loudly with
an explanation, rather than pretending to fix them.

## Layer 3: the out-of-band monitor

A Claude routine running on a schedule outside GitHub. Hourly during market
hours is enough — it is the backstop to the backstop, not the primary. It
checks the same staleness condition via the GitHub API and dispatches
`live-trading.yml` if both lower layers have gone quiet.

Because it does not run on GitHub, it survives the one failure mode layers 1
and 2 share.

## When the watchdog issue starts filling up

Self-healing is a mitigation, not a fix. If the `cron-watchdog` issue collects
comments day after day, the native cron is chronically broken and the response
is escalation, not more watchdog:

- Check <https://www.githubstatus.com/> for Actions degradation.
- Push any change to `live-trading.yml` — this re-registers the schedule and is
  what unstuck it on 2026-08-31.
- Confirm the repo is not a fork and Actions are enabled (Settings → Actions).
- Confirm the repo has not been idle for 60 days, which auto-disables scheduled
  workflows. (Not a risk while the cycle is committing state every 15 minutes,
  but it *is* how this comes back if the system is ever paused for a while.)
- Raise it with GitHub Support with the run history showing the gap.
