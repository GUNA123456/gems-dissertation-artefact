# Night A as a held-out night — v2 checkpoint, zero retraining

*2026-08-19. The deployed checkpoint (gems_model_v2.pt, trained only on the
2026-08-14 night) evaluated over the complete Night A dataset (2026-08-19,
19 completed episodes, v2.1-labelled). This is true out-of-sample: a fresh
night, five days of drift, scenarios at training magnitudes.*

## Per-episode (tau = 0.805)

| ep | scenario | maxP | model alarm | breached | static fired |
|---|---|---|---|---|---|
| 1 | redis | 0.88 | YES | YES | YES |
| 2 | payment | **0.80** | — | YES | YES |
| 4 | catalog | 0.65 | — | no | no |
| 5 | cart-mem | 0.62 | — | YES | no |
| 6 | payment | 0.74 | — | YES | YES |
| 7 | cart-mem | 0.62 | — | YES | no |
| 8 | cart-mem | 0.62 | — | YES | no |
| 9 | redis | 0.87 | YES | YES | YES |
| 10 | catalog | 0.65 | — | no | no |
| 11 | redis | 0.88 | YES | YES | YES |
| 12 | catalog | 0.65 | — | no | no |
| 13 | cart-mem | 0.61 | — | YES | no |
| 14 | payment | **0.80** | — | YES | YES |
| 15 | cart-mem | 0.62 | — | YES | no |
| 16 | cart-mem | **0.35** | — | YES | no |
| 17 | redis | 0.88 | YES | YES | YES |
| 18 | payment | **0.80** | — | YES | YES |
| 19 | cart-mem | 0.61 | — | YES | no |
| 20 | catalog | 0.65 | — | no | no |

Quiet periods (691 steps ≈ 5.8 h): resting median **0.614**, quiet max
**0.804**, false-alarm ticks **0**.

## Findings

1. **Cross-night generalisation on trained classes.** Redis 4/4 alarms at
   0.87–0.88 (training night: 0.88); catalog 4/4 correctly silent; 0 false
   alarms in 5.8 h of held-out quiet. The strongest validation evidence in
   the project so far, obtained without touching the model.
2. **The OOM baseline: 0/7.** Every cart-mem episode breached (v2.1 clauses:
   restart/err_in); the v2 model alarmed on none, sitting at resting — and
   ep16 *fell* to 0.35 mid-OOM, reproducing the Step 2 anti-learning
   signature out-of-sample. This is the "before" number the pooled v2.1
   retrain (expectation 1) must beat. Static also fired on 0/7 — the
   both-monitors-blind class, confirmed on a fresh night.
3. **The tau knife-edge, quantified.** Payment breached 4/4 with model peaks
   0.74/0.80/0.80/0.80 — all under tau by as little as 0.005, where the
   training night's payment episodes peaked 0.81–0.82. Five days of baseline
   drift (resting 0.65→0.61) ate the alarm margin. Signal present,
   operating point marginal.
4. **Pre-registered expectation 2 is in trouble — recorded, not retro-fitted.**
   Step4_Collection_Design.md §3.2 predicted pooled tau 0.70–0.75. Night A's
   quiet max of 0.804 says tau cannot drop meaningfully without buying false
   alarms: the 1-FA/h operating point may genuinely live near 0.80. If the
   pooled refit confirms that, the payment-class fix is better probability
   separation (Step 6 architecture/data axis), not a looser threshold.
   Expectation 5's drift risk is also now measured: resting median 0.614 vs
   0.65–0.69 across earlier nights.

## What this changes

- Ch5 gains a held-out-night validation section available immediately.
- The pooled retrain has a concrete scorecard: cart-mem test episodes to
  beat 0/7; redis/catalog behaviour to preserve; payment margin to widen.
- Tau discussion moves from "one night forces conservatism" to "the
  conservative point may be correct; separation, not threshold, is the
  lever" — pending the pooled refit as the decider.
