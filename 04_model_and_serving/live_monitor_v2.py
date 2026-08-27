#!/usr/bin/env python3
"""Live v2 inference monitor: the trained cascade model, ticking against the
real cluster every 30s, side by side with the honestly-budgeted static racer.

Train/serve parity by construction (Live_Monitor_v2_Plan.md):
  * features come from extract_v2.features_from_prometheus — the SAME function
    that built the training dataset, never a reimplementation;
  * every constant (normalization bounds, log channels, tau, static thresholds
    and their fair-budget multiplier, model dims, node order) is loaded from
    the checkpoint, never recomputed and never hard-coded.

Modes:
  live (default)          tick every 30s against now
  --replay START END      tick through a historical window (ISO UTC, e.g.
                          2026-08-15T07:00). With --compare-dataset FILE, each
                          tick is also computed from the dataset's stored
                          features and the max probability difference reported
                          — the gate that proves live features == training
                          features.

Each tick appends one JSON line to --ticks-log (evidence for the demo).
"""

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import torch

from extract_v2 import features_from_prometheus, NODE_MAP, STEP
from train_gnn import normalize_per_feature_global
from train_v2 import CascadeGCNLSTM, build_adj

WARMUP_STEPS = 7   # extra grid steps so client-side counter diffs have a prev


def short(n):
    return n.replace("stylehub-", "").replace("-service", "")


def load_checkpoint(path):
    c = torch.load(path, map_location="cpu", weights_only=False)
    model = CascadeGCNLSTM(len(c["nodes"]), len(c["feature_names"]),
                           c["gcn_hidden"], c["lstm_hidden"])
    model.load_state_dict(c["state_dict"])
    model.eval()
    adj = build_adj(c["nodes"], c["edges"])
    if c["nodes"] != NODE_MAP:
        raise SystemExit("checkpoint node order != extract_v2.NODE_MAP")
    return c, model, adj


def infer_window(c, model, adj, window):
    """window: raw features [seq_len, N, F] -> (breach probs [N], cause [N])."""
    X = np.asarray(window, dtype=np.float32).copy()
    X[..., c["log_channels"]] = np.log1p(X[..., c["log_channels"]] * c["log_scale"])
    X = normalize_per_feature_global(X, c["feature_min"], c["feature_max"])
    xb = torch.from_numpy(X[None])
    with torch.no_grad():
        bl, cl = model(xb, adj)
        return (torch.sigmoid(bl)[0].numpy(),
                torch.softmax(cl[0], dim=0).numpy())


def tick(c, model, adj, prom, end_ts):
    """One evaluation at aligned end_ts. Returns record dict or None."""
    n_steps = c["seq_len"] + WARMUP_STEPS
    grid = [end_ts - (n_steps - 1 - i) * STEP for i in range(n_steps)]
    feats, _ = features_from_prometheus(prom, grid)
    raw = np.asarray(feats, dtype=np.float32)
    if raw[-1, :, 1].sum() == 0.0:      # no memory readings on the last step
        return None                      # scrape not landed yet — skip tick
    prob, cause = infer_window(c, model, adj, raw[-c["seq_len"]:])
    lat_i = c["feature_names"].index("req_latency_s")
    thr = np.asarray(c["static_thresholds"])
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(thr > 0, raw[-1, :, lat_i] / thr, 0.0)
    return {
        "ts": end_ts,
        "iso": datetime.fromtimestamp(end_ts, timezone.utc).isoformat(timespec="seconds"),
        "prob": [round(float(p), 4) for p in prob],
        "cause": [round(float(v), 4) for v in cause],
        "max_prob": round(float(prob.max()), 4),
        "alarm": bool(prob.max() > c["tau"]),
        "cause_top": [[short(NODE_MAP[i]), round(float(cause[i]), 3)]
                      for i in np.argsort(-cause)[:3]],
        "static_max_ratio": round(float(np.nanmax(ratio)), 2),
        "static_fire": bool(np.nanmax(ratio) > c["static_fair_multiplier"]),
        "raw_window_last": None,   # placeholder keeps schema stable
    }


def push_metrics(pg_url, r, tau):
    """Publish the tick to Pushgateway so Prometheus/Grafana treat the model
    as just another metrics source — the model EXTENDS the monitoring stack.
    Best-effort: a push failure must never kill a demo tick."""
    lines = []
    for i, n in enumerate(NODE_MAP):
        s = short(n)
        lines.append('gems_breach_probability{service="%s"} %s' % (s, r["prob"][i]))
        lines.append('gems_cause_score{service="%s"} %s' % (s, r["cause"][i]))
    lines.append("gems_max_probability %s" % r["max_prob"])
    lines.append("gems_alarm %d" % (1 if r["alarm"] else 0))
    lines.append("gems_static_max_ratio %s" % r["static_max_ratio"])
    lines.append("gems_static_fire %d" % (1 if r["static_fire"] else 0))
    # honesty metrics: Pushgateway restamps samples at scrape time, so the
    # dashboard must be able to DISPLAY the lag rather than hide it, and the
    # alarm line must come from the checkpoint, not a hard-coded constant.
    lines.append("gems_prediction_as_of_seconds %d" % r["ts"])
    lines.append("gems_tau %s" % tau)
    body = ("\n".join(lines) + "\n").encode()
    try:
        req = urllib.request.Request(pg_url + "/metrics/job/gems_model",
                                     data=body, method="PUT")
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # noqa: BLE001
        print("  [pushgateway failed: %s]" % type(e).__name__)


def render(r, c):
    order = np.argsort(-np.asarray(r["prob"]))[:2]
    tops = ", ".join("%s %.2f" % (short(NODE_MAP[i]), r["prob"][i]) for i in order)
    static = "FIRING" if r["static_fire"] else "quiet(%.1fx)" % r["static_max_ratio"]
    line = "%s  max=%.2f (%s)  static:%-12s" % (r["iso"][11:19], r["max_prob"],
                                                tops, static)
    if r["alarm"]:
        causes = ", ".join("%s %.2f" % (n, v) for n, v in r["cause_top"][:2])
        line += "  ** ALARM ** cause: " + causes
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="gems_model_v2.pt")
    ap.add_argument("--prom", default="http://localhost:30900")
    ap.add_argument("--ticks-log", default="live_ticks.jsonl")
    ap.add_argument("--replay", nargs=2, metavar=("START", "END"),
                    help="ISO UTC, e.g. 2026-08-15T07:00 2026-08-15T07:35")
    ap.add_argument("--compare-dataset", default="",
                    help="with --replay: also infer from this dataset's stored "
                         "features and report the max probability difference")
    ap.add_argument("--pushgateway", default="",
                    help="Pushgateway base URL; when set, every tick is also "
                         "published as gems_* metrics for Grafana")
    args = ap.parse_args()

    c, model, adj = load_checkpoint(args.checkpoint)
    print("checkpoint: tau=%.3f static_mult=%.1f seq=%d nodes=%d"
          % (c["tau"], c["static_fair_multiplier"], c["seq_len"], len(c["nodes"])))
    log = open(args.ticks_log, "a", buffering=1)

    if args.replay:
        parse = lambda s: int(datetime.strptime(s, "%Y-%m-%dT%H:%M")
                              .replace(tzinfo=timezone.utc).timestamp())
        t_start, t_end = parse(args.replay[0]), parse(args.replay[1])
        t_start = t_start // STEP * STEP
        ds = None
        if args.compare_dataset:
            ds = json.load(open(args.compare_dataset))
            ds_idx = {ts: i for i, ts in enumerate(ds["timestamps"])}
            ds_feats = np.asarray(ds["features"], dtype=np.float32)
        worst = 0.0
        for end_ts in range(t_start, t_end + 1, STEP):
            r = tick(c, model, adj, args.prom, end_ts)
            if r is None:
                print("  %d: no data, skipped" % end_ts)
                continue
            extra = ""
            if ds is not None and end_ts in ds_idx:
                i = ds_idx[end_ts]
                if i >= c["seq_len"] - 1:
                    win = ds_feats[i - c["seq_len"] + 1:i + 1]
                    p2, _ = infer_window(c, model, adj, win)
                    dmax = float(np.abs(p2 - np.asarray(r["prob"])).max())
                    worst = max(worst, dmax)
                    extra = "  |dataset dprob=%.2e" % dmax
            print(render(r, c) + extra)
            log.write(json.dumps(r) + "\n")
        if ds is not None:
            verdict = "PASS" if worst < 1e-4 else "FAIL"
            print("\nREPLAY PARITY GATE: %s — max |dprob| = %.2e (tolerance 1e-4)"
                  % (verdict, worst))
        return

    print("live mode: prom=%s tick=%ds (evaluating the last COMPLETE step)"
          % (args.prom, STEP))
    while True:
        end_ts = (int(time.time()) // STEP) * STEP - STEP
        try:
            r = tick(c, model, adj, args.prom, end_ts)
            if r is None:
                print("%s  (scrape not landed, skipped)" %
                      datetime.now(timezone.utc).strftime("%H:%M:%S"))
            else:
                print(render(r, c))
                log.write(json.dumps(r) + "\n")
                if args.pushgateway:
                    push_metrics(args.pushgateway, r, c["tau"])
        except Exception as e:  # noqa: BLE001 — a demo must not die on a blip
            print("%s  tick failed: %s" %
                  (datetime.now(timezone.utc).strftime("%H:%M:%S"),
                   type(e).__name__))
        now = time.time()
        next_tick = (int(now) // STEP + 1) * STEP + 2   # +2s scrape settle
        time.sleep(max(1.0, next_tick - now))


if __name__ == "__main__":
    main()
