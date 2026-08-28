# Monitoring & observability stack

Everything the experiments observe flows through this stack, deployed on k3s
on the Azure VM (`gems-vm`). Versions are the deployed ones, read from the
live cluster, not assumed.

| Tool | Deployed as | Version | Role |
|---|---|---|---|
| **Prometheus** | Helm `prometheus-community/prometheus` | chart 29.24.0, app v3.13.2 | Primary datastore: 30 s scrape of cAdvisor + all service `/metrics`; every dataset is extracted from it (`03_data_pipeline/extract_v2.py`) |
| **Pushgateway** | bundled with the Prometheus chart | — | Entry point for the traffic generator's probe metrics and the live monitor's `gems_*` prediction metrics |
| **Grafana** | Helm `grafana/grafana` | chart 10.5.15, app 12.3.1 | Live dashboard, built as code by `04_model_and_serving/build_dashboard.py` (never hand-edited) |
| **Jaeger** | `jaeger.yaml` (this folder) | all-in-one | Distributed traces; collected as supporting evidence, never a model input |
| **Chaos Mesh** | Helm | 2.8.3 | Fault injection engine driven by `02_chaos_experiments/chaos_scheduler.py` |

Helm user-supplied values that define measurement behaviour (verbatim from
the release):

```yaml
# prometheus
server:
  global:
    scrape_interval: 30s        # the dataset grid resolution
    evaluation_interval: 30s
  retention: 21d                # raised from 5d on 2026-08-18 to keep all runs queryable
```

Files in this folder:

- `prometheus-nodeport.yaml` — pins Prometheus on `:30900` in a Service Helm
  does not own (a `helm upgrade` once reverted the hand-patched NodePort;
  this survives upgrades).
- `jaeger.yaml` — Jaeger all-in-one in the monitoring namespace.
- `traffic-generator-deployment.yaml` + `traffic_generator.py` — continuous
  load: 5 s health probes per service plus a 15 s real customer journey that
  keeps the dependency edges observable.
- `GEMS_Architecture_Diagram.html` — rendered system diagram.
- `Dockerfile` — traffic generator image.

Prometheus's live TSDB (raw telemetry, 21-day window) exists only on the VM;
the versioned datasets in `05_datasets/` are the durable extracts from it.
