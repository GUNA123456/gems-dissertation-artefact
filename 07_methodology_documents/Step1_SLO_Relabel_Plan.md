# Step 1 — Fix the SLO / failure labels (the relabelling ablation)

*First step of the final experiment roadmap. Principle in force: fix the
experimental design first, then see what happens — no change in this step is
chosen to make the model look better, and expected outcomes are written down
BEFORE running (§4), so results are judged against predictions, not narrated
after the fact.*

**Deadline pressure:** labels are recomputed from Prometheus's raw TSDB, whose
15-day retention deletes the overnight run's data around **Aug 29**. (The disk
snapshot preserves a copy, but re-extraction from the live TSDB is the easy
path.)

---

## 1. The two measured defects being fixed

**Defect A — the fixed 0.5s floor distorts who breaches when.** The current
latency clause is `latency > max(5 × quiet-median, 0.5s)`, and the floor
dominates for every service. Consequences, measured on 18 Aug: checkout
(baseline 76ms) reaches 0.5s at only ~6.6× its baseline and breached 64s
*before* the model's alarm, while cart (baseline 2.5ms) must degrade ~200×
before the same definition notices. Services are graded on wildly different
curves, purely as a function of their normal speed.

**Defect B — the labels are blind to availability.** Four OOM episodes
(perfect 9-minute memory precursors) produced ~5 positive samples, because the
kill's user-visible harm lands between 30s scrapes. The model consequently
learned nothing from memory signals — its probability *fell* during a memory
ramp. One pod-kill episode (ep8, payment) produced zero labels because no
order happened to arrive during its seconds-long outage: a service was DOWN
and the labels called it healthy.

## 2. The new label definition (v2.1)

A node-step is a breach if ANY clause fires:

| # | Clause | Definition | Replaces |
|---|--------|------------|----------|
| 1 | latency | `latency > max(10 × quiet-median, 100ms)` | `max(5 × median, 0.5s)` |
| 2 | server errors | any 5xx in the step | unchanged |
| 3 | dependency errors | any inbound dependency error | unchanged |
| 4 | **availability** *(new)* | pod restart observed: `pod_age[t] < pod_age[t-1]` (the age-reset marker already in feature 2); label the reset step AND the step before it (the kill itself) | — |

Rationale for clause 1's constants: 10× one's own baseline is unambiguous
degradation on any service; the 100ms floor exists because sub-100ms latency
is not user-perceptible harm regardless of ratio (protects the 1–3ms services
from noise labels). Every service now breaches at the same *relative*
distortion, subject to the same *absolute* meaningfulness bar.

Anticipated consequence, stated openly: cart's redis-delay breach moves EARLIER
(150ms stage-1 latency already exceeds max(25ms, 100ms)), shrinking cart's own
precursor window — while checkout's moves LATER (760ms vs 500ms), widening its.
The lead-time question shifts toward its true form: predicting the DOWNSTREAM
victims from the first victim's early degradation. That is the cascade
formulation, and it is the honest shape of the problem.

## 3. Also in this change: stop future re-labelling from needing Prometheus

`extract_v2.py` will persist into the dataset: the raw `fivexx` array, the
per-node quiet-median baselines, and a per-clause breach breakdown
(`breach_clauses[t][n]` bitmask). All future label experiments then run
offline from the dataset file, immune to TSDB retention.

## 4. Pre-registered expectations (written before running)

1. **cart-mem**: availability clause converts each OOM into positives; with
   memory's 9-min precursor now labelled, Step-2 retraining should give the
   model lead time here — and the latency-only static monitor stays blind
   until the kill. *This is the scenario where the headline may flip.*
2. **pod-kill**: becomes labelled (including silent ep8, via age-reset), but
   remains unpredictable — no precursor exists. The contrast class stays a
   contrast class; if the model "predicts" kills, something is wrong.
3. **redis-delay**: cart labels earlier (less own-lead), checkout/frontend
   later (more precursor room). Static stays fast on cart.
4. **payment-delay**: checkout's threshold rises 0.5→0.76s; breach arrives
   later in stage 4 with more precursor before it.
5. **catalog-cpu**: still zero breaches (nothing user-facing degrades) — the
   discipline test must survive relabelling.
6. **quiet windows**: near-zero breaches must hold (< ~10 node-steps across
   776 quiet steps); if relative thresholds ignite quiet noise, the
   multiplier is wrong, not the night.

## 5. Execution + gates

1. Edit `extract_v2.py` (clauses, persisted raws, clause breakdown).
2. VM up → re-extract → `telemetry_dataset_v2_1.json` (v2 dataset kept —
   the ablation needs both).
3. **Gates**: expectations 5 and 6 must PASS (discipline + quiet-noise);
   per-scenario per-clause table printed and eyeballed against §4;
   grid/features byte-identical to v2 (only labels may differ).
4. Commit dataset + code + gate output. Step 2 (retrain on v2.1, same seed,
   same everything) is a separate commit so the ablation stays clean.
