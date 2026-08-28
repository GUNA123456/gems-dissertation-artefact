# GEMS — Predicting Cascading Failures in Cloud Microservices

**Spatio-temporal GCN-LSTM with SLO-grounded labels**
MSc Major Project · COMP40321 · Gunadeep Pesari · Nottingham Trent University

Submission artefact: the project's code, datasets and experiment evidence.
Folders `01`–`07` mirror the submission zip exactly. The dissertation document
is a separate deliverable and is not in this repository.

## Layout

| Folder | Contents |
|---|---|
| `01_application/` | StyleHub testbed — 10 microservices + Redis, an 11-node dependency graph |
| `02_chaos_experiments/` | Chaos scheduler, run audits, ramped fault manifests (light/standard/heavy) |
| `03_data_pipeline/` | Feature extraction from Prometheus and v2.1 SLO labelling (`extract_v2.py`) |
| `04_model_and_serving/` | GCN-LSTM trainers, live/replay monitor, ablations, model checkpoints |
| `05_datasets/` | The labelled datasets for the collection runs |
| `06_experiment_evidence/` | Ground-truth chaos logs, audit reports, live-fire tick logs — verbatim |
| `07_infrastructure/` | Prometheus, Jaeger and traffic-generator manifests |

## Key results

- Trained on three collection runs, evaluated on a fourth it never saw:
  **AUROC 0.974, PR-AUC 0.840** (tuned static-threshold baseline: 0.856 / 0.707).
- **~3 minutes of warning before a memory-leak OOM kill** — a failure class
  latency thresholds never fire on.
- Live root-cause attribution: **Redis named at 1.00** during an injected
  cascade, although Redis exports no HTTP telemetry of its own.

## Related repositories

[`gems-research-comp40321`](https://github.com/GUNA123456/gems-research-comp40321) (working repo, drafts) ·
[`stylehub-microservices`](https://github.com/GUNA123456/stylehub-microservices) (testbed source)
