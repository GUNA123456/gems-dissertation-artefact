#!/usr/bin/env python3
"""Step-1 gates: v2 vs v2.1 label comparison against pre-registered expectations."""
import json
import sys

v2 = json.load(open(sys.argv[1]))
v21 = json.load(open(sys.argv[2]))

print("== gate: only labels may differ ==")
same_feat = v2["features"] == v21["features"]
same_ts = v2["timestamps"] == v21["timestamps"]
print("  features identical: %s | timestamps identical: %s  -> %s"
      % (same_feat, same_ts, "PASS" if same_feat and same_ts else "FAIL"))

nodes = v21["nodes"]
N = len(nodes)
T = len(v21["timestamps"])
ph = v21["context"]["phase"]
sc = v21["context"]["scenario"]
SC = v21["meta"]["scenarios"]
b2, b21 = v2["breach"], v21["breach"]
cl = v21["breach_clauses"]
BITS = {1: "latency", 2: "5xx", 4: "err_in", 8: "restart"}

q2 = sum(b2[i][n] for i in range(T) for n in range(N) if ph[i] == "quiet")
q21 = sum(b21[i][n] for i in range(T) for n in range(N) if ph[i] == "quiet")
print("\n== gate: quiet noise ==")
print("  quiet breach node-steps: v2=%d  v2.1=%d  (gate <10) -> %s"
      % (q2, q21, "PASS" if q21 < 10 else "FAIL"))

cat = SC.index("catalog-cpu-ramp")
c21 = sum(b21[i][n] for i in range(T) for n in range(N) if sc[i] == cat)
print("\n== gate: discipline (catalog-cpu must stay zero) ==")
print("  catalog-cpu breaches: v2.1=%d -> %s" % (c21, "PASS" if c21 == 0 else "FAIL"))

print("\n== per-scenario label counts, v2 -> v2.1 (with v2.1 clause mix) ==")
for s_i, s_name in enumerate(SC):
    idxs = [i for i in range(T) if sc[i] == s_i]
    n2 = sum(b2[i][n] for i in idxs for n in range(N))
    n21 = sum(b21[i][n] for i in idxs for n in range(N))
    mix = {}
    for i in idxs:
        for n in range(N):
            for b, bn in BITS.items():
                if cl[i][n] & b:
                    mix[bn] = mix.get(bn, 0) + 1
    print("  %-22s %4d -> %4d   %s" % (s_name, n2, n21, mix or ""))

print("\n== restart-clause audit: which node-steps got the new availability label ==")
from datetime import datetime, timezone
ts = v21["timestamps"]
for i in range(T):
    for n in range(N):
        if cl[i][n] & 8:
            print("  %s %-34s scenario=%s" % (
                datetime.fromtimestamp(ts[i], timezone.utc).strftime("%H:%M:%S"),
                nodes[n], SC[sc[i]] if sc[i] >= 0 else "quiet/slack"))

tot2 = sum(map(sum, b2))
tot21 = sum(map(sum, b21))
print("\ntotal breach node-steps: v2=%d -> v2.1=%d" % (tot2, tot21))
