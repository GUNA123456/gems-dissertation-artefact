#!/usr/bin/env python3
"""Step 3b — is the post-fault alarm tail insight or window drain?

Observed: after a fault clears, the static racer goes quiet immediately but
the model holds its alarm ~3.5 min. seq_len is 12 x 30s = 6 min, so for that
entire period the input window still CONTAINS fault steps. Until the two are
separated, the tail cannot be claimed as "the model knows danger persists".

Counterfactual per recovery tick t (fault over, window still contaminated):
    actual:         P( X[t-11 .. t] )
    counterfactual: same window, but every step inside the fault episode is
                    replaced by the pre-fault quiet profile (mean of the 6
                    steps before the episode started, per node) — i.e. "what
                    would the model say if the fault had never been seen?"

Pre-registered expectation (Current_Experiment_Plan.md Step 3b): the tail is
drain — counterfactual probability collapses to resting. If instead it stays
elevated, the model is reading lingering post-fault state (e.g. pod_age,
memory) and the tail is a finding.

Run on the laptop under GEMS_Model_Sandbox/venv.
"""
import json

import numpy as np
import torch

from train_gnn import normalize_per_feature_global
from train_v2 import CascadeGCNLSTM, build_adj

CKPT, DATA = "gems_model_v2.pt", "telemetry_dataset_v2.json"
PRE_STEPS = 6                     # quiet profile = mean of these, pre-episode

c = torch.load(CKPT, map_location="cpu", weights_only=False)
d = json.load(open(DATA))
L = c["seq_len"]
f = np.asarray(d["features"], dtype=np.float32)
ep = d["context"]["episode_id"]
sc = d["context"]["scenario"]
SCEN = d["meta"]["scenarios"]

model = CascadeGCNLSTM(len(c["nodes"]), len(c["feature_names"]),
                       c["gcn_hidden"], c["lstm_hidden"])
model.load_state_dict(c["state_dict"])
model.eval()
adj = build_adj(c["nodes"], c["edges"])


def prob(window):
    X = window.copy()
    X[..., c["log_channels"]] = np.log1p(X[..., c["log_channels"]] * c["log_scale"])
    X = normalize_per_feature_global(X, c["feature_min"], c["feature_max"])
    with torch.no_grad():
        bl, _ = model(torch.from_numpy(X[None]), adj)
        return float(torch.sigmoid(bl)[0].numpy().max())


episodes = {}
for i, e in enumerate(ep):
    if e:
        episodes.setdefault(e, []).append(i)

rows = []
print("ep  scenario            k  actual  counterfactual  alarm(act/cf)")
print("-" * 66)
for e, idx in sorted(episodes.items()):
    i0, i1 = idx[0], idx[-1]
    if i0 < PRE_STEPS + L:
        continue
    quiet = f[i0 - PRE_STEPS:i0].mean(axis=0)            # [N, F] pre-fault profile
    fault_set = set(idx)
    ep_alarmed = False
    for k in range(1, L):                                # tail: fault still in window
        t = i1 + k
        if t >= len(f) or ep[t] != 0:
            break
        win = f[t - L + 1:t + 1]
        p_act = prob(win)
        if k == 1 and p_act <= c["tau"]:
            break                                        # no tail to explain
        ep_alarmed = True
        cf = win.copy()
        for j, step in enumerate(range(t - L + 1, t + 1)):
            if step in fault_set:
                cf[j] = quiet
        p_cf = prob(cf)
        rows.append((k, p_act, p_cf))
        print("%-3d %-18s %2d  %6.3f  %14.3f  %s/%s"
              % (e, SCEN[sc[i0]], k, p_act, p_cf,
                 "A" if p_act > c["tau"] else "-",
                 "A" if p_cf > c["tau"] else "-"))
    if ep_alarmed:
        print()

if rows:
    r = np.asarray(rows)
    act_alarm = (r[:, 1] > c["tau"]).sum()
    cf_alarm = (r[:, 2] > c["tau"]).sum()
    print("VERDICT over %d tail ticks (tau=%.3f):" % (len(rows), c["tau"]))
    print("  alarms held  — actual: %d   counterfactual: %d" % (act_alarm, cf_alarm))
    print("  mean max_prob — actual: %.3f   counterfactual: %.3f"
          % (r[:, 1].mean(), r[:, 2].mean()))
    if cf_alarm == 0:
        print("  -> TAIL IS WINDOW DRAIN (pre-registered expectation confirmed):")
        print("     remove the fault from the window and every alarm vanishes.")
    else:
        print("  -> tail NOT fully explained by drain: %d counterfactual alarms"
              % cf_alarm)
        print("     survive — the model is reading lingering post-fault state.")
else:
    print("no post-fault tail ticks found above tau")
