> **SUPERSEDED for the redis demo (2026-08-20):** the deployed checkpoint is
> now `gems_model_pooled3.pt` under v2.1 labels — leads, tau (0.97) and
> framing changed. Use **Demo_Redis_Delay_Steps.md**. This file remains as
> the v2-era record (its numbers were correct for that checkpoint).

# Redis cascade demo — the ready-to-run tutorial

*Written against the cluster as verified on 2026-08-18 22:35 UTC. Every number
below was measured, not assumed. Where the honest expectation is unflattering,
it is stated in advance — the demo is stronger for saying it first.*

---

## 0. What this demo does and does not prove

State this to your supervisor **before** you inject anything. It costs nothing
(it is in the tick logs either way) and it buys the credibility to make the
narrower claim stick.

**It does NOT prove the model beats a threshold monitor to the alarm.** On a
latency ramp it does not, and this was pre-registered in
`Live_Monitor_v2_Plan.md` §6. Measured across two independent live-fire runs:

| Run | Static fires | Model alarms | Model's lead |
|---|---|---|---|
| 2026-08-16 | 00:08:00 | 00:11:30 | **−3m30s** |
| 2026-08-18 | 00:53:00 | 00:57:00 | **−4m00s** |

**What it DOES prove — the model alarms BEFORE the actual SLO breach.**
"Static fired" is not "breached": ground truth is only the SLO clause set
(`latency > max(5 × quiet-median, 0.5s) | 5xx | err_in`). Static's thresholds
sit far from the breach point by design (cart fires 13.5× *below* it,
checkout 2.4× *above* it). Measured from the 08-16 run against actual
breaches, from raw Prometheus + tick log (regenerate any time with
`demo_evidence.py`):

| Service | First actual breach | Model alarm lead | Static lead |
|---|---|---|---|
| cart | 00:14:00 (662ms) | **+2m30s** | +6m00s (at 62ms — 13.5× below SLO) |
| frontend | 00:13:30 | **+2m00s** | +5m30s |
| checkout | 00:11:00 | −30s | +3m00s |

Keep the two claims verbally separate, always:

1. **"Does the model give useful warning?"** — vs the SLO → **yes**, +2m30s
   on cart, +2m00s on frontend.
2. **"Does it beat a tuned threshold on latency ramps?"** — vs static → no.
   Static is earlier because it fires at 62ms on its false-alarm budget; the
   defensible edge is elsewhere: **redis exports no latency series, so static
   is structurally incapable of blaming it** (its threshold is `inf` in the
   checkpoint — computable, not rhetorical).
3. **The signal is not late — the operating point is.** Probability starts
   rising on the *same tick* static fires; tau=0.805 (forced by one night's
   quiet data) costs ~90s of achievable lead. That is the Step 4 argument.

---

## 1. Pre-flight — verified state as of 2026-08-18 22:35 UTC

All of this was checked and passed. Re-run before the meeting; it takes 60s.

```bash
ssh azureuser@51.11.129.130

# 1. every pod Running 1/1 — expect 12 rows, including traffic-generator
kubectl get pods -n default

# 2. no leftover chaos — expect "No resources found"
kubectl get workflow,networkchaos,stresschaos,podchaos -n default

# 3. chaos mesh alive
kubectl get pods -n chaos-mesh | head -4

# 4. the three endpoints
curl -s -o /dev/null -w "prom  %{http_code}\n" http://localhost:30900/
curl -s -o /dev/null -w "graf  %{http_code}\n" http://localhost:30300/
curl -s -o /dev/null -w "shop  %{http_code}\n" http://localhost:30080/
#   -> 302, 302, 200
```

**Verified results (2026-08-18 22:35 UTC):**

| Check | Result |
|---|---|
| Application pods | **12/12 Running**, 0 not-Running |
| Leftover chaos | none |
| Chaos Mesh | controller-manager ×3, daemon, dashboard, dns-server all Running |
| `:30900` Prometheus | HTTP 302 ✓ |
| `:30300` Grafana | HTTP 302 ✓ |
| `:30080` storefront | HTTP 200 ✓ |
| Pushgateway ClusterIP | `10.43.89.206` |
| venv | torch 2.13.0+cpu, numpy 2.2.6 ✓ |
| Checkpoint | tau=0.805, static_mult=9.4, seq=12, nodes=11 ✓ |
| Grafana `gems-model` dashboard | exists ✓ |
| Quiet soak (Gate D) | **6/6 ticks quiet, zero alarms** ✓ |

Current baseline latency: checkout 51ms, frontend 20ms, cart 1.8ms.

### ⚠ The one number that is off tonight

**Resting probability is 0.62.** In the two recorded runs it was 0.653 and
0.694. Tau is 0.805, and the largest excursion ever observed is about **+0.19**.

```
  0.694 resting (08-16)  + 0.19  =  0.88   comfortable alarm
  0.653 resting (08-18)  + 0.19  =  0.84   clear alarm
  0.620 resting (tonight)+ 0.19  =  0.81   MARGINAL — tau is 0.805
```

**The alarm may be marginal or may not fire at all tonight.** Do not discover
this in front of your supervisor. Either:

- **(a)** run §2 and §3 as a rehearsal first and see where it lands, or
- **(b)** lead with the trajectory as the deliverable, so a marginal crossing is
  a data point rather than a failure. The trajectory is reproducible; the
  crossing, from this baseline, is not guaranteed.

Option (b) is the honest framing regardless, and it is what §0 sets up.

### Or sidestep the baseline entirely: the replay track (recommended opener)

Replay is scientifically *stronger* than live injection: episodes 19/20/21 are
in the **test split** — the model never trained on them — and replay cannot
fail on the night. Verified working 2026-08-19. Three scenarios in ~3 minutes:

```bash
cd ~/gems
# 1. Discipline: catalog-cpu, no breach — model correctly stays quiet
./venv/bin/python -u live_monitor_v2.py --checkpoint gems_model_v2.pt \
  --prom http://localhost:30900 --replay 2026-08-15T06:34 2026-08-15T06:54

# 2. The flagship: redis 3-hop cascade, alarm 0.81→0.88, cause redis 0.72→0.80
./venv/bin/python -u live_monitor_v2.py --checkpoint gems_model_v2.pt \
  --prom http://localhost:30900 --replay 2026-08-15T07:12 2026-08-15T07:32

# 3. Second cascade shape: payment — the culprit static CAN see (fair contrast)
./venv/bin/python -u live_monitor_v2.py --checkpoint gems_model_v2.pt \
  --prom http://localhost:30900 --replay 2026-08-15T07:36 2026-08-15T07:55
```

Reproducibility card (all four redis episodes peak 0.88; all five payment
episodes 0.81–0.82 — stable, not cherry-picked). Best structure: replay for
the evidence, then ONE live redis ramp as "and here it is in real time".
These replays need the 2026-08-14/15 TSDB data — retained until ~2026-09-04
(21d retention; do not lower it).

---

## 2. Start the monitor (do this ~10 minutes before)

The monitor is **not currently running**. Start it in tmux so it survives.

```bash
PG=$(kubectl get svc -n monitoring prometheus-prometheus-pushgateway \
       -o jsonpath='{.spec.clusterIP}')     # -> 10.43.89.206

tmux new -s livemon "cd ~/gems && ./venv/bin/python -u live_monitor_v2.py \
  --checkpoint gems_model_v2.pt \
  --prom http://localhost:30900 \
  --pushgateway http://$PG:9091 \
  --ticks-log demo_$(date +%Y%m%d_%H%M).jsonl 2>&1 | tee -a demo_run.out"
```

Detach with **Ctrl-b then d**; re-attach with `tmux attach -t livemon`.

Confirm the header, then let it tick quietly for 3–4 minutes:

```
checkpoint: tau=0.805 static_mult=9.4 seq=12 nodes=11
live mode: prom=http://localhost:30900 tick=30s (evaluating the last COMPLETE step)
22:30:00  max=0.62 (cart 0.62, frontend 0.25)  static:quiet(0.5x)
```

**Gate:** every tick quiet, `max` stable around 0.62. If `max` is drifting or
any alarm fires on a healthy cluster, stop and diagnose — do not demo.

---

## 3. The demo, minute by minute

The ramp is 4 stages × 3 minutes = **12 minutes**, deadline 13m. The
interesting part is over by minute 9; you do not need to run it to the end.

| Stage | Redis delay | Duration |
|---|---|---|
| 1 | 150ms ± 30ms | 3 min |
| 2 | 400ms ± 60ms | 3 min |
| 3 | 900ms ± 120ms | 3 min |
| 4 | 1600ms ± 250ms | 3 min |

### Screen layout

- **Left:** terminal with `tmux attach -t livemon` — the primary instrument
- **Right:** Grafana `http://51.11.129.130:30300/d/gems-model`
- **Third tab:** storefront `http://51.11.129.130:30080`

### T−1 — establish health

Add something to the cart on the storefront, check out, get "Order Placed
Successfully".

> "A normal customer journey, working. The terminal shows the model's resting
> state — 0.62 for cart. That is its calibrated quiet level, not an alert. The
> alarm line is 0.805."

### T+0 — inject

```bash
kubectl apply -f ~/gems/demo-redis.yaml
```

> "I'm now injecting progressive network latency at Redis. Redis is the root
> cause; cart, checkout and frontend are the potential victims, in that order,
> because every cart operation touches Redis and checkout calls cart."

### T+1 — static fires (stage 1)

Expect the static racer to fire within about a minute, jumping straight to
15–16× its threshold.

> "The threshold monitor has fired. It is reading cart's raw latency, which has
> gone from under 2 milliseconds to roughly 150. I want you to note this time —
> the threshold monitor wins the race to the alarm on a latency ramp, and I'll
> come back to why that is the expected result rather than a disappointing one."

### T+1 to T+5 — the trajectory (this is the deliverable)

Read the climbing probability aloud every few ticks. Measured from 08-18:

```
00:53:00   model 0.663   static  15.3x   FIRE
00:54:00   model 0.690   static  43.0x   FIRE
00:55:00   model 0.726   static  44.8x   FIRE
00:56:00   model 0.774   static  85.8x   FIRE
00:57:00   model 0.827   static 125.2x   FIRE     <- alarm
```

> "The model's probability began climbing on the same tick the threshold fired
> — there is no detection lag in the signal. What you're watching is a graded
> forecast: 0.66, 0.69, 0.73, 0.77. The threshold monitor has one bit of
> information. This has a trajectory."

### T+4 to T+5 — the alarm (may be marginal tonight)

> "The model has crossed 0.805 and is now predicting that cart, checkout and
> frontend are likely to breach their SLO within six minutes."

Say *"is predicting … likely to breach"* — never *"has detected a failure."*
The model outputs a forecast, and the wording is the difference between an
accurate claim and an overclaim.

If it does **not** cross tonight, say so plainly and use it:

> "It has peaked at 0.79 against a threshold of 0.805. That is the honest
> result from tonight's baseline, and it is exactly the calibration problem I
> want to talk about — the threshold is set where a single night of training
> data forces it."

### T+9 — the cascade (stage 4)

Errors begin: cart returns 503 "redis unavailable (TimeoutError)", checkout
502, the storefront shows the order-failed page. Refresh the storefront tab.

> "The failure has propagated from Redis to cart, then checkout, then frontend.
> Grafana is showing the observed consequence."

### Stop it

```bash
kubectl delete workflow redis-delay-ramp -n default
kubectl get networkchaos -n default        # confirm cleared
```

Watch recovery on screen. **Verify clean before any further experiment.**

---

## 4. The evidence table — fill from the tick log, not the screen

This is your scientific artefact. **Terminal = prediction evidence. Grafana =
observed-system evidence. Tick log = authoritative timing.** Never read a
timestamp off a Grafana panel: the model's metrics reach Grafana via
Pushgateway, which restamps them at scrape time, so the model curve is shifted
60–120s right relative to the latency curve on the same axis.

The table now fills itself — `demo_evidence.py` computes **actual SLO breach
times** from Prometheus (same clause set as the training labels, via the
shared `features_from_prometheus`) and joins them with the tick log:

```bash
cd ~/gems
./venv/bin/python demo_evidence.py --ticks-log demo_<timestamp>.jsonl \
    --dataset telemetry_dataset_v2.json --prom http://localhost:30900
```

Output: first static fire, first model alarm, peak probability, and — per
service — the first *actual* breach with its clause and the **signed lead of
each monitor vs that breach**. Those per-service leads are the numbers that
go in the dissertation; quote them per-service, never averaged, and never
read off a Grafana panel (the PREDICTION AGE tile on the dashboard shows
exactly how stale the model curve is at any moment).

---

## 5. Three things not to claim

**Do not claim the cause ranking as evidence.** Redis is `cause_top` at
0.59–0.61 through the *entire quiet period* before any fault. It is always
ranked first. What is real is the **score rising 0.60 → 0.95** during the
event. Claim the trajectory, disclose the resting bias. If you claim "the model
correctly identified Redis" without that caveat and your supervisor checks the
quiet ticks, the whole demo loses credibility.

**Do not claim the tail as insight — this is now PROVEN, not suspected.** The
Step 3b counterfactual ablation (`tail_drain_ablation.py`, 2026-08-19)
replaced the fault steps in every post-fault window with the pre-fault quiet
profile: **all 12 tail alarms vanish (0 survive), counterfactual probability
collapses to resting 0.68–0.69 across 44 tail ticks.** The ~3.5-minute
post-fault alarm is entirely the 6-minute window still containing the fault.
If asked, say exactly that — it is a disclosed limitation with an ablation
behind it, which is worth more than the claim would have been.

**Do not improvise a second, larger fault.** On 2026-08-17 at 22:23 something
drove static to **6352×** and the model probability *fell*, 0.68 → 0.18, never
alarming — the same anti-correlation the ablation documented for memory.
Inputs far outside the training range normalize outside [0,1] and push the
network the wrong way. The Redis ramp is safe because it matches the training
shape (max ~460×). A pod-kill is not. **One fault, the rehearsed one.**

---

## 6. If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Monitor prints "scrape not landed, skipped" | Prometheus scrape hasn't landed | Normal occasionally; persistent means check `:30900` |
| `--prom` connection refused | NodePort 30900 missing | `kubectl apply -f Infra/prometheus-nodeport.yaml` |
| Grafana panels empty | monitor started without `--pushgateway` | restart with the PG flag (§2) |
| Grafana lags the terminal by ~2 min | Pushgateway restamping + 30s scrape + 30s refresh | expected; use the terminal |
| Probability *falls* during the fault | out-of-distribution input | stop, do not narrate it as a result; note it as the §5 finding |
| Alarm fires on a healthy cluster | baseline drift | abort the demo, re-run the quiet soak |

---

## 7. The closing statement

> "Cart actually breached its SLO at [T_breach]. The model alarmed [lead]
> before that — genuine warning of a real breach. The threshold monitor fired
> earlier still, but at 62 milliseconds, thirteen times below the breach
> point: that is what its false-alarm budget buys on a latency ramp, and I'm
> showing it deliberately. The model's probability began climbing the moment
> the fault began — its signal was not late, its threshold was, and that
> threshold is set where one night of training data forces it. The model also
> attributed the cascade to Redis, a service that exports no latency metric —
> the static monitor's threshold for it is infinity; it cannot blame Redis
> even in principle. I should note Redis is the model's resting top-ranked
> cause, so it is the score trajectory, 0.60 to 0.95, that carries the
> evidence. More collection nights move the operating point — that is Step 4."
