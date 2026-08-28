# Step 4 — Designed collection nights (pre-registered)

*Written 2026-08-19, before any Step 4 night has run. The Step 1 discipline
applies: expectations are on the record first, so the results mean something
whichever way they land. Do not edit §3 after the first night starts.*

## 1. Why these nights exist (from the Step 2/3 evidence)

1. **The OOM question is untestable today.** All four cart-mem episodes sit in
   train/val; zero in test. Three OOM events in training were enough to stop
   the v2.1 model anti-learning memory, not enough to teach it (ep18: flat
   ~0.20 during a 55→297Mi climb).
2. **Tau is data-starved.** 0.805 comes from ONE night's quiet periods at the
   ≤1 false-alarm/hour point, and costs ~90s of achievable lead on redis
   ramps (probability crosses 0.75 four minutes before cart's actual breach).
3. **Out-of-distribution inputs invert the model.** 2026-08-17 22:23: static
   6352× threshold, probability *fell* 0.68→0.18. All training ramps peak
   ≤~460×. The failure region is unexplored, not unexplorable.
4. **Diversity, not volume, is the constraint.** Nights that repeat the same
   five scenarios at the same magnitudes add correlated samples.

## 2. Night design

Common rules: scheduler (`chaos_scheduler.py`) with verified-injection ground
truth; one fault at a time, verified-clean between; audit must pass before a
night's data is used; every night inside the 21d Prometheus retention window
(all raw TSDB pools with 2026-08-14 until ~2026-09-04 — run the nights well
before that). **Pod-kill is excluded from all training nights** (pre-registered
in Step 2 as precursor-free label noise that destabilised training; it remains
a demo-only honest-limit scenario).

| Night | Composition | Purpose |
|---|---|---|
| **A** | The four ramps at v2run magnitudes, bag re-weighted: cart-mem ×2 (≈8 episodes), catalog-cpu / redis-delay / payment-delay ≈4 each | Comparability anchor (same magnitudes as 2026-08-14) + enough cart-mem that ≥2 land in the temporal test split |
| **B** | Magnitude ladder, same scenarios: light variants (~0.5× stage intensities, e.g. redis 75/200/450/800ms), standard (1×), heavy (~2×, redis up to 3200ms; cart-mem stress sizes ±50%) | Coverage of the OOD region under controlled conditions; teaches the normalizer the extremes |
| **C** | Composition fixed only after A+B are audited (declared adaptive now, so it is not a stealth do-over): fill whatever the A+B episode×scenario×magnitude matrix left thinnest | Close the gaps, not re-roll the dice |

Manifest work before Night B: author the light/heavy variants of the four
ramped Workflows in `chaos_manifests_v2/` (same 4-stage Serial shape, scaled
stage parameters). Night A needs only a bag-weight change.

## 3. Pre-registered expectations — written before any night runs

1. **OOM testability (the point of Night A).** Pooled v2.1 retrain with
   cart-mem in the test split: expect the memory-ramp probability trajectory
   on held-out cart-mem episodes to RISE during the ramp (vs flat ~0.20 now).
   If it stays flat with ~12 training OOM events, that is evidence the
   architecture (7-feature node vector, 6-min window) cannot express the
   precursor — a finding, reported as such, not a failure to hide.
2. **Tau drops.** Refit on pooled quiet periods at 1 FA/h: expect tau
   materially below 0.805 (point estimate: 0.70–0.75, from the resting-band
   spread 0.62–0.69 across observed nights). Conversion: the 08-16 onset
   slope is ~0.027/tick near tau, so each 0.01 of tau ≈ ~11s of lead.
3. **OOD inversion reproduces, then shrinks.** The CURRENT v2 checkpoint on
   Night B heavy episodes: expect probability inversion (falls during fault)
   on the largest magnitudes — the controlled reproduction of the 08-17
   pathology. After pooled retrain including Night B: expect inversion gone
   or reduced on a held-out heavy episode.
4. **Static baseline barely moves.** AUROC ~0.95 under v2.1 labels
   regardless of pooling — thresholds don't learn. If the MODEL's pooled
   v2.1 PR-AUC does not improve on 0.175, more same-kind data is the wrong
   lever and Step 6's architecture axis becomes the active question.
5. **Honest risk.** Baselines drift between nights (resting 0.62 vs 0.69
   across three observed nights). Extraction computes quiet-medians per run,
   so labels stay per-night-honest, but pooled training sees mixed baselines.
   Expect this to *cost* a little AUROC before it buys robustness.

## 4. Execution checklist (per night)

```bash
# on the VM, evening:
kubectl get pods -n default            # 12/12 Running
kubectl get workflow,networkchaos,stresschaos,podchaos -n default   # empty
tmux new -s chaos "cd ~/gems && ./venv/bin/python -u chaos_scheduler.py <night-args> \
  2>&1 | tee -a collection/night<X>.out"
# morning after:
./venv/bin/python audit_run.py <run-dir>            # must pass
./venv/bin/python extract_v2.py <run-args>          # per-night dataset
# laptop: commit dataset + ground truth + audit output before ANY training
```

Then: pooled extraction, Step 2-style retrain (same seed 42 first, grid later),
and the §3 scorecard — each expectation marked MATCHED / REFUTED with numbers.

## 5. What Step 4 hands to Steps 5–7

- Step 5 (unseen-service test): enough episodes per service to hold one
  service's episodes out entirely.
- Step 6 (grid): the pooled dataset the {1,2}-layer × 5-seed grid trains on,
  plus per-seed tau refits (expectation 2 becomes a distribution).
- Step 7 (mean±var): the §3 scorecard is the skeleton of Chapter 5's
  results-with-error-bars section.
