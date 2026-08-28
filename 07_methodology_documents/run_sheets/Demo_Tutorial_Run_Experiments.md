# Tutorial — running the cascade experiments live, one by one

*Everything here was executed and verified before being written down. Type the
commands exactly; expected output is shown after each. One golden rule
throughout: **one fault at a time, verified-clean between faults** — the same
rule the overnight scheduler enforces, applied by hand.*

---

## Part 0 — Before the meeting (~15 minutes ahead)

```bash
# 1. Start the VM (from your laptop)
az vm start -g gems-research-rg -n gems-vm
# wait ~2 min, then:

# 2. Open ONE terminal you'll keep for the whole meeting
ssh azureuser@51.11.129.130

# 3. Verify the cluster is fully healthy (run ON the VM)
kubectl get pods -n default
#   -> every row 1/1 Running. If not, wait a minute and re-check.

# 4. Verify no leftover chaos from a previous session
kubectl get workflow,networkchaos,stresschaos,podchaos -n default
#   -> "No resources found" on every kind.

# 5. Check the live model monitor is ticking
tmux attach -t livemon        # detach again with:  Ctrl-b then d
#   -> a new line every 30s, looking like:
#   10:12:30  max=0.68 (cart 0.68, frontend 0.35)  static:quiet(0.7x)
# If the session is dead, restart it (pushgateway makes Grafana work too):
#   PG=$(kubectl get svc -n monitoring prometheus-prometheus-pushgateway -o jsonpath='{.spec.clusterIP}')
#   tmux new -s livemon "cd ~/gems && ./venv/bin/python -u live_monitor_v2.py \
#     --checkpoint gems_model_v2.pt --prom http://localhost:30900 \
#     --pushgateway http://$PG:9091 \
#     --ticks-log demo_$(date +%H%M).jsonl 2>&1 | tee -a live_fire.out"

# 6. Browser tabs (work only from YOUR laptop's network — NSG is IP-locked):
#    storefront   http://51.11.129.130:30080
#    Grafana      http://51.11.129.130:30300   (admin / admin)
#    MODEL DASHBOARD  http://51.11.129.130:30300/d/gems-model   <- the demo star
#    Prometheus   http://51.11.129.130:30900
```

**Tell the supervisor once, up front:** "the monitor's resting number is ~0.68
— that's its calibrated quiet state, not an alert; the alarm line is 0.805."

### How to read the model dashboard (http://51.11.129.130:30300/d/gems-model)

| Panel | What it means | How to read it |
|---|---|---|
| **Breach probability per service** | the model's forecast: "will this service breach its SLO within 6 minutes?" | watch the *slope*, not the level. cart resting at ~0.65 is its calibrated quiet state (small-data artifact, stated honestly); an incident looks like curves *climbing together* toward the red 0.805 line |
| **MODEL ALARM tile** | max probability vs the 0.805 threshold (tuned for ≤1 false alarm/hour) | green QUIET / red ALARM — the model's single-bit verdict |
| **STATIC MONITOR tile** | the honestly-budgeted threshold racer | fires on raw latency; expect it *before* the model on ramps, and watch it go *quiet* at an error peak while the model holds — that contrast is the thesis |
| **Root-cause ranking** | "IF something is brewing, who is responsible?" | **only meaningful while MODEL ALARM is red.** In quiet periods it drifts to the model's training bias (redis ~0.5 at rest — an artifact, not a warning). During a real cascade the true cause climbs to 0.8–0.95 and turns red (threshold 0.7) |
| **Mean request latency** | the raw signal underneath everything | this is what the static racer watches and what the SLO is defined on — the "ground truth" strip |

One-line summary for the supervisor: *"top-left is the forecast, the tiles are
the two monitors' verdicts, bottom-left answers 'who did it', bottom-right is
the raw truth they're all reading."*

---

## Part 1 — Demo A: the visible cascade (~7 minutes)

*What it proves: failures propagate hop-by-hop, observably, with the broken
dependency NAMED at every level.*

**Step 1 — show health.** In the browser: storefront → add something to the
cart → checkout → "Order Placed Successfully". Say: *"a normal customer
journey, working."*

**Step 2 — set up the terminal probes.** (ON the VM, paste as one block)

```bash
CHK=$(kubectl get svc stylehub-checkout-service -o jsonpath='{.spec.clusterIP}')
CART=$(kubectl get svc stylehub-cart-service -o jsonpath='{.spec.clusterIP}')
ORDER='{"user_id":"demo","user_currency":"USD","email":"d@x.io","address":{"street_address":"1 Way","city":"NG","state":"NG","country":"UK","zip_code":1},"credit_card":{"credit_card_number":"4432-8015-6152-0454","credit_card_cvv":123,"credit_card_expiration_year":2028,"credit_card_expiration_month":12}}'
probe() {
  curl -s -o /dev/null -X POST http://$CART:8082/api/cart/add -H 'Content-Type: application/json' -d '{"user_id":"demo","item":{"product_id":"SH-001","quantity":1}}'
  curl -s -m 8 -X POST http://$CHK:8086/api/checkout -H 'Content-Type: application/json' -d "$ORDER" | head -c 120; echo
}
probe
#  -> {"order": {"order_id": "ORD-SH-...", ...}}       (healthy)
```

**Step 3 — kill redis.** Say: *"I'm now killing the database at the bottom of
the chain — three hops away from the user."*

```bash
kubectl scale deploy stylehub-redis --replicas=0
sleep 8 && probe
#  -> {"detail":"cart-service unavailable (ReadTimeout) — order not placed"}
```

Then in the browser: try to check out → the order-failed page. Say: *"checkout
failed and NAMED its broken dependency; the user sees an honest failure page —
in Round 1 this exact scenario reported a successful order."*

**Step 4 — show the propagation trail.** In the Prometheus tab, run:

```
service_dependency_errors_total
```

Point at the three edges: `cart→redis` (largest, hundreds), `checkout→cart`
(a few), `frontend→checkout` (fewer). Say: *"the counters get quieter the
further you are from the root cause — that gradient pointing at redis is
exactly the structure my model's cause head learns."*

**Step 5 — restore, and prove recovery.**

```bash
kubectl scale deploy stylehub-redis --replicas=1
kubectl rollout status deploy/stylehub-redis
sleep 8 && probe
#  -> {"order": ...}  again. Browser order works too.
```

*Expected side-effect:* the monitor may NOT alarm during this demo — a hard
kill has no precursor (metrics vanish rather than degrade). If asked, that IS
a finding: "the model predicts degradation, not disappearance — sudden death
is the contrast class."

---

## Part 2 — Demo B: the model calling a ramp live (~18 min, the flagship)

*What it proves: early warning WITH root cause, before users are hurt.*

**Step 1 —** open the model dashboard
(`http://51.11.129.130:30300/d/gems-model`) — the model publishes its output
into Prometheus every tick, so Grafana shows: per-service breach probability
with the 0.805 alarm line, a MODEL ALARM / STATIC MONITOR pair of state
tiles, the live root-cause ranking, and raw latency underneath. This is the
professional view — the terminal (tmux) is the same data if you prefer text.
Talking point: *"the model isn't a replacement for monitoring — it publishes
into the same Prometheus/Grafana stack as everything else."*

**Step 2 — inject the ramp.** Pre-built 3-minute-stage files live on the VM
(`~/gems/demo-*.yaml`), so this is ONE short line with no quotes to mangle:

```bash
kubectl apply -f ~/gems/demo-redis.yaml
```

> **Never paste multi-line blocks into the terminal during a demo.** A pasted
> block containing quotes or `\` continuations can leave zsh stuck at a
> `quote>` prompt (press Ctrl-C to escape). Type or paste ONE line at a time.
> Also: the `ssh ...` line and the commands that follow it belong to two
> different machines — connect first, wait for the VM prompt, then run the rest.

Other pre-built demos, same pattern:
`~/gems/demo-payment.yaml` (pure latency, zero errors),
`~/gems/demo-catalog-cpu.yaml` (stress with no user impact — the discipline test).

**Step 3 — narrate what appears** (from two rehearsed runs, timings ±1 min):

| When | Monitor shows | Say |
|---|---|---|
| min 0–4 (st.1) | max creeps 0.69→0.72, `static:FIRING` early | "the threshold monitor fires on the first latency symptom — a symptom, not a prognosis" |
| min 5–9 (st.2) | max 0.75→0.82 → `** ALARM ** cause: redis 0.68` | "**the model alarms BEFORE any SLO breach — and names redis**, which no per-service threshold can ever blame" |
| min 10–15 (st.3–4) | max ~0.88, cause redis →0.95; then `static:quiet` while ALARM continues | "requests are now failing fast, so latency drops and the static monitor STANDS DOWN at the worst moment — the model rides through on error edges" |

**Step 4 — clean up and watch recovery:**

```bash
kubectl delete workflow redis-delay-ramp -n default
# monitor decays back toward 0.69 over the next ~3 minutes
```

**Short-on-time fallback (3 min, zero risk)** — replay the overnight episode
instead of injecting:

```bash
cd ~/gems && ./venv/bin/python live_monitor_v2.py --checkpoint gems_model_v2.pt \
  --prom http://localhost:30900 --ticks-log /dev/null \
  --replay 2026-08-15T07:05 2026-08-15T07:35
```

Same arc, real recorded history, nothing injected.

---

## Part 3 — running MORE experiments, one by one

**The between-experiments ritual (always, ~2 min):**

```bash
kubectl get workflow,networkchaos,stresschaos,podchaos -n default   # -> none
kubectl get pods -n default    # -> all 1/1
# and wait until the monitor prints 2-3 ticks back at ~0.68-0.69
```

Never overlap faults — attribution evidence is destroyed if two are active.

**The menu (each = inject → observe → restore → ritual):**

| Experiment | Inject | Show | Restore |
|---|---|---|---|
| catalog outage (different cascade shape) | `kubectl scale deploy stylehub-product-catalog-service --replicas=0` | product page still renders (graceful), but `probe` → 502 naming catalog; recommendations 502 | `kubectl scale deploy stylehub-product-catalog-service --replicas=1` |
| payment ramp (pure latency, zero errors) | `kubectl apply -f ~/gems/chaos_manifests_v2/payment-delay-ramp.yaml` | order latency in Grafana 50ms→2.2s, all orders still succeed; monitor alarm late w/ cause payment | `kubectl delete workflow payment-delay-ramp -n default` |
| CPU stress (the discipline test) | `kubectl apply -f ~/gems/chaos_manifests_v2/catalog-cpu-ramp.yaml` | Grafana: catalog burning ~3 cores; monitor stays QUIET — correctly | `kubectl delete workflow catalog-cpu-ramp -n default` |
| redis kill again (repeatability) | as Part 1 | same cascade, same counters — reproducible on demand | as Part 1 |

*Do NOT demo:* cart-mem (model's probability falls — it's a dissertation
figure, not a live act) and simultaneous faults.

---

## Part 4 — when something misbehaves

| Symptom | Fix |
|---|---|
| monitor stopped ticking | restart command in Part 0 step 5 |
| ramp seems stuck / stage never changes | `kubectl delete workflow --all -n default` then the ritual |
| a pod won't go Ready | `kubectl rollout status deploy/<name>`; worst case `kubectl rollout restart deploy/<name>` |
| browser links dead but SSH works (timeout, not refused) | your IP changed (NSG is IP-locked; ISPs rotate). 30-second fix from the laptop: `az network nsg rule update -g gems-research-rg --nsg-name gems-vmNSG -n allow-gems-dashboards --source-address-prefixes $(curl -s ifconfig.me)` and the same for `-n allow-stylehub-frontend`. Check this the MORNING of the meeting — campus IP ≠ home IP |
| everything is on fire | show the committed evidence instead: `Collection_Runs/livefire-*.jsonl` and the replay — the demo becomes a walkthrough |

## Part 5 — after the meeting

```bash
# stop the money meter (from your laptop)
az vm deallocate -g gems-research-rg -n gems-vm
```

---

*Why the confidence: every step above was run at least twice before this file
was written — but run Part 1 once yourself on the morning of the meeting
anyway. The rule that got this project here: never assume a demonstration
works because it worked previously.*
