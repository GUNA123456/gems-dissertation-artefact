# Claim → evidence map

Every headline claim in the dissertation traces to a file in this artefact.

| Claim | Evidence |
|---|---|
| **3 m 14 s warning before an OOM kill**, while the static threshold never fires | `06_experiment_evidence/livefire-20260820-cartmem-pooled3.jsonl` (inject 13:52:44 → alarm 13:58:30 → OOM 14:01:44) + `04_model_and_serving/checkpoints/gems_model_pooled3.pt` |
| Held-out run: **AUROC 0.974, PR-AUC 0.840, HR@1 0.81** (static baseline 0.856 / 0.707) | regenerate with `04_model_and_serving/train_v2_pooled.py` over `05_datasets/` (seed 42); scored in `07_methodology_documents/Step4_Scorecard.md` |
| Honest SLO labels **lowered** every metric — and that is the finding | `05_datasets/telemetry_dataset_v2.json` vs `_v2_1.json` + `03_data_pipeline/compare_labels.py` + `07_methodology_documents/Step2_Ablation_Results.md` |
| Post-fault alarm tail is **window drain, not insight** (12/12 alarms vanish in the counterfactual) — a disclosed limitation | `04_model_and_serving/tail_drain_ablation.py` |
| Expectations were **pre-registered before collection and scored in public**, including one REFUTED decision rule | `07_methodology_documents/Step4_Collection_Design.md` (written first) → `Step4_Scorecard.md` (scored) |
| Cross-night generalisation with **zero retraining** (redis 4/4 alarms at training-night peaks, 0 false alarms in 5.8 h) | `07_methodology_documents/NightA_HeldOut_Results.md` + `06_experiment_evidence/nightA-20260819.jsonl` |
| Live root-cause attribution: **redis held at 1.00** for ten unbroken minutes, on a service exporting no HTTP telemetry | `06_experiment_evidence/livefire-20260816-redis-ramp.jsonl` + `07_methodology_documents/run_sheets/Demo_RedisDelay_RunSheet.md` (23 Aug live-fire timings) |
