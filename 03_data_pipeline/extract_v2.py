#!/usr/bin/env python3
"""v2 telemetry extraction: Prometheus + chaos ground truth -> training dataset.

Consumes a collection run's chaos_ground_truth.jsonl (the labels' source of
truth) and the cluster's Prometheus, and emits telemetry_dataset_v2.json on a
30s grid aligned to the scrape interval.

Contract with the scheduler (Chaos_Scheduler_Plan.md §8G):
  * fault windows come only from episodes with status "completed", using the
    OBSERVED stage timestamps, never the intended schedule;
  * negative windows come only from explicit "quiet" records (which the
    scheduler writes only after confirmed recovery);
  * anything else (apply/verify/cleanup slack, failed episodes) is phase
    "slack" and must be excluded from both classes by the trainer.

Lessons this file encodes (all measured, see v2_ramped/README.md):
  * counters are diffed CLIENT-SIDE per raw series with reset handling —
    increase() under-reports series born inside the query window;
  * a delayed service's own histogram never sees the delay (netem delays the
    wire, not the handler), so per-node latency is each service's server-side
    view and the callers carry the fault signal — the GCN's job is to
    attribute it down the edge;
  * pod_age is capped at 30min — Round 1's uncapped age saturated;
  * SLO breach is EMPIRICAL: latency > max(5 x quiet-median, 0.5s), or any
    5xx, or any inbound dependency error. The injection schedule never defines
    a breach directly; payment-delay (zero errors by design) still labels
    through the latency clause on its callers.

Feature vector per node per step (F=7):
  0 cpu_cores      rate(container_cpu_usage_seconds_total[2m])   (cadvisor)
  1 mem_mib        container_memory_working_set_bytes            (cadvisor)
  2 pod_age_min    min(now - container_start_time_seconds, 30m)  (cadvisor)
  3 req_rate       sum by service rate(http_requests_total[2m])
  4 req_latency_s  rate(duration_sum)/rate(duration_count) by service
  5 err_out_rate   outbound dependency errors/s (client-side diff)
  6 err_in_rate    inbound  dependency errors/s (client-side diff)

`features_from_prometheus()` is the ONLY place features are built — the live
monitor imports it, so training and serving cannot drift apart (the Round 1
live failure was exactly such a drift). Stdlib only; runs on the VM.
"""

import argparse
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone

NODE_MAP = [
    "stylehub-frontend",
    "stylehub-ad-service",
    "stylehub-cart-service",
    "stylehub-checkout-service",
    "stylehub-currency-service",
    "stylehub-email-service",
    "stylehub-payment-service",
    "stylehub-product-catalog-service",
    "stylehub-recommendation-service",
    "stylehub-shipping-service",
    "stylehub-redis",
]
NODE_IDX = {n: i for i, n in enumerate(NODE_MAP)}
SCENARIOS = ["catalog-cpu-ramp", "cart-mem-ramp", "redis-delay-ramp",
             "payment-delay-ramp", "pod-kill",
             # Night B magnitude ladder — appended so the indices of the five
             # original scenarios stay stable across datasets. Pooling across
             # datasets must still map scenarios BY NAME via meta.scenarios,
             # never by raw index.
             "catalog-cpu-ramp-light",
             "cart-mem-ramp-light", "cart-mem-ramp-heavy",
             "redis-delay-ramp-light", "redis-delay-ramp-heavy",
             "payment-delay-ramp-light", "payment-delay-ramp-heavy"]
STEP = 30
CAP_AGE_MIN = 30.0
# v2.1 labels (Step1_SLO_Relabel_Plan.md). The v2 definition was
# max(5 x quiet-median, 0.5s): the 0.5s floor dominated every service, so
# checkout (76ms baseline) breached at ~6.6x its baseline while cart (2.5ms)
# needed ~200x — services graded on different curves. Now every service
# breaches at the same relative distortion (10x its own quiet-median), with a
# 100ms floor only because sub-100ms latency is not user-perceptible harm.
SLO_LAT_MULT = 10.0
SLO_LAT_FLOOR_S = 0.1
LABEL_VERSION = "v2.1"
F = 7
FEATURE_NAMES = ["cpu_cores", "mem_mib", "pod_age_min", "req_rate",
                 "req_latency_s", "err_out_rate", "err_in_rate"]


def prom_range(prom, query, start, end, step=STEP):
    url = "%s/api/v1/query_range?%s" % (prom, urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}))
    with urllib.request.urlopen(url, timeout=120) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise RuntimeError("prometheus error for %s: %s" % (query[:60], data))
    return data["data"]["result"]


def pod_to_node(pod):
    for n in sorted(NODE_MAP, key=len, reverse=True):
        if pod.startswith(n + "-"):
            return n
    return None


def series_to_grid(series, grid):
    """{ts: value} for one series, restricted to grid timestamps."""
    gset = set(grid)
    return {int(float(t)): float(v) for t, v in series["values"]
            if int(float(t)) in gset and v != "NaN"}


def counter_deltas(raw_series, grid, key_labels):
    """Client-side counter diff per raw series (reset- and birth-safe),
    summed into {key: {ts: delta}} where key = tuple of key_labels values."""
    out = {}
    for s in raw_series:
        key = tuple(s["metric"].get(l, "") for l in key_labels)
        vals = series_to_grid(s, grid)
        prev = None
        acc = out.setdefault(key, {})
        for ts in grid:
            if ts not in vals:
                prev = vals.get(ts, prev)
                continue
            cur = vals[ts]
            if prev is not None:
                d = cur - prev if cur >= prev else cur  # reset -> count from 0
                if d > 0:
                    acc[ts] = acc.get(ts, 0.0) + d
            prev = cur
    return out


def features_from_prometheus(prom, grid):
    """Build (features [T][N][F], fivexx [T][N]) on an aligned 30s grid.

    Shared verbatim between extraction and the live monitor — any change here
    changes BOTH training data and serving, never one of them.
    """
    T, N = len(grid), len(NODE_MAP)
    t0, t1 = grid[0], grid[-1]
    gi = {ts: i for i, ts in enumerate(grid)}
    feats = [[[0.0] * F for _ in range(N)] for _ in range(T)]
    fivexx = [[0.0] * N for _ in range(T)]

    # -- cadvisor: cpu / mem / age (per pod -> node) ------------------------
    cad = 'container_cpu_usage_seconds_total{namespace="default",container!="",container!="POD",pod=~"stylehub-.*"}'
    for s in prom_range(prom, "rate(%s[2m])" % cad, t0, t1):
        node = pod_to_node(s["metric"].get("pod", ""))
        if node is None:
            continue
        for ts, v in series_to_grid(s, grid).items():
            feats[gi[ts]][NODE_IDX[node]][0] += v
    mem = 'container_memory_working_set_bytes{namespace="default",container!="",container!="POD",pod=~"stylehub-.*"}'
    for s in prom_range(prom, mem, t0, t1):
        node = pod_to_node(s["metric"].get("pod", ""))
        if node is None:
            continue
        for ts, v in series_to_grid(s, grid).items():
            feats[gi[ts]][NODE_IDX[node]][1] += v / 2**20
    age = 'container_start_time_seconds{namespace="default",container!="",container!="POD",pod=~"stylehub-.*"}'
    for s in prom_range(prom, age, t0, t1):
        node = pod_to_node(s["metric"].get("pod", ""))
        if node is None:
            continue
        for ts, v in series_to_grid(s, grid).items():
            cur = feats[gi[ts]][NODE_IDX[node]][2]
            a = min(max(ts - v, 0.0) / 60.0, CAP_AGE_MIN)
            feats[gi[ts]][NODE_IDX[node]][2] = a if cur == 0.0 else min(cur, a)

    # -- app metrics by the stable `service` label --------------------------
    for s in prom_range(prom, 'sum by (service)(rate(http_requests_total[2m]))', t0, t1):
        n = NODE_IDX.get(s["metric"].get("service", ""))
        if n is None:
            continue
        for ts, v in series_to_grid(s, grid).items():
            feats[gi[ts]][n][3] = v
    for s in prom_range(prom, 'sum by (service)(rate(http_requests_total{status=~"5.."}[2m]))', t0, t1):
        n = NODE_IDX.get(s["metric"].get("service", ""))
        if n is None:
            continue
        for ts, v in series_to_grid(s, grid).items():
            fivexx[gi[ts]][n] = v
    lat_num = prom_range(prom, 'sum by (service)(rate(http_request_duration_seconds_sum[2m]))', t0, t1)
    lat_den = prom_range(prom, 'sum by (service)(rate(http_request_duration_seconds_count[2m]))', t0, t1)
    den_map = {s["metric"].get("service", ""): series_to_grid(s, grid) for s in lat_den}
    for s in lat_num:
        svc = s["metric"].get("service", "")
        n = NODE_IDX.get(svc)
        if n is None:
            continue
        dens = den_map.get(svc, {})
        for ts, v in series_to_grid(s, grid).items():
            d = dens.get(ts, 0.0)
            if d > 1e-9:
                feats[gi[ts]][n][4] = v / d

    # -- dependency error counters: client-side diffs -----------------------
    err_raw = prom_range(prom, "service_dependency_errors_total", t0, t1)
    err_d = counter_deltas(err_raw, grid, ["source", "target", "instance"])
    for (src, tgt, _inst), deltas in err_d.items():
        si, ti = NODE_IDX.get(src), NODE_IDX.get(tgt)
        for ts, d in deltas.items():
            if si is not None:
                feats[gi[ts]][si][5] += d / STEP
            if ti is not None:
                feats[gi[ts]][ti][6] += d / STEP
    return feats, fivexx


def edges_from_prometheus(prom, grid):
    """Directed (source, target) pairs observed carrying call traffic."""
    call_raw = prom_range(prom, "service_dependency_calls_total",
                          grid[0], grid[-1])
    call_d = counter_deltas(call_raw, grid, ["source", "target"])
    return sorted({(s, t) for (s, t), d in call_d.items()
                   if s in NODE_IDX and t in NODE_IDX and sum(d.values()) > 0})


def resolve_prom():
    ip = subprocess.run(
        ["kubectl", "get", "svc", "-n", "monitoring", "prometheus-server",
         "-o", "jsonpath={.spec.clusterIP}"],
        capture_output=True, text=True, check=True).stdout.strip()
    return "http://%s:80" % ip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, help="chaos_ground_truth.jsonl")
    ap.add_argument("--out", default="telemetry_dataset_v2.json")
    ap.add_argument("--prom", default="",
                    help="Prometheus base URL; default: resolve ClusterIP via kubectl")
    args = ap.parse_args()

    prom = args.prom or resolve_prom()
    print("prometheus:", prom)

    recs = [json.loads(l) for l in open(args.log)]
    header = next(r for r in recs if r["type"] == "run_header")
    footer = next(r for r in recs if r["type"] == "run_footer")
    eps = [r for r in recs if r["type"] == "episode"]
    quiets = [r for r in recs if r["type"] == "quiet"]

    t0 = int(header["ts"] // STEP * STEP) + STEP
    t1 = int(footer["ts"] // STEP * STEP)
    grid = list(range(t0, t1 + 1, STEP))
    T, N = len(grid), len(NODE_MAP)
    print("grid: %d steps of %ds (%s -> %s UTC)" % (
        T, STEP,
        datetime.fromtimestamp(t0, timezone.utc).strftime("%H:%M"),
        datetime.fromtimestamp(t1, timezone.utc).strftime("%H:%M")))

    feats, fivexx = features_from_prometheus(prom, grid)
    edges = edges_from_prometheus(prom, grid)
    print("edges observed: %d" % len(edges))

    # -- context per step ---------------------------------------------------
    ep_id = [0] * T
    scen = [-1] * T
    target = [-1] * T
    stage = [0] * T
    phase = ["slack"] * T   # fault | quiet | slack
    for e in eps:
        if e["status"] != "completed":
            continue
        end = e.get("recovery_confirmed_ts") or e.get("cleanup_confirmed_ts")
        sidx = SCENARIOS.index(e["scenario"])
        tidx = NODE_IDX.get(e["target"], -1)
        # window extends one step past recovery: a counter delta lands on the
        # NEXT 30s boundary, so an error burst in the episode's final seconds
        # would otherwise be misfiled into the following quiet window (seen
        # with pod-kill, whose whole outage fits between two scrapes)
        for i, ts in enumerate(grid):
            if e["applied_ts"] <= ts <= end + STEP:
                ep_id[i], scen[i], target[i], phase[i] = \
                    e["episode_id"], sidx, tidx, "fault"
        for st in e["stages"]:
            stg = 5 if st["stage"] == "kill" else int(st["stage"])
            for i, ts in enumerate(grid):
                if st["start_ts"] <= ts <= st["end_ts"]:
                    stage[i] = stg
    for q in quiets:
        # first step of each gap skipped for the same boundary reason
        for i, ts in enumerate(grid):
            if q["start_ts"] + STEP <= ts <= q["end_ts"] and phase[i] == "slack":
                phase[i] = "quiet"

    # -- empirical SLO breach ----------------------------------------------
    quiet_idx = [i for i in range(T) if phase[i] == "quiet"]
    baselines = {}
    for n, name in enumerate(NODE_MAP):
        xs = sorted(feats[i][n][4] for i in quiet_idx if feats[i][n][4] > 0)
        baselines[name] = xs[len(xs) // 2] if xs else 0.0
    # clause bitmask per node-step: 1=latency, 2=5xx, 4=err_in, 8=restart.
    # Persisted so future label experiments run offline, immune to TSDB
    # retention, and so every label is auditable back to the clause that set it.
    breach = [[0] * N for _ in range(T)]
    clauses = [[0] * N for _ in range(T)]
    for i in range(T):
        for n, name in enumerate(NODE_MAP):
            slo = max(SLO_LAT_MULT * baselines[name], SLO_LAT_FLOOR_S)
            c = 0
            if feats[i][n][4] > slo:
                c |= 1
            if fivexx[i][n] > 0:
                c |= 2
            if feats[i][n][6] > 0:
                c |= 4
            # availability (new in v2.1): a pod restart IS user-facing harm even
            # when it lands between scrapes. pod_age advances +0.5/step and only
            # moves backwards on a container restart; a drop > 0.6 min is the
            # reset marker. The step BEFORE the reset (the kill itself) is
            # labelled too — that is when the harm actually happened.
            if i > 0:
                age_now, age_prev = feats[i][n][2], feats[i - 1][n][2]
                # age_now > 0 guards against a missing scrape (default 0.0)
                # masquerading as a reset
                if age_prev > 0 and 0 < age_now < age_prev - 0.6:
                    c |= 8
                    clauses[i - 1][n] |= 8
                    breach[i - 1][n] = 1
            clauses[i][n] |= c
            if clauses[i][n]:
                breach[i][n] = 1

    # -- sanity summary -----------------------------------------------------
    print("phase counts:", {p: phase.count(p) for p in ("fault", "quiet", "slack")})
    qb = sum(breach[i][n] for i in quiet_idx for n in range(N))
    print("breaches inside quiet windows: %d node-steps (must be ~0)" % qb)
    print("per-scenario breach node-steps (by breached node) and clause mix:")
    BITS = {1: "latency", 2: "5xx", 4: "err_in", 8: "restart"}
    for s_i, s_name in enumerate(SCENARIOS):
        idxs = [i for i in range(T) if scen[i] == s_i]
        by_node, mix = {}, {}
        for i in idxs:
            for n in range(N):
                if breach[i][n]:
                    short = NODE_MAP[n].replace("stylehub-", "").replace("-service", "")
                    by_node[short] = by_node.get(short, 0) + 1
                    for b, bn in BITS.items():
                        if clauses[i][n] & b:
                            mix[bn] = mix.get(bn, 0) + 1
        print("  %-22s fault_steps=%4d breaches=%s" %
              (s_name, len(idxs), by_node or "{}"))
        if mix:
            print("  %22s clauses: %s" % ("", mix))
    # honesty check on catalog-cpu: did latency move at all under the ramp?
    cat = NODE_IDX["stylehub-product-catalog-service"]
    cat_lat = [feats[i][cat][4] for i in range(T)
               if scen[i] == SCENARIOS.index("catalog-cpu-ramp")]
    if cat_lat:
        print("catalog latency inside catalog-cpu windows: max=%.0fms mean=%.0fms "
              "(baseline %.0fms, breach floor %.0fms)" %
              (max(cat_lat) * 1000, sum(cat_lat) / len(cat_lat) * 1000,
               baselines["stylehub-product-catalog-service"] * 1000,
               max(SLO_LAT_MULT * baselines["stylehub-product-catalog-service"],
                   SLO_LAT_FLOOR_S) * 1000))
    missing = sum(1 for i in range(T) for n in range(N)
                  if feats[i][n][1] == 0.0)
    print("node-steps with zero memory reading: %d of %d" % (missing, T * N))

    out = {
        "meta": {
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": header["run_id"], "seed": header["seed"],
            "source_log": args.log, "step_s": STEP,
            "grid_start": t0, "grid_end": t1,
            "feature_names": FEATURE_NAMES,
            "label_version": LABEL_VERSION,
            "slo": {"latency_mult": SLO_LAT_MULT, "latency_floor_s": SLO_LAT_FLOOR_S,
                    "clauses": "latency>max(mult*quiet_median,floor) | 5xx>0 | "
                               "err_in>0 | pod_age reset (restart)",
                    "clause_bits": {"1": "latency", "2": "5xx",
                                    "4": "err_in", "8": "restart"}},
            "scenarios": SCENARIOS,
            "phase_legend": "fault=inside completed episode; quiet=explicit gap; "
                            "slack=everything else — exclude from both classes",
        },
        "nodes": NODE_MAP,
        "edges": [list(e) for e in edges],
        "baseline_latency_s": baselines,
        "timestamps": grid,
        "features": feats,
        "fivexx": fivexx,
        "breach": breach,
        "breach_clauses": clauses,
        "context": {"episode_id": ep_id, "scenario": scen,
                    "target": target, "stage": stage, "phase": phase},
    }
    with open(args.out, "w") as f:
        json.dump(out, f)
    print("wrote %s (%.1f MB)" % (args.out,
          len(json.dumps(out)) / 1e6))


if __name__ == "__main__":
    main()
