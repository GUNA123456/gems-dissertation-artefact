#!/usr/bin/env python3
"""Phase F morning audit for a collection run: census, restart accounting,
heartbeat anomalies, and Prometheus cross-checks of sampled episodes."""
import json
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone

RUNLOG = sys.argv[1]
recs = [json.loads(l) for l in open(RUNLOG)]
eps = [r for r in recs if r["type"] == "episode"]
hbs = [r for r in recs if r["type"] == "heartbeat"]
quiets = [r for r in recs if r["type"] == "quiet"]
footer = next(r for r in recs if r["type"] == "run_footer")

iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S")

print("== 1. footer ==")
print("  reason=%r episodes=%s clean=%s pods=%s" %
      (footer["reason"], footer["episodes"], footer["final_clean"],
       footer["final_pods_ready"]))

print("== 2. census / statuses ==")
bad = [e for e in eps if e["status"] != "completed"]
print("  episodes=%d, non-completed=%d" % (len(eps), len(bad)))
for e in bad:
    print("   !! ep%s %s -> %s: %s" %
          (e["episode_id"], e["scenario"], e["status"], e.get("notes", "")))
ramp_eps = [e for e in eps if e["scenario"] != "pod-kill"]
partial = [e for e in ramp_eps
           if sum(1 for s in e["stages"] if s["phase"] == "Injected") != 4]
print("  ramp episodes with !=4 injected stages: %d" % len(partial))

print("== 3. quiet gaps ==")
mins = [(q["end_ts"] - q["start_ts"]) / 60 for q in quiets]
print("  n=%d min=%.1f max=%.1f mean=%.1f (floor must be >=8 except final cutoff)"
      % (len(mins), min(mins), max(mins), sum(mins) / len(mins)))

print("== 4. heartbeat anomalies (pods<12) ==")
anom = [h for h in hbs if 0 <= h["pods_ready"] < 12]
print("  %d of %d heartbeats; times:" % (len(anom), len(hbs)),
      [h["iso"][11:19] for h in anom])
# correlate each anomaly with the episode running at that time
for h in anom:
    t = h["ts"]
    owner = next((e for e in eps
                  if e["applied_ts"] - 30 <= t <=
                  e.get("recovery_confirmed_ts", e["applied_ts"] + 1200) + 30), None)
    print("    %s -> during ep%s (%s)" %
          (h["iso"][11:19], owner and owner["episode_id"], owner and owner["scenario"]))

print("== 5. restart accounting ==")
out = subprocess.run(
    ["kubectl", "get", "pods", "-n", "default", "-o", "json"],
    capture_output=True, text=True).stdout
n_oom = sum(1 for e in eps if e["scenario"] == "cart-mem-ramp")
for p in json.loads(out)["items"]:
    cs = p["status"]["containerStatuses"][0]
    if cs["restartCount"] > 0:
        last = cs.get("lastState", {}).get("terminated", {})
        print("  %-45s restarts=%d last=%s@%s" %
              (p["metadata"]["name"], cs["restartCount"],
               last.get("reason", "?"), last.get("finishedAt", "?")))
print("  expected: cart restarts ~= %d (one OOMKill per cart-mem episode)" % n_oom)

# ---- Prometheus cross-checks --------------------------------------------
def prom_range(query, start, end, step=30):
    url = ("http://localhost:9090/api/v1/query_range?query=%s&start=%d&end=%d&step=%d"
           % (urllib.parse.quote(query), start, end, step))
    out = subprocess.run(
        ["kubectl", "exec", "-n", "monitoring", "deploy/prometheus-server",
         "-c", "prometheus-server", "--", "wget", "-qO-", url],
        capture_output=True, text=True, timeout=60).stdout
    return json.loads(out)["data"]["result"]

def stage_means(series, stages):
    vals = [(float(t), float(v)) for s in series for t, v in s["values"]]
    outp = {}
    for st in stages:
        xs = [v for t, v in vals if st["start_ts"] <= t <= st["end_ts"]]
        if xs:
            outp[st["stage"]] = sum(xs) / len(xs)
    return outp

print("== 6. Prometheus cross-check: last redis-delay episode ==")
ep = [e for e in eps if e["scenario"] == "redis-delay-ramp"][-1]
q = ('sum(rate(http_request_duration_seconds_sum{app="stylehub-cart-service"}[2m]))'
     '/sum(rate(http_request_duration_seconds_count{app="stylehub-cart-service"}[2m]))')
r = prom_range(q, int(ep["applied_ts"]) - 300, int(ep["cleanup_confirmed_ts"]) + 60)
means = stage_means(r, ep["stages"])
print("  ep%s %s-%s — cart avg latency per stage:" %
      (ep["episode_id"], iso(ep["applied_ts"]), iso(ep["cleanup_confirmed_ts"])))
for st in ep["stages"]:
    m = means.get(st["stage"])
    print("    stage %s (%-12s): %s" %
          (st["stage"], st["params"], "%.0f ms" % (m * 1000) if m else "no samples"))

print("== 7. Prometheus cross-check: last cart-mem episode ==")
ep = [e for e in eps if e["scenario"] == "cart-mem-ramp"][-1]
q = ('container_memory_working_set_bytes{pod=~"stylehub-cart-service.*",'
     'container="cart-service"}')
r = prom_range(q, int(ep["applied_ts"]) - 60, int(ep["cleanup_confirmed_ts"]) + 60)
means = stage_means(r, ep["stages"])
print("  ep%s — cart working set per stage (expect ~157/202/248MiB then OOM drop):" %
      ep["episode_id"])
for st in ep["stages"]:
    m = means.get(st["stage"])
    print("    stage %s: %s" %
          (st["stage"], "%.0f MiB" % (m / 2**20) if m else "no samples"))

print("== AUDIT COMPLETE ==")
