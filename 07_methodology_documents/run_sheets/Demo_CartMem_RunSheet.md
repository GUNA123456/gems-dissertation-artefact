# Cart-memory demo — rehearsal run sheet (pooled3, verified 2026-08-20)

*Timings from the verified live fire (inject 13:52:44 → alarm 13:58:30 →
OOM 14:01:44). Expect ±1 min run-to-run. Total: ~17 min + 3 min pre-flight.*

## T-3 min — pre-flight (silently, before anyone watches)

```bash
ssh azureuser@51.11.129.130
kubectl get pods -n default                                          # 12/12 Running
kubectl get workflow,networkchaos,stresschaos,podchaos -n default    # empty
tail -f ~/gems/live_pooled3.out   # READ-ONLY view of the ticks — Ctrl-C here
                                  # is always safe (kills only the tail)
# tmux attach -t livemon  = the PROCESS ITSELF, not a viewer. Ctrl-C inside
# KILLS the monitor (measured: it did, 20:02 on 20 Aug — PREDICTION AGE tile
# caught it at 22 min). Attach only to interact; escape with Ctrl-b then d.
# If the age tile reads > ~1 min, the monitor is dead — restart (below).
```
Browser: `http://51.11.129.130:30300/d/gems-model` — time range **Last 30
minutes**, refresh 30s. If it times out: your IP changed —
`az network nsg rule update -g gems-research-rg --nsg-name gems-vmNSG -n allow-gems-dashboards --source-address-prefixes $(curl -s ifconfig.me)`
(and the same for `-n allow-stylehub-frontend`).

**Opening line:** "Everything you'll see is live — this cluster is serving
simulated customers right now, and both monitors are quiet."

## T+0 — inject

```bash
kubectl apply -f ~/gems/demo-cart-mem.yaml && date -u
```
**Say:** "I've just started a memory leak inside the cart service — the kind
of slow fault that kills systems in production. Watch three panels: memory,
latency, and the model."

## T+1 → T+2 — the first step appears (MEMORY panel)

Cart's line steps 62 → ~158 MiB. Latency panel: nothing.
**Say:** "There's the disease — memory climbing toward that red line, the
container's kill limit. Now look at latency: two milliseconds, flat. To every
threshold monitor in industry, this incident does not exist yet."

## T+3 → T+6 — the climb (PROBABILITY panel)

Memory steps to ~204 MiB; cart's probability climbs 0.6 → 0.8 → 0.95.
**Say:** "The model is reading the same dashboards we are — and it's
concluded harm is coming. Probability tracking the memory climb, while
latency still shows nothing. This is a learned association: rising memory on
THIS service, in THIS graph, ends in a kill."

*(Quiet beat — let the curves move. Mention: "the model panels run ~45s
behind wall clock — Pushgateway timestamping; measured, disclosed, and shown
on the PREDICTION AGE tile.")*

## T+6 (±1) — THE ALARM

MODEL ALARM tile flips red; terminal shows `** ALARM ** cause: cart 1.00`.
STATIC tile: still green.
**Say:** "Alarm — cause: cart, certainty 1.0 — and note the static monitor
is still green. In the verified run this moment came **three minutes and
fourteen seconds before the failure**. That gap is an on-call engineer's
head start."

*If the alarm doesn't cross (peak band 0.85–0.99 vs tau 0.97 — ~1 run in 4):*
**Say:** "It's riding just under the alarm line this run — the trajectory is
the signal; the line placement is a calibration choice I discuss in the
evaluation." *(The rise is guaranteed; never apologise.)*

## T+9 (±1) — THE KILL

Memory hits the red line and **cliffs back to 62 MiB**. Probability spike:
checkout/frontend jump ~0.98 (the cascade). Static may blip orange, after.
**Say:** "There's the OOM kill — the cliff. The kernel just executed the
container, exactly as predicted. See checkout and frontend spike — the model
widening to the cascade. And the static monitor's first and only reaction is
this little blip — *after* the harm."

## T+10 → T+14 — recovery

Probability decays; tiles green; memory flat at baseline.
**Say:** "And back to green — Kubernetes restarted the container, the model
released the alarm, nobody paged, nothing repaired by hand. Three minutes'
warning, the predicted failure, a clean recovery."

## T+15 — cleanup (can be silent or shown)

```bash
kubectl delete workflow cart-mem-ramp -n default --ignore-not-found
kubectl get workflow,networkchaos,stresschaos,podchaos -n default    # empty
kubectl get pods -n default                                          # 12/12
```

## Re-running the demo (practice or a second showing)

Workflows are ONE-SHOT. `kubectl apply` over a finished workflow prints
`configured` and **re-runs nothing** — the tell is the verb:

- `workflow.chaos-mesh.org/cart-mem-ramp created`     → it will run
- `workflow.chaos-mesh.org/cart-mem-ramp configured`  → it did NOTHING

Always delete first, then apply:

```bash
kubectl delete workflow cart-mem-ramp -n default --ignore-not-found
kubectl apply -f ~/gems/demo-cart-mem.yaml && date -u    # must say "created"
```

(Discovered in rehearsal 2026-08-20 19:27 — two `configured` applies injected
nothing while the dashboard stayed flat.)

## Contingencies

| If | Then |
|---|---|
| dashboard unreachable | terminal-only demo: tmux livemon IS the same data |
| stage timings drift | narrate panels, not the clock — the sequence is invariant |
| total disaster | replay variant, cannot fail: `./venv/bin/python -u live_monitor_v2.py --checkpoint gems_model_pooled3.pt --prom http://localhost:30900 --ticks-log /dev/null --replay 2026-08-20T13:48 2026-08-20T14:08` |
| cart prob ~0.0 after demo | normal post-restart undershoot (young pod age); recovers ~30 min |

**Never** improvise a bigger memory size for drama — beyond-ladder magnitudes
hit measured probe-kill traps and label the wrong fault.
