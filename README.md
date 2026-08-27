# GEMS — Predicting Cascading Failures in Cloud Microservices

**A Spatio-Temporal GCN-LSTM Model with SLO-Grounded Labels**
MSc Major Project · COMP40321 · Gunadeep Pesari

Consolidated private archive of the project's code, data and evidence.
Folders `01`–`08` mirror the submission auxiliary-files layout exactly, so the
submission zip is these eight folders and nothing else.

The dissertation itself is a **separate deliverable** (its own Dropbox, Word or
PDF, not zipped) and is deliberately kept out of this repository — drafts live
in [`gems-research-comp40321`](https://github.com/GUNA123456/gems-research-comp40321).

Working repositories: [`gems-research-comp40321`](https://github.com/GUNA123456/gems-research-comp40321) · [`stylehub-microservices`](https://github.com/GUNA123456/stylehub-microservices)

## Layout

| Folder | Contents |
|---|---|
| `01_application/` | The testbed — 10 FastAPI services + Redis as an 11-node dependency graph. `src/common/obs.py` carries instrumentation; `_call_critical` carries the failure-propagation policy. Helm chart, K8s manifests, build scripts. |
| `02_chaos_experiments/` | `chaos_scheduler.py` (randomised scheduler with **verified-injection** ground truth), `audit_run.py` (the audit that gates a night's data), ramped manifests with light/standard/heavy magnitudes. |
| `03_data_pipeline/` | `extract_v2.py` — `features_from_prometheus()` is the only place features are built, and the live monitor imports it, so training and serving cannot drift apart. v2.1 SLO clause set. Topology. |
| `04_model_and_serving/` | Trainers (single-night and pooled), the online monitor with live + replay modes, the drain-ablation counterfactual, lead-time measurement, and four checkpoints. |
| `05_datasets/` | Four labelled datasets — Night 0 under both label definitions (the ablation), Night A, Night B. |
| `06_experiment_evidence/` | Raw evidence, verbatim: ground-truth JSONL per night, audit reports, live-fire tick logs. |
| `07_infrastructure/` | Jaeger and Prometheus manifests, traffic generator, rendered architecture diagram. |

## Headline results, and the file that proves each

| Claim | Evidence |
|---|---|
| **3m14s warning before an OOM kill**, while the static threshold never fires | `06_.../livefire-20260820-cartmem-pooled3.jsonl` + `04_.../checkpoints/gems_model_pooled3.pt` |
| Three-night pooled: **AUROC 0.974, PR-AUC 0.840, HR@1 0.81** (static: 0.856 / 0.707) | Regenerate: `04_.../train_v2_pooled.py` over `05_datasets/` (seed 42) |
| Honest SLO labels **lowered** every metric — and that is the finding | `05_datasets/telemetry_dataset_v2.json` vs `_v2_1.json` + `03_.../compare_labels.py` |
| Cascades observable 8/8, no silent success | `01_application/src/common/`, `_call_critical` |
| Post-fault alarm tail is window drain, not insight (12/12 vanish) | `04_.../tail_drain_ablation.py` |

## Reproducing

Offline re-training and evaluation need only this repository:

```bash
python -m venv venv && ./venv/bin/pip install torch numpy
./venv/bin/python 04_model_and_serving/train_v2.py \
    --dataset 05_datasets/telemetry_dataset_v2_1.json
```

Live collection and the live monitor additionally require the Azure cluster
(Kubernetes + Chaos Mesh + Prometheus). Replay mode needs Prometheus TSDB data
inside its 21-day retention window.

## Deliberately excluded

| Excluded | Reason |
|---|---|
| `venv/` (~1.26 GB) | third-party packages, recreatable from imports |
| `Literature_Review/Papers_Markdown/` | full-text conversions of published papers — copyright; not our artefact |
| `__pycache__`, `.DS_Store`, `~$` locks, `.bak` | build and editor debris |
