#!/usr/bin/env python3
"""Demo evidence table: actual SLO breach times vs monitor alarm times.

Fixes the conflation that produced two wrong lead-time claims (one in a
suggested demo plan, one in conversation): "static fired" is NOT "breached".
Ground truth is only the SLO clause set — the same one extraction uses:

    latency > max(mult x quiet_median, floor)   |   5xx > 0   |   err_in > 0

Breach times are computed from Prometheus via features_from_prometheus (the
single shared feature builder, so clause parity with the training labels is
by construction). Alarm times come from the monitor's tick log (the
authoritative clock — never a Grafana panel; Pushgateway restamps).

Usage (on the VM, venv or system python — stdlib only):
    python3 demo_evidence.py --ticks-log demo_20260819_0100.jsonl \
        --dataset telemetry_dataset_v2.json --prom http://localhost:30900

Window defaults to the tick log's span. Output: one evidence table, with
signed leads of each monitor vs each service's FIRST actual breach.
"""

import argparse
import json
from datetime import datetime, timezone

from extract_v2 import features_from_prometheus, NODE_MAP, STEP

LAT, ERR_IN = 4, 6          # feature channel indices (extract_v2 docstring)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def hms(ts):
    return iso(ts)[11:19]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks-log", required=True)
    ap.add_argument("--dataset", default="telemetry_dataset_v2.json",
                    help="source of SLO params + quiet-median baselines "
                         "(must match the checkpoint being demoed)")
    ap.add_argument("--prom", default="http://localhost:30900")
    ap.add_argument("--start", default="", help="ISO UTC, e.g. 2026-08-16T00:05; "
                                               "default: tick log span")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    ticks = [json.loads(l) for l in open(args.ticks_log) if l.strip()]
    if not ticks:
        raise SystemExit("empty tick log")
    parse = lambda s: int(datetime.strptime(s, "%Y-%m-%dT%H:%M")
                          .replace(tzinfo=timezone.utc).timestamp())
    t0 = parse(args.start) if args.start else ticks[0]["ts"]
    t1 = parse(args.end) if args.end else ticks[-1]["ts"]
    t0 = t0 // STEP * STEP

    d = json.load(open(args.dataset))
    slo = d["meta"]["slo"]
    mult, floor = slo["latency_mult"], slo["latency_floor_s"]
    base = d["baseline_latency_s"]
    thr = {n: max(mult * base[n], floor) for n in NODE_MAP}

    grid = list(range(t0, t1 + 1, STEP))
    feats, fivexx = features_from_prometheus(args.prom, grid)

    # first actual breach per service, with the clause that tripped it
    first_breach = {}
    for i, ts in enumerate(grid):
        for n_i, n in enumerate(NODE_MAP):
            if n in first_breach:
                continue
            lat = feats[i][n_i][LAT]
            clauses = []
            if lat > thr[n]:
                clauses.append("latency %.0fms>%.0fms" % (lat * 1e3, thr[n] * 1e3))
            if fivexx[i][n_i] > 0:
                clauses.append("5xx")
            if feats[i][n_i][ERR_IN] > 0:
                clauses.append("err_in")
            if clauses:
                first_breach[n] = (ts, ", ".join(clauses))

    in_win = [r for r in ticks if t0 <= r["ts"] <= t1]
    t_static = next((r["ts"] for r in in_win if r["static_fire"]), None)
    t_alarm = next((r["ts"] for r in in_win if r["alarm"]), None)
    peak = max(in_win, key=lambda r: r["max_prob"])

    print("window %s -> %s UTC   (SLO: latency>max(%.1fx quiet-median, %.0fms) | 5xx | err_in)"
          % (iso(t0), iso(t1), mult, floor * 1e3))
    print()
    print("%-10s %-22s %-10s" % ("MONITOR", "event", "time"))
    print("%-10s %-22s %-10s" % ("static", "first fire", hms(t_static) if t_static else "never"))
    print("%-10s %-22s %-10s" % ("model", "first alarm (tau)", hms(t_alarm) if t_alarm else "never"))
    print("%-10s %-22s %-10s  max_prob=%.3f  cause_top=%s"
          % ("model", "peak probability", hms(peak["ts"]), peak["max_prob"],
             peak["cause_top"][0] if peak.get("cause_top") else "-"))
    print()
    if not first_breach:
        print("NO ACTUAL SLO BREACH in window — any alarm above was a false "
              "alarm; any silence was correct discipline.")
        return
    print("%-30s %-9s %-28s %12s %12s" % ("SERVICE (first actual breach)",
                                          "time", "clause", "static lead", "model lead"))
    print("-" * 96)
    for n, (ts, why) in sorted(first_breach.items(), key=lambda kv: kv[1][0]):
        sl = "%+ds" % (ts - t_static) if t_static else "n/a"
        ml = "%+ds" % (ts - t_alarm) if t_alarm else "n/a"
        print("%-30s %-9s %-28s %12s %12s"
              % (n.replace("stylehub-", ""), hms(ts), why, sl, ml))
    print()
    print("positive lead = monitor spoke BEFORE the breach. Leads are vs each")
    print("service's own first breach; quote them per-service, never averaged.")


if __name__ == "__main__":
    main()
