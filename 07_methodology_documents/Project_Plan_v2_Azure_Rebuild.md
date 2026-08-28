# GEMS Project — Goal, Plan & Next Steps (v2 — Azure Rebuild)

**Written:** 16 August 2026
**Status:** Round 1 complete on laptop/Minikube. Round 2 (improved rebuild) in progress on Azure.
**Supersedes:** `Current_Experiment_Plan.md` (June 2026, historical record — do not delete).

---

## 1. The Research Goal

**Project title:** AI-Assisted Cascading Failure Prediction in Cloud Microservices (COMP40321).

**The goal in one sentence:**

> The system detects an upcoming microservice failure **before traditional threshold
> monitoring does**, and **names the responsible service** — using a GCN-LSTM that reasons
> over the service dependency graph.

**How the goal sharpened over Round 1:**

| Version | Claim | Status |
|---|---|---|
| Original (Ob3) | Predict latency breaches ≥2 minutes in advance | Retired — at that horizon the fault signal is not yet in the data; the model learned the experiment's 28-min schedule instead (P saturates at 0.26 regardless of fault severity) |
| Refined | Detect + localize different failure types across the environment | **Achieved and demonstrated live** (CPU, memory; delay conditionally) |
| Refined | Alert **before** tuned threshold monitoring | **Achieved**: offline +32 s mean over 80 events; live +70 s on CPU (reproduced twice) |
| **v2 (this round)** | Predict the **downstream cascade**: given graph state, will service B breach its SLO in the next N seconds, and which upstream service caused it | The version that actually matches the project title — Round 1 labelled only the injected service, never the propagation |

---

## 2. What Round 1 Delivered (the evidence base)

- 11-service StyleHub e-commerce app on Minikube; Chaos Mesh; Prometheus/Grafana;
  traffic generator driving real user journeys.
- **9.3 h dataset**: 3,361 samples × 11 services × 4 metrics; 4 fault scenarios × 20 cycles.
- GCN-LSTM (detection mode): F1 0.854–0.942, AUROC 0.966–0.970, HR@1 93–99%, HR@2 100%,
  inference 0.32 ms.
- **Live verified:** CPU stress (P=0.9999, correct service), memory (P=1.0000, correct
  service), network delay (conditional), lead time **+70 s vs tuned static threshold**.
- Runtime dependency-graph discovery (`depgraph.py` + `discover_topology.py`): 12 real
  edges found; **3 declared edges proven not to exist** in the code.
- Honest negatives, all measured: RF beats GNN on detection (AUROC 0.9998 vs 0.9658 — GNN's
  edge is localization); static threshold beats GNN on memory (−30 s); pod-kill undetectable
  once `pod_age` drifts past the training range.

## 3. What Round 1 Taught Us (why v2 exists)

**Experiment-design flaws:**
1. Fixed 28-min injection cycle → the model learns the clock (leaks into offline scores).
2. Step-function faults → no precursor exists, so "prediction in advance" is impossible by construction.
3. Only 3 of 11 services ever faulted → localization is a 3-class problem.
4. Labels mark the **injected** service only → cascades (frontend 2.4× during cart delay) are recorded but never labelled. The project never actually trained on a cascade.
5. Random split of overlapping sliding windows → 96.4% of test windows are ≥92% identical to a training window; offline scores measure fit, not generalization.
6. `pod_age` is absolute wall-clock age → saturates as the cluster outlives training (4.62× within 2 days), destroying pod-kill (−79 pp) and degrading delay (−26 pp).
7. 60 s scrape vs 30–70 s lead times → the effect is barely larger than the measurement unit.

**Application flaws (verified in code):**
8. Failure masking: checkout succeeds with payment/cart/shipping/email all dead (`except: pass`); cart silently falls back off Redis. Error cascades cannot exist.
9. No service exposes `/metrics`; no error-rate metric anywhere.
10. Graph too shallow: only frontend + checkout make outbound calls; recommendation is a stub.
11. Zero probes, zero resource requests/limits in all 11 Helm templates.
12. N+1 currency conversion → frontend "normal" latency 745 ms vs ~90 ms leaves.
13. Env-wiring fragility: two silent `localhost` fallback bugs (AD_URL, SHIPPING_SERVICE_URL).

**Infrastructure flaw:**
14. 8 GB laptop, minikube at 69% idle, ~1.45 GB headroom — collapsed once mid-experiment.

## 4. The v2 Plan

### Infrastructure — Azure (in progress)
- **Done:** `gems-vm` (D4s_v3, 4 vCPU/16 GB, uksouth, SSH-only), k3s + Helm installed,
  source transferred, 10/11 images built (`payment_service_node` is dead code — delete).
- **Remaining:** Prometheus + Grafana + Chaos Mesh + **Jaeger**; deploy StyleHub chart;
  parameterise hardcoded paths/`localhost` URLs in scripts; end-to-end smoke test.
- Cost discipline: ~$0.19/hr; **deallocate between sessions** (`az vm deallocate`).

### Application improvements (agreed, not yet started)
- **Phase 1 — failure observability:** critical dependencies (payment, cart, catalog) return
  real 502s; graceful degradation only for ads/recommendations, as a documented choice.
  `service_dependency_errors_total` counter. Shared `/metrics` for all services.
  Fix the N+1 currency conversion. **OpenTelemetry auto-instrumentation → Jaeger**
  (traces = ground truth & demo; model input stays metrics-only, preserving the
  lit-review overhead argument and the 0.32 ms inference claim).
- **Phase 2 — deepen the graph:** implement the 3 phantom edges for real
  (recommendation→catalog, checkout→currency, checkout→catalog).
- **Phase 3 — K8s hygiene:** probes on all 11; resource requests + memory limits
  (gives memory-stress a defined OOM failure mode); keep replicas=1 deliberately.
- **Phase 4 — fragility removal:** startup logging of resolved dependency URLs with loud
  warning on `localhost` fallback; single TIMEOUT policy; delete dead service.

### Experiment redesign (the core scientific fix)
| Round 1 | Round 2 |
|---|---|
| Fixed 28-min cycle | **Randomised injection timing** |
| Step-function faults | **Ramped faults** (progressive CPU/memory) → real precursors |
| 3 of 11 services faulted | **Rotate across all 11** |
| Label = injected service only | **Cascade labels:** every SLO-breaching service labelled, origin = root cause |
| Random split | **Temporal split** (train early hours, test late) |
| 60 s scrape | **30 s** (not 15 — half the memory cost, adequate for 30–70 s leads) |
| Absolute `pod_age` | **Capped/relative encoding** |
| Hardcoded topology (3 phantom edges) | **Discovered topology** |
| No quiet baseline (0 samples ≥30 steps from anomaly) | **Long genuine quiet periods** |
| ~9 h collection | **~12–15 h**, unattended on the VM |

### Evaluation standards (locked in from Round 1 lessons)
- Always report false-alarm rate next to recall; never a baseline that fires >90% of the time.
- AUROC alongside F1; RF baseline always; temporal split as primary result.
- Lead time measured at real timestamps, per event, vs the **tuned** static baseline.

## 5. What We Are Doing Next (in order)

1. **Phase 1 + 2 application changes** — awaiting explicit go-ahead (rewrites app behaviour).
2. Rebuild images on the VM; deploy StyleHub + Prometheus + Grafana + Chaos Mesh + Jaeger.
3. Parameterise scripts (`--prometheus-url` everywhere; remove `/Users/gunadeep/...` paths).
4. Smoke test: SSH tunnel, telemetry flowing, one chaos injection, one trace in Jaeger.
5. Ramped-fault chaos manifests + randomised scheduler; verified return-to-baseline gates.
6. **12–15 h collection run** (unattended, `docker stats`-monitored, abort >85% memory).
7. Cascade relabelling + temporal split + retrain + full evaluation.
8. Out-of-distribution live tests (fault services never faulted in training).

**Parallel tracks (laptop, unaffected by the rebuild):**
- The Round 1 demo stays intact for the supervisor: CPU lead-time race (+70 s), blind
  memory localization, topology discovery. Re-rehearse on the day; `pod_age` reset to
  in-range by the reboot.
- **Dissertation writing is the dominant remaining work** (~20% done; all results material
  now exists). Fix the 9 wrong citations + duplicate paper in the lit review.
- Ob5 (SRE handbook) — feed it the Round 1 findings: pod_age non-stationarity, baseline
  false-alarm audits, chaos spacing rules, env-wiring validation.

---

*Round 1 proved the system works and taught us exactly why its hardest claim didn't.
Round 2 rebuilds the experiment so that claim can be tested honestly — on infrastructure
that can't fall over, with an application that's allowed to fail.*
