# Original application screenshots — capture rules

These are UNEDITED captures of the running system: no cropping, no
annotation, no retouching. Annotated copies for the report live separately
(Dissertation_Report_Drafts/Figures/); the files here are the raw evidence.

Naming: `YYYYMMDD-HHMM_what-it-shows.png` (time in UTC as shown on screen).

## The shot list

| # | File stem | What to capture | When |
|---|---|---|---|
| 1 | `storefront-healthy` | StyleHub home page + a completed order confirmation | any time, cluster up |
| 2 | `storefront-order-failed` | the order-failed page naming the broken dependency | during a redis kill |
| 3 | `dashboard-quiet` | full gems-model Grafana dashboard, both tiles green | before a demo |
| 4 | `dashboard-alarm` | dashboard with MODEL ALARM red, cause panel showing cart 1.00, memory panel climbing | cart-mem demo, ~T+6 min |
| 5 | `dashboard-post-oom` | memory cliff visible, recovery under way | cart-mem demo, ~T+10 min |
| 6 | `terminal-alarm-tick` | tmux/tail showing `** ALARM ** cause: cart 1.00` lines | same demo |
| 7 | `prometheus-error-gradient` | Prometheus query `service_dependency_errors_total` results | during/after redis kill |
| 8 | `jaeger-trace` | one checkout trace expanded to spans | any time under traffic |
| 9 | `chaosmesh-workflow` | Chaos Mesh dashboard showing a running workflow | during any ramp |
| 10 | `architecture-diagram` | GEMS_Architecture_Diagram.html rendered in browser | any time |

Caveat that belongs in any caption using #4/#5: the model panels lag wall
clock by ~45–73 s (Pushgateway re-stamping — shown on the PREDICTION AGE
tile); timing claims come from tick logs, not from these images.
