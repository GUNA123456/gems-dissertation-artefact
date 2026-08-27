#!/usr/bin/env python3
import os
import sys
import json
import time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

NORM_MODE = "per_feature_global"


def normalize_per_feature_global(raw, feature_min, feature_max):
    """Scale each metric channel by ONE shared (min, max) pooled across every node.

    This is deliberately different from the earlier per-node-per-metric scheme. Under
    per-node scaling each service got its own ruler, so a service whose CPU never
    exceeds 0.019 had that tiny range stretched across the full [0, 1] output — its
    ordinary idle noise (0.010 raw) landed at 0.528, scoring *higher* than a genuinely
    CPU-stressed service (0.832 raw of a 1.779 range) at 0.468. Root-cause localization
    is fundamentally a comparison *between* nodes, so the scales must be shared or that
    comparison is meaningless. Pooling per channel (not globally across all channels)
    keeps CPU-vs-CPU comparable without letting memory's ~1e8-magnitude byte counts
    crush CPU's sub-1.0 values to zero.

    Works on any array whose last axis is the feature/metric channel.
    """
    out = np.asarray(raw, dtype=np.float32).copy()
    for i in range(out.shape[-1]):
        lo = float(feature_min[i])
        hi = float(feature_max[i])
        if hi > lo:
            # Clipping matters here in a way it did not before: min/max now come from the
            # TRAINING split only, so test-split and live samples can legitimately fall
            # outside the fitted range and must be clamped rather than pushed past [0, 1].
            out[..., i] = np.clip((out[..., i] - lo) / (hi - lo), 0.0, 1.0)
        else:
            out[..., i] = 0.0
    return out


# GCN Spatial Message Passing Layer in pure PyTorch
class GCNLayer(nn.Module):
    def __init__(self, in_features, out_features):
        super(GCNLayer, self).__init__()
        self.linear = nn.Linear(in_features, out_features)

    def forward(self, x, adj):
        # x: [Batch, Seq_Len, Nodes, In_Features]
        # adj: [Nodes, Nodes] (normalized adjacency matrix)
        batch_size, seq_len, nodes, in_feat = x.size()
        
        # Reshape to [Batch * Seq_Len, Nodes, In_Features]
        x_reshaped = x.view(-1, nodes, in_feat)
        
        # Matrix multiplication: A_hat * X
        # adj: [Nodes, Nodes], x_reshaped: [Batch*Seq_Len, Nodes, In_Features]
        # We perform batch multiplication: adj @ x_reshaped
        support = torch.matmul(adj, x_reshaped) # [Batch*Seq_Len, Nodes, In_Features]
        
        # Apply linear transformation W
        output = self.linear(support) # [Batch*Seq_Len, Nodes, Out_Features]
        
        # Apply non-linear activation (ReLU)
        output = torch.relu(output)
        
        # Reshape back to [Batch, Seq_Len, Nodes, Out_Features]
        return output.view(batch_size, seq_len, nodes, -1)

# GCN-LSTM Spatio-Temporal Model Architecture
class GCNLSTMModel(nn.Module):
    def __init__(self, num_nodes, num_features, gcn_hidden, lstm_hidden):
        super(GCNLSTMModel, self).__init__()
        self.num_nodes = num_nodes
        self.gcn = GCNLayer(num_features, gcn_hidden)
        
        # LSTM processes sequence over time for each node independently
        self.lstm = nn.LSTM(
            input_size=gcn_hidden,
            hidden_size=lstm_hidden,
            num_layers=1,
            batch_first=True
        )
        
        # Binary Classification Head: Predict if failure will occur in the next step
        self.classifier = nn.Sequential(
            nn.Linear(lstm_hidden, 16),
            nn.ReLU(),
            nn.Linear(16, 2) # Normal vs Anomaly logits
        )
        
        # Localization Head: Predict which of the N nodes is the root cause
        self.localizer = nn.Sequential(
            nn.Linear(lstm_hidden, 16),
            nn.ReLU(),
            nn.Linear(16, 1) # Localization score per node
        )

    def forward(self, x, adj):
        # x: [Batch, Seq_Len, Nodes, Features]
        batch_size, seq_len, nodes, features = x.size()
        
        # 1. Spatial Aggregation via GCN
        x_spatial = self.gcn(x, adj) # [Batch, Seq_Len, Nodes, GCN_Hidden]
        
        # 2. Temporal Aggregation via LSTM
        # Reshape to process each node's sequence independently
        # Input to LSTM: [Batch * Nodes, Seq_Len, GCN_Hidden]
        x_lstm_in = x_spatial.transpose(1, 2).contiguous().view(batch_size * nodes, seq_len, -1)
        
        lstm_out, _ = self.lstm(x_lstm_in) # [Batch*Nodes, Seq_Len, LSTM_Hidden]
        # Take the last time step's hidden state
        x_temporal = lstm_out[:, -1, :] # [Batch*Nodes, LSTM_Hidden]
        
        # Reshape back to [Batch, Nodes, LSTM_Hidden]
        x_nodes = x_temporal.view(batch_size, nodes, -1)
        
        # 3. Global Graph Representation (average pooling over nodes)
        graph_repr = x_nodes.mean(dim=1) # [Batch, LSTM_Hidden]
        
        # 4. Heads
        anomaly_logits = self.classifier(graph_repr) # [Batch, 2]
        
        # Localization logit score for each node: shape [Batch, Nodes]
        loc_scores = self.localizer(x_nodes).squeeze(-1) # [Batch, Nodes]
        
        return anomaly_logits, loc_scores

# PyTorch Dataset for GEMS Telemetry Sequences
class GEMSTelemetryDataset(Dataset):
    def __init__(self, data_path, seq_len=12, lookahead_steps=12):
        with open(data_path, "r") as f:
            self.data = json.load(f)
            
        self.nodes = self.data["topology"]["nodes"]
        self.edge_index = self.data["topology"]["edge_index"]
        self.samples = self.data["samples"]
        self.seq_len = seq_len
        self.lookahead_steps = lookahead_steps
        
        # Build normalized adjacency matrix A_hat
        num_nodes = len(self.nodes)
        A = np.zeros((num_nodes, num_nodes))
        for edge in self.edge_index:
            A[edge[0], edge[1]] = 1.0
            
        # Add self-loops
        A_tilde = A + np.eye(num_nodes)
        
        # Degree matrix D_tilde
        D_tilde = np.diag(np.sum(A_tilde, axis=1))
        D_tilde_inv_sqrt = np.linalg.inv(np.sqrt(D_tilde))
        
        # Normalized Adjacency
        self.adj = torch.FloatTensor(D_tilde_inv_sqrt @ A_tilde @ D_tilde_inv_sqrt)
        
        # Extract features and targets
        self.all_features = []
        self.all_labels = []
        self.all_root_causes = []
        
        for s in self.samples:
            self.all_features.append(s["features"])
            self.all_labels.append(s["label"])
            self.all_root_causes.append(s["root_cause"])
            
        self.raw_features = np.array(self.all_features, dtype=np.float32) # [T, 11, 4], never mutated

        # Normalization is intentionally NOT fitted here. It is fitted in train_model() *after*
        # the train/test split, from the training sequences only, via fit_normalization(). Doing
        # it in __init__ would mean the scaling statistics saw the test split too.
        self.all_features = self.raw_features.copy()
        self.feature_min = None
        self.feature_max = None
        self.norm_mode = None

    def fit_normalization(self, train_seq_indices):
        """Fit per-feature global min/max on the TRAINING split only, then apply to all data.

        `train_seq_indices` are sequence (window) indices, not raw sample indices. A training
        window at index i shows the model raw timesteps i .. i+seq_len-1, so those are the rows
        that legitimately count as 'seen during training' for fitting the scaler.
        """
        covered = np.zeros(len(self.all_labels), dtype=bool)
        for idx in train_seq_indices:
            covered[idx : idx + self.seq_len] = True
        train_rows = self.raw_features[covered]  # [T_train, 11, 4]

        # axis=(0, 1) pools over both time AND nodes, leaving one min/max per metric channel.
        self.feature_min = train_rows.min(axis=(0, 1))  # [4]
        self.feature_max = train_rows.max(axis=(0, 1))  # [4]
        self.norm_mode = NORM_MODE
        self.all_features = normalize_per_feature_global(
            self.raw_features, self.feature_min, self.feature_max
        )
        return covered.sum(), len(covered)

    def __len__(self):
        # Number of sliding sequences accounting for context and lookahead
        return len(self.samples) - self.seq_len - self.lookahead_steps + 1

    def __getitem__(self, idx):
        # Input sequence of shape [seq_len, 11, 4]
        x_seq = torch.FloatTensor(self.all_features[idx : idx + self.seq_len])
        
        # Target is the status at the future lookahead step
        target_idx = idx + self.seq_len + self.lookahead_steps - 1
        y_label = torch.tensor(self.all_labels[target_idx], dtype=torch.long)
        
        # Root cause index (if normal, root cause is -1, mapped to cross entropy padding/ignored index)
        y_root_cause = self.all_root_causes[target_idx]
        if y_root_cause == -1:
            y_rc = torch.tensor(0, dtype=torch.long) # Dummy root cause, ignored if y_label is 0
        else:
            y_rc = torch.tensor(y_root_cause, dtype=torch.long)
            
        return x_seq, y_label, y_rc

def train_model(dataset_path, threshold=0.6, seed=42, checkpoint_path=None,
                seq_len=12, lookahead_steps=12):
    print("🚀 Initializing GEMS ST-GNN (GCN-LSTM) Training Pipeline...")
    print(f"⚙️  Anomaly decision threshold: {threshold}")
    print(f"🎲 Random seed: {seed}")
    print(f"🪟 seq_len={seq_len} ({seq_len * 10}s window) | "
          f"lookahead={lookahead_steps} ({lookahead_steps * 10}s ahead)"
          f"{'  [DETECTION mode: target is the last observed step]' if lookahead_steps == 0 else ''}")

    # Reproducibility: this pipeline has four independent sources of stochasticity —
    # (1) model weight initialization, drawn from the torch global RNG when GCNLSTMModel()
    #     is constructed below; (2) the train/test random_split; (3) DataLoader minibatch
    #     shuffling each epoch; (4) the RandomForestClassifier baseline (previously hardcoded
    #     to random_state=42 regardless of any other seed choice). All four are pinned to the
    #     same `seed` here — (2) and (3) via explicit Generators (decoupled from call order,
    #     rather than relying solely on consuming the global RNG stream in a fixed sequence).
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    split_generator = torch.Generator().manual_seed(seed)
    loader_generator = torch.Generator().manual_seed(seed)

    # lookahead_steps=12 is the proactive-forecasting setting (predict 120s ahead).
    # lookahead_steps=0 turns this into a detection task: the target is the last step the
    # model actually observes, so the fault signal is present in the input rather than
    # 120s in the future.
    dataset = GEMSTelemetryDataset(dataset_path, seq_len=seq_len, lookahead_steps=lookahead_steps)
    adj = dataset.adj

    dataset_size = len(dataset)
    if dataset_size < 10:
        print("⚠️ Warning: Dataset size is too small for realistic split. Using dummy expansion for structure check.")
        # Create a tiny mock dataset if necessary to compile and test

    train_size = int(0.8 * dataset_size)
    test_size = dataset_size - train_size

    train_dataset, test_dataset = torch.utils.data.random_split(
        dataset, [train_size, test_size], generator=split_generator
    )

    # Fit the feature scaler AFTER the split, on training windows only, so no test-split
    # statistic can influence the scaling. Note that with heavily-overlapping sliding windows
    # an 80% random split still touches nearly every raw timestep, so the fitted range will be
    # close to the full-dataset range — that is expected and is reported below for transparency.
    n_covered, n_total = dataset.fit_normalization(train_dataset.indices)
    print(f"📏 Normalization: {dataset.norm_mode} | fitted on {n_covered}/{n_total} raw timesteps "
          f"covered by training windows")
    for i, ch in enumerate(["cpu", "mem", "pod_age", "latency_ms"]):
        print(f"     {ch:<11} min={dataset.feature_min[i]:.6g}  max={dataset.feature_max[i]:.6g}")

    train_loader = DataLoader(train_dataset, batch_size=4, shuffle=True, generator=loader_generator)
    test_loader = DataLoader(test_dataset, batch_size=4, shuffle=False)
    
    # Model parameters
    model = GCNLSTMModel(
        num_nodes=len(dataset.nodes),
        num_features=4,
        gcn_hidden=16,
        lstm_hidden=32
    )
    
    # Transfer adj to model device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    adj = adj.to(device)

    # Class-weighted classification loss: anomalies are the minority class (see
    # Project_Documentary_Log.md Run 1/2 — unweighted training was biased toward
    # under-predicting anomalies, hurting recall and lead-time). Weight = balanced
    # inverse frequency computed from the actual training split, so a missed
    # anomaly (false negative) is penalized proportionally more than a false alarm.
    train_target_indices = [idx + dataset.seq_len + dataset.lookahead_steps - 1 for idx in train_dataset.indices]
    train_labels = [dataset.all_labels[i] for i in train_target_indices]
    num_normal = train_labels.count(0)
    num_anomaly = train_labels.count(1)
    total_train = num_normal + num_anomaly
    class_weights = torch.tensor([
        total_train / (2 * num_normal) if num_normal > 0 else 1.0,
        total_train / (2 * num_anomaly) if num_anomaly > 0 else 1.0,
    ], dtype=torch.float32).to(device)
    print(f"⚖️  Train split: {num_normal} normal, {num_anomaly} anomaly | class weights (normal, anomaly): "
          f"({class_weights[0]:.3f}, {class_weights[1]:.3f})")

    # Loss and Optimizer
    criterion_classification = nn.CrossEntropyLoss(weight=class_weights)
    criterion_localization = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.002) # lower learning rate for stable learning
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.5) # lr decays by half every 30 epochs

    print("🟢 Training GCN-LSTM Model for 100 Epochs...")
    model.train()
    
    for epoch in range(1, 101):
        epoch_loss = 0.0
        model.train()
        for x_batch, y_batch, rc_batch in train_loader:
            x_batch = x_batch.to(device)
            y_batch = y_batch.to(device)
            rc_batch = rc_batch.to(device)
            
            optimizer.zero_grad()
            
            # Forward pass
            anomaly_logits, loc_scores = model(x_batch, adj)
            
            # Classification loss
            loss_clf = criterion_classification(anomaly_logits, y_batch)
            
            # Localization loss (only backpropagate on true anomaly samples)
            loss_loc = 0.0
            anomaly_mask = (y_batch == 1)
            if anomaly_mask.sum() > 0:
                loss_loc = criterion_localization(loc_scores[anomaly_mask], rc_batch[anomaly_mask])
                
            loss = loss_clf + 0.5 * loss_loc
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            
        scheduler.step()
            
        if epoch % 10 == 0 or epoch == 1:
            print(f"Epoch {epoch}/100 | Training Loss: {epoch_loss/len(train_loader):.4f} | LR: {scheduler.get_last_lr()[0]:.6f}")

    # Evaluation
    print("\n🔍 Evaluating Proposed GCN-LSTM Model on Test Set...")
    model.eval()
    
    total_samples = 0
    correct_clf = 0
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    
    # Localization Hits metrics
    loc_total = 0
    hr_at_1 = 0
    hr_at_2 = 0

    # AUROC is threshold-independent, so unlike F1 it does not move when `--threshold`
    # changes. It answers "how well does the model rank anomalies above normals", which is
    # the fairer basis for comparing against a baseline tuned to a different operating point.
    auroc_scores = []
    auroc_labels = []

    with torch.no_grad():
        for x_batch, y_batch, rc_batch in test_loader:
            x_batch = x_batch.to(device)
            y_batch = y_batch.to(device)
            rc_batch = rc_batch.to(device)
            
            anomaly_logits, loc_scores = model(x_batch, adj)

            # 1. Classification Predictions (explicit `threshold`, not argmax's implicit 0.5 —
            # must match the threshold used in the lead-time timeline below)
            probs_clf = torch.softmax(anomaly_logits, dim=1)[:, 1]
            preds_clf = (probs_clf > threshold).long()
            correct_clf += (preds_clf == y_batch).sum().item()
            total_samples += y_batch.size(0)
            auroc_scores.extend(probs_clf.cpu().numpy().tolist())
            auroc_labels.extend(y_batch.cpu().numpy().tolist())
            
            for i in range(y_batch.size(0)):
                true_val = y_batch[i].item()
                pred_val = preds_clf[i].item()
                
                if true_val == 1 and pred_val == 1:
                    true_positives += 1
                    # 2. Evaluate Localization if it's an anomaly and predicted correctly
                    loc_total += 1
                    # Rank nodes by scores descending
                    node_scores = loc_scores[i].cpu().numpy()
                    ranked_indices = np.argsort(node_scores)[::-1] # descending
                    
                    target_rc = rc_batch[i].item()
                    if ranked_indices[0] == target_rc:
                        hr_at_1 += 1
                    if target_rc in ranked_indices[:2]:
                        hr_at_2 += 1
                elif true_val == 0 and pred_val == 1:
                    false_positives += 1
                elif true_val == 1 and pred_val == 0:
                    false_negatives += 1

    # Compute GCN-LSTM metrics
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = correct_clf / total_samples if total_samples > 0 else 0
    
    hr1_rate = hr_at_1 / loc_total if loc_total > 0 else 1.0
    hr2_rate = hr_at_2 / loc_total if loc_total > 0 else 1.0

    # roc_auc_score raises if the split happens to contain a single class; guard so a
    # degenerate split degrades one metric rather than killing the whole run.
    try:
        gnn_auroc = roc_auc_score(auroc_labels, auroc_scores)
    except ValueError:
        gnn_auroc = float("nan")

    # --------------------------------------------------
    # 🌿 1. Train and Evaluate Random Forest Baseline
    # --------------------------------------------------
    print("\n🌲 Initializing Classical Random Forest Baseline...")
    X_train_rf = []
    y_train_rf = []
    for idx in train_dataset.indices:
        x_seq, y_label, _ = dataset[idx]
        X_train_rf.append(x_seq.numpy().flatten())
        y_train_rf.append(y_label.item())
        
    X_test_rf = []
    y_test_rf = []
    for idx in test_dataset.indices:
        x_seq, y_label, _ = dataset[idx]
        X_test_rf.append(x_seq.numpy().flatten())
        y_test_rf.append(y_label.item())
        
    X_train_rf = np.array(X_train_rf)
    y_train_rf = np.array(y_train_rf)
    X_test_rf = np.array(X_test_rf)
    y_test_rf = np.array(y_test_rf)
    
    # Standard parameter RF (fair and reasonable, no extensive tuning as instructed)
    rf_model = RandomForestClassifier(n_estimators=100, random_state=seed)
    rf_model.fit(X_train_rf, y_train_rf)
    
    rf_preds = rf_model.predict(X_test_rf)
    try:
        rf_auroc = roc_auc_score(y_test_rf, rf_model.predict_proba(X_test_rf)[:, 1])
    except ValueError:
        rf_auroc = float("nan")
    
    rf_tp = sum((rf_preds == 1) & (y_test_rf == 1))
    rf_fp = sum((rf_preds == 1) & (y_test_rf == 0))
    rf_fn = sum((rf_preds == 0) & (y_test_rf == 1))
    rf_tn = sum((rf_preds == 0) & (y_test_rf == 0))
    
    rf_precision = rf_tp / (rf_tp + rf_fp) if (rf_tp + rf_fp) > 0 else 0
    rf_recall = rf_tp / (rf_tp + rf_fn) if (rf_tp + rf_fn) > 0 else 0
    rf_f1 = 2 * (rf_precision * rf_recall) / (rf_precision + rf_recall) if (rf_precision + rf_recall) > 0 else 0
    rf_accuracy = (rf_tp + rf_tn) / len(y_test_rf) if len(y_test_rf) > 0 else 0

    # --------------------------------------------------
    # ⏱️ 2. Benchmark Inference Latencies
    # --------------------------------------------------
    print("⏱️ Benchmarking Single-Sample Inference Latencies...")
    sample_x, _, _ = test_dataset[0]
    
    # GCN-LSTM
    model.eval()
    t_start = time.time()
    for _ in range(100):
        with torch.no_grad():
            _, _ = model(sample_x.unsqueeze(0).to(device), adj)
    gnn_latency = (time.time() - t_start) / 100 * 1000
    
    # Random Forest
    sample_rf = sample_x.numpy().flatten().reshape(1, -1)
    t_start = time.time()
    for _ in range(100):
        _ = rf_model.predict(sample_rf)
    rf_latency = (time.time() - t_start) / 100 * 1000

    # --------------------------------------------------
    # 🚨 3. Quantify Alert Warning Lead Time (Delta T)
    # --------------------------------------------------
    print("🚨 Quantifying Alert Warning Lead Time (Delta T)...")
    y_true_timeline = []
    y_pred_gnn_timeline = []
    y_pred_rf_timeline = []
    static_alert_timeline = []
    STATIC_THRESHOLD = 0.85
    
    for i in range(len(dataset)):
        x_seq, y_label, _ = dataset[i]
        target_idx = i + dataset.seq_len + dataset.lookahead_steps - 1
        
        y_true_timeline.append(y_label.item())
        
        with torch.no_grad():
            logits, _ = model(x_seq.unsqueeze(0).to(device), adj)
            prob = torch.softmax(logits, dim=1)[0, 1].item()
            y_pred_gnn_timeline.append(1 if prob > threshold else 0)
            
        rf_pred = rf_model.predict(x_seq.numpy().flatten().reshape(1, -1))[0]
        y_pred_rf_timeline.append(int(rf_pred))
        
        # Static check: normalized CPU (col 0) or Memory (col 1) > 0.85
        target_features = dataset.all_features[target_idx]
        cpu_max = target_features[:, 0].max()
        mem_max = target_features[:, 1].max()
        static_alert_timeline.append(1 if (cpu_max > STATIC_THRESHOLD or mem_max > STATIC_THRESHOLD) else 0)
        
    # Group into contiguous events
    anomaly_events = []
    current_event = []
    for idx, val in enumerate(y_true_timeline):
        if val == 1:
            current_event.append(idx)
        else:
            if len(current_event) > 0:
                anomaly_events.append(current_event)
                current_event = []
    if len(current_event) > 0:
        anomaly_events.append(current_event)
        
    lead_times_static = []
    lead_times_rf = []
    
    for event in anomaly_events:
        first_gnn_fire = None
        first_rf_fire = None
        first_static_fire = None
        
        for step in event:
            if first_gnn_fire is None and y_pred_gnn_timeline[step] == 1:
                first_gnn_fire = step
            if first_rf_fire is None and y_pred_rf_timeline[step] == 1:
                first_rf_fire = step
            if first_static_fire is None and static_alert_timeline[step] == 1:
                first_static_fire = step
                
        # Lead time must compare each detector's true real-world decision timestamp, not raw
        # array index. GNN/RF decide from window [step, step+seq_len-1], so their decision is
        # knowable at real sample-time (step + seq_len - 1). The static check reads the actual
        # ground-truth value AT the target sample itself — not a forecast — so it's only knowable
        # at real sample-time (step + seq_len + lookahead_steps - 1). Subtracting raw indices
        # (the old approach) silently cancels out the GNN's entire lookahead head start; see
        # Project_Documentary_Log.md for the worked example that caught this.
        if first_gnn_fire is not None and first_static_fire is not None:
            gnn_real_t = first_gnn_fire + dataset.seq_len - 1
            static_real_t = first_static_fire + dataset.seq_len + dataset.lookahead_steps - 1
            lead_times_static.append((static_real_t - gnn_real_t) * 10)
        if first_gnn_fire is not None and first_rf_fire is not None:
            gnn_real_t = first_gnn_fire + dataset.seq_len - 1
            rf_real_t = first_rf_fire + dataset.seq_len - 1
            lead_times_rf.append((rf_real_t - gnn_real_t) * 10)
            
    avg_lead_static = np.mean(lead_times_static) if len(lead_times_static) > 0 else 0.0
    avg_lead_rf = np.mean(lead_times_rf) if len(lead_times_rf) > 0 else 0.0

    # The static baseline thresholds NORMALIZED cpu/mem, so its firing rate depends on the
    # normalization scheme and is NOT comparable across schemes. Reported explicitly because a
    # baseline that fires on nearly every timestep is a degenerate alarm, and a lead time
    # measured against it would be near-meaningless however good the number looks.
    static_fire_rate = sum(static_alert_timeline) / len(static_alert_timeline)
    print(f"   [baseline audit] static alert fires on {sum(static_alert_timeline)}/"
          f"{len(static_alert_timeline)} timesteps ({static_fire_rate * 100:.1f}%) | "
          f"lead-time computed over {len(lead_times_static)}/{len(anomaly_events)} anomaly events "
          f"(static never fired in the rest)")

    print("----------------------------------------------------------------------")
    print(f"📊 Model Comparison Metrics (Test Split):")
    print(f"  {'Metric':<20} | {'GCN-LSTM (Proposed)':<22} | {'Random Forest':<15}")
    print(f"  {'-'*20}-+-{'-'*22}-+-{'-'*15}")
    print(f"  {'Accuracy':<20} | {accuracy * 100:>21.2f}% | {rf_accuracy * 100:>14.2f}%")
    print(f"  {'Precision':<20} | {precision:>22.4f} | {rf_precision:>15.4f}")
    print(f"  {'Recall':<20} | {recall:>22.4f} | {rf_recall:>15.4f}")
    print(f"  {'F1-Score':<20} | {f1:>22.4f} | {rf_f1:>15.4f}")
    print(f"  {'AUROC':<20} | {gnn_auroc:>22.4f} | {rf_auroc:>15.4f}")
    print(f"  {'Inference Latency':<20} | {gnn_latency:>20.4f} ms | {rf_latency:>13.4f} ms")
    print("----------------------------------------------------------------------")
    print(f"📊 Root-Cause Localization Metrics (Proposed ST-GNN HR@K):")
    print(f"  - Hit Ratio @ 1 (HR@1) : {hr1_rate * 100:.2f}%")
    print(f"  - Hit Ratio @ 2 (HR@2) : {hr2_rate * 100:.2f}%")
    print("----------------------------------------------------------------------")
    print(f"📊 Warning Alert Lead-Time Buffer (Proactive Delta T):")
    print(f"  - Warning lead time over static alerts (Delta T_static) : {avg_lead_static:.2f} seconds")
    print(f"  - Warning lead time over flat ML model  (Delta T_rf)     : {avg_lead_rf:.2f} seconds")
    print("----------------------------------------------------------------------")
    print("🎉 ST-GNN Model Training and Evaluation completed successfully!")

    if checkpoint_path:
        # Saves everything a separate live-inference script needs: weights, the exact
        # per-feature min/max used to normalize training data (new samples must be scaled
        # identically or the model's outputs are meaningless), the adjacency matrix, node
        # ordering, and the sequence/threshold config used at training time. `norm_mode` is
        # stored so live inference can assert it applies the matching transform rather than
        # silently misinterpreting a [4] stat array as the old [11, 4] one.
        torch.save({
            "model_state_dict": model.state_dict(),
            "norm_mode": dataset.norm_mode,
            "feature_min": dataset.feature_min,
            "feature_max": dataset.feature_max,
            "adj": dataset.adj,
            "nodes": dataset.nodes,
            "edge_index": dataset.edge_index,
            "seq_len": dataset.seq_len,
            "lookahead_steps": dataset.lookahead_steps,
            "threshold": threshold,
            "num_features": 4,
            "gcn_hidden": 16,
            "lstm_hidden": 32,
        }, checkpoint_path)
        print(f"💾 Model checkpoint saved to: {checkpoint_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train Ggems ST-GNN Model")
    parser.add_argument("--dataset", type=str, default="telemetry_dataset.json", help="Path to telemetry dataset JSON")
    parser.add_argument("--threshold", type=float, default=0.6,
                         help="Anomaly decision threshold on the softmax probability (default: %(default)s, "
                              "chosen as the F1-optimal point from the threshold sweep in Project_Documentary_Log.md)")
    parser.add_argument("--seed", type=int, default=42,
                         help="Random seed governing model init, train/test split, minibatch shuffling, "
                              "and the Random Forest baseline (default: %(default)s)")
    parser.add_argument("--checkpoint", type=str, default=None,
                         help="If set, save the trained model + normalization stats to this path "
                              "(for a separate live-inference script to load later)")
    parser.add_argument("--seq-len", type=int, default=12,
                         help="Input window length in 10s samples (default: %(default)s = 120s)")
    parser.add_argument("--lookahead", type=int, default=12,
                         help="Forecast horizon in 10s samples (default: %(default)s = 120s ahead). "
                              "Use 0 for detection-mode: the target becomes the last observed step.")
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        print(f"❌ Error: Dataset file not found at: {args.dataset}")
        sys.exit(1)

    train_model(args.dataset, threshold=args.threshold, seed=args.seed, checkpoint_path=args.checkpoint,
                seq_len=args.seq_len, lookahead_steps=args.lookahead)
