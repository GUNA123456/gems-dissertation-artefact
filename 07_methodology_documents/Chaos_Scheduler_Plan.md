# Randomised Chaos Scheduler — Build Plan

**Purpose.** Drive the v2 overnight collection run by injecting faults at
unpredictable times, in unpredictable order, and writing a ground-truth log
trustworthy enough to become training labels. This is the direct fix for Round
1's worst modelling failure: the fixed 28-minute cycle taught the GCN-LSTM the
schedule instead of the symptoms (probability saturated at 0.26 and the model
fired on the clock, not the cluster).

The scheduler's one hard invariant: **a window may only be labelled "fault" if
injection was *observed*, and only be labelled "quiet" if cleanup was
*confirmed*.** Anything unverifiable is discarded, never guessed.

---

## 1. What it runs

| # | Scenario | Mechanism | Shape it contributes |
|---|----------|-----------|----------------------|
| 1 | `catalog-cpu-ramp` | Workflow, 4 stages | CPU saturation, highest fan-in |
| 2 | `cart-mem-ramp` | Workflow, 4 stages | monotone memory climb → OOMKill |
| 3 | `redis-delay-ramp` | Workflow, 4 stages | latency that becomes errors (3-hop cascade) |
| 4 | `payment-delay-ramp` | Workflow, 4 stages | pure latency-SLO breach, zero errors |
| 5 | `pod-kill` (random target: payment / catalog / cart) | single PodChaos | sudden death — the fault class with no precursor, kept as contrast |

Sources: the four canonical manifests in
`GEMS_Model_Sandbox/chaos_manifests/v2_ramped/` (already staged on the VM at
`~/gems/chaos_manifests_v2/`). The scheduler patches stage deadlines at apply
time (string substitution on the YAML, logged); the canonical files stay
untouched.

**Stage duration for collection: 3 minutes** (not the demo-grade 5). Episode =
12 min of ramp. Rationale: 6 scrapes per stage at 30s is still solid, and the
9-minute precursor (stages 1–3) fully covers the model's 6-minute input window
(seq_len 12 × 30s). At 5-minute stages an overnight run yields only ~5 episodes
per scenario — too thin to survive a temporal split.

**Pod-kill is deliberately a minority class** and is flagged in the log so the
extraction can exclude it if it proves noisy: the killed pod's counters reset
and its scrape target vanishes for one to two intervals, which the pipeline must
handle by summing `max_over_time − min_over_time` per series (never
`increase()` — verified failure, see the v2_ramped README).

## 2. Randomisation design

- **Order — shuffled bag.** Each cycle is a random permutation of
  `[1, 2, 3, 4, 5]`; the bag is reshuffled when empty. Unpredictable ordering
  with guaranteed balance — no scenario can be starved or streaked by bad luck.
- **Quiet gaps — the actual schedule-killer.** After each episode, sleep
  `uniform(8, 22)` minutes, with a 10% chance of a long gap of
  `uniform(30, 45)` minutes so "it's been quiet a while" carries no information
  either. The 8-minute floor matters: it exceeds recovery time plus the
  6-minute input window, so clean negative windows with zero fault in their
  lookback are guaranteed to exist.
- **Seeded RNG.** The seed is chosen once, printed, and written into the run
  header — the whole night is reproducible in design even though the cluster
  isn't.
- **No intensity jitter in v1.** Stage intensities stay exactly as verified.
  Randomising *when* is the fix Round 1 needs; randomising *how hard* would
  blur the label definitions before we know the pipeline works.

**Arithmetic:** ~12 min episode + ~15 min mean gap ≈ 27 min per episode →
**~30 episodes in a 13.5 h run, ~6 per scenario.**

## 3. Episode lifecycle (state machine)

```
PRE-FLIGHT ─→ APPLY ─→ VERIFY-INJECTION ─→ OBSERVE-STAGES ─→ CLEANUP
                                                                │
     └──────────────── VERIFY-RECOVERY ←──────────────────────┘
                              │
                       LOG + QUIET GAP
```

1. **Pre-flight** (before *every* episode): all 12 pods ready, zero leftover
   chaos objects, traffic generator running. If unhealthy → do **not** inject;
   log a `preflight-blocked` event, wait 2 min, retry. Injecting into a sick
   cluster produces wrong labels for two episodes at once.
2. **Apply** the patched workflow (or PodChaos).
3. **Verify injection** — the non-negotiable step. Poll every 10 s, up to 90 s,
   for the stage's chaos object to report
   `.status.experiment.containerRecords[0].phase == "Injected"`. One smoke run
   had an accepted workflow that never created its NetworkChaos at all —
   latency flat for five minutes. Unverified ⇒ mark episode
   `failed-verification`, clean up, move on. Never abort the night.
4. **Observe stages**: poll every 15 s; record each observed stage transition
   `(stage, params, first_seen_ts, last_seen_ts, phase)`. The *observed*
   windows are the ground truth, not the intended ones.
5. **Cleanup**: delete the workflow, then **assert** zero
   workflow/networkchaos/stresschaos/podchaos objects remain.
6. **Verify recovery**: pods 12/12 ready, target's latency probe back under
   baseline × 3 (one curl to the affected service), for pod-kill the
   replacement pod Running. Record `recovery_confirmed_ts` — extraction uses
   it as the boundary where "quiet" may legally begin.
7. **Log** the episode record, sleep the random gap (gap start/end logged as an
   explicit `quiet` record — negatives are declared, never inferred).

## 4. Ground-truth log

JSONL at `~/gems/collection/<run_id>/chaos_ground_truth.jsonl`, one object per
event, UTC epoch + ISO timestamps (both — Prometheus alignment is epoch, humans
read ISO). Three record types:

```jsonc
{"type": "run_header", "run_id": "v2run-20260815", "seed": 1234,
 "stage_minutes": 3, "started": "...", "manifest_sha": {"catalog-cpu-ramp": "..."}}

{"type": "episode", "episode_id": 7, "scenario": "redis-delay-ramp",
 "target": "stylehub-redis", "status": "completed",   // or failed-verification
 "applied_ts": ..., "injection_confirmed_ts": ...,
 "stages": [{"stage": 1, "params": "delay 150ms", "start_ts": ..., "end_ts": ...}, ...],
 "cleanup_confirmed_ts": ..., "recovery_confirmed_ts": ..., "notes": ""}

{"type": "quiet", "start_ts": ..., "end_ts": ..., "planned_minutes": 14.2}
```

Plus a 60-second **heartbeat** record (`pods_ready`, `chaos_objects`) so the
extraction can audit cluster health at any timestamp and the morning-after
review can spot silent derailment.

## 5. Robustness (each maps to a real Round 1 / smoke-test failure)

- **Runs ON the VM** under `nohup`/`tmux`, kubectl local — a dropped SSH session
  must not kill the run (a dead port-forward destroyed a Round 1 lead-time test).
- **Wall-clock end time** (`--end-at 08:00`): last episode must *finish* before
  it; final act deletes all chaos objects and writes a `run_footer` even on
  crash (try/finally).
- **Every kubectl call wrapped**: timeout, one retry, failure → episode marked,
  never an unhandled exception. The night continues.
- **Python stdlib only** (subprocess + json + re). No pyyaml on the VM, no pip,
  no new dependencies to break at 3 a.m.
- **Pre-run checks**: Prometheus up and scraping 10 stylehub targets; disk
  headroom on the VM; traffic generator pod Running.

## 6. Acceptance before the overnight run

1. **Unit-ish dry run** (`--dry-run`): full night simulated in seconds — bag
   order, gaps, patched YAML — nothing applied. Sanity-check the schedule.
2. **90-minute dress rehearsal** (~3–4 episodes) with everything real. Pass =
   every episode `completed` or honestly `failed-verification`, zero leftover
   chaos objects, and a spot-check that Prometheus curves match the logged
   windows (e.g. cart p95 tracks the logged redis-delay stages).
3. Only then the 12–15 h run — started in tmux, VM left running overnight
   (deallocate *after* the run, not before).

## 7. Out of scope

Feature extraction, SLO-breach labelling, and the temporal split belong to the
v2 pipeline (next task). The scheduler's contract ends at a trustworthy
`chaos_ground_truth.jsonl`. One file, one job.

**Deliverable:** `COMP40321_Research_Methods/Scripts/chaos/chaos_scheduler.py`
(+ this plan), committed before the dress rehearsal so the run is reproducible
from git.

---

## 8. End-to-end workflow

The whole path from "plan approved" to "dataset labelling can start", with the
gate each phase must pass before the next may begin.

```
A. BUILD ──→ B. STAGE ──→ C. DRY RUN ──→ D. DRESS REHEARSAL ──→ E. OVERNIGHT RUN ──→ F. MORNING AFTER ──→ G. HANDOFF
   (laptop)     (VM)      (no cluster)      (90 min, real)         (12-15 h)           (audit + sync)      (extraction)
```

### A. Build (laptop)
Write `chaos_scheduler.py` to this plan. Commit **before** any real run, so the
run is reproducible from a git SHA recorded in the log header.
*Gate:* script committed; `python3 -m py_compile` clean.

### B. Stage (VM)
`scp` the script to `~/gems/`; confirm the four canonical manifests in
`~/gems/chaos_manifests_v2/` match the repo (the header logs each manifest's
SHA — a stale manifest on the VM must fail loudly here, not at 3 a.m.).
*Gate:* SHAs match; `kubectl get pods` from the VM works without sudo.

### C. Dry run (no cluster contact)
`python3 chaos_scheduler.py --dry-run --seed N --end-at +13.5h` prints the full
simulated night: bag order, per-episode timings, gaps, patched deadlines.
*Gate:* ~30 episodes, every scenario ≥5 times, no gap under 8 min, last episode
ends before the wall-clock cutoff.

### D. Dress rehearsal (90 min, everything real)
Same command minus `--dry-run`, with `--end-at +90m`, inside tmux. Covers 3–4
episodes.
*Gate (all four, no exceptions):*
1. every episode `completed` or honestly `failed-verification` — nothing hung;
2. zero leftover chaos objects and 12/12 pods ready at the end;
3. the log parses: header, ≥3 episodes, explicit quiet records, heartbeats,
   footer;
4. Prometheus spot-check — the target's latency/CPU/memory curve visibly
   matches the logged stage windows of at least one episode.
Fail any → fix, re-rehearse. The overnight run is never the first full test.

### E. Overnight run (12–15 h)
```
tmux new -s chaos
python3 ~/gems/chaos_scheduler.py --seed <N> --end-at 08:00 \
    --log-dir ~/gems/collection/v2run-<date>/
```
Detach. **Do not deallocate the VM** — it hosts the run. No SSH session needs to
survive; tmux owns the process. Optional morning-of check from the laptop:
`ssh … tail ~/gems/collection/v2run-<date>/chaos_ground_truth.jsonl`.

### F. Morning after (audit before anything is trusted)
1. `run_footer` present (no-crash proof); if absent, read the tail and triage.
2. Episode census: count per scenario and per status; a night with >10%
   `failed-verification` is investigated before it is used.
3. Cluster clean: zero chaos objects, 12/12 ready, restart counts explained by
   the log (cart-mem OOMKills should account for every increment).
4. Sync `~/gems/collection/v2run-<date>/` to the laptop; commit the log to git
   (it is small, and it *is* the labels).
5. Only now: `az vm deallocate -g gems-research-rg -n gems-vm` if pausing.

### G. Handoff to the v2 extraction pipeline
The pipeline consumes `chaos_ground_truth.jsonl` + Prometheus. Its contract with
this workflow: fault windows only from `episode` records with
`status: completed` (observed stage timestamps, not intended); negatives only
from inside explicit `quiet` records *after* `recovery_confirmed_ts`;
`failed-verification` episodes and everything around them excluded; pod-kill
episodes includable/excludable via their flag. Counter deltas via
`max_over_time − min_over_time`, never `increase()`.
