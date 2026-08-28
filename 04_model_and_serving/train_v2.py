#!/usr/bin/env python3


import argparse
import json

import numpy as np
import torch
import torch.nn as nn

from train_gnn import GCNLayer, normalize_per_feature_global  # reuse, verbatim


class CascadeGCNLSTM(nn.Module):
    """v1 backbone, v2 heads: per-node breach logit + cause scores."""

    def __init__(self, num_nodes, num_features, gcn_hidden=32, lstm_hidden=64):
        super().__init__()
        self.num_nodes = num_nodes
        self.gcn = GCNLayer(num_features, gcn_hidden)
        self.lstm = nn.LSTM(input_size=gcn_hidden, hidden_size=lstm_hidden,
                            num_layers=1, batch_first=True)
        self.breach_head = nn.Sequential(
            nn.Linear(lstm_hidden, 16), nn.ReLU(), nn.Linear(16, 1))
        self.cause_head = nn.Sequential(
            nn.Linear(lstm_hidden, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x, adj):
        b, s, n, f = x.size()
        xs = self.gcn(x, adj)
        xl = xs.transpose(1, 2).contiguous().view(b * n, s, -1)
        out, _ = self.lstm(xl)
        h = out[:, -1, :].view(b, n, -1)              # [B, N, H]
        breach = self.breach_head(h).squeeze(-1)      # [B, N]
        cause = self.cause_head(h).squeeze(-1)        # [B, N]
        return breach, cause


def build_adj(nodes, edges):
    n = len(nodes)
    idx = {name: i for i, name in enumerate(nodes)}
    A = np.zeros((n, n))
    for s, t in edges:
        A[idx[s], idx[t]] = 1.0
        A[idx[t], idx[s]] = 1.0   # undirected message passing, as in v1
    At = A + np.eye(n)
    D = np.diag(At.sum(axis=1))
    Dinv = np.linalg.inv(np.sqrt(D))
    return torch.FloatTensor(Dinv @ At @ Dinv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="telemetry_dataset_v2.json")
    ap.add_argument("--seq-len", type=int, default=12)
    ap.add_argument("--lookahead", type=int, default=12)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="gems_model_v2.pt")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    d = json.load(open(args.data))
    feats = np.asarray(d["features"], dtype=np.float32)    # [T, N, F]
    breach = np.asarray(d["breach"], dtype=np.float32)     # [T, N]
    phase = d["context"]["phase"]
    target = np.asarray(d["context"]["target"])
    scen = np.asarray(d["context"]["scenario"])
    ep_ids = np.asarray(d["context"]["episode_id"])
    nodes, scenarios = d["nodes"], d["meta"]["scenarios"]
    T, N, F = feats.shape
    S, H = args.seq_len, args.lookahead
    adj = build_adj(nodes, d["edges"])
    print("dataset: T=%d N=%d F=%d | seq=%d lookahead=%d (%d min warning)"
          % (T, N, F, S, H, H * d["meta"]["step_s"] // 60))

    # ---- samples: y[n] = any breach in (t, t+H]; cause = episode target -----
    ts_idx, Y, C = [], [], []
    for t in range(S - 1, T - H):
        horizon = slice(t + 1, t + 1 + H)
        y = breach[horizon].max(axis=0)
        cause = -1
        h_eps = ep_ids[horizon]
        if y.max() > 0:
            for j in range(t + 1, t + 1 + H):
                if breach[j].max() > 0 and ep_ids[j] > 0:
                    cause = int(target[j])
                    break
        ts_idx.append(t)
        Y.append(y)
        C.append(cause)
    ts_idx = np.asarray(ts_idx)
    Y = np.asarray(Y, dtype=np.float32)
    C = np.asarray(C)

    # ---- temporal split with overlap exclusion ------------------------------
    b1, b2 = int(T * 0.70), int(T * 0.85)
    lo = ts_idx - (S - 1)
    hi = ts_idx + H
    tr = (hi < b1)
    va = (lo >= b1) & (hi < b2)
    te = (lo >= b2)
    print("samples: train=%d val=%d test=%d (dropped at boundaries: %d)"
          % (tr.sum(), va.sum(), te.sum(),
             len(ts_idx) - tr.sum() - va.sum() - te.sum()))
    print("positive node-labels: train %.1f%%  val %.1f%%  test %.1f%%"
          % tuple(100 * Y[m].mean() for m in (tr, va, te)))

    # ---- normalization fitted on the TRAINING portion only ------------------
    # log1p on the heavy-tailed channels first: a single 9s latency spike in
    # training otherwise owns the min-max range and squashes the 0.1-1s band
    # (where every breach decision happens) into ~5% of the scale.
    LOG_CH = [d["meta"]["feature_names"].index(c)
              for c in ("req_latency_s", "err_out_rate", "err_in_rate")]
    feats_t = feats.copy()
    feats_t[..., LOG_CH] = np.log1p(feats_t[..., LOG_CH] * 100.0)
    train_rows = feats_t[:b1]
    fmin, fmax = train_rows.min(axis=(0, 1)), train_rows.max(axis=(0, 1))
    X = normalize_per_feature_global(feats_t, fmin, fmax)

    def batch(mask):
        idx = ts_idx[mask]
        xb = np.stack([X[t - S + 1:t + 1] for t in idx])
        return (torch.from_numpy(xb), torch.from_numpy(Y[mask]),
                torch.from_numpy(C[mask]))

    Xtr, Ytr, Ctr = batch(tr)
    Xva, Yva, Cva = batch(va)
    Xte, Yte, Cte = batch(te)

    # ---- train --------------------------------------------------------------
    # ~900 samples with ~35 positive windows: the full-size net memorises in a
    # handful of epochs (val AUROC peaked at epoch 1 in earlier runs). Half-size
    # model, capped class weight, gentle LR — all chosen on validation only.
    model = CascadeGCNLSTM(N, F, gcn_hidden=16, lstm_hidden=32)
    raw_w = float((Ytr.numel() - Ytr.sum()) / max(Ytr.sum(), 1.0))
    pos_w = torch.tensor(min(raw_w, 8.0))
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    ce = nn.CrossEntropyLoss()
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    print("pos_weight=%.1f (raw %.1f, capped 8)" % (pos_w.item(), raw_w))

    best_val, best_state, patience = -1, None, 0
    perm_gen = torch.Generator().manual_seed(args.seed)
    for epoch in range(args.epochs):
        model.train()
        perm = torch.randperm(len(Xtr), generator=perm_gen)
        tot = 0.0
        for i in range(0, len(perm), 32):
            sel = perm[i:i + 32]
            xb, yb, cb = Xtr[sel], Ytr[sel], Ctr[sel]
            opt.zero_grad()
            bl, cl = model(xb, adj)
            loss = bce(bl, yb)
            m = cb >= 0
            if m.any():
                loss = loss + 0.5 * ce(cl[m], cb[m])
            loss.backward()
            opt.step()
            tot += loss.item() * len(sel)
        model.eval()
        with torch.no_grad():
            bl, _ = model(Xva, adj)
            p = torch.sigmoid(bl).numpy().ravel()
        yv = Yva.numpy().ravel()
        from sklearn.metrics import roc_auc_score
        # early-stop on val AUROC: with 175 val samples PR-AUC is so noisy it
        # froze a run at epoch 11 on a spike; AUROC is the smoother signal
        val_auc = roc_auc_score(yv, p)
        if val_auc > best_val:
            best_val, best_state, patience = val_auc, \
                {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            patience += 1
        if epoch % 10 == 0 or patience == 0:
            print("  epoch %3d loss=%.4f val_AUROC=%.3f%s"
                  % (epoch, tot / len(Xtr), val_auc,
                     " *" if patience == 0 else ""))
        if patience >= 40:
            print("  early stop at epoch %d" % epoch)
            break
    model.load_state_dict(best_state)

    # ---- static-threshold baseline (train-quiet p99.5 x 1.2) ----------------
    from sklearn.metrics import average_precision_score, roc_auc_score
    LAT = d["meta"]["feature_names"].index("req_latency_s")
    quiet_tr = [i for i in range(b1) if phase[i] == "quiet"]
    thr = np.zeros(N)
    for n in range(N):
        xs = feats[quiet_tr, n, LAT]
        xs = xs[xs > 0]
        thr[n] = (np.percentile(xs, 99.5) * 1.2) if len(xs) else np.inf
    static_scores = np.stack([feats[t, :, LAT] / thr for t in ts_idx[te]])
    static_fire = (static_scores > 1.0)
    persistence = np.stack([breach[t] for t in ts_idx[te]])

    model.eval()
    with torch.no_grad():
        bl, cl = model(Xte, adj)
        prob = torch.sigmoid(bl).numpy()
    yt = Yte.numpy()

    print("\n== test metrics (node-step level, %d samples x %d nodes) =="
          % (len(Xte), N))
    for name, score in (("GCN-LSTM v2", prob.ravel()),
                        ("static-threshold", static_scores.ravel()),
                        ("persistence", persistence.ravel())):
        print("  %-18s AUROC=%.3f  PR-AUC=%.3f"
              % (name, roc_auc_score(yt.ravel(), score),
                 average_precision_score(yt.ravel(), score)))
    print("  static monitor firing rate on test: %.1f%% of node-steps "
          "(audit: >90%% = degenerate)" % (100 * static_fire.mean()))

    # ---- cause head: HR@1 / HR@2 on positive test samples -------------------
    mask = (Cte.numpy() >= 0) & (yt.max(axis=1) > 0)
    if mask.any():
        order = np.argsort(-cl.numpy()[mask], axis=1)
        truth = Cte.numpy()[mask]
        hr1 = float((order[:, 0] == truth).mean())
        hr2 = float(((order[:, 0] == truth) | (order[:, 1] == truth)).mean())
        print("  cause HR@1=%.2f HR@2=%.2f on %d positive test samples"
              % (hr1, hr2, mask.sum()))

    # ---- lead-time race on test episodes ------------------------------------
    # Both racers get the SAME alarm budget, tuned on the same validation
    # samples: <=1 false alarm per hour, where a false alarm is an alarm on a
    # sample whose entire horizon is breach-free (alarming while an onset is
    # already inside the horizon is a correct early warning, not a false one).
    with torch.no_grad():
        blv, _ = model(Xva, adj)
        pv = torch.sigmoid(blv).numpy().max(axis=1)
    va_neg = Yva.numpy().max(axis=1) == 0
    taus = np.linspace(0.05, 0.99, 189)
    tau = next((x for x in taus
                if (pv[va_neg] > x).mean() * 120 <= 1.0), 0.99)
    static_va = np.stack([feats[t, :, LAT] / thr for t in ts_idx[va]]).max(axis=1)
    mults = np.linspace(1.0, 20.0, 100)
    smult = next((m for m in mults
                  if (static_va[va_neg] > m).mean() * 120 <= 1.0), mults[-1])
    print("\nalarm budget <=1 FA/hour on val: model tau=%.2f | "
          "static needs %.1fx its tuned threshold" % (tau, smult))
    static_alarm_te = static_scores.max(axis=1) > smult

    test_eps = sorted({int(e) for i, e in zip(ts_idx[te], ep_ids[ts_idx[te]])
                       if e > 0} | {int(ep_ids[t + 1]) for t in ts_idx[te]
                                    if t + 1 < T and ep_ids[t + 1] > 0})
    step_s = d["meta"]["step_s"]
    print("test-window episodes and lead times:")
    te_idx = ts_idx[te]
    prob_max = prob.max(axis=1)
    for e in test_eps:
        in_ep = np.array([ep_ids[min(t + H, T - 1)] == e or ep_ids[t] == e
                          for t in te_idx])
        if not in_ep.any():
            continue
        ep_ts = te_idx[in_ep]
        sc = scen[ep_ts[ep_ts < T][0]] if (scen[ep_ts] >= 0).any() else -1
        sc_name = scenarios[int(scen[ep_ts][scen[ep_ts] >= 0][0])] \
            if (scen[ep_ts] >= 0).any() else "?"
        breach_steps = [t for t in range(ep_ts.min(), min(ep_ts.max() + H + 1, T))
                        if ep_ids[t] == e and breach[t].max() > 0]
        alarm_steps = [t for t, m in zip(te_idx[in_ep], prob_max[in_ep]) if m > tau]
        static_steps = [t for t, f in zip(te_idx[in_ep], static_alarm_te[in_ep])
                        if f]
        fb = breach_steps[0] if breach_steps else None

        def fmt(x):
            if x is None:
                return "no alarm"
            if fb is None:
                return "FALSE ALARM"
            return "%+ds" % ((fb - x) * step_s)
        print("  ep%-3d %-20s first_breach=%-6s model=%-12s static=%s"
              % (e, sc_name, "none" if fb is None else "t+%d" % fb,
                 fmt(alarm_steps[0] if alarm_steps else None),
                 fmt(static_steps[0] if static_steps else None)))

    # Everything serving needs lives in the checkpoint — the live monitor must
    # never recompute or hard-code a constant the training run determined.
    torch.save({"state_dict": model.state_dict(), "feature_min": fmin,
                "feature_max": fmax, "nodes": nodes, "edges": d["edges"],
                "seq_len": S, "lookahead": H, "tau": float(tau),
                "static_thresholds": thr.tolist(),
                "static_fair_multiplier": float(smult),
                "feature_names": d["meta"]["feature_names"],
                "log_channels": LOG_CH, "log_scale": 100.0,
                "gcn_hidden": 16, "lstm_hidden": 32,
                "slo": d["meta"]["slo"], "seed": args.seed}, args.out)
    print("\nsaved %s" % args.out)


if __name__ == "__main__":
    main()
