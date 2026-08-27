# Datasets

Four labelled telemetry datasets, extracted from Prometheus by
`../03_data_pipeline/extract_v2.py`. They are formatted for reading: the structure is
indented, and each timestep occupies **one line** in `features`, `breach`,
`breach_clauses` and `fivexx`. A full `indent=2` would have exploded
`features` alone into ~100,000 lines, which GitHub will not render — this way
each file is 3,500–6,200 lines and stays browsable. Formatting is whitespace
only; every file reparses identical to its minified original.

| File | Steps | Nodes | Positive labels | Label version | Night |
|---|---:|---:|---:|---|---|
| `telemetry_dataset_v2.json` | 1,317 | 11 | 295 | v2 | 2026-08-14 |
| `telemetry_dataset_v2_1.json` | 1,317 | 11 | 339 | **v2.1** | 2026-08-14 |
| `telemetry_dataset_nightA.json` | 1,284 | 11 | 357 | v2.1 | Night A — cart-mem ×8 |
| `telemetry_dataset_nightB.json` | 1,320 | 11 | 474 | v2.1 | Night B — magnitude ladder |

The first two are **the same night's telemetry under two different label
definitions**. Nothing else differs — not the features, not the timestamps.
That is what makes the Chapter 5 label ablation a controlled experiment rather
than a comparison of two runs, and the 295 → 339 change is the honest label
definition finding more breaches the old one missed.

## Schema

| Key | Shape | Contents |
|---|---|---|
| `meta` | dict | `run_id`, `seed`, `step_s` (30), source ground-truth log, label version |
| `nodes` | 11 | node order — index into every tensor below |
| `edges` | 15 × 2 | directed dependency edges, as node-index pairs |
| `baseline_latency_s` | dict | per-node quiet-period median; the SLO threshold is `max(10 × this, 0.1 s)` |
| `timestamps` | T | Unix seconds, 30-second grid |
| `features` | **T × 11 × 7** | the model input tensor |
| `breach` | **T × 11** | the label: is this node in breach at this step |
| `context` | dict | `episode_id`, `scenario`, `target`, `stage`, `phase` per step |

Feature order (index 0–6): `cpu_cores`, `mem_mib`, `pod_age_min`, `req_rate`,
`req_latency_s`, `err_out_rate`, `err_in_rate`.

`context.target` is the **injected** root cause, taken from the scheduler's
verified-injection record — not inferred. It is what the cause head trains
against.

## Loading

```python
import json
d = json.load(open("telemetry_dataset_v2_1.json"))
X = d["features"]      # T x 11 x 7
y = d["breach"]        # T x 11
print(d["nodes"][2], X[100][2][1])   # cart's mem_mib at step 100
```

Retraining needs nothing outside this folder:

```bash
python ../04_model_and_serving/train_v2.py --dataset telemetry_dataset_v2_1.json
```

## Provenance

Raw telemetry lives in the cluster's Prometheus TSDB under a 21-day retention
window; these files are extractions from it. Once a night falls outside
retention, **these datasets are the only surviving form of that data.**
Ground truth for what was injected during each night is in
`../06_experiment_evidence/`.
