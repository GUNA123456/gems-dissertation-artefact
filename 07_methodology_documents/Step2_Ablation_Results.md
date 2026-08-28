# Step 2 — The labelling ablation (v2 → v2.1 labels, everything else frozen)

*Same night, same seed (42), same architecture, same temporal split, same
training recipe. The only change: the label definition. This is the ablation
Step 1 set up, and its principle was pre-registered: fix the design first,
then see what happens — even if what happens is unflattering.*

## Result: with honest labels, the model gets WORSE on this night

| Metric (test = last 15%) | v2 labels | v2.1 labels | Static (v2.1) |
|---|---|---|---|
| AUROC | 0.931 | **0.823** | 0.950 |
| PR-AUC | 0.576 | **0.175** | 0.827 |
| Cause HR@1 / HR@2 | 0.70 / 0.75 | **0.30 / 0.40** | — |
| Discipline (catalog-cpu) | correctly silent | **FALSE ALARM** | correctly silent |
| Alarm threshold tau (1 FA/h) | 0.805 | 0.39 (poorly calibrated) | — |

The static baseline is essentially unchanged (0.946→0.950) — robust to the
relabelling, still owning the latency-only test window.

## Why — three mechanisms, all diagnosable

1. **Part of v2's apparent skill was a label artifact.** Under v2, cart's
   redis-delay breach fell at 0.5s ≈ stage 3, so the model's input window
   contained two stages of visible precursor before each positive label —
   relatively easy. Under v2.1 cart breaches at 100ms ≈ stage 1, whose
   preceding window is pure quiet: the earliest labels are now genuinely
   unpredictable from the features, and the score drops accordingly. The
   0.931 was measuring, in part, how forgiving the old labels were.
2. **The new fault classes inject unlearnable positives into training.**
   Pod-kill labels (correctly present now) have no precursor by design;
   they are label noise from the optimizer's perspective and destabilise an
   already small-data training run (val AUROC 0.27 at epoch 0, rockier
   convergence, tau collapsing to 0.39, one false alarm on the discipline
   episode).
3. **The intended win — memory→OOM prediction — is untestable on this
   split and unlearned from this volume.** All four cart-mem episodes sit
   in train/val; none in test. The ep18 (validation) trajectory diagnostic:

   | during the memory ramp | v2 model | v2.1 model |
   |---|---|---|
   | cart probability as memory climbs 55→297Mi | **falls** 0.69 → 0.00 (anti-learned) | **flat** ~0.20 (pathology cured, precursor NOT learned) |

   Three independent OOM events in training were enough to stop the model
   anti-learning memory, and not enough to teach it. The claim "with
   availability labels the model gains OOM lead time" remains open — it
   needs OOM events in the test window and more of them in training, which
   is precisely Step 4 (additional nights).

## What this means

- The ablation did its job: it separated real skill from label-shape
  flattery, at the cost of the headline number. This is the "don't make the
  model look better" principle producing exactly the kind of result it
  exists to protect.
- **Step 4 is now a requirement, not an enhancement.** On one night, the
  question the project actually cares about (can graph models predict
  breaches thresholds cannot see?) is unanswerable: the favourable fault
  classes never reach the test split and are too rare in training.
- All Step-2 numbers are single-seed; the Step 6+7 grid (architectures x
  seeds) is where any of them become quotable with error bars.
- The live demo keeps the v2 checkpoint (gems_model_v2.pt): it is the
  better-calibrated model and matches the deployed dashboard; v2.1
  (gems_model_v2_1.pt) is the research artifact of this ablation.
