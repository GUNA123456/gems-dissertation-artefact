# Redis-delay ramp demo — rehearsal run sheet (pooled3, verified 2026-08-23)

*Timings from the live fire of 23 Aug 2026: inject 16:58:01 → static FIRING
16:59:00 → **MODEL ALARM 16:59:30, cause redis 0.92** → redis 1.00 by 17:00:30
→ fault ends 17:11:30 → fully decayed 17:12:30. Expect ±1 min run-to-run.*

**Total: ~16 min full, or ~7 min if you stop early (see T+5).**

---

## What this demo claims — say it BEFORE you inject

**This is NOT a lead-time demo.** Under the honest v2.1 labels a latency ramp
breaches almost immediately — 150 ms injected is 60× cart's 2.5 ms baseline —
so detection is a three-way tie: static, model and the SLO all fire inside the
first minute. Say that yourself before anyone asks; volunteering it reads as
rigour, and the lead-time claim lives in the cart-memory demo instead.

**It is the ATTRIBUTION demo.** Detection ties. Attribution is a monopoly:
only the model names **redis**, holds it at 1.00 for ten unbroken minutes, and
does so about a component that **exports no telemetry of its own** — no
per-node threshold can watch Redis at any tuning. Static's strongest possible
statement is "cart is slow": a symptom, on the wrong service.

**Closing line:** *"Detection was a tie. Attribution was a monopoly."*

---

## T-3 min — pre-flight (silently, before anyone watches)

```bash
ssh azureuser@51.11.129.130

# 1. Cluster healthy — 12/12 Running
kubectl get pods -n default

# 2. No fault already in flight — MUST be empty
kubectl get workflow,networkchaos,stresschaos,podchaos -n default

# 3. Monitor alive?
pgrep -fa live_monitor_v2 | head -2

# 4. Resting ticks — cart should sit ~0.5-0.6, static quiet
tail -f ~/gems/live_pooled3.out      # Ctrl-C here is ALWAYS SAFE (kills only the tail)
```

> **Never `tmux attach -t livemon` to watch.** That attaches to the monitor
> *process*; Ctrl-C inside it kills the monitor (measured: it did, 20:02 on
> 20 Aug — the PREDICTION AGE tile caught it 22 minutes later). Use `tail -f`.
> If you must attach, escape with **Ctrl-b then d**, never Ctrl-C.

If the monitor is dead, restart it:

```bash
tmux kill-session -t livemon 2>/dev/null
tmux new-session -d -s livemon "cd ~/gems && ./venv/bin/python -u live_monitor_v2.py \
  --checkpoint gems_model_pooled3.pt --prom http://localhost:30900 \
  --pushgateway http://10.43.89.206:9091 --ticks-log live_pooled3.jsonl 2>&1 \
  | tee -a live_pooled3.out"
sleep 40 && tail -3 ~/gems/live_pooled3.out    # confirm it is ticking again
```

Browser: `http://51.11.129.130:30300/d/gems-model` — time range **Last 30
minutes**, refresh **30s**. If it times out your IP has changed:

```bash
az network nsg rule update -g gems-research-rg --nsg-name gems-vmNSG \
  -n allow-gems-dashboards --source-address-prefixes $(curl -s ifconfig.me)
az network nsg rule update -g gems-research-rg --nsg-name gems-vmNSG \
  -n allow-stylehub-frontend --source-address-prefixes $(curl -s ifconfig.me)
```

**Opening line:** "Everything here is live. This cluster is serving simulated
customers right now, and both monitors are quiet."

---

## T+0 — inject

The workflow is **one-shot**. Applying over a finished one prints `configured`
and runs **nothing**. Always delete first, and check the word:

```bash
kubectl delete workflow redis-delay-ramp -n default --ignore-not-found
kubectl apply -f ~/gems/demo-redis.yaml && date -u
```

> Output **must** say `created`. If it says `configured`, nothing will happen —
> delete and re-apply.

**Say:** "I've just put network latency on Redis — the store behind the cart
service. It ramps in four stages: 150, 400, 900, then 1600 milliseconds. Watch
which monitor tells you *what broke*, and which tells you *why*."

---

## T+0:30 → T+1 — the rise

Ticks show cart climbing 0.59 → 0.71, static still quiet but its multiplier
jumps (tonight: `static:quiet(6.5x)`).

**Say:** "Cart is degrading — every cart operation touches Redis, so the delay
lands on all of them."

## T+1 — STATIC FIRES first

```
16:59:00  max=0.92 (cart 0.92, checkout 0.91)  static:FIRING
```

**Say:** "The threshold monitor just fired, and it is right — cart *is* slow.
Note what it says: *cart*. That's the symptom, and it's the wrong service."

## T+1:30 — THE MODEL ALARM, and the point of the demo

```
16:59:30  max=0.98  static:FIRING  ** ALARM ** cause: redis 0.92, cart 0.06
```

**Say:** "Same moment, but a different sentence. The model says **Redis** — and
Redis exports no metrics of its own. There is no threshold you could set on
Redis, because there is nothing to watch. The model names it purely from the
shape of the dependency graph and the error gradient along it."

## T+2:30 → T+4 — attribution locks, the cascade widens

```
17:00:30  cause: redis 1.00, cart 0.00
17:01:00  max=1.00 (cart 1.00, frontend 1.00)   cause: redis 1.00
```

**Say:** "Redis is now at 1.00 and the victim set is widening — cart, then
checkout, then frontend. That's the three-hop cascade, and the model is
forecasting it while it spreads, still pointing at the origin."

---

## T+5 — EARLY STOP (recommended for live audiences and the video)

The argument is complete. The remaining ten minutes only show the attribution
*holding*, which is one sentence, not ten minutes of screen time.

```bash
kubectl delete workflow redis-delay-ramp -n default --ignore-not-found
kubectl delete networkchaos --all -n default        # drop the active stage immediately
date -u
```

**Say:** "I'll stop it here. Left alone it runs another ten minutes, and the
cause stays pinned to Redis at 1.00 for every one of those ticks — I have that
on the record from the full run."

Then jump to **Recovery** below.

---

## T+9 → T+12 — stage 4, the error phase (full run only)

Stage 4 is 1600 ms ± 250 ms jitter. Redis operations intermittently cross
cart's 2-second socket timeout, so cart begins answering **503 "redis
unavailable (TimeoutError)"**, checkout answers 502, and the storefront shows
the order-failed page.

**Optional — show the user-visible harm** (this is the Figure 5.5 shot):

```
http://51.11.129.130:30080/            # browse, add to cart → error banner
```

**Say:** "This is what the customer sees. Note the banner blames the *cart
service* — the frontend can only name its immediate dependency. The model has
been saying Redis for ten minutes."

## T+13:30 — the fault ends, both monitors release

```
17:11:30  max=0.99  static:FIRING  ** ALARM ** cause: redis 1.00
17:12:00  max=0.29  static:quiet(0.5x)
17:12:30  max=0.02  static:quiet(0.5x)
```

**Say:** "Fault over. Both monitors release within about ninety seconds — no
stuck alarm, no manual reset."

---

## Recovery — run this every time, full run or early stop

```bash
# 1. Remove the workflow and any surviving chaos resources
kubectl delete workflow redis-delay-ramp -n default --ignore-not-found
kubectl delete networkchaos --all -n default --ignore-not-found

# 2. Verify NOTHING is left (must print nothing)
kubectl get workflow,networkchaos,stresschaos,podchaos -A --no-headers

# 3. Cluster back to 12/12 Running
kubectl get pods -n default

# 4. Redis healthy and untouched (this demo never kills it — restarts should be 0)
kubectl get pod -l app=stylehub-redis -o wide

# 5. Probabilities decayed to resting (~0.5 or below) before any next demo
tail -5 ~/gems/live_pooled3.out

# 6. Storefront serving normally again
curl -s -o /dev/null -w "frontend HTTP %{http_code}\n" http://localhost:30080/
```

**Green light for the next demo:** chaos list empty, 12/12 pods, and the tick
log back under ~0.6.

---

## Re-running (practice, or a second showing)

Unlike cart-memory, this demo has **no cool-down requirement** — nothing is
killed, no container is replaced, so there is no newborn-pod suppression to
wait out. You can re-run as soon as the probabilities have decayed, about two
minutes after cleanup.

Still run the full pre-flight ritual between runs. One fault at a time.

---

## The zero-risk alternative — replay (~2 min, cannot fail)

For the recorded video, or any situation where a live failure would be
awkward. Re-runs the withheld R2 episode against stored Prometheus history.
Nothing is injected; nothing can go wrong.

```bash
cd ~/gems && ./venv/bin/python -u live_monitor_v2.py \
  --checkpoint gems_model_pooled3.pt --prom http://localhost:30900 \
  --ticks-log /dev/null --replay 2026-08-20T08:08 2026-08-20T08:25
```

Same arc, compressed: quiet → static fires → model alarms naming redis →
twelve minutes of redis 1.00 → release.

---

## Pitfalls (all measured, not hypothetical)

- **`configured` vs `created`.** Re-applying a finished workflow runs nothing.
  Delete first; read the word.
- **Never Ctrl-C inside `tmux attach -t livemon`** — that is the monitor
  process. Use `tail -f ~/gems/live_pooled3.out`.
- **Dashboard lags 45–73 s** by design (Pushgateway re-stamps at scrape).
  The PREDICTION AGE panel shows it live. **All timing claims come from the
  tick log, never the screen** — say so; it reads as rigour.
- **Don't improvise bigger delays "for effect."** Magnitudes beyond the
  trained ladder cross probe budgets and convert a latency fault into a
  restart fault, which is a different experiment (measured: payment at
  1500 ms killed a healthy pod).
- **One fault at a time.** Never overlap with a cart-memory run.
- **If asked "so there's no lead time here?"** — Correct, and neither has
  anything else: the honest labels put the breach inside the fault's first
  minute. Lead time is the memory demo. This one is about *who*.
