#!/usr/bin/env python3
"""Step 4 pooled trainer: multiple collection nights, one model.

Same recipe as train_v2.py (seed, half-size net, capped pos_weight, val-AUROC
early stop) — deliberately unchanged so pooling is the only new variable.
Differences forced by pooling, all pre-registered in Step4_Collection_Design:

  * windows never span a dataset boundary (each night is its own timeline);
  * the temporal 70/15/15 split is applied PER NIGHT, then pooled — so every
    night contributes to train, val and test, and test stays strictly after
    train within each night;
  * pod-kill episodes are excluded from ALL samples by scenario NAME (the
    Step-2 pre-registration: precursor-free label noise; demo-only scenario);
  * normalization bounds fit on the union of the nights' training portions;
  * scenario indices differ across datasets — mapping is always BY NAME via
    each dataset's meta.scenarios, never by raw index.
"""

import argparse
import json

import numpy as np
import torch
import torch.nn as nn

from train_gnn import normalize_per_feature_global
from train_v2 import CascadeGCNLSTM, build_adj


def load_night(path, S, H):
    d = json.load(open(path))
    feats = np.asarray(d["features"], dtype=np.float32)
    breach = np.asarray(d["breach"], dtype=np.float32)
    ep_ids = np.asarray(d["context"]["episode_id"])
    target = np.asarray(d["context"]["target"])
    scen = np.asarray(d["context"]["scenario"])
    names = d["meta"]["scenarios"]
    scen_name = np.array([names[s] if s >= 0 else "" for s in scen])
    T = len(feats)

    ts_idx, Y, C = [], [], []
    for t in range(S - 1, T - H):
        y = breach[t + 1:t + 1 + H].max(axis=0)
        cause = -1
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

    # pod-kill exclusion by name, over the sample's full extent
    keep = np.array([not any("pod-kill" in scen_name[j]
                             for j in range(t - S + 1, min(t + H + 1, T)))
                     for t in ts_idx])
    b1, b2 = int(T * 0.70), int(T * 0.85)
    lo, hi = ts_idx - (S - 1), ts_idx + H
    tr = (hi < b1) & keep
    va = (lo >= b1) & (hi < b2) & keep
    te = (lo >= b2) & keep
    return {"path": path, "d": d, "feats": feats, "breach": breach,
            "ep_ids": ep_ids, "scen_name": scen_name, "T": T, "b1": b1,
            "ts_idx": ts_idx, "Y": Y, "C": C, "tr": tr, "va": va, "te": te,
            "dropped_podkill": int((~keep).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--seq-len", type=int, default=12)
    ap.add_argument("--lookahead", type=int, default=12)
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="gems_model_v2_pooled.pt")
    args = ap.parse_args()
    S, H = args.seq_len, args.lookahead

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    nights = [load_night(p, S, H) for p in args.data]
    meta0 = nights[0]["d"]["meta"]
    nodes = nights[0]["d"]["nodes"]
    N, F = len(nodes), len(meta0["feature_names"])
    for ng in nights:
        assert ng["d"]["nodes"] == nodes, "node order differs between nights"
    edges = sorted({tuple(e) for ng in nights for e in ng["d"]["edges"]})
    adj = build_adj(nodes, edges)
    LOG_CH = [meta0["feature_names"].index(c)
              for c in ("req_latency_s", "err_out_rate", "err_in_rate")]
    LAT = meta0["feature_names"].index("req_latency_s")

    for ng in nights:
        print("night %-45s T=%d train/val/test=%d/%d/%d (pod-kill dropped: %d)"
              % (ng["path"].split("/")[-1], ng["T"], ng["tr"].sum(),
                 ng["va"].sum(), ng["te"].sum(), ng["dropped_podkill"]))

    # pooled normalization: union of the nights' training rows
    rows = []
    for ng in nights:
        r = ng["feats"][:ng["b1"]].copy()
        r[..., LOG_CH] = np.log1p(r[..., LOG_CH] * 100.0)
        rows.append(r)
    train_rows = np.concatenate(rows)
    fmin = train_rows.min(axis=(0, 1))
    fmax = train_rows.max(axis=(0, 1))

    def windows(ng, mask):
        Xn = ng["feats"].copy()
        Xn[..., LOG_CH] = np.log1p(Xn[..., LOG_CH] * 100.0)
        Xn = normalize_per_feature_global(Xn, fmin, fmax)
        idx = ng["ts_idx"][mask]
        xb = np.stack([Xn[t - S + 1:t + 1] for t in idx]) if len(idx) else \
            np.zeros((0, S, N, F), dtype=np.float32)
        return (torch.from_numpy(xb), torch.from_numpy(ng["Y"][mask]),
                torch.from_numpy(ng["C"][mask]))

    def pooled(split):
        xs, ys, cs = zip(*[windows(ng, ng[split]) for ng in nights])
        return torch.cat(xs), torch.cat(ys), torch.cat(cs)

    Xtr, Ytr, Ctr = pooled("tr")
    Xva, Yva, Cva = pooled("va")
    Xte, Yte, Cte = pooled("te")
    print("pooled samples: train=%d val=%d test=%d | positive node-labels: "
          "train %.1f%% val %.1f%% test %.1f%%"
          % (len(Xtr), len(Xva), len(Xte),
             100 * Ytr.numpy().mean(), 100 * Yva.numpy().mean(),
             100 * Yte.numpy().mean()))

    # ---- identical training recipe to train_v2 ------------------------------
    model = CascadeGCNLSTM(N, F, gcn_hidden=16, lstm_hidden=32)
    raw_w = float((Ytr.numel() - Ytr.sum()) / max(Ytr.sum(), 1.0))
    pos_w = torch.tensor(min(raw_w, 8.0))
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    ce = nn.CrossEntropyLoss()
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    print("pos_weight=%.1f (raw %.1f, capped 8)" % (pos_w.item(), raw_w))

    from sklearn.metrics import average_precision_score, roc_auc_score
    best_val, best_state, patience = -1, None, 0
    perm_gen = torch.Generator().manual_seed(args.seed)
    for epoch in range(args.epochs):
        model.train()
        perm = torch.randperm(len(Xtr), generator=perm_gen)
        tot = 0.0
        for i in range(0, len(perm), 32):
            sel = perm[i:i + 32]
            opt.zero_grad()
            bl, cl = model(Xtr[sel], adj)
            loss = bce(bl, Ytr[sel])
            m = Ctr[sel] >= 0
            if m.any():
                loss = loss + 0.5 * ce(cl[m], Ctr[sel][m])
            loss.backward()
            opt.step()
            tot += loss.item() * len(sel)
        model.eval()
        with torch.no_grad():
            bl, _ = model(Xva, adj)
            p = torch.sigmoid(bl).numpy().ravel()
        val_auc = roc_auc_score(Yva.numpy().ravel(), p)
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

    # ---- static baseline: pooled train-quiet p99.5 x 1.2 --------------------
    quiet_rows = np.concatenate(
        [ng["feats"][[i for i in range(ng["b1"])
                      if ng["d"]["context"]["phase"][i] == "quiet"]]
         for ng in nights])
    thr = np.zeros(N)
    for n in range(N):
        xs = quiet_rows[:, n, LAT]
        xs = xs[xs > 0]
        thr[n] = (np.percentile(xs, 99.5) * 1.2) if len(xs) else np.inf

    def static_scores_for(ng, mask):
        return np.stack([ng["feats"][t, :, LAT] / thr
                         for t in ng["ts_idx"][mask]]) if mask.sum() else \
            np.zeros((0, N))

    st_te = np.concatenate([static_scores_for(ng, ng["te"]) for ng in nights])
    pers_te = np.concatenate(
        [np.stack([ng["breach"][t] for t in ng["ts_idx"][ng["te"]]])
         if ng["te"].sum() else np.zeros((0, N)) for ng in nights])

    model.eval()
    with torch.no_grad():
        bl, cl = model(Xte, adj)
        prob = torch.sigmoid(bl).numpy()
    yt = Yte.numpy()

    print("\n== pooled test metrics (%d samples x %d nodes) ==" % (len(Xte), N))
    for name, score in (("GCN-LSTM pooled", prob.ravel()),
                        ("static-threshold", st_te.ravel()),
                        ("persistence", pers_te.ravel())):
        print("  %-18s AUROC=%.3f  PR-AUC=%.3f"
              % (name, roc_auc_score(yt.ravel(), score),
                 average_precision_score(yt.ravel(), score)))

    mask = (Cte.numpy() >= 0) & (yt.max(axis=1) > 0)
    if mask.any():
        order = np.argsort(-cl.numpy()[mask], axis=1)
        truth = Cte.numpy()[mask]
        hr1 = float((order[:, 0] == truth).mean())
        hr2 = float(((order[:, 0] == truth) | (order[:, 1] == truth)).mean())
        print("  cause HR@1=%.2f HR@2=%.2f on %d positive test samples"
              % (hr1, hr2, int(mask.sum())))

    # ---- tau refit on pooled val (pre-registered expectation 2) -------------
    with torch.no_grad():
        blv, _ = model(Xva, adj)
        pv = torch.sigmoid(blv).numpy().max(axis=1)
    va_neg = Yva.numpy().max(axis=1) == 0
    taus = np.linspace(0.05, 0.99, 189)
    tau = next((x for x in taus if (pv[va_neg] > x).mean() * 120 <= 1.0), 0.99)
    st_va = np.concatenate([static_scores_for(ng, ng["va"]) for ng in nights])
    sv = st_va.max(axis=1)
    mults = np.linspace(1.0, 20.0, 100)
    smult = next((m for m in mults if (sv[va_neg] > m).mean() * 120 <= 1.0),
                 mults[-1])
    print("\npooled alarm budget <=1 FA/hour: model tau=%.2f (was 0.805 on one "
          "night) | static needs %.1fx" % (tau, smult))

    # ---- per-night test-episode lead table ----------------------------------
    step_s = meta0["step_s"]
    for ng in nights:
        if not ng["te"].sum():
            continue
        Xn, _, _ = windows(ng, ng["te"])
        with torch.no_grad():
            bln, _ = model(Xn, adj)
            pmax = torch.sigmoid(bln).numpy().max(axis=1)
        te_idx = ng["ts_idx"][ng["te"]]
        st = static_scores_for(ng, ng["te"]).max(axis=1)
        eps = sorted({int(ng["ep_ids"][min(t + H, ng["T"] - 1)]) for t in te_idx
                      if ng["ep_ids"][min(t + H, ng["T"] - 1)] > 0}
                     | {int(ng["ep_ids"][t]) for t in te_idx if ng["ep_ids"][t] > 0})
        print("\n%s test episodes:" % ng["path"].split("/")[-1])
        for e in eps:
            in_ep = np.array([ng["ep_ids"][min(t + H, ng["T"] - 1)] == e
                              or ng["ep_ids"][t] == e for t in te_idx])
            if not in_ep.any():
                continue
            names_here = [n for n in ng["scen_name"][ng["ep_ids"] == e] if n]
            sc_name = names_here[0] if names_here else "?"
            breach_steps = [t for t in range(int(te_idx[in_ep].min()),
                                             min(int(te_idx[in_ep].max()) + H + 1,
                                                 ng["T"]))
                            if ng["ep_ids"][t] == e and ng["breach"][t].max() > 0]
            alarms = [t for t, m in zip(te_idx[in_ep], pmax[in_ep]) if m > tau]
            statics = [t for t, sv_ in zip(te_idx[in_ep], st[in_ep]) if sv_ > smult]
            fb = breach_steps[0] if breach_steps else None

            def fmt(x):
                if x is None:
                    return "no alarm"
                if fb is None:
                    return "FALSE ALARM"
                return "%+ds" % ((fb - x) * step_s)
            print("  ep%-3d %-28s first_breach=%-6s model=%-12s static=%s"
                  % (e, sc_name, "none" if fb is None else "t+%d" % fb,
                     fmt(alarms[0] if alarms else None),
                     fmt(statics[0] if statics else None)))

    torch.save({"state_dict": model.state_dict(), "feature_min": fmin,
                "feature_max": fmax, "nodes": nodes,
                "edges": [list(e) for e in edges],
                "seq_len": S, "lookahead": H, "tau": float(tau),
                "static_thresholds": thr.tolist(),
                "static_fair_multiplier": float(smult),
                "feature_names": meta0["feature_names"],
                "log_channels": LOG_CH, "log_scale": 100.0,
                "gcn_hidden": 16, "lstm_hidden": 32,
                "slo": meta0["slo"], "seed": args.seed,
                "pooled_from": [ng["path"] for ng in nights]}, args.out)
    print("\nsaved %s" % args.out)


if __name__ == "__main__":
    main()
