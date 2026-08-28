# Live v2 Inference Monitor — Build Plan

**Purpose.** Upgrade the supervisor demonstration from "here is a results
table" to "watch the model call the cascade live": a terminal monitor that,
every 30 s, reads the cluster's last 6 minutes from Prometheus, runs the
trained v2 checkpoint, and prints per-service breach probability plus the
ranked root-cause — side by side with the honestly-tuned static monitor, so
the demo shows the true division of labour (static alarms early on latency;
the model names the cause).

**Deliverable.** `Scripts/telemetry/live_monitor_v2.py` + a small refactor of
`extract_v2.py`, committed before any demo.

---

## 1. The one invariant that decides success: train/serve parity

Round 1's live failure was partly a train/live mismatch (normalization applied
differently at inference). The v2 monitor therefore must not reimplement
feature building — it must **import** it.

* Refactor `extract_v2.py`: pull the Prometheus queries + feature assembly
  (7 channels, client-side counter diffs, pod→node mapping) into a function
  `features_from_prometheus(prom_url, t_start, t_end) -> (features, fivexx)`
  usable on any time window. The extraction script becomes a thin caller.
* **Parity gate for the refactor:** re-run extraction on the overnight run and
  byte-compare the regenerated `telemetry_dataset_v2.json` against the
  committed one. Identical file ⇒ the refactor changed nothing.
* The monitor then builds each tick's input by calling that same function on
  `[now − 9 min, now]`, taking the last 12 steps, applying `log1p` and the
  **saved** `feature_min`/`feature_max` from the checkpoint (never refitted),
  in the **saved** node order.

## 2. What the monitor does each tick (every 30 s)

```
query Prometheus (last 9 min, step 30s)
  -> features [T', 11, 7]  ->  last 12 steps  ->  [1, 12, 11, 7]
  -> model -> breach prob per service + cause scores
  -> static racer: current latency / (tuned thresholds x fair multiplier)
  -> print one line; append one JSONL record
```

Terminal line (compact, demo-readable):

```
18:42:30  max=0.34 (checkout 0.34, cart 0.29)   static: quiet      cause if asked: redis, cart
18:45:00  max=0.86 (checkout 0.86, cart 0.71)   static: FIRING     ** ALARM ** cause: redis (0.61), cart (0.22)
```

* Model alarm: `max prob > tau` with tau **loaded from the checkpoint**
  (0.81 — the ≤1 false-alarm/hour operating point; never re-tuned live).
* Static racer: the checkpoint's per-node thresholds × the fair-budget
  multiplier (9.4 — to be **saved into the checkpoint** by a one-line
  train_v2 change, not hard-coded).
* Every tick appended to `live_ticks.jsonl` — the demo leaves evidence.

## 3. Where it runs

On the VM, next to Prometheus (`localhost:30900` NodePort — no port-forward
fragility, the Round 1 lesson). The VM has no torch: create `~/gems/venv`
with CPU-only torch + numpy (~800 MB disk; VM has headroom, verified before
install). The checkpoint (`gems_model_v2.pt`, ~100 KB) and the two scripts
are scp'd up. Inference cost is trivial (one [1,12,11,7] forward pass).

## 4. Build phases, each with a gate

**A. Refactor + parity (laptop).** Extract the shared function; regenerate
the dataset; byte-compare against the committed file. *Gate: identical.*

**B. Save the race constants (laptop).** train_v2 saves the fair-budget
static multiplier and tau into the checkpoint; retrain-free (re-run the
eval path only, same seed). *Gate: checkpoint contains tau + multiplier +
thresholds; test metrics unchanged.*

**C. Replay mode (VM).** `--replay <start> <end>` ticks through a historical
window (last night's ep20 redis-delay). *Gate: the monitor's probabilities
on those timesteps match offline predictions from the dataset within float
tolerance — proves live feature building == training feature building.*

**D. Quiet soak (VM, ~10 min).** Live against the healthy cluster.
*Gate: zero alarms, max prob stays low, static racer quiet.*

**E. Live fire (VM, ~15 min).** Run `redis-delay-ramp` (demo-grade 5-min
stages) with the monitor running. *Gate: probability visibly climbs through
stages 1–3; alarm fires by stage 3–4; cause ranking has redis or cart top-2;
tick log saved as the rehearsal artifact.* Payment ramp as a second shape if
time allows.

Only after E passes does this enter the supervisor demo script.

## 5. What the demo then looks like (5 minutes)

1. Terminal A: `python3 live_monitor_v2.py` — a couple of quiet ticks.
2. Terminal B: `kubectl apply -f redis-delay-ramp.yaml`.
3. Narrate stage 1–2: latency climbing in Grafana, every request still 200,
   model probability rising tick by tick — *the precursor being read*.
4. Stage 3–4: static racer fires on cart's latency; model alarm fires naming
   **redis** — a service the static monitor cannot blame because it exports
   no latency. That contrast is the thesis, live.
5. `kubectl delete workflow redis-delay-ramp` — recovery on screen.

## 6. Honest limitations, stated in advance

* Calibration: offline, the model's alarm crossed tau only at breach (+0 s)
  on redis-delay. The demo's persuasive content is the **probability
  trajectory and the cause ranking**, not beating static to the alarm — the
  static racer is displayed deliberately and may fire first on latency ramps.
* One night of training data; the monitor demos inference, not superiority.
* If the live cluster drifts from the training night's baselines (e.g. after
  many restarts), probabilities may sit higher/lower than offline — the quiet
  soak (gate D) is the check, and its outcome is reported, not hidden.
