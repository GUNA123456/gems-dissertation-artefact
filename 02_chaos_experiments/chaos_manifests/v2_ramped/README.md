# v2 ramped chaos manifests

Four Chaos Mesh `Workflow` manifests that replace Round 1's step-function faults
with progressive four-stage ramps. Every number below was measured on the Azure
k3s cluster (`gems-vm`, 4 vCPU, Chaos Mesh 2.8.3, Prometheus at 30s scrape), not
predicted.

## Why ramps

Round 1 injected faults as a step: zero stress to full stress in one transition.
The first anomalous sample was therefore already the failure, so no precursor
window existed and "predicting" a fault meant detecting one that had already
happened. Each ramp here holds four escalating stages for 5 minutes (~10 scrapes
each), so degradation is visible in a service's own metrics — and then in its
neighbours' — for 15 minutes before the terminal stage breaches anything.

## The four scenarios

| Manifest | Target | Stages | Terminal outcome |
|---|---|---|---|
| `catalog-cpu-ramp.yaml` | product-catalog | 1w@30% → 1w@70% → 2w@90% → 3w@100% | CPU saturation, highest fan-in in the graph |
| `cart-mem-ramp.yaml` | cart-service | 96 → 144 → 192 → 224 MB | **OOMKill** at the 256Mi limit |
| `redis-delay-ramp.yaml` | redis | 150 → 400 → 900 → 1600 ms | latency **becomes errors**: cart 503 → checkout 502 |
| `payment-delay-ramp.yaml` | payment-service | 100 → 300 → 800 → 1100 ms | **pure latency SLO breach**, zero errors |

The last two are deliberately different shapes. `redis-delay-ramp` gives the
model an error signal at the end; `payment-delay-ramp` never does, so it is the
stricter lead-time test — degradation must be predicted from degradation alone.

## Verified behaviour

**`catalog-cpu-ramp`** — CPU climbed 308m → 707m → 1790m → 2904m across the four
stages, cleanly monotonic and stage-aligned. Catalog memory stayed flat (~51Mi),
confirming the fault is isolated to CPU.

**`cart-mem-ramp`** — working set climbed 149 → 195 → 241 Mi, then the cgroup hit
its 256Mi limit and the kernel OOM-killed the container (`exitCode: 137`,
`reason: OOMKilled`, restart count 0 → 1).

One important detail for the labeller: the kernel kills the *largest* task in the
cgroup, and `dmesg` confirms it killed `memStress` (205MB RSS) **and** the
`python` app process (53MB) in the same OOM event. The pod did restart here, but
that is not guaranteed — a marginal overshoot can kill only the stress worker,
leaving the app alive. **Do not treat `restart_count` as the only OOM signal**;
sustained working-set at the limit is the more reliable feature.

**`redis-delay-ramp`** — cart latency tracked the injected delay almost exactly
for three stages (3.4ms baseline → 133-180ms → 391-424ms → 848-995ms), all HTTP
200 with zero errors. Stage 4 then broke *non-linearly*: 9.4s, a full timeout,
then 4.1s, with 14.2 `cart→redis` errors recorded.

The non-linearity is the interesting part and it is a real property of the app,
not an artefact. Cart's redis client uses `socket_timeout=2`, and on any failure
`_redis_op` discards the connection so the next call reconnects — but the
reconnect handshake is itself delayed 1.6s. Failure therefore amplifies rather
than degrading smoothly, which is exactly the kind of knee a predictor should
learn to anticipate.

**`payment-delay-ramp`** — order latency 50ms baseline → 0.27s → 0.69s → 1.67s →
2.23s, all HTTP 200, no errors, no pod restart. See the manifest header for why
there is deliberately no error stage: `requests`' scalar timeout is per-phase, so
an error needs >2.0s of delay, while payment's liveness probe fails above ~1.36s.
The windows do not overlap.

## Traps these runs exposed

**1. A latency fault can silently become a pod-restart fault.** At 1500ms,
payment's liveness probe (`timeoutSeconds: 3`) failed and Kubernetes restarted
the pod, so the terminal failure surfaced as `ConnectionError` from a dead pod
rather than `ReadTimeout` from a slow one. The injected label said "delay"; the
cluster did something else. Any new delay scenario must be checked against the
target's probe budget — roughly, keep injected delay below `timeoutSeconds / 2`.

**2. `increase()` under-reports counters that are born inside the query window.**
Querying `increase(service_dependency_errors_total{target=~".*payment.*"}[6m])`
returned **0.0** while the pod's own `/metrics` showed **3**. The series did not
exist before the first error, so there was no baseline sample to rise from. This
is the same failure that made `discover_topology.py` silently drop low-traffic
edges, where the fix was `max_over_time` minus `min_over_time`. **The v2
extraction pipeline must use that delta form, not `increase()`.**

**3. Redis had the payment trap too, hidden behind a default.** Its tcpSocket
probes declared no `timeoutSeconds`, so they defaulted to 1s — and under
stage-4 delay the SYN-ACK alone takes ~1.6–1.85s. The probe killed a healthy
redis four times during delay smoke tests (clean exits at exactly the stage-4
timestamps). Fixed in the chart (`timeoutSeconds: 3` on both probes) and
re-verified: 2 minutes of stage-4 delay, zero restarts, endpoints never
flapped. Lesson generalised: *every* delay target needs its probe budget
checked against worst-case injected RTT, including implicit defaults.

**4. Delay faults are visible only from the caller's side.** During the
payment ramp, payment's own `http_request_duration_seconds` stayed flat at
~2ms through all four stages — netem delays the wire, not the handler — while
checkout's climbed 69ms → 193 → 524 → 1296 → 2071ms in lockstep with the
stages. Consequence for the v2 feature design: a node's own server-side
latency cannot represent a delay fault on that node; the model must receive
caller-side latency (and the graph lets it attribute blame downward). A
per-edge dependency-latency histogram in `obs.py` would make root-cause
attribution for delay faults much easier — noted as a v2.1 candidate, not
built yet.

## Operational notes

* **Verify injection; never assume `kubectl apply` worked.** One run had the
  workflow accepted and running while no `NetworkChaos` object was ever created —
  latency stayed flat for a full 5 minutes. Poll for
  `.status.experiment.containerRecords[0].phase == "Injected"` before trusting a
  scenario window, and discard any window that cannot be confirmed.
* **Scale-to-zero is not a usable fault for data collection.** It deletes the pod,
  which resets every counter on it and removes it from Prometheus entirely. A
  vanished node is not the same as a stressed node, and a fixed adjacency matrix
  has no way to represent one. Use these ramps instead.
* **Stage duration must exceed the scrape interval by a wide margin.** At 30s
  scrape, the 5-minute stages give ~10 samples each. The earlier audit's ~5s
  faults produced 1-3 scrapes, which is noise inside a 12-step input window.
* **Smoke-testing:** compress with
  `sed 's/deadline: 5m/deadline: 60s/; s/deadline: 21m/deadline: 5m/'` to exercise
  all four stages in ~4 minutes. Collection runs use the uncompressed files.
* **Cleanup:** `kubectl delete workflow <name> -n default` removes the chaos and
  recovery is immediate — all four scenarios returned to baseline latency within
  one poll and left 12/12 pods ready.
