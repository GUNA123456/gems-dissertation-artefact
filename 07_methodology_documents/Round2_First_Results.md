# Round 2 — First Results (one overnight run)

**Dataset:** `v2run-20260814` — 21/21 completed episodes, 1317 × 11 × 7,
temporal split 70/15/15 with boundary-crossing windows dropped (Round 1's
random split had 96.4% train/test window overlap; these numbers are the first
in the project that measure prediction rather than memorisation).

**Task:** for every service, predict an SLO breach within 6 minutes
(empirical breach: latency > max(5× quiet-median, 0.5 s) | any 5xx | any
inbound dependency error), plus name the injected root-cause service.

## Headline numbers (test = last ~1h40m of the night, unseen)

| Predictor | AUROC | PR-AUC |
|---|---|---|
| static threshold (tuned, per-node) | **0.946** | **0.825** |
| GCN-LSTM v2 | 0.931 | 0.576 |
| persistence (breaching now ⇒ soon) | 0.775 | 0.546 |

| Root-cause localisation (60 positive test samples) | |
|---|---|
| GCN-LSTM cause head HR@1 | **0.70** |
| GCN-LSTM cause head HR@2 | 0.75 |
| static threshold | cannot name a cause that never breaches (redis has no latency of its own) |

**Lead-time race** (both alarms tuned on validation to the same budget,
≤1 false alarm/hour; false alarm = alarming when no breach follows in 6 min):

| Test episode | First breach | GCN-LSTM | Static |
|---|---|---|---|
| ep19 catalog-cpu (no-breach contrast) | none | correctly silent | correctly silent |
| ep20 redis-delay | stage 3 | +0 s (at breach) | **+180 s early** |
| ep21 payment-delay | stage 3 | −390 s (late) | −210 s (late) |

## Honest reading

1. **The tuned static baseline wins breach prediction on this night — and that
   is a finding, not a failure.** Every breach-producing scenario in this run
   is latency-driven, and a victim's own latency is a smooth monotone
   precursor of its own latency breach: predicting latency-breach from
   latency is the threshold monitor's home turf. Round 1 never saw this
   because its baseline was degenerate (96.4% firing rate). The correct
   research claim after one night is therefore *not* "the GNN beats
   thresholds" — it is the two rows below.
2. **The model's edge is causal, not temporal (so far).** HR@1 = 0.70: given
   an unseen cascade, the cause head names the injected service first try 70%
   of the time — including redis, which exports no latency and which no
   per-node threshold can ever blame. Thresholds detect victims; the graph
   model names causes.
3. **The "tuned" baseline is only honest after a 9.4× correction.** The
   textbook recipe (quiet p99.5 × 1.2 per node) exceeded the 1 FA/hour budget
   by an order of magnitude on validation; the race above uses the corrected
   threshold. Any dissertation comparison must state its baseline's
   false-alarm budget or the lead-time numbers are meaningless.
4. **Both monitors passed the false-alarm discipline test** (catalog-cpu:
   heavy visible stress, zero SLO impact, zero alarms from either).
5. **Payment-delay is predicted late by both** — its only victim (checkout)
   breaches quickly once the 2 s timeout zone is approached, and nothing else
   degrades first. Cross-run, more payment episodes may help; per-route
   latency (checkout's /api/checkout specifically) is the cleaner fix — the
   route-averaged latency dilutes the signal.

## Limitations, stated plainly

One night = ~35 positive windows for training; the deep model is at the small
end of viable. All breach clauses this run reduced to latency (no OOM or
pod-kill landed in the test window). Results are from a single seed (42);
multi-seed variance is unmeasured. The SLO definition (5×/0.5s floor) was
fixed before training and not swept.

## What would move the needle next

More nights (the pipeline is now one command per night, ~30 episodes each);
per-route latency features; a dependency-latency histogram in obs.py (v2.1
candidate — delay faults are only visible caller-side); a CPU scenario that
actually breaches (CPU limit on catalog → throttling).
