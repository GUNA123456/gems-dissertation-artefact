# Step 4 scorecard — pooled retrain (v2run-20260814 + Night B), seed 42

*Scored against Step4_Collection_Design.md §3, written before any Step-4 night
ran. Pod-kill excluded from all samples per the Step-2 pre-registration
(99 windows dropped, all from the 08-14 night).*

Pooled data: 1748 train / 321 val / 350 test windows across two nights,
per-night temporal splits. Checkpoint: `gems_model_v2_pooled.pt`.

| # | Pre-registered expectation | Verdict |
|---|---|---|
| 1 | OOM trajectory rises on held-out cart-mem | **PENDING — needs Night A.** Still zero cart-mem episodes in any test split (Night B's test window drew catalog-light + payment×2). This was always Night A's job (cart-mem ×2 weighting). |
| 2 | Tau drops to ~0.70–0.75 | **MATCHED (direction), 0.68 vs predicted band.** 0.805 → 0.68 on pooled quiet at 1 FA/h — slightly below the point estimate; ≈ +2 min of achievable lead at the 08-16 onset slope. |
| 3 | OOD inversion reproduces on heavies (v2 ckpt), then shrinks (pooled) | **MATCHED, both halves.** v2 checkpoint inverts on ep8 payment-heavy (0.64→0.58) and ep12 cart-mem-heavy (0.63→0.38); pooled checkpoint flat on all three probes including held-out ep19 (0.68→0.68). The collapse-under-extremes pathology is gone; no false confidence appeared in its place. |
| 4 | Static ~0.95 regardless; model PR-AUC must beat 0.175 or Step 6 activates | **REFUTED — in a direction that matters.** Static AUROC *fell* 0.950 → **0.813** (PR-AUC 0.825 → 0.654): once the test window contains non-latency breach classes (restart/5xx from the heavy compound faults), latency-only thresholds pay for their blindness. The model **overtook static on AUROC for the first time: 0.838 vs 0.813**. BUT model PR-AUC = 0.166 < 0.175 ⇒ **the pre-registered decision rule fires: more same-kind data is not the lever; Step 6 (architecture axis) is now the active question.** |
| 5 | Mixed per-night baselines cost a little AUROC | **NOT SEPARABLE.** Single-night 0.823 vs pooled 0.838 — but on different test sets; no observable cost, no clean comparison. |

## Additional observations (not pre-registered — flagged as such)

- **Discipline restored**: no false alarm on catalog-cpu (either variant) in
  either night's test window — the v2.1 single-night false alarm is gone.
- **Static goes late under honest labels**: −30s on held-out payment-heavy,
  −150s on Night B's standard payment; its only remaining lead is +30s on
  redis-delay. The baseline's Round-2 dominance was substantially a property
  of the latency-monoculture labels.
- **Model alarms never fire in test episodes** (tau 0.68 uncrossed): ranking
  improved, calibration did not. Consistent with PR-AUC stagnation — the
  architecture, not the data volume, is the suspect. Cause HR@2 improved
  (0.40 → 0.58 on 123 samples); HR@1 flat at 0.31.

## Night A update (2026-08-20) — three-night pooled retrain (`gems_model_pooled3.pt`)

Night A: 21/21 completed, cart-mem ×8 (one OOMKill each, verified in restart
accounting), audit clean. Pooled A + B + Night-0: 520 test windows.

| Metric | 2-night pooled | **3-night pooled** | static (3-night) |
|---|---|---|---|
| AUROC | 0.838 | **0.974** | 0.856 |
| PR-AUC | 0.166 | **0.840** | 0.707 |
| HR@1 / HR@2 | 0.31 / 0.58 | **0.81 / 0.94** (159 samples) | — |
| tau (1 FA/h) | 0.68 | 0.97 | — |

**Expectation 1: MATCHED.** Held-out cart-mem ep20 (Night A test split):
P(cart) rises 0.48 → 0.87 → 0.97 tracking the memory climb, **ALARM 3 min
before the OOM breach, clean decay after recovery — while the static monitor
never fires** (memory is invisible to latency thresholds). The regime the
project predicted — graph model wins where thresholds are structurally
blind — demonstrated on unseen data. The v2 model anti-learned this exact
scenario (0.69→0.00); v2.1 was flat (~0.20); pooled3 rises to alarm.

**Honest correction to the fired decision rule.** At two nights the
pre-registered rule ("PR-AUC < 0.175 ⇒ architecture is the lever") fired; the
third night refutes that conclusion — PR-AUC 0.166 → 0.840 with no
architecture change. Both evaluations stand on the record: the rule was
evaluated honestly each time, and the n=2 conclusion was simply premature.
Step 6's grid remains scheduled, now as multi-seed confirmation (error bars)
rather than rescue.

Remaining weak spot, stated plainly: payment-delay — late (−240s) on the
held-out heavy, no alarm on Night B's standard episode. The route-averaged
latency dilution diagnosed on 08-16 remains the suspected mechanism; per-route
latency stays on the future-work list.

## What this hands onward

- **Night A tonight** (cart-mem ×2, no pod-kill, standard magnitudes):
  expectation 1 becomes scoreable.
- **Step 6 grid is now the active experiment** per the fired decision rule:
  {1,2}-layer × 5 seeds on the pooled (A+B+original) dataset, per-seed tau.
- Chapter 5 gains its second ablation table: labels (Step 2) and now data
  volume (Step 4) — each isolating one variable, each with pre-registered
  predictions scored in public.
