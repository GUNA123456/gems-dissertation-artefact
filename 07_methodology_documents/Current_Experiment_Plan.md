# Current Experiment Plan — Steps 3–7 (v2.1 era)

*Replaces the pre-Azure-rebuild plan (Minikube, old IP) that previously lived
here. Written 2026-08-19. Steps 1–2 are complete; this defines and sequences
the rest of the roadmap agreed after Round 2: re-eval → more nights →
unseen-service test → seed grid → mean±var. The step numbers below are the
same ones `Step2_Ablation_Results.md` forward-references.*

**Standing principle (pre-registration):** for every step, write down the
expected outcome before running it. The Step 1→2 ablation produced an
unflattering number and was more valuable for it; that discipline continues.

---

## Where the project stands (2026-08-19)

Done and committed:

- **Step 1** — v2.1 SLO relabel, all pre-registered expectations matched.
- **Step 2** — retrain ablation: honest labels made the headline worse
  (AUROC 0.931→0.823, PR-AUC 0.576→0.175); three mechanisms diagnosed;
  demo stays on the v2 checkpoint.
- Prometheus retention raised 5d→21d (2026-08-18) — the 2026-08-14 training
  night's raw TSDB data is now safe until ~2026-09-04, and new nights
  collected within the window can be pooled with it. NodePort 30900 pinned in
  `Infra/prometheus-nodeport.yaml` (a Service Helm does not own).
- All VM-only artifacts rescued into `Collection_Runs/`.

Corrected findings from the 2026-08-18/19 session (these supersede earlier
statements in conversation and tutorial):

1. **Breach ≠ static firing.** Ground truth is only the SLO clause set
   (`latency > max(mult × quiet_median, floor) | 5xx | err_in`). The static
   monitor is a rival predictor scored against that same target, never the
   yardstick. Its thresholds sit 13.5× below cart's breach point and 2.4×
   *above* checkout's.
2. **The model has real positive lead time vs actual breaches** (08-16 run):
   cart +2m30s, frontend +2m00s, checkout −30s. Static fires earlier still,
   but at latencies far inside the SLO.
3. **Tau is the bottleneck, not the signal.** Probability leaves resting on
   the same tick static fires; tau=0.805 (forced by one night's quiet data)
   costs ~90s of achievable lead.
4. **Cause ranking is confounded at rest** (redis top at 0.59–0.61 in quiet);
   only the 0.60→0.95 trajectory is evidence.
5. **Out-of-distribution inputs invert the model** (2026-08-17 22:23 event:
   static 6352×, probability *fell* 0.68→0.18).
6. **Static also structurally misses memory breaches** — cart-mem is a
   both-monitors-blind class where only the model has the input channel
   (`mem_mib`) to ever learn it. This is the architecture argument.

---

## Step 3 — Re-evaluation with honest measures *(active now)*

Purpose: fix every place where the evaluation or its presentation conflates
"static fired" with "breached", and close the two analysis questions that
block claims.

- [ ] **3a. Evidence tooling.** `Scripts/telemetry/demo_evidence.py`: given a
  tick log + time window, compute per-service *actual* SLO breach times from
  Prometheus (same clause set as extraction, via
  `features_from_prometheus`), join with first static fire / first model
  alarm, and print the demo evidence table with signed leads. No number in a
  meeting is ever read off a Grafana panel again.
- [ ] **3b. Window-drain ablation.** The post-fault alarm tail (~3.5 min)
  cannot be claimed while `seq_len` (6 min) still contains the fault.
  Counterfactual: re-run inference on recovery ticks with fault-period steps
  replaced by pre-fault quiet features. *Pre-registered expectation: the tail
  is drain — counterfactual probability collapses to resting. If it does
  not, that is a finding (the model reads lingering state, e.g. pod_age).*
- [ ] **3c. Monitor/dashboard honesty.** `live_monitor_v2.py` pushes
  `gems_prediction_as_of_seconds` (+ `gems_tau`) so Grafana can display
  prediction age instead of hiding Pushgateway restamping; dashboard reads
  tau from the checkpoint instead of hard-coding 0.805; probability and
  latency panels stacked at identical x/width so their time axes align.
- [ ] **3d. Demo tutorial updated** with the corrected lead-time framing
  (claims vs SLO and vs static kept verbally separate) and the replay track
  (test-split episodes 19/20/21 — verified working 2026-08-19) as the
  primary evidence path, live ramp as theatre.

Gate: evidence table reproduces the 08-16 numbers from raw sources; drain
ablation answered either way; replay smoke test still passes after monitor
edits (inference path untouched — additive push only).

## Step 4 — 2–3 designed collection nights

Not "more of the same": the binding constraint is episode diversity.
Design doc: `Step4_Collection_Design.md` (night composition, magnitudes,
pre-registered expectations — written before the first night runs).

- Cart-mem gets enough episodes that ≥2 land in the temporal test split —
  the specific gap that makes the OOM claim untestable today.
- Fault magnitudes varied deliberately, including the extreme region that
  currently inverts the model (finding 5). Repetition at known magnitudes
  does not fix OOD.
- Pod-kill excluded from training nights (pre-registered as unlearnable
  label noise that destabilised v2.1) — kept only as an honest-limit demo.
- All nights within the 21d retention window so raw TSDB pools with
  2026-08-14; re-extraction possible for all of them at once.

Gate: scheduler audit passes per night; pooled extraction reproduces each
night's committed dataset byte-identically.

## Step 5 — Unseen-service test

Generalisation: can the model predict breaches for a service whose episodes
it never saw in training (hold out one target service's episodes, not one
time window)? This is the claim that the graph structure — not per-service
memorisation — carries the prediction. Design after Step 4 data exists;
single seed is fine here, the grid comes next.

## Step 6 — Architecture × seed grid

{1,2}-GCN-layer × 5 seeds on the pooled dataset, plus the no-graph baseline
(same LSTM, adjacency = identity) that Chapter 5 needs to defend the GNN at
all. Also re-fit tau per seed on pooled quiet data — pre-registered
expectation: tau drops materially below 0.805, converting directly into
lead time (finding 3).

## Step 7 — Mean ± variance, and the write-up

Every quotable number becomes mean±sd over seeds. Chapter 5 rewritten around
the two-question framing (useful warning vs SLO: yes; beats tuned static on
latency ramps: no — and where the structural edge actually is), with the
three disclosed confounds (findings 4, 5, and 3b's answer) as stated
limitations. This is where "writing woven in after step 3" lands.

---

## Standing constraints

- Demo checkpoint stays `gems_model_v2.pt` (calibrated, matches dashboard)
  until the Step 6 grid produces a successor with error bars.
- Trainer runs under `GEMS_Model_Sandbox/venv` on the laptop; VM venv is
  CPU-torch for inference only.
- One fault at a time, verified-clean between faults — unchanged.
- After any session: push to `github` and `azure` remotes.
