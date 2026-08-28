# Redis-delay demo — steps (pooled3 era, verified 2026-08-20)

*Deployed checkpoint: `gems_model_pooled3.pt` (tau 0.97). All numbers below are
from the held-out Night A ep19 replay verified today — parity 5.0e-05.
Supersedes the redis sections of Demo_Redis_Ramp_Tutorial.md (v2-era numbers).*

## What this demo claims — say it BEFORE running

**Not a lead-time demo.** Under the honest v2.1 labels, a latency ramp breaches
almost immediately (150ms injected = 60x cart's 2.5ms baseline), so detection
is a three-way tie — static, model, and the SLO all fire within ~60s. The old
"+180s static lead" was an artifact of the lenient 0.5s floor.

**It is the ATTRIBUTION demo:** detection ties, but only the model names the
cause — **redis at 1.00, sustained for twelve minutes, about a component that
emits no telemetry of its own**. Static's best statement is "cart is slow":
a symptom, on the wrong service.

---

## Variant 1 — replay (~2 min, cannot fail; recommended)

Re-runs the held-out Night A episode against recorded Prometheus history.
Nothing is injected; nothing can go wrong.

```bash
ssh azureuser@51.11.129.130
cd ~/gems && ./venv/bin/python -u live_monitor_v2.py \
  --checkpoint gems_model_pooled3.pt --prom http://localhost:30900 \
  --ticks-log /dev/null --replay 2026-08-20T08:08 2026-08-20T08:25
```

What appears, and what to say:

| You see | Say |
|---|---|
| `08:08-08:10  max~0.60  static:quiet` | "healthy cluster, both monitors calm" |
| `08:11:00  static:FIRING` | "the threshold monitor sees a symptom: cart is slow" |
| `08:11:30  ** ALARM ** cause: redis 0.98` | "same moment, the model — but naming REDIS, which exports no metrics at all; no threshold can even watch it" |
| `08:12-08:23  max=1.00, cause: redis 1.00` every tick | "twelve minutes of unwavering attribution, held straight through the error storm" |
| `08:24  max=0.09, static quiet` | "fault ends, both release — no stuck alarm" |

Close: *"detection was a tie; attribution was a monopoly."*

## Variant 2 — live injection (~18 min)

Same arc on the live cluster. Replay-verified expectations; live runs vary
(peaks 0.99-1.00 here are robust, timing +/-1 min).

```bash
# 1. Pre-flight (the ritual — always)
kubectl get pods -n default                        # 12/12 Running
kubectl get workflow,networkchaos,stresschaos,podchaos -n default   # empty
tmux attach -t livemon    # ticking ~0.55 resting; detach: Ctrl-b d

# 2. Inject (3-minute stages; ~12 min of ramp)
kubectl apply -f ~/gems/demo-redis.yaml
date -u

# 3. Watch: tmux livemon, or dashboard http://51.11.129.130:30300/d/gems-model
#    (NSG is IP-locked - refresh the rule if links time out:
#     az network nsg rule update -g gems-research-rg --nsg-name gems-vmNSG \
#       -n allow-gems-dashboards --source-address-prefixes $(curl -s ifconfig.me))
```

Expected timeline from injection (T0):

| ~When | Event |
|---|---|
| T0+1..2 min | static FIRING (cart latency crosses its corrected threshold) |
| T0+1.5..2.5 min | first actual breach (cart, latency clause) and MODEL ALARM within a tick of it — cause redis ~0.98 |
| T0+2..12 min | alarm locked 0.99-1.00; cause redis -> 1.00; victims widen to checkout+frontend (the cascade, in the forecast) |
| stage 4 (T0+9..12) | error phase: cart 503s appear; alarm holds while static may flap |
| after stage 4 | decay to ~0.55 within ~2 min |

```bash
# 4. Clean up (workflow self-expires, but delete explicitly anyway)
kubectl delete workflow redis-delay-ramp -n default --ignore-not-found
kubectl get pods -n default    # 12/12 before the next demo — the ritual
```

## Pitfalls

- **One fault at a time**; run the pre-flight ritual between demos.
- **PREDICTION AGE panel (~45s)**: the dashboard lags the model by design
  (Pushgateway restamps). Timing claims come from the tick log, never the
  screen — volunteering this reads as rigor.
- Do not improvise bigger delays "for effect": magnitudes beyond the trained
  ladder risk probe-kills (payment/redis probe budget traps, both measured).
- If asked "so it has no lead time here?" — correct, and neither does
  anything else: the honest labels put the breach in the fault's first
  minute. Lead time lives in the memory demo; this one is about *who*.
